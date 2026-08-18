"""서버가 검증한 요청·주체·route를 요청별 상태에 묶고 context, SQL 계획, query, artifact stage를 조기 차단 가능한 순서로 실행한다."""

from __future__ import annotations

from typing import Any, Callable

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    RequestContext,
    Role,
    StageOutcome,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.model import ModelAdapter
from app.services.analysis_context_stage import AnalysisContextStage
from app.services.analysis_pipeline_state import AnalysisPipelineState
from app.services.analysis_plan_stage import AnalysisPlanStage
from app.services.analysis_query_stage import AnalysisQueryStage
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.analysis_result_stage import AnalysisResultStage
from app.services.execution_control import IsolatedExecutionCache, secure_cache_key
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision


class AnalysisPipeline:
    """한 분석 요청을 context·계획·query·artifact stage 순서로 실행하는 조정자다.

    외부 adapter와 model은 주입받되 stage마다 공유하는 mutable 값은 요청별
    ``AnalysisPipelineState``에만 보관해 동시 요청의 권한·cache·trace가 섞이지 않게 한다.
    """
    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
        cache: IsolatedExecutionCache,
    ) -> None:
        self._responses = responses
        self._context_stage = AnalysisContextStage(
            adapter, model, support, responses
        )
        self._plan_stage = AnalysisPlanStage(model, support, responses, cache)
        self._query_stage = AnalysisQueryStage(adapter, support, responses, cache)
        self._result_stage = AnalysisResultStage(model, support, responses)

    async def run(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
        execution_sink: Callable[[dict[str, Any]], None] | None = None,
        progress_sink: Callable[[PipelineStage, StageOutcome], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AnalysisResponse:
        """서버가 검증한 요청·사용자 context·route 판정으로 전체 분석 실행을 시작한다.

        역할과 취소 신호를 controller 경계에서 먼저 확인하고 각 stage의 조기 차단 응답을
        즉시 반환한다. 모든 선행 stage가 상태 증거를 남긴 경우에만 결과 artifact stage까지 진행한다.
        """
        state = AnalysisPipelineState(
            payload=payload,
            context=context,
            decision=decision,
            responses=self._responses,
            execution_sink=execution_sink,
            progress_sink=progress_sink,
            cancel_check=cancel_check,
        )
        state.machine.transition(AnalysisStatus.ROUTED)
        state.record(PipelineStage.ROUTER)
        audit_id = secure_cache_key(
            "audit",
            trace_id=context.trace_id,
            entitlement=f"{context.user_id}:{context.role.value}",
            role=context.role.value,
            as_of=context.as_of,
            mask_scope=context.role.value,
            policy="policy-v1",
        )[:16]
        state.record(PipelineStage.CONTROLLER, f"audit={audit_id}")

        cancelled = state.cancelled(PipelineStage.CONTROLLER)
        if cancelled is not None:
            return cancelled
        if context.role is not Role.HOTEL_ANALYST:
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTROLLER,
                AnalysisStatus.BLOCKED,
                ErrorCode.ACCESS_DENIED,
                "분석 Agent는 hotel_analyst 역할만 사용할 수 있습니다.",
                decision,
            )

        for stage in (
            self._context_stage,
            self._plan_stage,
            self._query_stage,
        ):
            response = await stage.run(state)
            if response is not None:
                return response
        return await self._result_stage.run(state)
