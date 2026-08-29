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

from app.agent_contracts import AgentExecutionPhase  # noqa: E402
from app.contracts import RequestContext  # noqa: E402
from app.conversation_contracts import ConversationCommandRequest  # noqa: E402
from app.ports.agent import AgentKind, AgentRequest, AgentResult  # noqa: E402
from app.services.agent_supervisor import (  # noqa: E402
    AgentDispatchError,
    DeterministicAgentSupervisor,
)
from app.services.langgraph_agent_runtime import LangGraphAgentRuntime  # noqa: E402


def _request(requested_route: str | None = None) -> AgentRequest:
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
