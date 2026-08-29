"""결정론적 Agent supervisor의 route·port·fail-closed 계약을 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from uuid import uuid4

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.contracts import RequestContext
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import AgentKind, AgentRequest, AgentResult
from app.services.agent_supervisor import (
    AgentDispatchError,
    CallableAgentPort,
    DeterministicAgentSupervisor,
)


def _request(
    requested_route: str | None = None,
    *,
    conversation_id=None,
    context_conversation_id=None,
) -> AgentRequest:
    """테스트용 command와 identity가 결속된 AgentRequest를 만든다."""

    target_conversation_id = conversation_id or uuid4()
    return AgentRequest(
        conversation_id=target_conversation_id,
        command=ConversationCommandRequest(
            user_message="승인된 범위에서 처리해줘",
            idempotency_key=uuid4().hex,
            expected_head_turn_id=None,
            requested_route=requested_route,
        ),
        context=RequestContext(conversation_id=context_conversation_id),
    )


class _MismatchedResultPort:
    """선택과 다른 AgentResult를 반환하는 결함 adapter다."""

    agent = AgentKind.ANALYSIS_WORKFLOW

    async def execute(self, request: AgentRequest) -> AgentResult:
        """Supervisor가 차단해야 하는 교차 Agent 결과를 반환한다."""

        return AgentResult(
            agent=AgentKind.INTERNAL_GUIDELINE,
            payload={"status": "SUCCESS", "data": {}},
        )


class DeterministicAgentSupervisorTest(unittest.IsolatedAsyncioTestCase):
    """현재 두 실행 경로가 모델 fallback 없이 한 port로만 전달되는지 확인한다."""

    async def test_explicit_internal_guideline_routes_only_to_rag_port(self) -> None:
        """명시된 내부지침 route만 RAG port를 선택한다."""

        calls: list[AgentKind] = []

        async def analysis_handler(request: AgentRequest):
            calls.append(AgentKind.ANALYSIS_WORKFLOW)
            return {"status": "SUCCESS", "data": {"agent": "analysis"}}

        async def rag_handler(request: AgentRequest):
            calls.append(AgentKind.INTERNAL_GUIDELINE)
            return {"status": "SUCCESS", "data": {"agent": "rag"}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                ),
                AgentKind.INTERNAL_GUIDELINE: CallableAgentPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    rag_handler,
                ),
            }
        )

        result = await supervisor.execute(_request("INTERNAL_GUIDELINE"))

        self.assertEqual(result.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(result.payload["data"]["agent"], "rag")
        self.assertEqual(calls, [AgentKind.INTERNAL_GUIDELINE])

    async def test_other_current_routes_stay_in_governed_analysis_workflow(self) -> None:
        """일반·분석·표현·Report Action은 기존 conversation 상태 머신을 유지한다."""

        calls: list[str | None] = []

        async def analysis_handler(request: AgentRequest):
            calls.append(request.command.requested_route)
            return {"status": "SUCCESS", "data": {"route": "analysis"}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                )
            }
        )

        for route in (None, "ANALYSIS", "PRESENTATION", "REPORT_ACTION"):
            with self.subTest(route=route):
                result = await supervisor.execute(_request(route))
                self.assertEqual(result.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(calls, [None, "ANALYSIS", "PRESENTATION", "REPORT_ACTION"])

    async def test_missing_selected_port_fails_closed(self) -> None:
        """RAG port가 없을 때 분석이나 범용 모델로 우회하지 않는다."""

        supervisor = DeterministicAgentSupervisor({})

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request("INTERNAL_GUIDELINE"))

        self.assertEqual(raised.exception.code, "AGENT_NOT_CONFIGURED")

    async def test_cross_agent_result_is_rejected(self) -> None:
        """선택과 다른 Agent identity를 반환한 adapter 결과를 차단한다."""

        supervisor = DeterministicAgentSupervisor(
            {AgentKind.ANALYSIS_WORKFLOW: _MismatchedResultPort()}
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request())

        self.assertEqual(raised.exception.code, "AGENT_RESULT_MISMATCH")

    def test_request_rejects_cross_conversation_context(self) -> None:
        """다른 Conversation에 이미 결속된 RequestContext를 재사용하지 못한다."""

        with self.assertRaises(ValidationError):
            _request(
                conversation_id=uuid4(),
                context_conversation_id=uuid4(),
            )


if __name__ == "__main__":
    unittest.main()
