from __future__ import annotations

from app.contracts import AnalysisStatus, ApiResponse, ErrorBody, ErrorCode, RequestContext, response_meta
from app.ports.data_platform import DataPlatformAdapter
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


class AnalysisService:
    """Fixed minimal transition: RECEIVED -> ROUTED -> terminal fake result."""

    def __init__(self, adapter: DataPlatformAdapter) -> None:
        self._adapter = adapter

    def analyze(self, question: str, context: RequestContext, decision: RouteDecision) -> ApiResponse:
        machine = AnalysisStateMachine()
        if not question.strip():
            return self.blocked(context, ErrorBody(code=ErrorCode.CONTEXT_INCOMPLETE, message="질문을 입력해야 합니다."))

        machine.transition(AnalysisStatus.ROUTED)
        assets = self._adapter.search_assets(question, context.model_dump(mode="json"))
        machine.transition(AnalysisStatus.SUCCEEDED)
        return ApiResponse(
            data={
                "status": AnalysisStatus.SUCCEEDED,
                "transitions": machine.history,
                "route": decision.route_type,
                "template_id": decision.template_id,
                "gates": {"g1_required": decision.requires_g1, "g2_required": decision.requires_g2},
                "result": {"summary": "Fake 분석 결과입니다.", "assets": assets},
            },
            meta=response_meta(context),
        )

    def blocked(self, context: RequestContext, error: ErrorBody) -> ApiResponse:
        machine = AnalysisStateMachine()
        machine.transition(AnalysisStatus.BLOCKED)
        return ApiResponse(data={"status": AnalysisStatus.BLOCKED, "transitions": machine.history}, meta=response_meta(context), error=error)
