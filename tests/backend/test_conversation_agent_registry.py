"""Conversation Agent registry가 구현 완료 port만 노출하는지 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent_contracts import AgentDecisionSource
from app.contracts import RequestContext
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import AgentKind, AgentRequest
from app.services.agent_supervisor import AgentDispatchError, SupervisorDecision
from app.services.conversation_agent_registry import (
    build_conversation_agent_supervisor,
)
from app.services.execution_control import ConcurrentExecutionGate


class ConversationAgentRegistryTest(unittest.IsolatedAsyncioTestCase):
    """미구현 ML·Report Agent가 빈 port로 등록되지 않게 한다."""

    def test_registry_contains_only_concrete_conversation_agents(self) -> None:
        supervisor = build_conversation_agent_supervisor(
            orchestrator=object(),
            execution_gate=ConcurrentExecutionGate(),
            internal_manual_query_service_factory=lambda: None,
        )

        self.assertEqual(
            supervisor.registered_agents,
            frozenset(
                {
                    AgentKind.ANALYSIS_WORKFLOW,
                    AgentKind.INTERNAL_GUIDELINE,
                }
            ),
        )

    def test_registry_keeps_capability_routing_disabled_by_default(self) -> None:
        """RAG·ML 교체 전에는 capability receipt가 있어도 자동 route를 실행하지 않는다."""

        resolver_calls = 0

        class CapabilityResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.CAPABILITY_EVIDENCE}
            )

            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                nonlocal resolver_calls
                resolver_calls += 1
                return SupervisorDecision(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    reason="RAG_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                    evidence_refs=("rag-probe:replacement-not-approved",),
                )

        with self.assertRaises(AgentDispatchError) as raised:
            build_conversation_agent_supervisor(
                orchestrator=object(),
                execution_gate=ConcurrentExecutionGate(),
                internal_manual_query_service_factory=lambda: None,
                route_resolver=CapabilityResolver(),
            )

        self.assertEqual(
            raised.exception.code,
            "AGENT_ROUTE_RESOLVER_NOT_APPROVED",
        )
        self.assertEqual(resolver_calls, 0)

    async def test_registry_requires_explicit_code_gate_for_capability_routing(self) -> None:
        """교체 adapter 승인 시에만 builder의 명시 flag로 capability 결정을 연다."""

        class CapabilityResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.CAPABILITY_EVIDENCE}
            )

            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                return SupervisorDecision(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    reason="RAG_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                    evidence_refs=("rag-probe:replacement-approved",),
                )

        conversation_id = uuid4()
        request = AgentRequest(
            conversation_id=conversation_id,
            command=ConversationCommandRequest(
                user_message="승인된 내부지침을 찾아줘",
                idempotency_key="registry-capability-enabled",
                expected_head_turn_id=None,
            ),
            context=RequestContext(
                conversation_id=conversation_id,
                command_id=uuid4(),
                permission_snapshot_id="permission-receipt-v1",
                product_release_id="product-release-v1",
                semantic_release_id="semantic-release-v1",
            ),
        )
        supervisor = build_conversation_agent_supervisor(
            orchestrator=object(),
            execution_gate=ConcurrentExecutionGate(),
            internal_manual_query_service_factory=lambda: None,
            route_resolver=CapabilityResolver(),
            capability_routing_enabled=True,
        )

        routing = await supervisor.route_with_state(request)

        self.assertEqual(routing.decision.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(
            routing.decision.source,
            AgentDecisionSource.CAPABILITY_EVIDENCE,
        )


if __name__ == "__main__":
    unittest.main()
