"""검증된 파이프라인 상태와 lineage를 API의 성공·부분·차단·실패 계약으로 조립하고, 허용되지 않은 상태 전이는 예외로 드러낸다."""

from __future__ import annotations

from app.contracts import (
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ArtifactReference,
    ClarificationType,
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
from app.services.analysis_evidence import (
    _evidence_filters,
    _gate_evidence,
    _gate_history,
    _metric_term,
    _model_invocations,
    _reduce_metric_values,
)
from app.services.context_builder import ContextPackage
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


class AnalysisResponseFactory:
    """분석 실행 결과를 공통 API 계약으로 조립한다."""

    @staticmethod
    def success(
        *,
        support: PipelineSupport,
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
        """G3를 통과한 query·artifact·context를 성공 또는 부분 성공 응답으로 조립한다.

        runtime metric 규칙대로 행 값을 축약하고 source·기간·model·gate 근거를 함께 고정한다.
        호출 전 검증된 필드가 없거나 상태 전이가 잘못되면 예외를 숨기지 않으며, query의
        ``PARTIAL`` 상태만 재시도 가능한 ``PARTIAL_FAILURE``로 표현한다.
        """
        query_status = query.get("status")
        status = (
            AnalysisStatus.PARTIAL
            if query_status == "PARTIAL"
            else AnalysisStatus.SUCCEEDED
        )
        machine.transition(status)
        rows = tuple(query["rows"])
        metric_values = []
        for metric in package.metrics:
            field = metric.result_field
            if not rows or not all(field in row for row in rows):
                continue
            values = [row[field] for row in rows if row[field] is not None]
            reduced = _reduce_metric_values(metric.reduction, values)
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
        metric_ids = tuple(
            dict.fromkeys(
                [metric.id for metric in package.metrics]
                + [metric.metric_id for metric in metrics]
            )
        )
        result_fields = {metric.id: metric.result_field for metric in package.metrics}
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
        """라우팅 이전의 typed 오류를 실행 근거가 없는 ``BLOCKED`` 응답으로 만든다.

        새 상태 머신과 ROUTER 차단 trace를 생성해 SQL이나 모델 실행이 일어난 것처럼 기존
        전이를 재사용하지 않으며, 호출자가 전달한 ``ErrorBody``를 보존한다.
        """
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
        clarification_type: ClarificationType | None = None,
    ) -> AnalysisResponse:
        """실행 중 실패 stage를 trace와 상태 머신에 기록하고 표준 오류 응답을 반환한다.

        ``status``에 따라 BLOCKED/FAILED outcome을 구분하고 route·gate·repair 횟수를 보존한다.
        허용되지 않은 상태 전이는 ``InvalidTransitionError``를 전파해 모순된 응답 생성을 막는다.
        """
        AnalysisResponseFactory.record(
            trace,
            stage,
            detail or code.value,
            StageOutcome.BLOCKED
            if status == AnalysisStatus.BLOCKED
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
            ),
            meta=response_meta(context),
            error=ErrorBody(
                code=code,
                message=message,
                retryable=retryable,
                suggestions=suggestions,
                clarification_type=clarification_type,
            ),
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
        """모델 호출 실패 코드를 사용자용 메시지와 재시도 정책이 포함된 응답으로 변환한다.

        명시적 code가 없을 때만 timeout 여부로 기본 코드를 고르고, endpoint·timeout·circuit
        장애만 재시도 가능하게 표시한다. 지원하지 않는 code는 즉시 ``KeyError``로 드러난다.
        """
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
        """분석 응답 factory 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
        trace.append(TraceStep(stage=stage, outcome=outcome, detail=detail))

    @staticmethod
    def gates(decision: RouteDecision) -> GateRequirements:
        """서버의 route 판정에 고정된 G1·G2 요구 여부를 API 계약 객체로 복사한다.

        모델 출력이나 클라이언트 입력에서 gate 상태를 추론하지 않아 우회된 검증 요구가 응답에 반영되지 않게 한다.
        """
        return GateRequirements(
            g1_required=decision.requires_g1,
            g2_required=decision.requires_g2,
        )
