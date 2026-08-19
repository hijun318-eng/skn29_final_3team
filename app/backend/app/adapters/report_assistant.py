"""승인 분석 artifact만 사용해 보고서 제목·요약·시각화 label 제안을 모델에서 생성한다."""

from __future__ import annotations

import os
from time import perf_counter

from app.adapters.contract_model import openai_transport
from app.adapters.model_schemas import PROMPT_IDS, request_definition, response_definition
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
