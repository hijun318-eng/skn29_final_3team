from __future__ import annotations

from app.contracts import (
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ErrorBody,
    ErrorCode,
    Evidence,
    GateRequirements,
    RequestContext,
    SourceReference,
    response_meta,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.context_policy import ContextGateInputProvider
from app.services.context_gate import ContextGate
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


class AnalysisService:
    """Fixed minimal transition: RECEIVED -> ROUTED -> terminal fake result."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        context_gate: ContextGate,
        context_provider: ContextGateInputProvider,
    ) -> None:
        self._adapter = adapter
        self._context_gate = context_gate
        self._context_provider = context_provider

    def analyze(self, question: str, context: RequestContext, decision: RouteDecision) -> AnalysisResponse:
        machine = AnalysisStateMachine()
        if not question.strip():
            return self.blocked(context, ErrorBody(code=ErrorCode.CONTEXT_INCOMPLETE, message="질문을 입력해야 합니다."))

        machine.transition(AnalysisStatus.ROUTED)
        assets = self._adapter.search_assets(question, context.model_dump(mode="json"))
        gate_result = None
        if decision.requires_g1:
            gate_request = self._context_provider.prepare(assets, context, decision)
            gate_result = self._context_gate.evaluate(gate_request)
            if not gate_result.allowed:
                machine.transition(AnalysisStatus.BLOCKED)
                return self.blocked(
                    context,
                    ErrorBody(
                        code=gate_result.error_code or ErrorCode.CONTEXT_INCOMPLETE,
                        message=f"G1 Context Gate가 요청을 차단했습니다: {gate_result.reason_code.value}",
                    ),
                    machine,
                )
        machine.transition(AnalysisStatus.SUCCEEDED)
        sources = tuple(
            SourceReference(
                urn=asset["urn"],
                fqn=asset["fqn"],
                name=asset["name"],
                schema_version=asset["schema_version"],
                seed_version=asset["seed_version"],
            )
            for asset in assets
        )
        return AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.SUCCEEDED,
                transitions=machine.history,
                route=decision.route_type,
                template_id=decision.template_id,
                gates=GateRequirements(
                    g1_required=decision.requires_g1,
                    g2_required=decision.requires_g2,
                ),
                result=AnalysisResult(
                    summary="Fake 분석 결과입니다.",
                    evidence=Evidence(
                        as_of=context.as_of,
                        sources=sources,
                        context_release=(
                            gate_request.package.context_release
                            if gate_result is not None
                            else None
                        ),
                        policy_version=(
                            gate_request.package.policy_version
                            if gate_result is not None
                            else None
                        ),
                    ),
                ),
            ),
            meta=response_meta(context),
        )

    def blocked(
        self,
        context: RequestContext,
        error: ErrorBody,
        machine: AnalysisStateMachine | None = None,
    ) -> AnalysisResponse:
        machine = machine or AnalysisStateMachine()
        if machine.history[-1] is not AnalysisStatus.BLOCKED:
            machine.transition(AnalysisStatus.BLOCKED)
        return AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.BLOCKED,
                transitions=machine.history,
            ),
            meta=response_meta(context),
            error=error,
        )
