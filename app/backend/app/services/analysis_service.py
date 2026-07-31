from __future__ import annotations

from app.contracts import (
    AnalysisData,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ArtifactReference,
    ErrorBody,
    ErrorCode,
    Evidence,
    GateRequirements,
    PipelineStage,
    RequestContext,
    StageOutcome,
    TableResult,
    TraceStep,
    response_meta,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.model import ModelAdapter
from app.services.context_builder import ContextPackageBuilder
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


class AnalysisService:
    """R4가 소유하는 결정론적 Gate·query·Artifact 제어 흐름."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        context_builder: ContextPackageBuilder | None = None,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._support = PipelineSupport(
            adapter,
            context_builder or ContextPackageBuilder(),
        )

    def analyze(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
    ) -> AnalysisResponse:
        machine = AnalysisStateMachine()
        trace: list[TraceStep] = []
        machine.transition(AnalysisStatus.ROUTED)
        self._record(trace, PipelineStage.ROUTER)
        self._record(trace, PipelineStage.CONTROLLER)

        assets = self._adapter.search_assets(
            payload.question,
            context.model_dump(mode="json"),
        )
        package = self._support.build_context(payload, context, assets)
        self._record(trace, PipelineStage.CONTEXT, package.package_hash)

        scenario = str(payload.parameters.get("scenario") or "")
        if scenario == "clarification":
            return self._error(
                context,
                machine,
                trace,
                PipelineStage.G1,
                AnalysisStatus.BLOCKED,
                ErrorCode.CONTEXT_INCOMPLETE,
                "분석 기간 또는 기준을 보완해 주세요.",
                decision,
            )
        self._record(trace, PipelineStage.G1)

        references = [
            {"urn": item.urn, "fqn": item.fqn, "columns": list(item.columns)}
            for item in package.assets
        ]
        plan = self._model.generate(
            "node2",
            {"scenario": scenario, "references": references},
        )
        self._record(trace, PipelineStage.MODEL, plan.get("model_version"))

        repair_count = 0
        violation = self._support.g2_violation(plan, package)
        if violation == "UNSAFE_SQL":
            return self._error(
                context,
                machine,
                trace,
                PipelineStage.G2,
                AnalysisStatus.BLOCKED,
                ErrorCode.SQL_POLICY_BLOCKED,
                "조회 전용 SQL만 허용합니다.",
                decision,
            )
        if violation:
            self._record(trace, PipelineStage.G2, violation, StageOutcome.BLOCKED)
            repair_count = 1
            plan = self._model.generate(
                "node2_repair",
                {
                    "scenario": scenario,
                    "attempt": repair_count,
                    "references": references,
                },
            )
            self._record(trace, PipelineStage.REPAIR, "attempt=1")
            if self._support.g2_violation(plan, package):
                return self._error(
                    context,
                    machine,
                    trace,
                    PipelineStage.G2,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SQL_POLICY_BLOCKED,
                    "SQL repair 1회 후에도 정책 검증을 통과하지 못했습니다.",
                    decision,
                    repair_count,
                )
        self._record(trace, PipelineStage.G2)

        gate_token = self._support.gate_token(package, str(plan["sql"]))
        query = self._adapter.execute_query(
            plan["sql"],
            plan.get("parameters", {}),
            gate_token,
        )
        query = self._adapter.get_query_status(query["query_id"])
        if query["status"] == "FAILED":
            return self._error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회에 실패했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        self._record(trace, PipelineStage.QUERY, query["query_id"])

        if not query.get("evidence_complete"):
            return self._error(
                context,
                machine,
                trace,
                PipelineStage.G3,
                AnalysisStatus.FAILED,
                ErrorCode.RESULT_EVIDENCE_MISSING,
                "근거가 완전하지 않아 Artifact를 생성하지 않았습니다.",
                decision,
                repair_count,
            )
        self._record(trace, PipelineStage.G3)

        explanation = self._model.generate("node3", {"scenario": scenario})
        artifact_id = self._support.artifact_id(
            context.trace_id,
            query["query_id"],
            package.package_hash,
        )
        artifact = ArtifactReference(
            artifact_id=artifact_id,
            query_id=query["query_id"],
            context_hash=package.package_hash,
        )
        self._record(trace, PipelineStage.ARTIFACT, str(artifact_id))

        status = (
            AnalysisStatus.PARTIAL
            if query["status"] == "PARTIAL"
            else AnalysisStatus.SUCCEEDED
        )
        machine.transition(status)
        rows = tuple(query["rows"])
        result = AnalysisResult(
            summary=explanation["summary"],
            table=TableResult(
                columns=tuple(rows[0]) if rows else (),
                rows=rows,
            ),
            evidence=Evidence(
                as_of=context.as_of,
                sources=self._support.sources(assets),
                query_id=query["query_id"],
                artifact_id=artifact_id,
                context_release=package.context_release,
                policy_version=package.policy_version,
                model_version=explanation["model_version"],
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
                gates=self._gates(decision),
                result=result,
                trace=tuple(trace),
                repair_count=repair_count,
                artifact=artifact,
            ),
            meta=response_meta(context),
            error=error,
        )

    def blocked(self, context: RequestContext, error: ErrorBody) -> AnalysisResponse:
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

    def _error(
        self,
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
    ) -> AnalysisResponse:
        self._record(
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
                gates=self._gates(decision),
                trace=tuple(trace),
                repair_count=repair_count,
            ),
            meta=response_meta(context),
            error=ErrorBody(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )

    @staticmethod
    def _record(
        trace: list[TraceStep],
        stage: PipelineStage,
        detail: str | None = None,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        trace.append(TraceStep(stage=stage, outcome=outcome, detail=detail))

    @staticmethod
    def _gates(decision: RouteDecision) -> GateRequirements:
        return GateRequirements(
            g1_required=decision.requires_g1,
            g2_required=decision.requires_g2,
        )
