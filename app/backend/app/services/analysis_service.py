from __future__ import annotations

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.contracts import AnalysisStatus, ApiResponse, ErrorBody, ErrorCode, RequestContext, response_meta


class AnalysisService:
    """Fixed minimal transition: RECEIVED -> ROUTED -> terminal fake result."""

    def __init__(self, adapter: FakeDataPlatformAdapter) -> None:
        self._adapter = adapter

    def analyze(self, question: str, context: RequestContext) -> ApiResponse:
        if not question.strip():
            return ApiResponse(
                meta=response_meta(context),
                error=ErrorBody(code=ErrorCode.CONTEXT_INCOMPLETE, message="질문을 입력해야 합니다."),
            )

        assets = self._adapter.search_assets(question, context.model_dump(mode="json"))
        return ApiResponse(
            data={
                "status": AnalysisStatus.SUCCEEDED,
                "transitions": [AnalysisStatus.RECEIVED, AnalysisStatus.ROUTED, AnalysisStatus.SUCCEEDED],
                "route": "FAKE_DATA_PLATFORM",
                "result": {"summary": "Fake 분석 결과입니다.", "assets": assets},
            },
            meta=response_meta(context),
        )
