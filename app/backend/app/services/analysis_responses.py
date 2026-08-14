from __future__ import annotations

import re
from decimal import Decimal

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
    GateEvidence,
    GateHistoryEvidence,
    GateRequirements,
    MaskingEvidence,
    MetricReference,
    MetricValue,
    ModelInvocationEvidence,
    PeriodEvidence,
    PipelineStage,
    RequestContext,
    SamplingEvidence,
    StageOutcome,
    TableResult,
    TraceStep,
    response_meta,
)
from app.services.context_builder import ContextMetricTerm, ContextPackage
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


def _evidence_filters(
    filters: object,
    package: ContextPackage,
) -> dict[str, object]:
    if not isinstance(filters, dict):
        return {}
    approved = package.required_filters or tuple(
        item for metric in package.metrics for item in metric.required_filters
    )
    displayed = {}
    for name, value in filters.items():
        match = re.fullmatch(r"required_filter_(\d+)", str(name))
        index = int(match.group(1)) - 1 if match else -1
        field = approved[index].field if 0 <= index < len(approved) else str(name)
        displayed[field] = value
    return displayed


def _metric_term(package: ContextPackage, metric_id: str) -> ContextMetricTerm:
    try:
        return next(term for term in package.metric_terms if term.id == metric_id)
    except StopIteration as error:
        raise ValueError(
            f"Approved Context is missing DataHub Metric Glossary Term: {metric_id}"
        ) from error


def _model_invocations(trace: list[TraceStep]) -> tuple[ModelInvocationEvidence, ...]:
    invocations: list[ModelInvocationEvidence] = []
    for step in trace:
        if step.stage not in {PipelineStage.MODEL, PipelineStage.REPAIR} or not step.detail:
            continue
        fields = {}
        for item in step.detail.split(";"):
            key, separator, value = item.partition("=")
            if separator:
                fields[key] = value
        prompt_id, separator, prompt_version = fields.get("prompt", "").rpartition("@")
        node = fields.get("node")
        model_version = fields.get("model")
        if not separator or not node or not model_version or not prompt_id or not prompt_version:
            continue
        if "unknown" in {node, model_version, prompt_id, prompt_version}:
            continue
        invocations.append(
            ModelInvocationEvidence(
                node=node,
                model_version=model_version,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
            )
        )
    return tuple(invocations)


def _gate_evidence(trace: list[TraceStep]) -> GateEvidence:
    outcomes = {
        step.stage: step.outcome
        for step in trace
        if step.stage in {PipelineStage.G1, PipelineStage.G2, PipelineStage.G3}
    }
    missing = [
        stage.value
        for stage in (PipelineStage.G1, PipelineStage.G2, PipelineStage.G3)
        if stage not in outcomes
    ]
    if missing:
        raise ValueError(f"successful analysis is missing gate evidence: {', '.join(missing)}")
    return GateEvidence(
        g1=outcomes[PipelineStage.G1],
        g2=outcomes[PipelineStage.G2],
        g3=outcomes[PipelineStage.G3],
    )


def _gate_history(trace: list[TraceStep]) -> GateHistoryEvidence:
    return GateHistoryEvidence(
        g1=tuple(step.outcome for step in trace if step.stage == PipelineStage.G1),
        g2=tuple(step.outcome for step in trace if step.stage == PipelineStage.G2),
        g3=tuple(step.outcome for step in trace if step.stage == PipelineStage.G3),
    )


def _reduce_metric_values(reduction: str, values: list[object]) -> Decimal | None:
    if not values:
        return None
    decimals = [Decimal(str(value)) for value in values]
    if reduction == "sum":
        return sum(decimals, Decimal(0))
    if reduction == "min":
        return min(decimals, default=None)
    if reduction == "max":
        return max(decimals, default=None)
    if reduction == "average" and decimals:
        return sum(decimals, Decimal(0)) / len(decimals)
    if reduction == "scalar" and len(decimals) == 1:
        return decimals[0]
    # Formula/ratio metrics require approved components, not a sum of row ratios.
    return None


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
        metrics: tuple[MetricValue, ...] = ()
        selected_metric = package.metrics[0] if len(package.metrics) == 1 else None
        selected_term = (
            _metric_term(package, selected_metric.id) if selected_metric else None
        )
        selected_metric_field = selected_metric.result_field if selected_metric else None
        if selected_metric_field and rows and all(
            selected_metric_field in row for row in rows
        ):
            values = [row[selected_metric_field] for row in rows if row[selected_metric_field] is not None]
            reduced = _reduce_metric_values(selected_metric.reduction, values)
            if reduced is not None:
                metrics = (
                    MetricValue(
                        metric_id=selected_metric.id,
                        result_field=selected_metric_field,
                        label=selected_term.label,
                        definition=selected_term.definition,
                        value=int(reduced) if reduced == reduced.to_integral() else float(reduced),
                        unit=selected_metric.unit or selected_term.unit,
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
            values = [row[revenue_field] for row in rows if row[revenue_field] is not None]
            if not values:
                revenue_field = None
        if revenue_field == "total_guest_revenue_krw" or (
            decision.template_id == "weekly-room-operations" and revenue_field
        ):
            total = sum(Decimal(str(value)) for value in values)
            metric_id = (
                "total_guest_revenue_krw"
                if revenue_field == "total_guest_revenue_krw"
                else "recognized_room_revenue"
            )
            term = _metric_term(package, metric_id)
            metrics = (
                MetricValue(
                    metric_id=metric_id,
                    result_field=revenue_field,
                    label=term.label,
                    definition=term.definition,
                    value=int(total) if total == total.to_integral() else float(total),
                    unit=term.unit,
                ),
            )
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
                    else support.period(context.as_of)
                ),
                filters=_evidence_filters(query.get("filters", {}), package),
                sources=support.sources(assets),
                query_id=str(query["query_id"]),
                artifact_id=artifact.artifact_id,
                context_release=package.context_release,
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
        trace.append(TraceStep(stage=stage, outcome=outcome, detail=detail))

    @staticmethod
    def gates(decision: RouteDecision) -> GateRequirements:
        return GateRequirements(
            g1_required=decision.requires_g1,
            g2_required=decision.requires_g2,
        )
