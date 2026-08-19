"""DataPlatform·model adapter의 수명주기를 소유하고 검증된 API 입력을 요청별 AnalysisPipeline으로 넘기는 애플리케이션 facade다."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    ErrorBody,
    PipelineStage,
    RequestContext,
    StageOutcome,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.model import ModelAdapter
from app.services.analysis_model_support import (
    _model_failure_code,
    _model_trace_detail,
    is_numeric,
)
from app.services.analysis_pipeline import AnalysisPipeline
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextPackageBuilder
from app.services.execution_control import IsolatedExecutionCache
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision


class AnalysisService:
    """분석 요청을 검증된 context, query, artifact 흐름으로 조정한다.

    공개 서비스 계약과 adapter 수명주기는 이 facade가 소유하고, 각 실행
    단계의 결정론적 검증은 분리된 pipeline stage가 수행한다.
    """

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        context_builder: ContextPackageBuilder | None = None,
        cache: IsolatedExecutionCache | None = None,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._support = PipelineSupport(
            adapter,
            context_builder or ContextPackageBuilder(),
            model,
        )
        self._responses = AnalysisResponseFactory()
        self._cache = cache or IsolatedExecutionCache()

    @property
    def data_platform(self) -> DataPlatformAdapter:
        """이 facade가 소유한 단일 DataPlatformAdapter를 다른 조정자가 재사용할 수 있게 노출한다."""
        return self._adapter

    @property
    def support(self) -> PipelineSupport:
        """이 facade가 소유한 단일 PipelineSupport를 다른 조정자가 재사용할 수 있게 노출한다."""
        return self._support

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다.

        Release network resources owned by production adapters.
        """
        close_model = getattr(self._model, "aclose", None)
        close_operations = [self._adapter.aclose()]
        if callable(close_model):
            close_operations.append(close_model())
        results = await asyncio.gather(*close_operations, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def analyze(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
        execution_sink: Callable[[dict[str, Any]], None] | None = None,
        progress_sink: Callable[[PipelineStage, StageOutcome], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AnalysisResponse:
        """검증된 요청 context와 route 판정을 새 분석 파이프라인 실행에 전달한다.

        선택적 sink와 취소 확인 함수는 해당 실행에만 주입하며, adapter·model·격리 cache는
        facade가 소유한다. 파이프라인의 성공·차단·실패는 모두 ``AnalysisResponse``로 반환된다.
        """
        pipeline = AnalysisPipeline(
            self._adapter,
            self._model,
            self._support,
            self._responses,
            self._cache,
        )
        return await pipeline.run(
            payload,
            context,
            decision,
            execution_sink,
            progress_sink,
            cancel_check,
        )

    _is_numeric = staticmethod(is_numeric)

    def blocked(self, context: RequestContext, error: ErrorBody) -> AnalysisResponse:
        """파이프라인 진입 전에 확정된 거부 사유를 표준 차단 응답으로 변환한다.

        호출자가 검증한 ``RequestContext``와 typed ``ErrorBody``만 사용하며 SQL·모델 실행은
        시작하지 않아 인증·라우팅 실패가 분석 경계를 우회하지 못하게 한다.
        """
        return self._responses.blocked(context, error)


__all__ = ["AnalysisService"]
