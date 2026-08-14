from __future__ import annotations

from typing import Any, Callable

from app.context import ContextValidationError
from app.contracts import AnalysisRequest, AnalysisResponse, ErrorCode, RequestContext
from app.services.analysis_service import AnalysisService
from app.services.routing_service import RoutingError, RoutingService


class AnalysisController:
    def __init__(self, service: AnalysisService, routing: RoutingService) -> None:
        self._service = service
        self._routing = routing

    def submit(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        execution_sink: Callable[[dict[str, Any]], None] | None = None,
        progress_sink: Callable[[object, object], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AnalysisResponse:
        try:
            decision = self._routing.decide(payload, context.role)
        except RoutingError as exc:
            raise ContextValidationError(
                exc.code,
                exc.message,
                403 if exc.code == ErrorCode.ACCESS_DENIED else 422,
            ) from exc
        return self._service.analyze(
            payload, context, decision, execution_sink, progress_sink, cancel_check
        )
