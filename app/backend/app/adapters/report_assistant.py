"""승인 분석 artifact만 사용해 보고서 제목·요약·시각화 label 제안을 모델에서 생성한다."""

from __future__ import annotations

import os
from time import perf_counter

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


class ReportAssistantModelError(RuntimeError):
    """보고서 제안 모델의 구성·transport·schema 검증 실패로 draft를 신뢰할 수 없음을 알린다."""
    pass


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
            "Report Assistant model configuration is unavailable"
        ) from error
    try:
        validate_payload(request_definition("report_assistant"), payload)
    except (ContractError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant request violates the active model contract"
        ) from error
    timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in (1, 2):
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
                },
            )
        except (OSError, TimeoutError, TypeError, ValueError) as error:
            last_error = error
    raise ReportAssistantModelError("Report Assistant model call failed") from last_error


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
        validate_payload(request_definition(node), payload)
    except (ContractError, OSError, TypeError, ValueError) as error:
        raise ReportAssistantModelError(
            "Report Assistant turn configuration or request is invalid"
        ) from error
    timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in (1, 2):
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
            kind = result["change_kind"]
            plan = result["analysis_plan"]
            raw_patch = result["patch"]
            patch = None
            if kind == "existing_artifact":
                if plan is not None or not isinstance(raw_patch, dict):
                    raise ValueError("existing_artifact requires a patch and no analysis plan")
                operations = []
                for raw_operation in raw_patch["operations"]:
                    operation = {
                        key: value
                        for key, value in raw_operation.items()
                        if key not in {"after_block_id", "width"} and value is not None
                    }
                    if raw_operation["op"] in {"add_text", "add_artifact_view"}:
                        operation["placement"] = {
                            "after_block_id": raw_operation["after_block_id"],
                            "width": raw_operation["width"] or "full",
                        }
                    elif raw_operation["op"] == "reposition_block":
                        operation["after_block_id"] = raw_operation["after_block_id"]
                        operation["width"] = raw_operation["width"] or "full"
                    operations.append(operation)
                patch = ReportAssistantPatch.model_validate(
                    {"summary": raw_patch["summary"], "operations": operations}
                ).model_dump(mode="json")
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
                },
                {
                    "model_version": transport_meta.get("model_version") or route.model,
                    "model_snapshot": transport_meta.get("model_snapshot"),
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.metadata()["hash"],
                    "attempts": attempt,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                },
            )
        except (ContractError, OSError, TimeoutError, TypeError, ValueError) as error:
            last_error = error
    raise ReportAssistantModelError("Report Assistant turn model call failed") from last_error
