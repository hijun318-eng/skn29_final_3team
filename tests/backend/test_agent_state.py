"""Agent 공통 상태·reducer·checkpoint identity 계약을 검증한다."""

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

from app.agent_contracts import (
    AgentCheckpoint,
    AgentDecisionSource,
    AgentExecutionPhase,
    AgentExecutionState,
    AgentStateUpdate,
)
from app.contracts import RequestContext
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import AgentKind, AgentRequest
from app.services.agent_state import (
    AgentStateTransitionError,
    checkpoint_agent_state,
    initial_agent_state,
    reduce_agent_state,
)


def _request(*, conversation_id=None, idempotency_key="agent-state-key") -> AgentRequest:
    target_id = conversation_id or uuid4()
    return AgentRequest(
        conversation_id=target_id,
        command=ConversationCommandRequest(
            user_message="2026년 6월 객실 매출을 분석해줘",
            idempotency_key=idempotency_key,
            expected_head_turn_id=None,
            requested_route="ANALYSIS",
        ),
        context=RequestContext(conversation_id=target_id),
    )


class AgentStateContractTest(unittest.TestCase):
    """공통 상태가 순방향·최소 정보·멱등성 범위 불변식을 지키는지 확인한다."""

    def test_initial_state_uses_conversation_scoped_idempotency_identity(self) -> None:
        """같은 key라도 Conversation이 다르면 checkpoint thread가 격리된다."""

        first = initial_agent_state(_request(idempotency_key="same-key"))
        second = initial_agent_state(_request(idempotency_key="same-key"))

        self.assertEqual(first.phase, AgentExecutionPhase.RECEIVED)
        self.assertEqual(first.revision, 0)
        self.assertNotEqual(first.checkpoint.thread_id, second.checkpoint.thread_id)
        self.assertEqual(first.checkpoint.idempotency_key, "same-key")
        self.assertNotIn("객실 매출", str(first.model_dump(mode="json")))

    def test_reducer_advances_only_through_legal_forward_transitions(self) -> None:
        """route·start·complete가 revision을 하나씩 증가시키고 terminal을 고정한다."""

        state = initial_agent_state(_request())
        state = reduce_agent_state(
            state,
            AgentStateUpdate(
                event="ROUTE",
                agent=AgentKind.ANALYSIS_WORKFLOW,
                reason="GOVERNED_CONVERSATION_ROUTE",
                source=AgentDecisionSource.EXPLICIT_COMMAND,
            ),
        )
        state = reduce_agent_state(state, AgentStateUpdate(event="START"))
        state = reduce_agent_state(state, AgentStateUpdate(event="COMPLETE"))

        self.assertEqual(state.phase, AgentExecutionPhase.COMPLETED)
        self.assertEqual(state.revision, 3)
        self.assertEqual(state.selected_agent, AgentKind.ANALYSIS_WORKFLOW)
        checkpoint = checkpoint_agent_state(state)
        self.assertEqual(checkpoint.identity, state.checkpoint)
        self.assertEqual(checkpoint.revision, 3)

        with self.assertRaises(AgentStateTransitionError):
            reduce_agent_state(state, AgentStateUpdate(event="COMPLETE"))

    def test_route_failure_produces_terminal_checkpoint(self) -> None:
        """port 미구성 같은 route 실패는 RUNNING을 거치지 않고 terminal이 된다."""

        state = initial_agent_state(_request())
        state = reduce_agent_state(
            state,
            AgentStateUpdate(
                event="ROUTE",
                agent=AgentKind.ANALYSIS_WORKFLOW,
                reason="GOVERNED_CONVERSATION_ROUTE",
                source=AgentDecisionSource.EXPLICIT_COMMAND,
            ),
        )
        failed = reduce_agent_state(
            state,
            AgentStateUpdate(event="FAIL", code="AGENT_NOT_CONFIGURED"),
        )

        self.assertEqual(failed.phase, AgentExecutionPhase.FAILED)
        self.assertEqual(failed.terminal_code, "AGENT_NOT_CONFIGURED")
        self.assertEqual(failed.revision, 2)

    def test_capability_route_requires_and_preserves_evidence_refs(self) -> None:
        """자동 route는 승인 probe 참조 없이 상태에 기록될 수 없다."""

        state = initial_agent_state(_request())
        with self.assertRaises(ValidationError):
            AgentStateUpdate(
                event="ROUTE",
                agent=AgentKind.INTERNAL_GUIDELINE,
                reason="RAG_CAPABILITY_MATCH",
                source=AgentDecisionSource.CAPABILITY_EVIDENCE,
            )

        routed = reduce_agent_state(
            state,
            AgentStateUpdate(
                event="ROUTE",
                agent=AgentKind.INTERNAL_GUIDELINE,
                reason="RAG_CAPABILITY_MATCH",
                source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                evidence_refs=("rag-probe:receipt-1",),
            ),
        )

        self.assertEqual(
            routed.decision_source,
            AgentDecisionSource.CAPABILITY_EVIDENCE,
        )
        self.assertEqual(routed.decision_evidence_refs, ("rag-probe:receipt-1",))

    def test_route_resolution_failure_can_end_before_agent_selection(self) -> None:
        """resolver 실패도 선택 Agent를 꾸며내지 않고 terminal checkpoint가 된다."""

        failed = reduce_agent_state(
            initial_agent_state(_request()),
            AgentStateUpdate(event="FAIL", code="AGENT_ROUTE_RESOLUTION_FAILED"),
        )

        self.assertEqual(failed.phase, AgentExecutionPhase.FAILED)
        self.assertIsNone(failed.selected_agent)
        self.assertEqual(failed.revision, 1)

    def test_route_failure_preserves_terminal_evidence_without_fake_decision(self) -> None:
        """0개·복수 매칭 receipt는 선택 Agent 없이 FAILED 감사 근거로 남는다."""

        failed = reduce_agent_state(
            initial_agent_state(_request()),
            AgentStateUpdate(
                event="FAIL",
                code="AGENT_ROUTE_NOT_RESOLVED",
                evidence_refs=("probe:no-match-receipt",),
            ),
        )

        self.assertEqual(
            failed.terminal_evidence_refs,
            ("probe:no-match-receipt",),
        )
        self.assertEqual(failed.decision_evidence_refs, ())
        self.assertIsNone(failed.decision_source)

    def test_non_terminal_state_rejects_terminal_evidence(self) -> None:
        """실패 근거가 RUNNING·COMPLETED 상태에 잘못 붙지 못하게 한다."""

        state = initial_agent_state(_request())
        with self.assertRaises(ValidationError):
            AgentExecutionState.model_validate(
                {
                    **state.model_dump(mode="python"),
                    "terminal_evidence_refs": ("probe:invalid-phase",),
                }
            )

    def test_fail_update_rejects_duplicate_terminal_evidence(self) -> None:
        """동일 receipt가 terminal 감사 근거에 중복 저장되지 않게 한다."""

        with self.assertRaises(ValidationError):
            AgentStateUpdate(
                event="FAIL",
                code="AGENT_ROUTE_AMBIGUOUS",
                evidence_refs=("probe:duplicate", "probe:duplicate"),
            )

    def test_checkpoint_rejects_mismatched_revision(self) -> None:
        """외부 key와 내부 state revision이 다른 snapshot을 checkpoint로 만들 수 없다."""

        state = initial_agent_state(_request())

        with self.assertRaises(ValidationError):
            AgentCheckpoint(
                identity=state.checkpoint,
                revision=1,
                state=state,
            )


if __name__ == "__main__":
    unittest.main()
