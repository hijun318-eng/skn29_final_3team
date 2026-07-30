from __future__ import annotations

from app.contracts import AnalysisRequest, AnalysisResponse, ErrorBody, RequestContext
from app.services.analysis_service import AnalysisService
from app.services.routing_service import RoutingError, RoutingService


class AnalysisController:
    def __init__(self, service: AnalysisService, routing: RoutingService) -> None:
        self._service = service
        self._routing = routing

    def submit(self, payload: AnalysisRequest, context: RequestContext) -> AnalysisResponse:
        try:
            decision = self._routing.decide(payload)
        except RoutingError as exc:
            return self._service.blocked(context, ErrorBody(code=exc.code, message=exc.message))
        return self._service.analyze(payload.question, context, decision)
