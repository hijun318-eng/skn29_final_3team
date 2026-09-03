"""승인 분석 artifact만 사용해 보고서 제목·요약·시각화 label 제안을 모델에서 생성한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any
from uuid import UUID

from app.adapters.async_model_client import (
    ModelAuthenticationError,
    ModelRateLimitError,
    ModelRequestRejectedError,
)
from app.adapters.contract_model import openai_transport
from app.adapters.model_schemas import (
    PROMPT_IDS,
    openai_payload,
    qwen_payload,
    request_definition,
    response_definition,
)
from app.report_contracts import ReportAssistantPatch
from app.report_patch import ATOMIC_ARTIFACT_VIEWS, artifact_view_title
from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, validate_payload
from src.modelops.runtime import _TRANSPORT_META_KEY
from src.modelops.runtime_config import (
    active_route_for_node,
    resolve_active_model_routes,
)


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class ReportAssistantModelInvocation:
    """동의와 비용 preflight를 통과해 호출별 receipt 기록만 남은 모델 실행권이다."""

    node: str
    route: Any
    payload_hash: str
    timeout: float
    max_attempts: int
    authorization: Any
    repository: Any
    model_execution_id: str | None = None


def bind_report_assistant_model_execution(
    invocation: ReportAssistantModelInvocation,
    model_execution_id: str,
) -> ReportAssistantModelInvocation:
    """preflight invocation을 단 한 DB execution fencing token에 결속한다."""

    try:
        execution_id = str(UUID(model_execution_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant model execution token is invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            attempts=0,
        ) from error
    if invocation.model_execution_id is not None:
        raise ReportAssistantModelError(
            "Report Assistant model invocation is already bound",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            attempts=0,
        )
    return replace(invocation, model_execution_id=execution_id)


def _provider_request_payload(
    route: Any, node: str, payload: dict[str, object]
) -> dict[str, object]:
    """비용과 receipt hash가 실제 transport와 같은 provider request를 사용하게 한다."""

    if route.provider == "openai":
        return openai_payload(route.model, node, payload)
    if route.provider == "qwen":
        return qwen_payload(route.model, node, payload)
    raise ValueError("unsupported Report Assistant model provider")


def prepare_report_assistant_model_invocation(
    node: str,
    payload: dict[str, object],
    *,
    authorization: Any,
    repository: Any,
) -> ReportAssistantModelInvocation:
    """동의 gate 다음에 contract·비용을 검사하고 transport용 불변 실행권을 만든다."""

    route = authorization.route
    if (
        authorization.node != node
        or node not in route.nodes
        or authorization.route.route_fingerprint != route.route_fingerprint
    ):
        raise ReportAssistantModelError(
            "Report Assistant transfer authorization is invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            attempts=0,
        )
    try:
        validate_payload(request_definition(node), payload)
        provider_request = _provider_request_payload(route, node, payload)
    except (ContractError, KeyError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant request violates the active model contract",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
            attempts=0,
        ) from error
    timeout, configured_max_attempts = _model_runtime_limits()
    # 외부 provider는 receipt commit 뒤 응답을 잃으면 실제 처리 여부를 증명할
    # 수 없다. provider idempotency 계약 없이 같은 payload를 자동 재전송하지
    # 않도록 외부 전송은 한 execution당 단 한 번만 허용한다. 내부 route만
    # manifest가 승인한 네트워크 경계 안에서 configured retry를 사용한다.
    max_attempts = (
        1 if route.data_boundary == "external" else configured_max_attempts
    )
    if max_attempts > 4:
        raise ReportAssistantModelError(
            "Report Assistant model limits exceed the receipt contract",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            attempts=0,
        )
    _enforce_model_cost_preflight(route, node, payload, max_attempts)
    payload_hash = hashlib.sha256(
        json.dumps(
            provider_request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return ReportAssistantModelInvocation(
        node=node,
        route=route,
        payload_hash=payload_hash,
        timeout=timeout,
        max_attempts=max_attempts,
        authorization=authorization,
        repository=repository,
    )


def _validated_invocation(
    invocation: ReportAssistantModelInvocation | None,
    node: str,
    payload: dict[str, object],
) -> ReportAssistantModelInvocation:
    """임의 payload 직접 호출이 receipt 없이 transport에 도달하지 못하게 닫는다."""

    try:
        execution_id = str(UUID(str(invocation.model_execution_id))) if invocation else ""
    except (TypeError, ValueError):
        execution_id = ""
    if (
        invocation is None
        or invocation.node != node
        or invocation.authorization.node != node
        or invocation.authorization.route.route_fingerprint
        != invocation.route.route_fingerprint
        or not execution_id
    ):
        raise ReportAssistantModelError(
            "Report Assistant transfer authorization is required",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            attempts=0,
        )
    actual_hash = hashlib.sha256(
        json.dumps(
            _provider_request_payload(invocation.route, node, payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if actual_hash != invocation.payload_hash:
        raise ReportAssistantModelError(
            "Report Assistant transfer payload changed after authorization",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
            attempts=0,
        )
    return invocation


def validate_report_change_operation_scope(
    proposal: dict[str, object],
    operation_scope: object,
) -> None:
    """서버가 지정한 turn 범위를 모델의 route와 typed patch보다 우선해 검증한다."""

    if operation_scope == "full_report":
        return
    if operation_scope != "report_title":
        raise ValueError("Report Assistant operation scope is invalid")
    kind = proposal.get("change_kind")
    if kind == "clarification":
        if proposal.get("analysis_plan") is not None or proposal.get("patch") is not None:
            raise ValueError("report_title clarification must not include a plan or patch")
        return
    patch = proposal.get("patch")
    operations = patch.get("operations") if isinstance(patch, dict) else None
    if (
        kind != "existing_artifact"
        or proposal.get("analysis_plan") is not None
        or not isinstance(operations, (list, tuple))
        or len(operations) != 1
        or not isinstance(operations[0], dict)
        or operations[0].get("op") != "set_report_title"
    ):
        raise ValueError("report_title scope allows only one set_report_title operation")


class ReportAssistantModelError(RuntimeError):
    """보고서 제안 모델의 구성·transport·schema 검증 실패로 draft를 신뢰할 수 없음을 알린다."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "REPORT_ASSISTANT_TURN_MODEL_FAILED",
        attempts: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = attempts
        self.duration_ms = duration_ms


def _model_failure(
    error: Exception | None,
    *,
    message: str,
    attempts: int | None,
    started: float | None,
) -> ReportAssistantModelError:
    """provider 원문을 노출하지 않고 실패 종류와 안전한 관측치만 보존한다."""

    if isinstance(error, ModelAuthenticationError):
        code = "REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED"
    elif isinstance(error, ModelRateLimitError):
        code = "REPORT_ASSISTANT_MODEL_RATE_LIMITED"
    elif isinstance(error, ModelRequestRejectedError):
        code = "REPORT_ASSISTANT_MODEL_REQUEST_REJECTED"
    elif isinstance(error, TimeoutError):
        code = "REPORT_ASSISTANT_MODEL_TIMEOUT"
    elif isinstance(error, OSError):
        code = "REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED"
    elif isinstance(error, ValueError) and str(error) == "ASSISTANT_MODEL_EXECUTION_CONFLICT":
        code = "ASSISTANT_MODEL_EXECUTION_CONFLICT"
    elif isinstance(error, (ContractError, TypeError, ValueError)):
        code = "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID"
    else:
        code = "REPORT_ASSISTANT_TURN_MODEL_FAILED"
    duration_ms = None if started is None else round((perf_counter() - started) * 1000, 3)
    return ReportAssistantModelError(
        message,
        code=code,
        attempts=attempts,
        duration_ms=duration_ms,
    )


def _model_runtime_limits() -> tuple[float, int]:
    """Report Assistant 공통 timeout·시도 제한을 한 번 검증해 반환한다."""

    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
        max_attempts = int(os.getenv("REPORT_ASSISTANT_MAX_MODEL_ATTEMPTS", "2"))
    except ValueError as error:
        raise ReportAssistantModelError(
            "Report Assistant model limits are invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
        ) from error
    if timeout <= 0 or not 1 <= max_attempts <= 4:
        raise ReportAssistantModelError(
            "Report Assistant model limits are invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
        )
    return timeout, max_attempts


def _enforce_model_cost_preflight(
    route: Any,
    node: str,
    payload: dict[str, object],
    max_attempts: int,
) -> None:
    """실제 provider 요청과 모든 내부 시도의 보수적 최대 비용을 호출 전에 제한한다."""

    from app.services.report_assistant_operations import (
        report_assistant_model_cost_policy,
    )
    from src.modelops.runtime import estimate_token_count

    try:
        if route.provider == "openai":
            request_payload = openai_payload(route.model, node, payload)
            output_budget = request_payload["max_completion_tokens"]
        elif route.provider == "qwen":
            request_payload = qwen_payload(route.model, node, payload)
            output_budget = request_payload["max_tokens"]
        else:
            raise ValueError("unsupported Report Assistant model provider")
        serialized = json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        input_tokens = estimate_token_count(serialized)
        if (
            isinstance(output_budget, bool)
            or not isinstance(output_budget, int)
            or output_budget < 1
        ):
            raise ValueError("invalid Report Assistant output budget")
        policy = report_assistant_model_cost_policy()
        maximum_cost = policy.estimate(
            input_tokens * max_attempts,
            output_budget * max_attempts,
        )
    except (KeyError, RuntimeError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant model cost configuration is invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            attempts=0,
        ) from error
    if maximum_cost > policy.max_estimated_cost_usd:
        raise ReportAssistantModelError(
            "Report Assistant model cost budget would be exceeded",
            code="ASSISTANT_COST_BUDGET_EXCEEDED",
            attempts=0,
        )


def _validation_error_signature(error: Exception | None) -> str:
    """Pydantic 오류에서 입력값을 제외한 필드 경로·오류 유형만 반환한다."""

    errors = getattr(error, "errors", None)
    if not callable(errors):
        return "none"
    try:
        items = errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    except TypeError:
        return "unavailable"
    signatures = []
    for item in items[:8]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "root"
        signatures.append(f"{location}:{item.get('type', 'unknown')}")
    return ",".join(signatures) or "none"


def report_evidence_catalog(
    artifact: dict[str, Any],
    reference_prefix: str = "",
) -> tuple[dict[str, object], ...]:
    """승인 Artifact에서 실제 식별자를 제외한 narrative·metric 근거 catalog를 만든다."""

    catalog: list[dict[str, object]] = [{
        "ref": f"{reference_prefix}artifact_narrative",
        "kind": "narrative",
        "label": "Artifact 요약",
        "content": str(artifact.get("narrative_markdown") or ""),
        "value": None,
        "unit": None,
    }]
    evidence = artifact.get("evidence_json")
    metric_values = evidence.get("metric_values", ()) if isinstance(evidence, dict) else ()
    if isinstance(metric_values, (list, tuple)):
        for index, metric in enumerate(metric_values[:15], start=1):
            if not isinstance(metric, dict) or not str(metric.get("label") or "").strip():
                continue
            raw_value = metric.get("value")
            value = raw_value if raw_value is None or isinstance(raw_value, (str, int, float, bool)) else str(raw_value)
            catalog.append({
                "ref": f"{reference_prefix}metric_{index}",
                "kind": "metric",
                "label": str(metric["label"]).strip()[:255],
                "content": str(metric.get("definition") or "").strip()[:1000] or None,
                "value": value,
                "unit": str(metric.get("unit")).strip()[:64] if metric.get("unit") is not None else None,
            })
    return tuple(catalog)


def validate_report_patch_evidence(
    patch: ReportAssistantPatch,
    catalog: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    """텍스트 patch의 모든 근거가 현재 Artifact catalog 별칭인지 확인하고 공개 목록을 반환한다."""

    allowed = {str(item["ref"]) for item in catalog}
    referenced: list[str] = []
    for operation in patch.operations:
        evidence_refs = getattr(operation, "evidence_refs", ())
        if (
            operation.op == "add_text"
            or (operation.op == "update_text" and operation.content is not None)
        ) and not evidence_refs:
            raise ValueError("Report patch의 생성 본문에는 Artifact 근거가 필요합니다.")
        for evidence_ref in evidence_refs:
            if evidence_ref not in allowed:
                raise ValueError("Report patch가 허용되지 않은 Artifact 근거를 참조했습니다.")
            if evidence_ref not in referenced:
                referenced.append(evidence_ref)
    return tuple(referenced)


def report_patch_model_payload(patch: ReportAssistantPatch) -> dict[str, object]:
    """서버 typed patch를 strict 모델 계약의 nullable 고정 필드 형태로 직렬화한다."""

    operations = []
    for operation in patch.operations:
        raw = operation.model_dump(mode="json")
        placement = raw.pop("placement", None)
        item = {
            "op": operation.op,
            "block_id": raw.get("block_id"),
            "artifact_ref": raw.get("artifact_ref"),
            "view": raw.get("view"),
            "title": (
                None if operation.op == "add_artifact_view" else raw.get("title")
            ),
            "content": raw.get("content"),
            "orientation": raw.get("orientation"),
            "currency_display_unit": raw.get("currency_display_unit"),
            "block_width": raw.get("block_width"),
            "block_height": raw.get("block_height"),
            "chart_type": raw.get("chart_type"),
            "show_legend": raw.get("show_legend"),
            "density": raw.get("density"),
            "show_row_numbers": raw.get("show_row_numbers"),
            "size_mode": raw.get("size_mode"),
            "after_block_id": raw.get("after_block_id"),
            "width": raw.get("width"),
            "evidence_refs": raw.get("evidence_refs", []),
        }
        if isinstance(placement, dict):
            item["after_block_id"] = placement.get("after_block_id")
            item["width"] = placement.get("width")
        operations.append(item)
    return {"summary": patch.summary, "operations": operations}


def _validate_wire_text_operation(
    payload: dict[str, object],
    raw_operation: dict[str, object],
) -> dict[str, object]:
    """모델 wire text 연산의 의미를 바꾸지 않고 typed 계약 위반을 닫는다."""

    operation = raw_operation.get("op")
    if operation == "add_text":
        if not str(raw_operation.get("title") or "").strip():
            raise ValueError("Report Assistant add_text requires a non-empty title")
        return raw_operation
    if operation != "update_text":
        return raw_operation

    report = payload.get("report")
    blocks = report.get("blocks") if isinstance(report, dict) else None
    if not isinstance(blocks, list):
        raise ValueError("Report Assistant report blocks are invalid")
    target = next(
        (
            block
            for block in blocks
            if isinstance(block, dict)
            and block.get("block_id") == raw_operation.get("block_id")
        ),
        None,
    )
    if target is None or target.get("type") == "text":
        return raw_operation
    raise ValueError(
        "Report Assistant update_text requires an existing text block"
    )


def _normalize_model_resize_operation(
    payload: dict[str, object],
    raw_operation: dict[str, object],
) -> dict[str, object]:
    """모델 resize 값을 현재 block 유형의 렌더링 최소 크기로 올린다."""

    if raw_operation.get("op") != "resize_block":
        return raw_operation
    report = payload.get("report")
    blocks = report.get("blocks") if isinstance(report, dict) else None
    if not isinstance(blocks, list):
        return raw_operation
    target = next(
        (
            block
            for block in blocks
            if isinstance(block, dict)
            and block.get("block_id") == raw_operation.get("block_id")
        ),
        None,
    )
    minimums = {
        "text": (4, 4),
        "chart": (6, 7),
        "table": (6, 5),
        "artifact": (6, 12),
    }
    block_minimums = minimums.get(target.get("type")) if target else None
    if block_minimums is None:
        return raw_operation
    minimum_width, minimum_height = block_minimums
    return {
        **raw_operation,
        "block_width": max(int(raw_operation["block_width"]), minimum_width),
        "block_height": max(int(raw_operation["block_height"]), minimum_height),
    }


def _normalize_model_turn_response(result: dict[str, object]) -> dict[str, object]:
    """모델이 생략한 의미 없는 nullable wire 필드만 strict 계약 형태로 채운다."""

    normalized = dict(result)
    normalized.setdefault("analysis_plan", None)
    normalized.setdefault("patch", None)
    normalized.setdefault("suggestions", [])
    normalized.setdefault("exact_page_count", None)
    patch = normalized.get("patch")
    if not isinstance(patch, dict):
        return normalized
    operations = patch.get("operations")
    if not isinstance(operations, list):
        return normalized
    nullable_fields = (
        "block_id", "artifact_ref", "view", "title", "content", "orientation",
        "currency_display_unit", "block_width", "block_height", "chart_type",
        "show_legend", "density", "show_row_numbers", "size_mode",
        "after_block_id", "width",
    )
    normalized_operations = []
    for operation in operations:
        if not isinstance(operation, dict):
            normalized_operations.append(operation)
            continue
        normalized_operation = dict(operation)
        for field in nullable_fields:
            normalized_operation.setdefault(field, None)
        normalized_operation.setdefault("evidence_refs", [])
        normalized_operations.append(normalized_operation)
    normalized["patch"] = {**patch, "operations": normalized_operations}
    return normalized


def _model_artifact_by_alias(
    payload: dict[str, object],
    artifact_ref: object,
) -> dict[str, object]:
    """모델 별칭을 서버가 제공한 Artifact 공개 payload 한 건으로만 해석한다."""

    candidates = [payload.get("artifact")]
    additional = payload.get("additional_artifacts")
    if isinstance(additional, list):
        candidates.extend(additional)
    artifact = next(
        (
            item for item in candidates
            if isinstance(item, dict) and item.get("artifact_id") == artifact_ref
        ),
        None,
    )
    if artifact is None:
        raise ValueError("Report Assistant Artifact alias is invalid")
    return artifact


def _validate_patch_target_types(
    payload: dict[str, object],
    patch: ReportAssistantPatch,
) -> None:
    """남은 typed 설정 연산이 현재 Report block 유형과 맞는지 확인한다."""

    report = payload.get("report")
    blocks = report.get("blocks") if isinstance(report, dict) else None
    if not isinstance(blocks, list):
        raise ValueError("Report Assistant report blocks are invalid")
    block_types = {
        str(block["block_id"]): str(block["type"])
        for block in blocks
        if isinstance(block, dict)
        and isinstance(block.get("block_id"), str)
        and isinstance(block.get("type"), str)
    }
    required_types = {
        "update_text": frozenset({"text"}),
        "update_block_title": frozenset({"text"}),
        "update_chart_settings": frozenset({"chart"}),
        "update_table_settings": frozenset({"table"}),
        "set_block_size_mode": frozenset({"artifact", "chart", "table"}),
    }
    for operation in patch.operations:
        accepted = required_types.get(operation.op)
        if accepted is None:
            continue
        block_type = block_types.get(str(operation.block_id))
        if block_type not in accepted:
            raise ValueError(
                f"{operation.op} targets an incompatible report block type"
            )


async def generate_report_draft(
    payload: dict[str, object],
    *,
    invocation: ReportAssistantModelInvocation | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    """승인 artifact 입력에서 제목·요약·표·차트 label만 모델에 제안받는다.

    active request/response schema를 양쪽에서 검증하고 두 번까지만 호출하며, 빈 필드나 설정·
    transport 실패는 draft를 저장하지 못하도록 ``ReportAssistantModelError``로 닫는다.
    """
    invocation = _validated_invocation(invocation, "report_assistant", payload)
    route = invocation.route
    timeout, max_attempts = invocation.timeout, invocation.max_attempts
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await invocation.authorization.record_attempt(
                invocation.repository,
                attempt=attempt,
                payload_hash=invocation.payload_hash,
                model_execution_id=invocation.model_execution_id,
                minimum_lease_seconds=math.ceil(timeout) + 5,
            )
            # httpx의 numeric timeout은 connect/read/write/pool 단계별 inactivity
            # 제한이다. 느린 streaming 응답이 실행 lease보다 오래 살아남지 않도록
            # provider attempt 전체 wall-clock도 같은 상한으로 닫는다.
            async with asyncio.timeout(timeout):
                result = await openai_transport(
                    route.endpoint,
                    route.token,
                    "report_assistant",
                    payload,
                    timeout,
                    model=route.model,
                    provider=route.provider,
                )
            transport_meta = result.pop(_TRANSPORT_META_KEY, {})
            validate_payload(response_definition("report_assistant"), result)
            fields = ("title", "executive_summary", "table_title", "chart_title")
            if any(not result[field].strip() for field in fields):
                raise ValueError("Report Assistant returned a blank draft field")
            prompt = get_prompt(PROMPT_IDS["report_assistant"])
            return (
                {field: result[field].strip() for field in fields},
                {
                    "model_version": transport_meta.get("model_version") or route.model,
                    "model_snapshot": transport_meta.get("model_snapshot"),
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.metadata()["hash"],
                    "attempts": attempt,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "input_tokens": transport_meta.get("input_tokens"),
                    "output_tokens": transport_meta.get("output_tokens"),
                },
            )
        except (OSError, TimeoutError, TypeError, ValueError) as error:
            last_error = error
            if (
                isinstance(error, (ModelAuthenticationError, ModelRequestRejectedError))
                or str(error) == "ASSISTANT_MODEL_EXECUTION_CONFLICT"
            ):
                break
    raise _model_failure(
        last_error,
        message="Report Assistant model call failed",
        attempts=attempt,
        started=started,
    ) from last_error


async def generate_report_change_proposal(
    payload: dict[str, object],
    *,
    invocation: ReportAssistantModelInvocation | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """사용자 지시가 기존 artifact로 가능한지 새 분석 계획이 필요한지만 제안받는다.

    별도 turn schema로 입출력을 검증하고 ``new_data``와 계획 객체의 결속을 서버에서 다시
    확인한다. 모델은 request ID·승인·실행 권한을 만들 수 없으며 두 번 실패하면 닫힌다.
    """

    node = "report_assistant_turn"
    invocation = _validated_invocation(invocation, node, payload)
    route = invocation.route
    timeout, max_attempts = invocation.timeout, invocation.max_attempts
    started = perf_counter()
    last_error: Exception | None = None
    failure_stage = "model_transport"
    observed_operation_types: tuple[str, ...] = ()
    for attempt in range(1, max_attempts + 1):
        try:
            failure_stage = "model_transport"
            await invocation.authorization.record_attempt(
                invocation.repository,
                attempt=attempt,
                payload_hash=invocation.payload_hash,
                model_execution_id=invocation.model_execution_id,
                minimum_lease_seconds=math.ceil(timeout) + 5,
            )
            async with asyncio.timeout(timeout):
                result = await openai_transport(
                    route.endpoint,
                    route.token,
                    node,
                    payload,
                    timeout,
                    model=route.model,
                    provider=route.provider,
            )
            transport_meta = result.pop(_TRANSPORT_META_KEY, {})
            failure_stage = "response_contract"
            result = _normalize_model_turn_response(result)
            validate_payload(response_definition(node), result)
            failure_stage = "change_contract"
            kind = result["change_kind"]
            plan = result["analysis_plan"]
            raw_patch = result["patch"]
            patch = None
            if kind == "existing_artifact":
                if plan is not None or not isinstance(raw_patch, dict):
                    raise ValueError("existing_artifact requires a patch and no analysis plan")
                operation_fields = {
                    "set_report_title": {"title"},
                    "set_report_orientation": {"orientation"},
                    "set_currency_display_unit": {"currency_display_unit"},
                    "compact_report_layout": set(),
                    "add_report_page": set(),
                    "update_block_title": {"block_id", "title"},
                    "resize_block": {"block_id", "block_width", "block_height"},
                    "update_chart_settings": {"block_id", "chart_type", "show_legend", "size_mode"},
                    "update_table_settings": {"block_id", "density", "show_row_numbers", "size_mode"},
                    "set_block_size_mode": {"block_id", "size_mode"},
                    "add_text": {"title", "content"},
                    "update_text": {"block_id", "title", "content"},
                    "add_artifact_view": {
                        "artifact_ref", "view", "chart_type", "show_legend",
                        "density", "show_row_numbers", "size_mode",
                    },
                    "reposition_block": {"block_id"},
                    "remove_block": {"block_id"},
                    "duplicate_block": {"block_id"},
                    "restore_previous_revision": set(),
                }
                operations = []
                for raw_operation in raw_patch["operations"]:
                    failure_stage = "wire_text_validation"
                    raw_operation = _validate_wire_text_operation(
                        payload, raw_operation
                    )
                    raw_operation = _normalize_model_resize_operation(
                        payload, raw_operation
                    )
                    failure_stage = "operation_projection"
                    allowed_fields = operation_fields[raw_operation["op"]]
                    if raw_operation["op"] == "add_artifact_view":
                        view = raw_operation["view"]
                        if view not in ATOMIC_ARTIFACT_VIEWS:
                            raise ValueError(
                                "Report Assistant can add only one atomic Artifact view"
                            )
                        source_artifact = _model_artifact_by_alias(
                            payload, raw_operation["artifact_ref"]
                        )
                        available_views = source_artifact.get("available_views")
                        if not isinstance(available_views, list) or view not in available_views:
                            raise ValueError(
                                "Report Assistant requested an unavailable Artifact view"
                            )
                        view_fields = {
                            "summary": set(),
                            "kpi": set(),
                            "chart": {"chart_type", "show_legend"},
                            "table": {"density", "show_row_numbers"},
                        }[view]
                        allowed_fields = {
                            "artifact_ref", "view", "size_mode", *view_fields,
                        }
                    operation = {
                        "op": raw_operation["op"],
                        **{
                            key: raw_operation[key]
                            for key in allowed_fields
                            if raw_operation.get(key) is not None
                        },
                    }
                    if raw_operation["op"] in {"add_text", "update_text"}:
                        operation["evidence_refs"] = raw_operation["evidence_refs"]
                    if raw_operation["op"] in {"add_text", "add_artifact_view"}:
                        default_width = (
                            "half"
                            if raw_operation["op"] == "add_artifact_view"
                            and raw_operation["view"] in {"summary", "kpi"}
                            else "full"
                        )
                        operation["placement"] = {
                            "after_block_id": raw_operation["after_block_id"],
                            "width": raw_operation["width"] or default_width,
                        }
                    if raw_operation["op"] == "add_artifact_view":
                        operation["title"] = artifact_view_title(
                            str(source_artifact["title"]), str(operation["view"])
                        )
                    elif raw_operation["op"] == "reposition_block":
                        operation["after_block_id"] = raw_operation["after_block_id"]
                        operation["width"] = raw_operation["width"] or "full"
                    operations.append(operation)
                observed_operation_types = tuple(
                    str(operation["op"]) for operation in operations
                )
                failure_stage = "typed_patch"
                summary = raw_patch["summary"].strip()
                if not summary:
                    raise ValueError("Report Assistant returned a blank patch summary")
                patch = ReportAssistantPatch.model_validate(
                    {
                        "summary": summary,
                        "operations": operations,
                    }
                )
                failure_stage = "target_type_validation"
                _validate_patch_target_types(payload, patch)
                patch = patch.model_dump(mode="json")
            elif kind == "new_data" and (not isinstance(plan, dict) or raw_patch is not None):
                raise ValueError("new_data requires an analysis plan and no patch")
            elif kind == "clarification" and (plan is not None or raw_patch is not None):
                raise ValueError("clarification must not include a plan or patch")
            if not str(result["message"]).strip():
                raise ValueError("Report Assistant returned a blank message")
            proposal = {
                "change_kind": kind,
                "message": str(result["message"]).strip(),
                "analysis_plan": plan,
                "patch": patch,
                "suggestions": tuple(str(item).strip() for item in result["suggestions"]),
                "exact_page_count": result["exact_page_count"],
            }
            failure_stage = "operation_scope_validation"
            validate_report_change_operation_scope(
                proposal,
                payload.get("operation_scope"),
            )
            prompt = get_prompt(PROMPT_IDS[node])
            return (
                proposal,
                {
                    "model_version": transport_meta.get("model_version") or route.model,
                    "model_snapshot": transport_meta.get("model_snapshot"),
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.metadata()["hash"],
                    "attempts": attempt,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "input_tokens": transport_meta.get("input_tokens"),
                    "output_tokens": transport_meta.get("output_tokens"),
                },
            )
        except (ContractError, OSError, TimeoutError, TypeError, ValueError) as error:
            last_error = error
            if (
                isinstance(error, (ModelAuthenticationError, ModelRequestRejectedError))
                or str(error) == "ASSISTANT_MODEL_EXECUTION_CONFLICT"
            ):
                break
    logger.warning(
        "Report Assistant turn failed after %s attempt(s): "
        "stage=%s error_type=%s operations=%s validation=%s",
        attempt,
        failure_stage,
        type(last_error).__name__ if last_error is not None else "unknown",
        observed_operation_types,
        _validation_error_signature(last_error),
    )
    raise _model_failure(
        last_error,
        message="Report Assistant turn model call failed",
        attempts=attempt,
        started=started,
    ) from last_error


async def generate_report_quality_review(
    payload: dict[str, object],
    *,
    invocation: ReportAssistantModelInvocation | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """현재 Report·승인 Artifact를 읽기만 하는 strict 품질 검토를 실행한다."""

    node = "report_assistant_review"
    invocation = _validated_invocation(invocation, node, payload)
    route = invocation.route
    timeout, max_attempts = invocation.timeout, invocation.max_attempts
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await invocation.authorization.record_attempt(
                invocation.repository,
                attempt=attempt,
                payload_hash=invocation.payload_hash,
                model_execution_id=invocation.model_execution_id,
                minimum_lease_seconds=math.ceil(timeout) + 5,
            )
            async with asyncio.timeout(timeout):
                result = await openai_transport(
                    route.endpoint,
                    route.token,
                    node,
                    payload,
                    timeout,
                    model=route.model,
                    provider=route.provider,
                )
            transport_meta = result.pop(_TRANSPORT_META_KEY, {})
            validate_payload(response_definition(node), result)
            prompt = get_prompt(PROMPT_IDS[node])
            return (
                result,
                {
                    "model_version": transport_meta.get("model_version") or route.model,
                    "model_snapshot": transport_meta.get("model_snapshot"),
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.metadata()["hash"],
                    "attempts": attempt,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "input_tokens": transport_meta.get("input_tokens"),
                    "output_tokens": transport_meta.get("output_tokens"),
                },
            )
        except (ContractError, OSError, TimeoutError, TypeError, ValueError) as error:
            last_error = error
            if (
                isinstance(error, (ModelAuthenticationError, ModelRequestRejectedError))
                or str(error) == "ASSISTANT_MODEL_EXECUTION_CONFLICT"
            ):
                break
    raise _model_failure(
        last_error,
        message="Report Assistant review model call failed",
        attempts=attempt,
        started=started,
    ) from last_error
