"""확정된 대화 슬롯을 분석 요청으로 변환하고 분석 응답의 artifact 참조를 추출한다."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.contracts import AnalysisRequest, ResolvedSlots
from app.services.conversation.slot_resolver import ResolvedTurnSlots


def build_structured_analysis_request(
    user_message: str,
    slots: ResolvedTurnSlots,
) -> AnalysisRequest:
    """확정·상속된 슬롯을 typed 요청으로 보존해 하류의 불필요한 재해석을 막는다."""

    resolved = None
    # metric_id는 상속뿐 아니라 모호성 해소로도 확정된다. 선택값을 누락하면 하류
    # model이 같은 질문을 다시 해석해 사용자의 선택과 다른 metric을 고를 수 있다.
    if (
        slots.metric_id
        or slots.is_inherited_metric
        or slots.is_inherited_period
        or slots.is_inherited_dimension
        or slots.time_range
        or slots.user_filters
    ):
        dimension_ids = tuple(
            dimension.get("column", "")
            if isinstance(dimension, dict)
            else str(dimension)
            for dimension in slots.dimension_fields
            if (isinstance(dimension, dict) and dimension.get("column"))
            or (isinstance(dimension, str) and dimension)
        )
        resolved = ResolvedSlots(
            metric_id=slots.metric_id,
            dimension_ids=dimension_ids,
            user_filters=tuple(dict(item) for item in slots.user_filters),
            period_start=(
                slots.time_range.start.isoformat() if slots.time_range else None
            ),
            period_end_exclusive=(
                slots.time_range.end_exclusive.isoformat()
                if slots.time_range
                else None
            ),
        )
    return AnalysisRequest(question=user_message, resolved_slots=resolved)


def extract_artifact_id(analysis_response: Any) -> UUID | None:
    """공개 응답의 artifact 또는 evidence 위치에서 동일한 artifact UUID를 추출한다."""

    dumped = (
        analysis_response.model_dump(mode="python")
        if hasattr(analysis_response, "model_dump")
        else {}
    )
    data = dumped.get("data") or {}
    artifact = data.get("artifact") or {}
    value = artifact.get("artifact_id")
    if not value:
        result = data.get("result") or {}
        evidence = result.get("evidence") or {}
        value = evidence.get("artifact_id")
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))
