from __future__ import annotations

from app.contracts import AnalysisRequest, ApiResponse, RequestContext
from app.services.analysis_service import AnalysisService


class AnalysisController:
    def __init__(self, service: AnalysisService) -> None:
        self._service = service

    def submit(self, payload: AnalysisRequest, context: RequestContext) -> ApiResponse:
        return self._service.analyze(payload.question, payload.context or context)
