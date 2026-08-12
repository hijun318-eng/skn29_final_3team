from __future__ import annotations

from decimal import Decimal

from app.contracts import (
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ArtifactReference,
    ClarificationOption,
    ErrorBody,
    ErrorCode,
    Evidence,
    GateRequirements,
    MaskingEvidence,
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
        query_status = query.get("status")
        status = (
            AnalysisStatus.PARTIAL
            if query_status == "PARTIAL"
            else AnalysisStatus.SUCCEEDED
        )
        machine.transition(status)
        rows = tuple(query["rows"])
        first_value = next(iter(rows[0].values()), None) if rows else 0
        metrics = (
            MetricValue(
                metric_id="synthetic_result_count",
                label="합성 결과",
                value=first_value,
                unit="건",
            ),
        )
        revenue_field = next(
            (
                field
                for field in (
                    "total_guest_revenue_krw",
                    "recognized_room_revenue_krw",
                    "room_revenue",
                )
                if rows and all(field in row for row in rows)
            ),
            None,
        )
        if revenue_field == "total_guest_revenue_krw" or (
            decision.template_id == "weekly-room-operations" and revenue_field
        ):
            total = sum(Decimal(str(row[revenue_field])) for row in rows)
            metric_id = (
                "total_guest_revenue_krw"
                if revenue_field == "total_guest_revenue_krw"
                else "recognized_room_revenue"
            )
            metrics = (
                MetricValue(
                    metric_id=metric_id,
                    label=(
                        "객실·식음 통합 매출"
                        if revenue_field == "total_guest_revenue_krw"
                        else "인식 객실 매출"
                    ),
                    value=int(total) if total == total.to_integral() else float(total),
                    unit="KRW",
                ),
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
                period=(
                    PeriodEvidence.model_validate(query["period"])
                    if query.get("period", {}).get("start")
                    else support.period(context.as_of)
                ),
                filters=query.get("filters", {}),
                sources=support.sources(assets),
                query_id=str(query["query_id"]),
                artifact_id=artifact.artifact_id,
                context_release=package.context_release,
                policy_version=package.policy_version,
                model_version=str(explanation["model_version"]),
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
        clarification_options: tuple[ClarificationOption, ...] = (),
    ) -> AnalysisResponse:
        AnalysisResponseFactory.record(
            trace,
            stage,
            code.value,
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
                clarification_options=clarification_options,
            ),
        )

    @staticmethod
    def model_error(
        context: RequestContext,
        machine: AnalysisStateMachine,
        trace: list[TraceStep],
        decision: RouteDecision,
        repair_count: int = 0,
    ) -> AnalysisResponse:
        return AnalysisResponseFactory.error(
            context,
            machine,
            trace,
            PipelineStage.MODEL,
            AnalysisStatus.FAILED,
            ErrorCode.INTERNAL_ERROR,
            "모델 응답 계약을 확인할 수 없습니다.",
            decision,
            repair_count,
            retryable=True,
        )

    @staticmethod
    def record(
        trace: list[TraceStep],
        stage: PipelineStage,
        detail: str | None = None,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        trace.append(TraceStep(stage=stage, outcome=outcome, detail=detail))

    @staticmethod
    def gates(decision: RouteDecision) -> GateRequirements:
        return GateRequirements(
            g1_required=decision.requires_g1,
            g2_required=decision.requires_g2,
        )
