"""LangGraph Supervisor→sub-agent 실행 경계의 결정론적 동작을 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.agent_contracts import AgentDecisionSource, AgentExecutionPhase  # noqa: E402
from app.contracts import RequestContext  # noqa: E402
from app.conversation_contracts import ConversationCommandRequest  # noqa: E402
from app.ports.agent import (  # noqa: E402
    AgentKind,
    AgentRequest,
    AgentResult,
    MLPredictionInvocation,
)
from app.services.agent_supervisor import (  # noqa: E402
    AgentDispatchError,
    DeterministicAgentSupervisor,
    SupervisorDecision,
)
from app.services.langgraph_agent_runtime import (  # noqa: E402
    LangGraphAgentRuntime,
    ML_PREDICTION_AGENT_NODE,
    _agent_node_name,
)


def _request(
    requested_route: str | None = None,
    *,
    ml_invocation: bool = False,
) -> AgentRequest:
    """공통 admission receipt가 결속된 테스트용 AgentRequest를 만든다."""

    conversation_id = uuid4()
    return AgentRequest(
        conversation_id=conversation_id,
        command=ConversationCommandRequest(
            user_message="승인된 범위에서 처리해줘",
            idempotency_key=f"graph-{uuid4()}",
            expected_head_turn_id=None,
            requested_route=requested_route,
        ),
        context=RequestContext(
            conversation_id=conversation_id,
            command_id=uuid4(),
            permission_snapshot_id="permission-receipt-v1",
            product_release_id="product-release-v1",
            semantic_release_id="semantic-release-v1",
        ),
        target_agent=(AgentKind.ML_PREDICTION if ml_invocation else None),
        invocation=(
            MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=90,
            )
            if ml_invocation
            else None
        ),
    )


class _RecordingPort:
    """호출 순서와 선택 Agent를 기록하는 테스트 전용 port다."""

    def __init__(self, agent: AgentKind, calls: list[str]) -> None:
        self._agent = agent
        self._calls = calls

    @property
    def agent(self) -> AgentKind:
        """이 port가 담당하는 Agent 종류를 반환한다."""

        return self._agent

    async def execute(self, request: AgentRequest) -> AgentResult:
        """실제 외부 호출 없이 선택된 Agent 종류만 기록한다."""

        self._calls.append(self._agent.value)
        return AgentResult(
            agent=self._agent,
            payload={"status": "SUCCESS", "data": {"agent": self._agent.value}},
        )


class _MlCapabilityResolver:
    """승인 receipt로 향후 ML port를 선택하는 테스트 전용 resolver다."""

    decision_sources = frozenset({AgentDecisionSource.CAPABILITY_EVIDENCE})

    async def resolve(self, _request: AgentRequest) -> SupervisorDecision:
        return SupervisorDecision(
            agent=AgentKind.ML_PREDICTION,
            reason="ML_CAPABILITY_MATCH",
            source=AgentDecisionSource.CAPABILITY_EVIDENCE,
            evidence_refs=("agent-capability:v1:ml-prediction:test",),
        )


class LangGraphAgentRuntimeTest(unittest.IsolatedAsyncioTestCase):
    """일반 모델 fallback 없이 정확히 한 sub-agent node만 실행하는지 확인한다."""

    async def test_default_route_executes_only_analysis_agent_node(self) -> None:
        calls: list[str] = []
        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: _RecordingPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    calls,
                ),
                AgentKind.INTERNAL_GUIDELINE: _RecordingPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    calls,
                ),
            }
        )

        outcome = await LangGraphAgentRuntime(supervisor).execute(_request())

        self.assertEqual(calls, [AgentKind.ANALYSIS_WORKFLOW.value])
        self.assertEqual(outcome.result.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(outcome.state.phase, AgentExecutionPhase.COMPLETED)

    async def test_explicit_internal_guideline_executes_only_rag_agent_node(self) -> None:
        calls: list[str] = []
        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: _RecordingPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    calls,
                ),
                AgentKind.INTERNAL_GUIDELINE: _RecordingPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    calls,
                ),
            }
        )

        outcome = await LangGraphAgentRuntime(supervisor).execute(
            _request("INTERNAL_GUIDELINE")
        )

        self.assertEqual(calls, [AgentKind.INTERNAL_GUIDELINE.value])
        self.assertEqual(outcome.result.agent, AgentKind.INTERNAL_GUIDELINE)

    async def test_after_route_hook_finishes_before_selected_port(self) -> None:
        calls: list[str] = []
        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: _RecordingPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    calls,
                )
            }
        )

        async def after_route(routing) -> None:
            self.assertEqual(routing.decision.agent, AgentKind.ANALYSIS_WORKFLOW)
            calls.append("ROUTE_FINISHED")

        await LangGraphAgentRuntime(
            supervisor,
            after_route=after_route,
        ).execute(_request())

        self.assertEqual(
            calls,
            ["ROUTE_FINISHED", AgentKind.ANALYSIS_WORKFLOW.value],
        )

    async def test_missing_selected_port_fails_without_cross_agent_fallback(self) -> None:
        calls: list[str] = []
        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: _RecordingPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    calls,
                )
            }
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await LangGraphAgentRuntime(supervisor).execute(
                _request("INTERNAL_GUIDELINE")
            )

        self.assertEqual(raised.exception.code, "AGENT_NOT_CONFIGURED")
        self.assertEqual(raised.exception.state.phase, AgentExecutionPhase.FAILED)
        self.assertEqual(calls, [])

    async def test_future_ml_port_uses_common_graph_without_runtime_branch(self) -> None:
        """교체 ML port는 공통 Agent 계약만 구현하면 단일 node로 실행된다."""

        calls: list[str] = []
        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ML_PREDICTION: _RecordingPort(
                    AgentKind.ML_PREDICTION,
                    calls,
                )
            },
            route_resolver=_MlCapabilityResolver(),
            allowed_decision_sources=frozenset(
                {AgentDecisionSource.CAPABILITY_EVIDENCE}
            ),
        )

        outcome = await LangGraphAgentRuntime(supervisor).execute(
            _request(ml_invocation=True)
        )

        self.assertEqual(_agent_node_name(AgentKind.ML_PREDICTION), ML_PREDICTION_AGENT_NODE)
        self.assertEqual(calls, [AgentKind.ML_PREDICTION.value])
        self.assertEqual(outcome.result.agent, AgentKind.ML_PREDICTION)
