from __future__ import annotations

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ArtifactReference,
    ErrorBody,
    ErrorCode,
    PipelineStage,
    RequestContext,
    StageOutcome,
    TraceStep,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.model import ModelAdapter
from app.services.analysis_responses import AnalysisResponseFactory
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
        self._responses = AnalysisResponseFactory()

    def analyze(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
    ) -> AnalysisResponse:
        machine = AnalysisStateMachine()
        trace: list[TraceStep] = []
        machine.transition(AnalysisStatus.ROUTED)
        self._responses.record(trace, PipelineStage.ROUTER)
        self._responses.record(trace, PipelineStage.CONTROLLER)

        assets = self._adapter.search_assets(
            payload.question,
            context.model_dump(mode="json"),
        )
        package = self._support.build_context(payload, context, assets)
        self._responses.record(trace, PipelineStage.CONTEXT, package.package_hash)

        scenario = str(payload.parameters.get("scenario") or "")
        g1_error = self._support.g1_error(scenario)
        if g1_error:
            error_code, message = g1_error
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.G1,
                AnalysisStatus.BLOCKED,
                error_code,
                message,
                decision,
            )
        self._responses.record(trace, PipelineStage.G1)

        references = [
            {"urn": item.urn, "fqn": item.fqn, "columns": list(item.columns)}
            for item in package.assets
        ]
        try:
            plan = self._model.generate(
                "node2",
                {"scenario": scenario, "references": references},
            )
        except (TimeoutError, TypeError, ValueError):
            return self._responses.model_error(context, machine, trace, decision)
        if self._support.model_plan_violation(plan):
            return self._responses.model_error(context, machine, trace, decision)
        self._responses.record(trace, PipelineStage.MODEL, plan.get("model_version"))

        repair_count = 0
        violation = self._support.g2_violation(plan, package)
        if violation == "UNSAFE_SQL":
            return self._responses.error(
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
            self._responses.record(
                trace,
                PipelineStage.G2,
                violation,
                StageOutcome.BLOCKED,
            )
            repair_count = 1
            try:
                plan = self._model.generate(
                    "node2_repair",
                    {
                        "scenario": scenario,
                        "attempt": repair_count,
                        "references": references,
                    },
                )
            except (TimeoutError, TypeError, ValueError):
                return self._responses.model_error(
                    context,
                    machine,
                    trace,
                    decision,
                    repair_count,
                )
            self._responses.record(trace, PipelineStage.REPAIR, "attempt=1")
            if (
                self._support.model_plan_violation(plan)
                or self._support.g2_violation(plan, package)
            ):
                return self._responses.error(
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
        self._responses.record(trace, PipelineStage.G2)

        gate_token = self._support.gate_token(package, str(plan["sql"]))
        try:
            query = self._adapter.execute_query(
                plan["sql"],
                plan.get("parameters", {}),
                gate_token,
            )
            query = self._adapter.get_query_status(query["query_id"])
        except (KeyError, TimeoutError, TypeError, ValueError):
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회 상태를 확인할 수 없습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        query_id = str(query.get("query_id", ""))
        self._responses.record(trace, PipelineStage.QUERY, query_id)
        query_status = query.get("status")
        if query_status == "TIMEOUT":
            try:
                terminal = self._adapter.cancel_query(query_id)
            except (KeyError, TimeoutError, TypeError, ValueError):
                terminal = {}
            if terminal.get("status") != "CANCELLED":
                return self._responses.error(
                    context,
                    machine,
                    trace,
                    PipelineStage.QUERY,
                    AnalysisStatus.FAILED,
                    ErrorCode.INTERNAL_ERROR,
                    "시간 초과 조회의 종료 상태를 확인할 수 없습니다.",
                    decision,
                    repair_count,
                )
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "조회 시간이 초과되어 취소했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        if query_status == "CANCELLED":
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.CANCELLED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "요청이 취소되었습니다.",
                decision,
                repair_count,
            )
        if query_status == "FAILED":
            return self._responses.error(
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
        if query_status not in {"SUCCEEDED", "PARTIAL"}:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회가 정상 종료 상태가 아닙니다.",
                decision,
                repair_count,
                retryable=True,
            )

        g3_violation = self._support.g3_violation(query)
        if g3_violation:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.G3,
                AnalysisStatus.FAILED,
                ErrorCode.RESULT_EVIDENCE_MISSING,
                "근거 또는 결과 범위가 유효하지 않아 Artifact를 생성하지 않았습니다.",
                decision,
                repair_count,
            )
        self._responses.record(trace, PipelineStage.G3)

        try:
            explanation = self._model.generate("node3", {"scenario": scenario})
            if (
                not isinstance(explanation, dict)
                or not isinstance(explanation.get("summary"), str)
                or not isinstance(explanation.get("model_version"), str)
            ):
                raise ValueError("invalid node3 response")
        except (TimeoutError, TypeError, ValueError):
            return self._responses.model_error(
                context,
                machine,
                trace,
                decision,
                repair_count,
            )
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
        self._responses.record(trace, PipelineStage.ARTIFACT, str(artifact_id))

        return self._responses.success(
            support=self._support,
            context=context,
            machine=machine,
            trace=trace,
            decision=decision,
            package=package,
            assets=assets,
            query=query,
            explanation=explanation,
            artifact=artifact,
            repair_count=repair_count,
        )

    def blocked(self, context: RequestContext, error: ErrorBody) -> AnalysisResponse:
        return self._responses.blocked(context, error)
