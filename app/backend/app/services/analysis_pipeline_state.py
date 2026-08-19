"""한 요청의 context·계획·결과·trace와 취소 callback을 격리해 stage 간 전달하며, 취소 신호를 표준 종단 응답으로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    RequestContext,
    StageOutcome,
    TraceStep,
)
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextPackage
from app.services.execution_control import ModelCallBudget
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


@dataclass
class AnalysisPipelineState:
    """한 분석 요청의 권한 컨텍스트, 라우팅 판정, 단계별 산출물과 호출 예산을 보존하는 실행 상태다.

    이 객체는 요청 사이에 공유되지 않으며 stage service만 값을 채운다. ``machine``과
    ``trace``는 상태 전이의 순서를, sink와 cancel callback은 외부 실행 기록·취소 경계를
    유지하므로 transport 응답이나 전역 cache로 재사용해서는 안 된다.
    """
    payload: AnalysisRequest
    context: RequestContext
    decision: RouteDecision
    responses: AnalysisResponseFactory
    execution_sink: Callable[[dict[str, Any]], None] | None = None
    progress_sink: Callable[[PipelineStage, StageOutcome], None] | None = None
    cancel_check: Callable[[], bool] | None = None
    machine: AnalysisStateMachine = field(default_factory=AnalysisStateMachine)
    trace: list[TraceStep] = field(default_factory=list)
    budget: ModelCallBudget = field(default_factory=ModelCallBudget)
    assets: list[dict[str, Any]] = field(default_factory=list)
    normalized_question: str = ""
    structured_request: dict[str, Any] = field(default_factory=dict)
    package: ContextPackage | None = None
    references: list[dict[str, Any]] = field(default_factory=list)
    common_key: dict[str, Any] = field(default_factory=dict)
    plan_key: str = ""
    plan: dict[str, Any] | None = None
    plan_cached: bool = False
    repair_count: int = 0
    result_key: str = ""
    query: dict[str, Any] | None = None
    result_cached: bool = False

    def record(
        self,
        stage: PipelineStage,
        detail: str | None = None,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        """분석 파이프라인 상태 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
        self.responses.record(self.trace, stage, detail, outcome)
        if self.progress_sink is not None:
            self.progress_sink(stage, outcome)

    def cancelled(self, stage: PipelineStage) -> AnalysisResponse | None:
        """현재 요청의 취소 신호를 확인하고 취소된 경우에만 종단 응답을 만든다.

        신호가 없으면 ``None``을 반환해 stage 실행을 계속한다. 신호가 있으면 진행 상태를
        실패로 기록하고 상태 머신을 ``CANCELLED``로 전이한 typed API 응답을 반환한다.
        """
        if self.cancel_check is None or not self.cancel_check():
            return None
        if self.progress_sink is not None:
            self.progress_sink(stage, StageOutcome.FAILED)
        return self.responses.error(
            self.context,
            self.machine,
            self.trace,
            stage,
            AnalysisStatus.CANCELLED,
            ErrorCode.REQUEST_CANCELLED,
            "사용자가 분석 요청을 취소했습니다.",
            self.decision,
        )
