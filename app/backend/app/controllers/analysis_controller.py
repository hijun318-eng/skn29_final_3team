"""요청 orchestration controller의 공개 계약을 제공한다."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.context import ContextValidationError
from app.contracts import AnalysisRequest, AnalysisResponse, ErrorCode, RequestContext
from app.services.analysis import AnalysisService
from app.services.execution_control import ModelCallBudget
from app.services.routing_service import RoutingError, RoutingService


class AnalysisController:
    """AnalysisController는 분석 컨트롤러 단계의 입력, 상태 전이, 다음 처리 결과를 조정한다."""
    def __init__(self, service: AnalysisService, routing: RoutingService) -> None:
        self._service = service
        self._routing = routing

    @property
    def data_platform(self):
        """singleton service가 소유한 DataPlatformAdapter를 다른 조정자가 재사용하도록 위임한다."""
        return self._service.data_platform

    @property
    def support(self):
        """singleton service가 소유한 PipelineSupport를 다른 조정자가 재사용하도록 위임한다."""
        return self._service.support

    async def submit(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        execution_sink: Callable[[dict[str, Any]], None] | None = None,
        progress_sink: Callable[[object, object], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        run_admission_sink: Callable[[], Awaitable[None]] | None = None,
        model_budget: ModelCallBudget | None = None,
    ) -> AnalysisResponse:
        """권한별 route 결정을 먼저 확정한 뒤 동일 결정을 분석 pipeline에 전달한다.

        라우팅의 접근 거부와 입력 모호성은 각각 403·422 Context 오류로 변환하며,
        실행 근거·진행 상태·취소·Run admission callback은 변경하지 않고 service 경계까지 전달한다.
        """
        try:
            decision = await self._routing.decide(payload, context.role)
        except RoutingError as exc:
            raise ContextValidationError(
                exc.code,
                exc.message,
                403 if exc.code == ErrorCode.ACCESS_DENIED else 422,
            ) from exc
        return await self._service.analyze(
            payload,
            context,
            decision,
            execution_sink=execution_sink,
            progress_sink=progress_sink,
            cancel_check=cancel_check,
            run_admission_sink=run_admission_sink,
            model_budget=model_budget,
        )

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다."""
        await self._service.aclose()
