"""외부 API 계층과 분석 파이프라인을 중계하는 애플리케이션 파사드 서비스(AnalysisService) 모듈.

[핵심 목적]
1. DataPlatformAdapter 및 ModelAdapter의 인스턴스 및 비동기 수명주기(aclose) 관리
2. 라우팅 결정(`RouteDecision`)을 인입받아 새로운 `AnalysisPipeline` 인스턴스를 생성하고 실행 위임
3. 라우팅 이전 차단 요청에 대한 즉각적인 BLOCKED 응답 생성
"""

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
from app.services.analysis.model_support import (
    _model_failure_code,
    _model_trace_detail,
    is_numeric,
)
from app.services.analysis.pipeline import AnalysisPipeline
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.context.builder import ContextPackageBuilder
from app.services.execution_control import IsolatedExecutionCache
from app.services.routing_service import RouteDecision


class AnalysisService:
    """분석 파이프라인의 수명주기 및 실행 진입점을 총괄하는 애플리케이션 서비스 클래스."""

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
        """DataPlatformAdapter 인스턴스를 반환합니다."""
        return self._adapter

    @property
    def support(self) -> PipelineSupport:
        """PipelineSupport 인스턴스를 반환합니다."""
        return self._support

    async def aclose(self) -> None:
        """연결된 어댑터 및 모델 리소스를 비동기적으로 안전하게 종료합니다."""
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
        """분석 요청을 새 AnalysisPipeline 인스턴스에 위임하여 실행합니다."""
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
        """라우팅 또는 선행 단계에서 차단된 BLOCKED 응답을 생성합니다."""
        return self._responses.blocked(context, error)


__all__ = ["AnalysisService"]
