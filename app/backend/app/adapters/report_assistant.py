"""승인 분석 artifact만 사용해 보고서 제목·요약·시각화 label 제안을 모델에서 생성한다."""

from __future__ import annotations

import logging
import os
import re
from time import perf_counter
from typing import Any

from app.adapters.async_model_client import (
    ModelAuthenticationError,
    ModelRateLimitError,
    ModelRequestRejectedError,
)
from app.adapters.contract_model import openai_transport
from app.adapters.model_schemas import PROMPT_IDS, request_definition, response_definition
from app.report_contracts import ReportAssistantPatch
from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, validate_payload
from src.modelops.runtime import _TRANSPORT_META_KEY
from src.modelops.runtime_config import (
    active_route_for_node,
    resolve_active_model_routes,
)


logger = logging.getLogger("uvicorn.error")


_KOREAN_TEXT_PATTERN = re.compile(r"[가-힣]")
_PATCH_OPERATION_LABELS = {
    "set_report_title": "보고서 제목 변경",
    "set_report_orientation": "용지 방향 변경",
    "set_currency_display_unit": "금액 단위 변경",
    "compact_report_layout": "보고서 여백 정돈",
    "add_report_page": "보고서 페이지 추가",
    "update_block_title": "블록 제목 수정",
    "resize_block": "블록 크기 조정",
    "update_chart_settings": "차트 표시 방식 변경",
    "update_table_settings": "표 표시 방식 변경",
    "set_block_size_mode": "블록 크기 방식 변경",
    "add_text": "텍스트 블록 추가",
    "update_text": "텍스트 내용 수정",
    "add_artifact_view": "분석 결과 보기 추가",
    "reposition_block": "블록 위치 조정",
    "remove_block": "블록 삭제",
    "duplicate_block": "블록 복제",
    "restore_previous_revision": "이전 보고서 버전 복구",
}


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
            "title": raw.get("title"),
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


def _user_facing_patch_summary(
    raw_summary: object,
    operations: list[dict[str, object]],
) -> str:
    """영문 모델 요약을 내부 operation 기반의 짧은 한국어 설명으로 대체한다."""

    summary = str(raw_summary or "").strip()
    if _KOREAN_TEXT_PATTERN.search(summary):
        return summary
    labels = list(dict.fromkeys(
        _PATCH_OPERATION_LABELS.get(str(operation.get("op")), "보고서 구성 변경")
        for operation in operations
    ))
    if not labels:
        return "보고서 변경안"
    if len(labels) == 1:
        return labels[0]
    return " · ".join(labels[:3])


def _normalize_wire_text_operation(
    payload: dict[str, object],
    raw_operation: dict[str, object],
) -> dict[str, object]:
    """모델 wire text 연산을 typed patch 검증 전에 보존적으로 정규화한다."""

    normalized = dict(raw_operation)
    operation = normalized.get("op")
    if operation == "add_text":
        if normalized.get("content") is not None and normalized.get("title") is None:
            normalized["title"] = "핵심 요약"
        return normalized
    if operation != "update_text":
        return normalized

    report = payload.get("report")
    blocks = report.get("blocks") if isinstance(report, dict) else None
    if not isinstance(blocks, list):
        raise ValueError("Report Assistant report blocks are invalid")
    target = next(
        (
            block
            for block in blocks
            if isinstance(block, dict)
            and block.get("block_id") == normalized.get("block_id")
        ),
        None,
    )
    if target is None or target.get("type") == "text":
        return normalized
    if normalized.get("content") is None:
        normalized["op"] = "update_block_title"
        return normalized

    normalized.update(
        {
            "op": "add_text",
            "block_id": None,
            "title": normalized.get("title") or "핵심 요약",
            "after_block_id": target["block_id"],
            "width": "full",
        }
    )
    return normalized


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
) -> tuple[dict[str, str], dict[str, object]]:
    """승인 artifact 입력에서 제목·요약·표·차트 label만 모델에 제안받는다.

    active request/response schema를 양쪽에서 검증하고 두 번까지만 호출하며, 빈 필드나 설정·
    transport 실패는 draft를 저장하지 못하도록 ``ReportAssistantModelError``로 닫는다.
    """
    try:
        route = active_route_for_node(
            resolve_active_model_routes(),
            "report_assistant",
        )
    except (OSError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant model configuration is unavailable",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
        ) from error
    try:
        validate_payload(request_definition("report_assistant"), payload)
    except (ContractError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant request violates the active model contract",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
        ) from error
    timeout, max_attempts = _model_runtime_limits()
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
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
            if isinstance(error, (ModelAuthenticationError, ModelRequestRejectedError)):
                break
    raise _model_failure(
        last_error,
        message="Report Assistant model call failed",
        attempts=attempt,
        started=started,
    ) from last_error


async def generate_report_change_proposal(
    payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """사용자 지시가 기존 artifact로 가능한지 새 분석 계획이 필요한지만 제안받는다.

    별도 turn schema로 입출력을 검증하고 ``new_data``와 계획 객체의 결속을 서버에서 다시
    확인한다. 모델은 request ID·승인·실행 권한을 만들 수 없으며 두 번 실패하면 닫힌다.
    """

    node = "report_assistant_turn"
    try:
        route = active_route_for_node(resolve_active_model_routes(), node)
    except (OSError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant turn configuration is invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
        ) from error
    try:
        validate_payload(request_definition(node), payload)
    except (ContractError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant turn request is invalid",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
        ) from error
    timeout, max_attempts = _model_runtime_limits()
    started = perf_counter()
    last_error: Exception | None = None
    failure_stage = "model_transport"
    observed_operation_types: tuple[str, ...] = ()
    for attempt in range(1, max_attempts + 1):
        try:
            failure_stage = "model_transport"
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
                        "artifact_ref", "view", "title", "chart_type", "show_legend",
                        "density", "show_row_numbers", "size_mode",
                    },
                    "reposition_block": {"block_id"},
                    "remove_block": {"block_id"},
                    "duplicate_block": {"block_id"},
                    "restore_previous_revision": set(),
                }
                operations = []
                for raw_operation in raw_patch["operations"]:
                    failure_stage = "wire_text_normalization"
                    raw_operation = _normalize_wire_text_operation(
                        payload, raw_operation
                    )
                    failure_stage = "operation_projection"
                    allowed_fields = operation_fields[raw_operation["op"]]
                    if raw_operation["op"] == "add_artifact_view":
                        view_fields = {
                            "chart": {"chart_type", "show_legend"},
                            "table": {"density", "show_row_numbers"},
                            "artifact": set(),
                        }[raw_operation["view"]]
                        allowed_fields = {
                            "artifact_ref", "view", "title", "size_mode", *view_fields,
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
                        operation["placement"] = {
                            "after_block_id": raw_operation["after_block_id"],
                            "width": raw_operation["width"] or "full",
                        }
                    elif raw_operation["op"] == "reposition_block":
                        operation["after_block_id"] = raw_operation["after_block_id"]
                        operation["width"] = raw_operation["width"] or "full"
                    operations.append(operation)
                observed_operation_types = tuple(
                    str(operation["op"]) for operation in operations
                )
                failure_stage = "typed_patch"
                patch = ReportAssistantPatch.model_validate(
                    {
                        "summary": _user_facing_patch_summary(
                            raw_patch["summary"], operations
                        ),
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
            prompt = get_prompt(PROMPT_IDS[node])
            return (
                {
                    "change_kind": kind,
                    "message": str(result["message"]).strip(),
                    "analysis_plan": plan,
                    "patch": patch,
                    "suggestions": tuple(str(item).strip() for item in result["suggestions"]),
                },
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
            if isinstance(error, (ModelAuthenticationError, ModelRequestRejectedError)):
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
) -> tuple[dict[str, object], dict[str, object]]:
    """현재 Report·승인 Artifact를 읽기만 하는 strict 품질 검토를 실행한다."""

    node = "report_assistant_review"
    try:
        route = active_route_for_node(resolve_active_model_routes(), node)
    except (OSError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant review configuration is invalid",
            code="REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
        ) from error
    try:
        validate_payload(request_definition(node), payload)
    except (ContractError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant review request is invalid",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
        ) from error
    timeout, max_attempts = _model_runtime_limits()
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
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
            if isinstance(error, (ModelAuthenticationError, ModelRequestRejectedError)):
                break
    raise _model_failure(
        last_error,
        message="Report Assistant review model call failed",
        attempts=attempt,
        started=started,
    ) from last_error
