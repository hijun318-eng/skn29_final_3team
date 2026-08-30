"""결정론적 Agent supervisor의 route·port·fail-closed 계약을 검증한다."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent_contracts import AgentDecisionSource, AgentExecutionPhase
from app.contracts import RequestContext
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import (
    AgentKind,
    AgentPortReadiness,
    AgentRequest,
    AgentResult,
    MLPredictionInvocation,
)
from app.services.agent_supervisor import (
    AgentCapabilityEvidence,
    AgentDispatchError,
    CapabilityEvidenceRouteResolver,
    CallableAgentPort,
    DeterministicAgentSupervisor,
    ReadinessGuardedAgentPort,
    SupervisorDecision,
)
from app.services.agent_state import checkpoint_agent_state


def _request(
    requested_route: str | None = None,
    *,
    conversation_id=None,
    context_conversation_id=None,
    admitted: bool = False,
    invocation: MLPredictionInvocation | None = None,
) -> AgentRequest:
    """테스트용 command와 identity가 결속된 AgentRequest를 만든다."""

    target_conversation_id = conversation_id or uuid4()
    context_id = (
        target_conversation_id if admitted else context_conversation_id
    )
    return AgentRequest(
        conversation_id=target_conversation_id,
        command=ConversationCommandRequest(
            user_message="승인된 범위에서 처리해줘",
            idempotency_key=uuid4().hex,
            expected_head_turn_id=None,
            requested_route=requested_route,
        ),
        context=RequestContext(
            conversation_id=context_id,
            command_id=uuid4() if admitted else None,
            permission_snapshot_id=("permission-receipt-v1" if admitted else None),
            product_release_id=("product-release-v1" if admitted else None),
            semantic_release_id=("semantic-release-v1" if admitted else None),
        ),
        target_agent=(AgentKind.ML_PREDICTION if invocation is not None else None),
        invocation=invocation,
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


class _StaticCapabilityProbe:
    """테스트가 지정한 capability receipt 또는 오류를 반환한다."""

    def __init__(
        self,
        agent: AgentKind,
        evidence: AgentCapabilityEvidence | None = None,
        error: Exception | None = None,
    ) -> None:
        self._agent = agent
        self._evidence = evidence
        self._error = error
        self.calls = 0

    @property
    def agent(self) -> AgentKind:
        return self._agent

    async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._evidence is not None
        return self._evidence


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

        default_outcome = await supervisor.execute_with_state(_request())
        self.assertEqual(
            default_outcome.state.decision_source,
            AgentDecisionSource.GOVERNED_DEFAULT,
        )

    async def test_missing_selected_port_fails_closed(self) -> None:
        """RAG port가 없을 때 분석이나 범용 모델로 우회하지 않는다."""

        supervisor = DeterministicAgentSupervisor({})

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request("INTERNAL_GUIDELINE"))

        self.assertEqual(raised.exception.code, "AGENT_NOT_CONFIGURED")
        self.assertIsNotNone(raised.exception.state)
        self.assertEqual(
            raised.exception.state.phase,
            AgentExecutionPhase.FAILED,
        )
        self.assertEqual(raised.exception.state.revision, 2)

    async def test_cross_agent_result_is_rejected(self) -> None:
        """선택과 다른 Agent identity를 반환한 adapter 결과를 차단한다."""

        supervisor = DeterministicAgentSupervisor(
            {AgentKind.ANALYSIS_WORKFLOW: _MismatchedResultPort()}
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request())

        self.assertEqual(raised.exception.code, "AGENT_RESULT_MISMATCH")
        self.assertEqual(
            raised.exception.state.phase,
            AgentExecutionPhase.FAILED,
        )
        self.assertEqual(raised.exception.state.revision, 3)

    async def test_port_error_keeps_original_type_and_attaches_failed_state(self) -> None:
        """도메인 오류 매핑을 깨지 않고 공통 상태를 FAILED로 종결한다."""

        class RagUnavailable(RuntimeError):
            code = "RAG_FEATURE_DISABLED"

        async def rag_handler(request: AgentRequest):
            raise RagUnavailable("내부지침 검색 기능이 비활성화되었습니다.")

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.INTERNAL_GUIDELINE: CallableAgentPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    rag_handler,
                )
            }
        )

        with self.assertRaises(RagUnavailable) as raised:
            await supervisor.execute(_request("INTERNAL_GUIDELINE"))

        state = raised.exception.agent_execution_state
        self.assertEqual(state.phase, AgentExecutionPhase.FAILED)
        self.assertEqual(state.terminal_code, "RAG_FEATURE_DISABLED")
        self.assertEqual(state.revision, 3)

    async def test_analysis_timeout_keeps_selected_agent_in_failed_state(self) -> None:
        """HTTP 경계가 분석 timeout만 504로 변환할 수 있도록 선택 근거를 보존한다."""

        async def analysis_handler(request: AgentRequest):
            raise TimeoutError("analysis deadline")

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                )
            }
        )

        with self.assertRaises(TimeoutError) as raised:
            await supervisor.execute(_request())

        state = raised.exception.agent_execution_state
        self.assertEqual(state.phase, AgentExecutionPhase.FAILED)
        self.assertEqual(state.selected_agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(
            state.decision_source,
            AgentDecisionSource.GOVERNED_DEFAULT,
        )

    async def test_success_returns_completed_common_state(self) -> None:
        """기존 AgentResult와 별도로 checkpoint 가능한 최종 상태를 제공한다."""

        async def analysis_handler(request: AgentRequest):
            return {"status": "SUCCESS", "data": {"agent": "analysis"}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                )
            }
        )

        outcome = await supervisor.execute_with_state(_request("ANALYSIS"))

        self.assertEqual(outcome.result.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(outcome.state.phase, AgentExecutionPhase.COMPLETED)
        self.assertEqual(outcome.state.revision, 3)
        self.assertEqual(outcome.state.selected_agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(
            outcome.state.decision_source,
            AgentDecisionSource.EXPLICIT_COMMAND,
        )

    async def test_route_and_execute_are_separate_single_resolution_nodes(self) -> None:
        """route 결과를 다음 node에 넘겨도 resolver와 port를 각각 한 번만 호출한다."""

        resolver_calls = 0
        port_calls = 0

        class CountingResolver:
            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                nonlocal resolver_calls
                resolver_calls += 1
                return SupervisorDecision(
                    agent=AgentKind.ANALYSIS_WORKFLOW,
                    reason="GOVERNED_CONVERSATION_ROUTE",
                    source=AgentDecisionSource.GOVERNED_DEFAULT,
                )

        async def analysis_handler(request: AgentRequest):
            nonlocal port_calls
            port_calls += 1
            return {"status": "SUCCESS", "data": {"agent": "analysis"}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                )
            },
            route_resolver=CountingResolver(),
        )
        request = _request(admitted=True)

        routing = await supervisor.route_with_state(request)
        route_checkpoint = checkpoint_agent_state(routing.state)
        outcome = await supervisor.execute_routed_with_state(request, routing)

        self.assertEqual(routing.state.phase, AgentExecutionPhase.ROUTED)
        self.assertEqual(routing.state.revision, 1)
        self.assertEqual(route_checkpoint.identity, routing.state.checkpoint)
        self.assertEqual(route_checkpoint.revision, 1)
        self.assertEqual(outcome.state.phase, AgentExecutionPhase.COMPLETED)
        self.assertEqual(outcome.state.revision, 3)
        self.assertEqual(resolver_calls, 1)
        self.assertEqual(port_calls, 1)

    async def test_route_timeout_fails_before_any_port_execution(self) -> None:
        """bounded route node는 resolver를 취소하고 FAILED 상태를 보존한다."""

        resolver_cancelled = False
        port_calls = 0

        class HangingResolver:
            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                nonlocal resolver_cancelled
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    resolver_cancelled = True
                    raise

        async def analysis_handler(request: AgentRequest):
            nonlocal port_calls
            port_calls += 1
            return {"status": "SUCCESS", "data": {}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                )
            },
            route_resolver=HangingResolver(),
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.route_with_state(
                _request(admitted=True),
                timeout_seconds=0.01,
            )

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_TIMEOUT")
        self.assertEqual(
            raised.exception.agent_execution_state.phase,
            AgentExecutionPhase.FAILED,
        )
        self.assertEqual(
            raised.exception.agent_execution_state.terminal_code,
            "AGENT_ROUTE_TIMEOUT",
        )
        self.assertTrue(resolver_cancelled)
        self.assertEqual(port_calls, 0)

    async def test_routed_state_cannot_execute_a_different_command(self) -> None:
        """한 command의 route snapshot을 다른 command 실행에 재사용하지 못한다."""

        port_calls = 0

        async def analysis_handler(request: AgentRequest):
            nonlocal port_calls
            port_calls += 1
            return {"status": "SUCCESS", "data": {}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    analysis_handler,
                )
            }
        )
        routed_request = _request(admitted=True)
        routing = await supervisor.route_with_state(routed_request)
        other_request = _request(
            conversation_id=routed_request.conversation_id,
            admitted=True,
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute_routed_with_state(other_request, routing)

        self.assertEqual(
            raised.exception.code,
            "AGENT_ROUTE_REQUEST_MISMATCH",
        )
        self.assertEqual(raised.exception.state.phase, AgentExecutionPhase.FAILED)
        self.assertEqual(port_calls, 0)

    async def test_capability_resolver_can_route_without_client_route(self) -> None:
        """교체 RAG의 승인 probe가 생기면 일반 입력도 같은 Supervisor 경계를 사용한다."""

        class EvidenceResolver:
            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                self.requested_route = request.command.requested_route
                return SupervisorDecision(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    reason="RAG_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                    evidence_refs=("rag-probe:receipt-1",),
                )

        resolver = EvidenceResolver()

        async def rag_handler(request: AgentRequest):
            return {"status": "SUCCESS", "data": {"agent": "rag"}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.INTERNAL_GUIDELINE: CallableAgentPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    rag_handler,
                )
            },
            route_resolver=resolver,
        )

        outcome = await supervisor.execute_with_state(_request(admitted=True))

        self.assertIsNone(resolver.requested_route)
        self.assertEqual(outcome.result.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(
            outcome.state.decision_source,
            AgentDecisionSource.CAPABILITY_EVIDENCE,
        )
        self.assertEqual(
            outcome.state.decision_evidence_refs,
            ("rag-probe:receipt-1",),
        )

    async def test_runtime_policy_can_block_capability_decision_before_port(self) -> None:
        """production registry가 승인하기 전에는 유효한 probe receipt도 실행으로 승격하지 않는다."""

        port_calls = 0

        class EvidenceResolver:
            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                return SupervisorDecision(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    reason="RAG_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                    evidence_refs=("rag-probe:receipt-disabled",),
                )

        async def rag_handler(request: AgentRequest):
            nonlocal port_calls
            port_calls += 1
            return {"status": "SUCCESS", "data": {}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.INTERNAL_GUIDELINE: CallableAgentPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    rag_handler,
                )
            },
            route_resolver=EvidenceResolver(),
            allowed_decision_sources=frozenset(
                {
                    AgentDecisionSource.EXPLICIT_COMMAND,
                    AgentDecisionSource.GOVERNED_DEFAULT,
                }
            ),
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request(admitted=True))

        self.assertEqual(
            raised.exception.code,
            "AGENT_DECISION_SOURCE_NOT_APPROVED",
        )
        self.assertEqual(port_calls, 0)
        self.assertEqual(
            raised.exception.agent_execution_state.terminal_evidence_refs,
            ("rag-probe:receipt-disabled",),
        )

    async def test_resolver_cannot_emit_an_undeclared_decision_source(self) -> None:
        """사전 registry 검사를 통과하려고 안전한 source만 선언한 resolver의 거짓 결정을 차단한다."""

        class LyingResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.GOVERNED_DEFAULT}
            )

            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                return SupervisorDecision(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    reason="RAG_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                    evidence_refs=("rag-probe:undeclared-source",),
                )

        supervisor = DeterministicAgentSupervisor(
            {},
            route_resolver=LyingResolver(),
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request(admitted=True))

        self.assertEqual(
            raised.exception.code,
            "AGENT_ROUTE_RESOLVER_SOURCE_MISMATCH",
        )
        self.assertEqual(
            raised.exception.agent_execution_state.terminal_evidence_refs,
            ("rag-probe:undeclared-source",),
        )

    async def test_capability_decision_without_evidence_fails_before_port(self) -> None:
        """자동 RAG를 주장하면서 probe receipt가 없으면 실행하지 않는다."""

        class InvalidResolver:
            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                return SupervisorDecision(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    reason="RAG_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                )

        supervisor = DeterministicAgentSupervisor(
            {},
            route_resolver=InvalidResolver(),
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request())

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_EVIDENCE_REQUIRED")
        state = raised.exception.agent_execution_state
        self.assertEqual(state.phase, AgentExecutionPhase.FAILED)
        self.assertIsNone(state.selected_agent)
        self.assertEqual(state.revision, 1)

    async def test_capability_probe_routes_only_one_evidence_backed_match(self) -> None:
        """일반 입력은 정확히 한 probe가 매칭될 때만 해당 Agent로 전달된다."""

        analysis_probe = _StaticCapabilityProbe(
            AgentKind.ANALYSIS_WORKFLOW,
            AgentCapabilityEvidence(
                agent=AgentKind.ANALYSIS_WORKFLOW,
                matched=False,
                reason="ANALYSIS_NOT_SUPPORTED",
                evidence_refs=("analysis-probe:receipt-1",),
            ),
        )
        rag_probe = _StaticCapabilityProbe(
            AgentKind.INTERNAL_GUIDELINE,
            AgentCapabilityEvidence(
                agent=AgentKind.INTERNAL_GUIDELINE,
                matched=True,
                reason="RAG_CAPABILITY_MATCH",
                evidence_refs=("rag-probe:receipt-1",),
            ),
        )

        async def rag_handler(request: AgentRequest):
            return {"status": "SUCCESS", "data": {"agent": "rag"}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.INTERNAL_GUIDELINE: CallableAgentPort(
                    AgentKind.INTERNAL_GUIDELINE,
                    rag_handler,
                )
            },
            route_resolver=CapabilityEvidenceRouteResolver(
                {
                    AgentKind.ANALYSIS_WORKFLOW: analysis_probe,
                    AgentKind.INTERNAL_GUIDELINE: rag_probe,
                }
            ),
        )

        outcome = await supervisor.execute_with_state(_request(admitted=True))

        self.assertEqual(outcome.result.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(
            outcome.state.decision_evidence_refs,
            ("rag-probe:receipt-1",),
        )
        self.assertEqual(analysis_probe.calls, 1)
        self.assertEqual(rag_probe.calls, 1)

    async def test_capability_probes_run_as_bounded_parallel_fan_in(self) -> None:
        """독립 search-only probe의 지연을 순차 합산하지 않고 결과 순서만 고정한다."""

        both_started = asyncio.Event()
        started: set[AgentKind] = set()

        class CoordinatedProbe:
            def __init__(self, agent: AgentKind, matched: bool) -> None:
                self._agent = agent
                self._matched = matched

            @property
            def agent(self) -> AgentKind:
                return self._agent

            async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
                started.add(self._agent)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=0.5)
                return AgentCapabilityEvidence(
                    agent=self._agent,
                    matched=self._matched,
                    reason=(
                        "ANALYSIS_CAPABILITY_MATCH"
                        if self._matched
                        else "RAG_CAPABILITY_NOT_MATCHED"
                    ),
                    evidence_refs=(f"probe:{self._agent.value}",),
                )

        resolver = CapabilityEvidenceRouteResolver(
            {
                AgentKind.ANALYSIS_WORKFLOW: CoordinatedProbe(
                    AgentKind.ANALYSIS_WORKFLOW,
                    True,
                ),
                AgentKind.INTERNAL_GUIDELINE: CoordinatedProbe(
                    AgentKind.INTERNAL_GUIDELINE,
                    False,
                ),
            }
        )

        decision = await resolver.resolve(_request(admitted=True))

        self.assertEqual(decision.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(
            started,
            {AgentKind.ANALYSIS_WORKFLOW, AgentKind.INTERNAL_GUIDELINE},
        )

    async def test_explicit_route_bypasses_capability_probes(self) -> None:
        """명시된 사용자 route는 candidate probe 가용성에 의존하지 않는다."""

        rag_probe = _StaticCapabilityProbe(
            AgentKind.INTERNAL_GUIDELINE,
            error=RuntimeError("probe must not run"),
        )
        resolver = CapabilityEvidenceRouteResolver(
            {AgentKind.INTERNAL_GUIDELINE: rag_probe}
        )

        decision = await resolver.resolve(_request("INTERNAL_GUIDELINE"))

        self.assertEqual(decision.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(decision.source, AgentDecisionSource.EXPLICIT_COMMAND)
        self.assertEqual(rag_probe.calls, 0)

    async def test_no_capability_match_fails_with_probe_receipts(self) -> None:
        """0개 매칭을 기존 분석 경로로 숨기지 않고 판정 근거와 함께 차단한다."""

        resolver = CapabilityEvidenceRouteResolver(
            {
                AgentKind.INTERNAL_GUIDELINE: _StaticCapabilityProbe(
                    AgentKind.INTERNAL_GUIDELINE,
                    AgentCapabilityEvidence(
                        agent=AgentKind.INTERNAL_GUIDELINE,
                        matched=False,
                        reason="RAG_NOT_SUPPORTED",
                        evidence_refs=("rag-probe:no-match-1",),
                    ),
                )
            }
        )
        supervisor = DeterministicAgentSupervisor({}, route_resolver=resolver)

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request(admitted=True))

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_NOT_RESOLVED")
        self.assertEqual(
            raised.exception.evidence_refs,
            ("rag-probe:no-match-1",),
        )
        self.assertEqual(
            raised.exception.agent_execution_state.phase,
            AgentExecutionPhase.FAILED,
        )
        self.assertEqual(
            raised.exception.agent_execution_state.terminal_evidence_refs,
            ("rag-probe:no-match-1",),
        )

    async def test_multiple_capability_matches_fail_as_ambiguous(self) -> None:
        """복수 Agent 매칭은 registry 순서로 임의 선택하지 않는다."""

        resolver = CapabilityEvidenceRouteResolver(
            {
                AgentKind.ANALYSIS_WORKFLOW: _StaticCapabilityProbe(
                    AgentKind.ANALYSIS_WORKFLOW,
                    AgentCapabilityEvidence(
                        agent=AgentKind.ANALYSIS_WORKFLOW,
                        matched=True,
                        reason="ANALYSIS_CAPABILITY_MATCH",
                        evidence_refs=("analysis-probe:match-1",),
                    ),
                ),
                AgentKind.INTERNAL_GUIDELINE: _StaticCapabilityProbe(
                    AgentKind.INTERNAL_GUIDELINE,
                    AgentCapabilityEvidence(
                        agent=AgentKind.INTERNAL_GUIDELINE,
                        matched=True,
                        reason="RAG_CAPABILITY_MATCH",
                        evidence_refs=("rag-probe:match-1",),
                    ),
                ),
            }
        )
        supervisor = DeterministicAgentSupervisor({}, route_resolver=resolver)

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request(admitted=True))

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_AMBIGUOUS")
        self.assertEqual(
            raised.exception.evidence_refs,
            ("analysis-probe:match-1", "rag-probe:match-1"),
        )
        self.assertEqual(
            raised.exception.agent_execution_state.terminal_evidence_refs,
            ("analysis-probe:match-1", "rag-probe:match-1"),
        )

    async def test_duplicate_cross_probe_receipt_is_rejected(self) -> None:
        """서로 다른 Agent가 같은 receipt를 주장하면 임의 route 결정을 만들지 않는다."""

        duplicate_ref = "probe:duplicated-receipt"
        resolver = CapabilityEvidenceRouteResolver(
            {
                AgentKind.ANALYSIS_WORKFLOW: _StaticCapabilityProbe(
                    AgentKind.ANALYSIS_WORKFLOW,
                    AgentCapabilityEvidence(
                        agent=AgentKind.ANALYSIS_WORKFLOW,
                        matched=True,
                        reason="ANALYSIS_CAPABILITY_MATCH",
                        evidence_refs=(duplicate_ref,),
                    ),
                ),
                AgentKind.INTERNAL_GUIDELINE: _StaticCapabilityProbe(
                    AgentKind.INTERNAL_GUIDELINE,
                    AgentCapabilityEvidence(
                        agent=AgentKind.INTERNAL_GUIDELINE,
                        matched=False,
                        reason="RAG_CAPABILITY_NOT_MATCHED",
                        evidence_refs=(duplicate_ref,),
                    ),
                ),
            }
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await resolver.resolve(_request(admitted=True))

        self.assertEqual(
            raised.exception.code,
            "AGENT_CAPABILITY_EVIDENCE_INVALID",
        )

    async def test_capability_probe_failure_does_not_fall_back(self) -> None:
        """probe 장애를 분석 Agent 선택으로 바꾸지 않는다."""

        resolver = CapabilityEvidenceRouteResolver(
            {
                AgentKind.INTERNAL_GUIDELINE: _StaticCapabilityProbe(
                    AgentKind.INTERNAL_GUIDELINE,
                    error=TimeoutError("probe timeout"),
                )
            }
        )
        supervisor = DeterministicAgentSupervisor({}, route_resolver=resolver)

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request(admitted=True))

        self.assertEqual(raised.exception.code, "AGENT_CAPABILITY_PROBE_FAILED")
        self.assertEqual(
            raised.exception.agent_execution_state.phase,
            AgentExecutionPhase.FAILED,
        )

    async def test_unadmitted_general_request_never_calls_capability_probe(self) -> None:
        """command lease·release receipt 전에는 search-only probe도 실행하지 않는다."""

        probe = _StaticCapabilityProbe(
            AgentKind.ANALYSIS_WORKFLOW,
            AgentCapabilityEvidence(
                agent=AgentKind.ANALYSIS_WORKFLOW,
                matched=True,
                reason="ANALYSIS_CAPABILITY_MATCH",
                evidence_refs=("analysis-probe:must-not-run",),
            ),
        )
        resolver = CapabilityEvidenceRouteResolver(
            {AgentKind.ANALYSIS_WORKFLOW: probe}
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await resolver.resolve(_request())

        self.assertEqual(
            raised.exception.code,
            "AGENT_CAPABILITY_CONTEXT_INCOMPLETE",
        )
        self.assertEqual(probe.calls, 0)

    async def test_ml_route_without_structured_invocation_is_rejected(self) -> None:
        calls = 0

        class MLResolver:
            async def resolve(self, request: AgentRequest) -> SupervisorDecision:
                return SupervisorDecision(
                    agent=AgentKind.ML_PREDICTION,
                    reason="STRUCTURED_ML_ROUTE",
                    source=AgentDecisionSource.GOVERNED_DEFAULT,
                )

        async def handler(request: AgentRequest):
            nonlocal calls
            calls += 1
            return {"status": "SUCCESS", "data": {}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ML_PREDICTION: CallableAgentPort(
                    AgentKind.ML_PREDICTION,
                    handler,
                )
            },
            route_resolver=MLResolver(),
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(_request(admitted=True))

        self.assertEqual(raised.exception.code, "AGENT_INVOCATION_MISMATCH")
        self.assertEqual(calls, 0)

    async def test_ml_invocation_cannot_flow_to_a_non_ml_agent(self) -> None:
        calls = 0

        async def handler(request: AgentRequest):
            nonlocal calls
            calls += 1
            return {"status": "SUCCESS", "data": {}}

        supervisor = DeterministicAgentSupervisor(
            {
                AgentKind.ANALYSIS_WORKFLOW: CallableAgentPort(
                    AgentKind.ANALYSIS_WORKFLOW,
                    handler,
                )
            }
        )
        request = _request(
            admitted=True,
            invocation=MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=90,
            ),
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.execute(request)

        self.assertEqual(raised.exception.code, "AGENT_INVOCATION_MISMATCH")
        self.assertEqual(calls, 0)

    async def test_readiness_guard_blocks_port_execution_without_ready_receipt(self) -> None:
        calls = 0

        class NotReadyPort:
            agent = AgentKind.INTERNAL_GUIDELINE

            async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
                return AgentPortReadiness(
                    agent=self.agent,
                    status="not_ready",
                    capability_version="RagRuntimeReceipt.v1",
                    reason="runtime unavailable",
                )

            async def execute(self, request: AgentRequest) -> AgentResult:
                nonlocal calls
                calls += 1
                return AgentResult(agent=self.agent, payload={})

        guarded = ReadinessGuardedAgentPort(NotReadyPort())

        with self.assertRaises(AgentDispatchError) as raised:
            await guarded.execute(_request("INTERNAL_GUIDELINE"))

        self.assertEqual(raised.exception.code, "AGENT_PORT_NOT_READY")
        self.assertEqual(calls, 0)

    async def test_callable_port_readiness_is_explicitly_test_scoped(self) -> None:
        async def handler(request: AgentRequest):
            return {"status": "SUCCESS"}

        readiness = await CallableAgentPort(
            AgentKind.ANALYSIS_WORKFLOW,
            handler,
        ).readiness(_request())

        self.assertEqual(readiness.capability_version, "CallableAgentPort.test.v1")
        self.assertTrue(readiness.release_refs[0].startswith("agent-port:test-callable:"))

    def test_request_rejects_cross_conversation_context(self) -> None:
        """다른 Conversation에 이미 결속된 RequestContext를 재사용하지 못한다."""

        with self.assertRaises(ValidationError):
            _request(
                conversation_id=uuid4(),
                context_conversation_id=uuid4(),
            )

    def test_request_rejects_ml_target_without_prediction_invocation(self) -> None:
        payload = _request(admitted=True).model_dump()
        payload["target_agent"] = AgentKind.ML_PREDICTION

        with self.assertRaises(ValidationError):
            AgentRequest.model_validate(payload)

    def test_request_rejects_prediction_invocation_for_non_ml_target(self) -> None:
        payload = _request(admitted=True).model_dump()
        payload["target_agent"] = AgentKind.ANALYSIS_WORKFLOW
        payload["invocation"] = MLPredictionInvocation(
            property_id="GRAND",
            as_of="2026-08-28",
            horizon_days=90,
        ).model_dump()

        with self.assertRaises(ValidationError):
            AgentRequest.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
