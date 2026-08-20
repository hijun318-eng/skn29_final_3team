"""분석 파이프라인의 성공/부분성공/차단/실패/모호성해소 응답 조립 팩토리(Response Factory) 모듈.

[핵심 목적]
파이프라인 실행 중 각 단계(Router, Context, Model, G1~G3, Query, Result)의 상태 머신 전이와
트레이스 이력(`trace`), 검증된 SQL/결과 테이블, 아티팩트(`ArtifactReference`)를
일관된 표준 API 응답 계약(`AnalysisResponse`)으로 조립합니다.
"""

from __future__ import annotations

from app.contracts import (
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ArtifactReference,
    ClarificationType,
    DisambiguationOption,
    ErrorBody,
    ErrorCode,
    Evidence,
    GateRequirements,
    MaskingEvidence,
    MetricReference,
    MetricValue,
    PeriodEvidence,
    PipelineStage,
    RequestContext,
    SamplingEvidence,
    StageOutcome,
    TableResult,
    TraceStep,
    response_meta,
)
from app.services.analysis.evidence import (
    _evidence_filters,
    _gate_evidence,
    _gate_history,
    _metric_term,
    _model_invocations,
    _reduce_context_metric,
)
from app.services.context.builder import ContextMetric, ContextPackage
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


def _business_metrics(package: ContextPackage) -> tuple[ContextMetric, ...]:
    """Return only metrics that have an approved user-facing glossary term.

    SUPPORT metrics remain in ``ContextPackage.metrics`` because ratio metrics need
    their operands during planning and execution.  They deliberately have no
    BUSINESS glossary term, so they must not leak into result values or evidence.
    The context builder already enforces an exact BUSINESS metric/term boundary;
    using that boundary here keeps every derived metric on the same path.
    """

    business_ids = {term.id for term in package.metric_terms}
    return tuple(metric for metric in package.metrics if metric.id in business_ids)


def _presentation_rows(
    package: ContextPackage,
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """내부 계산 Metric 컬럼을 제거한 사용자용 결과 행을 반환한다.

    SUPPORT Metric은 ratio 검증·reduction을 위해 원시 query 실행 상태에만 남긴다.
    승인된 BUSINESS Glossary Term이 없으므로 API table·chart와 이 table에서 영속되는
    artifact snapshot에는 노출하지 않는다. 차원·시간 컬럼과 BUSINESS Metric 결과 필드는
    입력 순서를 그대로 보존한다.
    """

    business_ids = {term.id for term in package.metric_terms}
    hidden_fields = {
        metric.result_field
        for metric in package.metrics
        if metric.id not in business_ids
    }
    return tuple(
        {
            field: value
            for field, value in row.items()
            if field not in hidden_fields
        }
        for row in rows
    )


class AnalysisResponseFactory:
    """분석 실행 결과를 공통 API 계약(AnalysisResponse)으로 조립하는 팩토리 클래스."""

    @staticmethod
    def success(
        *,
        support: Any,
        context: RequestContext,
        machine: AnalysisStateMachine,
        trace: list[TraceStep],
        decision: RouteDecision,
        package: ContextPackage,
        assets: list[dict[str, object]],
        query: dict[str, object],
        explanation: dict[str, object],
        artifact: ArtifactReference,
        repair_count: int,
        cached: bool = False,
    ) -> AnalysisResponse:
        """G3 게이트를 통과한 정상 실행 결과를 SUCCEEDED 또는 PARTIAL 상태의 AnalysisResponse로 조립합니다."""
        query_status = query.get("status")
        status = (
            AnalysisStatus.PARTIAL
            if query_status == "PARTIAL"
            else AnalysisStatus.SUCCEEDED
        )
        machine.transition(status)
        source_rows = tuple(query["rows"])
        rows = _presentation_rows(package, source_rows)
        presentation_metrics = _business_metrics(package)
        metric_values = []
        for metric in presentation_metrics:
            field = metric.result_field
            if not source_rows or not all(field in row for row in source_rows):
                continue
            reduced = _reduce_context_metric(metric, package, source_rows)
            if reduced is not None:
                term = _metric_term(package, metric.id)
                metric_values.append(
                    MetricValue(
                        metric_id=metric.id,
                        result_field=field,
                        label=term.label,
                        definition=term.definition,
                        value=int(reduced) if reduced == reduced.to_integral() else float(reduced),
                        unit=metric.unit or term.unit,
                    )
                )
        metrics = tuple(metric_values)
        metric_ids = tuple(metric.id for metric in presentation_metrics)
        result_fields = {
            metric.id: metric.result_field for metric in presentation_metrics
        }
        result_fields.update(
            {metric.metric_id: metric.result_field for metric in metrics}
        )
        evidence_metrics = tuple(
            MetricReference(
                metric_id=metric_id,
                result_field=result_fields[metric_id],
                label=_metric_term(package, metric_id).label,
                definition=_metric_term(package, metric_id).definition,
                unit=_metric_term(package, metric_id).unit,
            )
            for metric_id in metric_ids
        )
        result = AnalysisResult(
            summary=str(explanation["summary"]),
            metrics=metrics,
            table=TableResult(
                columns=tuple(rows[0]) if rows else (),
                rows=rows,
            ),
            evidence=Evidence(
                as_of=context.as_of,
                timezone=context.timezone,
                period=(
                    PeriodEvidence.model_validate(query["period"])
                    if query.get("period", {}).get("start")
                    else support.period(context.as_of, package)
                ),
                filters=_evidence_filters(query.get("filters", {}), package),
                sources=support.sources(assets),
                query_id=str(query["query_id"]),
                artifact_id=artifact.artifact_id,
                context_release=package.context_release,
                product_release_id=package.product_release_id,
                evidence_cutoff=package.evidence_cutoff,
                policy_version=package.policy_version,
                model_version=str(explanation["model_version"]),
                metrics=evidence_metrics,
                metric_values=metrics,
                models=_model_invocations(trace),
                gates=_gate_evidence(trace),
                gate_history=_gate_history(trace),
                sampling=SamplingEvidence.model_validate(
                    query.get(
                        "sampling",
                        {
                            "returned_rows": len(rows),
                            "total_rows": len(rows),
                        },
                    )
                ),
                masking=MaskingEvidence.model_validate(
                    query.get("masking", {})
                ),
                cached=cached,
            ),
        )
        error = (
            ErrorBody(
                code=ErrorCode.PARTIAL_FAILURE,
                message="일부 원천 결과만 반환했습니다.",
                retryable=True,
            )
            if status == AnalysisStatus.PARTIAL
            else None
        )
        return AnalysisResponse(
            data=AnalysisData(
                status=status,
                transitions=machine.history,
                route=decision.route_type,
                template_id=decision.template_id,
                gates=AnalysisResponseFactory.gates(decision),
                result=result,
                trace=tuple(trace),
                repair_count=repair_count,
                artifact=artifact,
            ),
            meta=response_meta(context),
            error=error,
        )

    @staticmethod
    def blocked(context: RequestContext, error: ErrorBody) -> AnalysisResponse:
        """라우팅 또는 선행 거버넌스 단계에서 차단된 BLOCKED 응답을 생성합니다."""
        machine = AnalysisStateMachine()
        machine.transition(AnalysisStatus.BLOCKED)
        return AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.BLOCKED,
                transitions=machine.history,
                trace=(
                    TraceStep(
                        stage=PipelineStage.ROUTER,
                        outcome=StageOutcome.BLOCKED,
                        detail=error.code.value,
                    ),
                ),
            ),
            meta=response_meta(context),
            error=error,
        )

    @staticmethod
    def error(
        context: RequestContext,
        machine: AnalysisStateMachine,
        trace: list[TraceStep],
        stage: PipelineStage,
        status: AnalysisStatus,
        code: ErrorCode,
        message: str,
        decision: RouteDecision,
        repair_count: int = 0,
        retryable: bool = False,
        detail: str | None = None,
        suggestions: tuple[str, ...] = (),
        disambiguation_options: tuple[DisambiguationOption, ...] = (),
        clarification_type: ClarificationType | None = None,
    ) -> AnalysisResponse:
        """파이프라인 실행 도중 발생한 에러를 기록하고 표준 실패/차단 응답을 반환합니다."""
        AnalysisResponseFactory.record(
            trace,
            stage,
            detail or code.value,
            StageOutcome.BLOCKED
            if status in (AnalysisStatus.BLOCKED, AnalysisStatus.CLARIFICATION_REQUIRED)
            else StageOutcome.FAILED,
        )
        machine.transition(status)
        return AnalysisResponse(
            data=AnalysisData(
                status=status,
                transitions=machine.history,
                route=decision.route_type,
                template_id=decision.template_id,
                gates=AnalysisResponseFactory.gates(decision),
                trace=tuple(trace),
                repair_count=repair_count,
                disambiguation_options=disambiguation_options,
            ),
            meta=response_meta(context),
            error=ErrorBody(
                code=code,
                message=message,
                retryable=retryable,
                suggestions=suggestions,
                disambiguation_options=disambiguation_options,
                clarification_type=clarification_type,
            ),
        )

    @staticmethod
    def clarification_required(
        context: RequestContext,
        machine: AnalysisStateMachine,
        trace: list[TraceStep],
        stage: PipelineStage,
        message: str,
        decision: RouteDecision,
        suggestions: tuple[str, ...] = (),
        disambiguation_options: tuple[DisambiguationOption, ...] = (),
        clarification_type: ClarificationType | None = None,
    ) -> AnalysisResponse:
        """모호성이 발생했을 때 CLARIFICATION_REQUIRED 상태와 사용자 선택지를 담은 응답을 반환합니다."""
        return AnalysisResponseFactory.error(
            context=context,
            machine=machine,
            trace=trace,
            stage=stage,
            status=AnalysisStatus.CLARIFICATION_REQUIRED,
            code=ErrorCode.CONTEXT_INCOMPLETE,
            message=message,
            decision=decision,
            suggestions=suggestions,
            disambiguation_options=disambiguation_options,
            clarification_type=clarification_type,
        )

    @staticmethod
    def model_error(
        context: RequestContext,
        machine: AnalysisStateMachine,
        trace: list[TraceStep],
        decision: RouteDecision,
        repair_count: int = 0,
        *,
        timed_out: bool = False,
        code: ErrorCode | None = None,
    ) -> AnalysisResponse:
        """LLM 모델 호출 실패 코드를 사용자 친화적 메시지와 재시도 정책이 포함된 응답으로 변환합니다."""
        resolved_code = code or (
            ErrorCode.MODEL_TIMEOUT if timed_out else ErrorCode.MODEL_CONTRACT_INVALID
        )
        messages = {
            ErrorCode.MODEL_TIMEOUT: "모델 응답 시간이 초과되었습니다.",
            ErrorCode.MODEL_ENDPOINT_UNAVAILABLE: "모델 서비스에 연결할 수 없습니다.",
            ErrorCode.MODEL_CONTRACT_INVALID: "모델 응답 계약을 검증하지 못했습니다.",
            ErrorCode.MODEL_OUTPUT_UNGROUNDED: "모델 응답을 승인된 근거로 확인하지 못했습니다.",
            ErrorCode.CIRCUIT_OPEN: "모델 서비스 보호 회로가 열려 있습니다.",
            ErrorCode.INSUFFICIENT_CONTEXT: "분석에 필요한 정보가 부족합니다.",
            ErrorCode.UNREPAIRABLE: "안전하게 수정 가능한 모델 응답을 만들지 못했습니다.",
        }
        return AnalysisResponseFactory.error(
            context,
            machine,
            trace,
            PipelineStage.MODEL,
            AnalysisStatus.FAILED,
            resolved_code,
            messages[resolved_code],
            decision,
            repair_count,
            retryable=resolved_code in {
                ErrorCode.MODEL_TIMEOUT,
                ErrorCode.MODEL_ENDPOINT_UNAVAILABLE,
                ErrorCode.CIRCUIT_OPEN,
            },
        )

    @staticmethod
    def record(
        trace: list[TraceStep],
        stage: PipelineStage,
        detail: str | None = None,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        """트레이스 단계 리스트에 새 단계 실행 결과를 추가합니다."""
        trace.append(TraceStep(stage=stage, outcome=outcome, detail=detail))

    @staticmethod
    def gates(decision: RouteDecision) -> GateRequirements:
        """라우팅 결정에 따른 G1/G2 게이트 필수 요구 여부를 반환합니다."""
        return GateRequirements(
            g1_required=decision.requires_g1,
            g2_required=decision.requires_g2,
        )
