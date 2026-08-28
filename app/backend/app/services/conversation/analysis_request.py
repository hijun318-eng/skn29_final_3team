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
        or slots.metric_ids
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
            metric_ids=slots.metric_ids,
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
            comparison_period_start=(
                slots.comparison_time_range.start.isoformat()
                if slots.comparison_time_range
                else None
            ),
            comparison_period_end_exclusive=(
                slots.comparison_time_range.end_exclusive.isoformat()
                if slots.comparison_time_range
                else None
            ),
            analysis_operation=slots.analysis_operation,
            analysis_time_bucket=slots.analysis_time_bucket,
            result_limit=slots.result_limit,
        )
    return AnalysisRequest(question=user_message, resolved_slots=resolved)


def build_replay_analysis_request(
    definition: dict[str, Any],
    parameters: dict[str, object],
) -> AnalysisRequest:
    """저장 시 확정된 슬롯으로 재실행 요청을 만들고 현재 거버넌스에서 다시 검증한다."""

    semantic_request = definition.get("semantic_request")
    snapshot = (
        semantic_request.get("resolved_slots")
        if isinstance(semantic_request, dict)
        else None
    )
    return AnalysisRequest(
        question=str(definition["question"]),
        parameters=parameters,
        resolved_slots=_resolved_slots_from_snapshot(snapshot, parameters),
    )


def _resolved_slots_from_snapshot(
    snapshot: object,
    parameters: dict[str, object],
) -> ResolvedSlots | None:
    """대화 Turn의 승인 슬롯 snapshot만 공개 ``ResolvedSlots`` 계약으로 축소한다."""

    if not isinstance(snapshot, dict):
        return None
    metric_ids = tuple(
        str(item)
        for item in snapshot.get("metric_ids", ())
        if isinstance(item, str) and item.strip()
    )
    metric_id = snapshot.get("metric_id")
    if not isinstance(metric_id, str) or not metric_id.strip():
        metric_id = None
    if not metric_ids and metric_id is None:
        return None

    raw_dimensions = snapshot.get("dimension_ids")
    if not isinstance(raw_dimensions, (list, tuple)):
        raw_dimensions = snapshot.get("dimension_fields", ())
    dimension_ids = tuple(
        str(item.get("column"))
        if isinstance(item, dict) and item.get("column")
        else str(item)
        for item in raw_dimensions
        if (isinstance(item, dict) and item.get("column"))
        or (isinstance(item, str) and item)
    )
    raw_filters = snapshot.get("user_filters", ())
    user_filters = tuple(
        {str(key): str(value) for key, value in item.items() if value is not None}
        for item in raw_filters
        if isinstance(item, dict)
    )
    period = snapshot.get("time_range")
    comparison_period = snapshot.get("comparison_time_range")
    parameter_period_start = parameters.get("period_start")
    parameter_period_end = parameters.get("period_end_exclusive")
    period_start = (
        parameter_period_start
        if isinstance(parameter_period_start, str)
        else period.get("start")
        if isinstance(period, dict)
        else None
    )
    period_end_exclusive = (
        parameter_period_end
        if isinstance(parameter_period_end, str)
        else period.get("end_exclusive")
        if isinstance(period, dict)
        else None
    )
    return ResolvedSlots(
        metric_id=metric_id,
        metric_ids=metric_ids,
        dimension_ids=dimension_ids,
        user_filters=user_filters,
        period_start=str(period_start) if period_start is not None else None,
        period_end_exclusive=(
            str(period_end_exclusive)
            if period_end_exclusive is not None
            else None
        ),
        comparison_period_start=(
            str(comparison_period.get("start"))
            if isinstance(comparison_period, dict) and comparison_period.get("start")
            else None
        ),
        comparison_period_end_exclusive=(
            str(comparison_period.get("end_exclusive"))
            if isinstance(comparison_period, dict)
            and comparison_period.get("end_exclusive")
            else None
        ),
        analysis_operation=(
            str(snapshot["analysis_operation"])
            if snapshot.get("analysis_operation") is not None
            else None
        ),
        analysis_time_bucket=(
            str(snapshot["analysis_time_bucket"])
            if snapshot.get("analysis_time_bucket") is not None
            else None
        ),
        result_limit=snapshot.get("result_limit"),
    )


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
