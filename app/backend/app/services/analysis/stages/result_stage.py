"""파이프라인 4단계: 자연어 요약 생성, 차트 규격 조립 및 Artifact 생성 단계(ResultStage) 모듈.

[핵심 목적]
1. LLM(Node 3)을 통한 실데이터 근거 기반의 자연어 요약(Summary) 생성 (Template 라우트는 자동 요약)
2. 테이블 데이터를 분석하여 지표 컬럼에 맞는 시각화 차트 규격(`ChartSpec`) 자동 구성
3. 결정론적 아티팩트 참조(`ArtifactReference`) 발급 및 최종 성공 응답(`AnalysisResponse`) 조립
4. 백그라운드 감사 로그/실행 기록 sink에 성공 데이터 전달
"""

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
from app.services.analysis.model_support import (
    is_numeric,
    model_trace_detail,
)
from app.services.analysis.pipeline_state import AnalysisPipelineState
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.context.builder import ContextPackage
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.analysis.result_narrative import (
    explanation_is_grounded,
    grounded_summary,
)


def _chart_spec(
    rows: list[dict[str, Any]],
    governed_result_fields: tuple[str, ...],
) -> ChartSpec | None:
    """결과 데이터 행들과 지표 필드들로부터 최적의 바 차트(ChartSpec) 규격을 조립합니다."""
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
    """분석 결과 요약, 차트 규격 구성 및 아티팩트 발급을 총괄하는 단계 처리기 클래스."""

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
        """결과 단계를 수행하여 최종 AnalysisResponse를 조립 및 반환합니다."""
        package = cast(ContextPackage, state.package)
        plan = cast(dict[str, Any], state.plan)
        query = cast(dict[str, Any], state.query)
        context = state.context
        decision = state.decision

        # 1. 템플릿 요약 또는 LLM Node 3 자연어 요약 생성
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
                    raise ValueError("Node3 응답 형식이 올바르지 않습니다.")
                if not explanation_is_grounded(explanation["summary"], query, package):
                    explanation = {
                        "summary": grounded_summary(query, package),
                        "model_version": "GROUNDED-NARRATIVE-v1.0.0",
                    }
            except (TimeoutError, OSError, TypeError, ValueError):
                # SQL과 G3 결과가 이미 승인된 뒤의 설명 실패는 분석값까지 숨길 이유가 없다.
                # 모델 응답을 복구하거나 추정하지 않고 같은 governed rows에서 만든 요약으로
                # 대체해 결과·설명 수치를 항상 일치시킨다.
                explanation = {
                    "summary": grounded_summary(query, package),
                    "model_version": "GROUNDED-NARRATIVE-v1.0.0",
                }

        # 2. 결정론적 아티팩트 참조 ID 발급
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

        # 3. 최종 성공 응답 조립
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

        # 4. 차트 규격 조립 및 주입
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
