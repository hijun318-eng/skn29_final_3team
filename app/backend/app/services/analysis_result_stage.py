"""G3 query에 검증된 설명과 결정론적 artifact ID·chart를 결합하며, model 계약 실패 시 근거 없는 성공 응답 대신 typed 오류를 반환한다."""

from __future__ import annotations

from typing import Any, cast

from app.contracts import (
    AnalysisResponse,
    ArtifactReference,
    ChartSpec,
    PipelineStage,
    RouteType,
)
from app.ports.model import ModelAdapter
from app.services.analysis_model_support import (
    is_numeric,
    model_failure_code,
    model_trace_detail,
)
from app.services.analysis_pipeline_state import AnalysisPipelineState
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextPackage
from app.services.pipeline_support import PipelineSupport


def _chart_spec(
    rows: list[dict[str, Any]],
    governed_result_fields: tuple[str, ...],
) -> ChartSpec | None:
    if not rows:
        return None
    columns = tuple(rows[0])
    numeric_fields = tuple(
        column
        for column in columns
        if all(is_numeric(row.get(column)) for row in rows)
    )
    y_fields = tuple(
        field
        for field in governed_result_fields
        if field in numeric_fields
    )
    if y_fields:
        x_candidates = tuple(
            column
            for column in columns
            if column not in y_fields and column not in numeric_fields
        ) or tuple(column for column in columns if column not in y_fields)
        if not x_candidates:
            return None
        x_field = x_candidates[0]
    else:
        x_candidates = tuple(
            column for column in columns if column not in numeric_fields
        ) or columns[:1]
        if not x_candidates:
            return None
        x_field = x_candidates[0]
        y_fields = tuple(
            column for column in numeric_fields if column != x_field
        )
    if not y_fields:
        return None
    return ChartSpec(chart_type="bar", x_field=x_field, y_fields=y_fields)


class AnalysisResultStage:
    """AnalysisResultStage는 분석 결과 단계 단계의 입력, 상태 전이, 다음 처리 결과를 조정한다."""
    def __init__(
        self,
        model: ModelAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
    ) -> None:
        self._model = model
        self._support = support
        self._responses = responses

    async def run(self, state: AnalysisPipelineState) -> AnalysisResponse:
        """G3 검증 결과를 설명·artifact lineage·선택적 chart가 포함된 최종 응답으로 조립한다.

        일반 route의 설명은 node3 계약을 검증하고 template route는 모델을 호출하지 않는다.
        request/query/context hash로 artifact ID를 고정하며, 모델 실패는 typed 오류 응답으로
        반환한다. execution sink에는 성공 응답을 만든 동일 plan·query·package만 전달한다.
        """
        package = cast(ContextPackage, state.package)
        plan = cast(dict[str, Any], state.plan)
        query = cast(dict[str, Any], state.query)
        context = state.context
        decision = state.decision
        if decision.route_type is RouteType.TEMPLATE:
            explanation = {
                "summary": f"승인된 분석에서 {len(query['rows'])}건을 조회했습니다.",
                "model_version": "TEMPLATE-RESULT-v1.0.0",
            }
        else:
            try:
                explanation = await state.budget.call(
                    self._model,
                    "node3",
                    {
                        "query": query,
                        "assets": state.assets,
                        "context": context,
                        "package": package,
                    },
                )
                state.record(
                    PipelineStage.MODEL,
                    model_trace_detail(self._model),
                )
                if (
                    not isinstance(explanation, dict)
                    or not isinstance(explanation.get("summary"), str)
                    or not isinstance(explanation.get("model_version"), str)
                ):
                    raise ValueError("invalid node3 response")
            except (TimeoutError, OSError, TypeError, ValueError) as error:
                return self._responses.model_error(
                    context,
                    state.machine,
                    state.trace,
                    decision,
                    state.repair_count,
                    code=model_failure_code(error),
                )
        artifact_id = self._support.artifact_id(
            str(context.request_id),
            query["query_id"],
            package.package_hash,
        )
        artifact = ArtifactReference(
            artifact_id=artifact_id,
            query_id=query["query_id"],
            context_hash=package.package_hash,
        )
        state.record(PipelineStage.ARTIFACT, str(artifact_id))

        response = self._responses.success(
            support=self._support,
            context=context,
            machine=state.machine,
            trace=state.trace,
            decision=decision,
            package=package,
            assets=state.assets,
            query=query,
            explanation=explanation,
            artifact=artifact,
            repair_count=state.repair_count,
            cached=state.result_cached,
        )
        rows = query["rows"]
        if rows and response.data.result is not None:
            chart = _chart_spec(
                rows,
                tuple(metric.result_field for metric in package.metrics),
            )
            if chart is not None:
                response.data.result.chart = chart
        if state.execution_sink is not None:
            state.execution_sink({"plan": plan, "query": query, "package": package})
        return response
