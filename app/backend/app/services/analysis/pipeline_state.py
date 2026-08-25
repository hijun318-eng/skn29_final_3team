"""단일 분석 요청의 실행 컨텍스트, 트레이스, 상태 머신 및 수명주기를 격리 관리하는 상태(State) 모듈.

[핵심 목적]
요청(Request) 인입부터 라우팅, 컨텍스트 구성, 모델 계획 생성, Trino 실행, 최종 결과 조립까지의
모든 가변 상태(`AnalysisPipelineState`)를 단일 객체에 캡슐화하여 각 파이프라인 단계(`stages/`) 간에
부작용(Side-effect) 없이 안전하게 전달합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

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
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.context.builder import ContextPackage
from app.services.execution_control import ModelCallBudget
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


@dataclass
class AnalysisPipelineState:
    """단일 분석 요청의 전체 생명주기 동안 유지되는 불변/가변 상태 데이터 클래스.

    Attributes:
        payload: 클라이언트 요청 파라미터 (AnalysisRequest)
        context: 인증 및 세션 컨텍스트 (RequestContext)
        decision: 라우팅 판정 결과 (RouteDecision)
        responses: 응답 조립 팩토리 인스턴스 (AnalysisResponseFactory)
        execution_sink: 쿼리 실행 메타데이터 비동기 저장 콜백
        progress_sink: 실시간 진행률 알림 콜백
        cancel_check: 클라이언트 취소 여부 확인 함수
        machine: 유한 상태 머신 (AnalysisStateMachine)
        trace: 단계별 실행 트레이스 목록 (list[TraceStep])
        budget: LLM 호출 횟수/토큰 예산 제어기 (ModelCallBudget)
        assets: DataHub에서 조회/필터링된 자산 목록
        normalized_question: Node 1을 통해 정규화된 질문 문자열
        structured_request: 지표, 차원, 필터, 기간 구조화 요청 딕셔너리
        package: 최소 권한 검증을 통과한 불변 ContextPackage
        analysis_plan: SQL 생성 전에 서버가 확정한 버전형 논리 분석 계획
        references: 데이터 리니지 참조 목록
        plan: LLM이 생성하고 G2 가드를 통과한 실행 계획
        query: Trino 엔진 실행 결과 딕셔너리
    """

    payload: AnalysisRequest
    context: RequestContext
    decision: RouteDecision
    responses: AnalysisResponseFactory
    execution_sink: Callable[[dict[str, Any]], None] | None = None
    progress_sink: Callable[[PipelineStage, StageOutcome], None] | None = None
    cancel_check: Callable[[], bool] | None = None
    run_admission_sink: Callable[[], Awaitable[None]] | None = None
    machine: AnalysisStateMachine = field(default_factory=AnalysisStateMachine)
    trace: list[TraceStep] = field(default_factory=list)
    budget: ModelCallBudget = field(default_factory=ModelCallBudget)
    assets: list[dict[str, Any]] = field(default_factory=list)
    normalized_question: str = ""
    structured_request: dict[str, Any] = field(default_factory=dict)
    package: ContextPackage | None = None
    analysis_plan: dict[str, Any] | None = None
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
        """트레이스 리스트와 progress_sink에 단계 완료 상태를 기록합니다."""
        self.responses.record(self.trace, stage, detail, outcome)
        if self.progress_sink is not None:
            self.progress_sink(stage, outcome)

    def cancelled(self, stage: PipelineStage) -> AnalysisResponse | None:
        """취소 신호가 인입되었는지 확인하고, 취소된 경우 CANCELLED 상태의 응답을 반환합니다."""
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
