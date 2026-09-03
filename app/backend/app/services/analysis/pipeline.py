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
from app.services.analysis.sql_generation_mode import SqlGenerationMode
from app.services.execution_control import (
    IsolatedExecutionCache,
    ModelCallBudget,
    secure_cache_key,
)
from app.services.routing_service import RouteDecision


class AnalysisPipeline:
    """[책임] 단일 분석 요청에 대해 4개 스테이지(Context → Plan → Query → Result)를 조율 실행하는 메인 오케스트레이터.
    - 입출력: AnalysisRequest 및 RequestContext 수신 → 파이프라인 상태 머신을 전이하며 최종 AnalysisResponse 생성
    - 주의조건: 스테이지별 조기 차단, 권한 거부, 쿼리 취소 감지 시 fail-closed 원칙에 따라 즉각적인 안전 응답 반환
    """

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
        cache: IsolatedExecutionCache,
        sql_generation_mode: SqlGenerationMode = SqlGenerationMode.HYBRID,
    ) -> None:
        """[책임] 데이터 플랫폼, 모델 어댑터, 실행 제어 캐시 및 4개 하위 스테이지를 조립하여 파이프라인을 초기화한다.
        - 입출력: DataPlatformAdapter, ModelAdapter, Cache, Mode 등 주입 수신 → 내부 4개 분석 스테이지 인스턴스 생성
        - 주의조건: sql_generation_mode 설정(HYBRID vs COMPILER_ONLY)에 따라 PlanStage의 모델 호출 허용 여부가 고정됨
        """
        self._responses = responses
        self._context_stage = AnalysisContextStage(
            adapter, model, support, responses
        )
        self._plan_stage = AnalysisPlanStage(
            model,
            support,
            responses,
            cache,
            sql_generation_mode,
        )
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
        """[책임] 단일 분석 요청을 받아 전체 파이프라인 4단계를 순차 구동하고 최종 결과를 반환한다.
        - 입출력: AnalysisRequest, RequestContext, RouteDecision 수신 → 상태 머신 전이 및 각 Stage 실행 후 AnalysisResponse 반환
        - 주의조건: RBAC 권한 결여(RUN_ANALYSIS 부재), 사용자 취소, 스테이지 실패 시 즉시 fail-closed 안전 응답 반환
        """
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
