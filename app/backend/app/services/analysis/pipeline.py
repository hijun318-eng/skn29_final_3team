"""분석 파이프라인(AnalysisPipeline) 전체 실행 오케스트레이터 모듈.

[핵심 목적]
단일 분석 요청에 대해 4개 단계(Context -> Plan -> Query -> Result)를 순차적으로 실행하고,
각 단계의 조기 차단/실패/취소 신호를 감지하여 Fail-Closed 원칙에 따라 즉각적인 안전 응답을 반환합니다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    Capability,
    ErrorCode,
    PipelineStage,
    RequestContext,
    StageOutcome,
)
from app.authorization import has_capability
from app.ports.data_platform import DataPlatformAdapter
from app.ports.model import ModelAdapter
from app.services.analysis.pipeline_state import AnalysisPipelineState
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.analysis.stages.context_stage import AnalysisContextStage
from app.services.analysis.stages.plan_stage import AnalysisPlanStage
from app.services.analysis.stages.query_stage import AnalysisQueryStage
from app.services.analysis.stages.result_stage import AnalysisResultStage
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.execution_control import (
    IsolatedExecutionCache,
    ModelCallBudget,
    secure_cache_key,
)
from app.services.routing_service import RouteDecision


class AnalysisPipeline:
    """분석 파이프라인의 4개 단계를 순차 실행하는 메인 파이프라인 오케스트레이터 클래스."""

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
        run_admission_sink: Callable[[RequestContext], Awaitable[None]] | None = None,
        context_receipt_sink: (
            Callable[[RequestContext, Any], Awaitable[None]] | None
        ) = None,
        model_budget: ModelCallBudget | None = None,
    ) -> AnalysisResponse:
        """분석 요청을 받아 전체 파이프라인을 구동하고 최종 AnalysisResponse를 반환합니다."""
        # 1. 요청별 격리된 파이프라인 상태 객체 초기화
        state = AnalysisPipelineState(
            payload=payload,
            context=context,
            decision=decision,
            responses=self._responses,
            execution_sink=execution_sink,
            progress_sink=progress_sink,
            cancel_check=cancel_check,
            run_admission_sink=run_admission_sink,
            context_receipt_sink=context_receipt_sink,
            budget=model_budget or ModelCallBudget(),
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

        # 2. 역할 권한(RBAC) 검증
        if not has_capability(context.role, Capability.RUN_ANALYSIS):
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTROLLER,
                AnalysisStatus.BLOCKED,
                ErrorCode.ACCESS_DENIED,
                "분석 Agent는 analyst 권한이 필요합니다.",
                decision,
            )

        # 3. ContextStage가 typed request 확정 직후 Run을 admission하고 G1까지 완료한다.
        response = await self._context_stage.run(state)
        if response is not None:
            return response

        # 4. Plan, Query 단계 순차 실행 (조기 차단 발생 시 즉시 반환)
        for stage in (self._plan_stage, self._query_stage):
            response = await stage.run(state)
            if response is not None:
                return response

        # 5. Result 단계 실행 및 최종 응답 반환
        return await self._result_stage.run(state)
