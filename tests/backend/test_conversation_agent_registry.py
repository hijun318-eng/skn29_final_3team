"""Conversation Agent registry가 구현 완료 port만 노출하는지 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent_contracts import AgentDecisionSource
from app.authorization import permission_snapshot_id
from app.contracts import RequestContext, Role
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import AgentKind, AgentRequest, MLPredictionInvocation
from app.services.agent_supervisor import (
    AgentDispatchError,
    CallableAgentPort,
    ReadinessGuardedAgentPort,
    SupervisorDecision,
)
from app.services.conversation_agent_registry import (
    build_conversation_agent_supervisor,
)
from app.services.execution_control import ConcurrentExecutionGate


def _ml_capability(
    *,
    max_horizon_days: int = 90,
    approval: str = "APPROVED",
    approval_status: str = "APPROVED",
    synthetic_training_data: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": "MLRuntimeCapability.v2",
        "prediction_contract_version": "MLRoomDemandPrediction.v1",
        "model_version": "approved-demand-release",
        "model_hash": "a" * 64,
        "feature_contract_sha256": "b" * 64,
        "model_type": "daily-demand-forecast",
        "estimator_type": "ApprovedRegressor",
        "approval": approval,
        "approval_status": approval_status,
        "min_horizon_days": 1,
        "max_horizon_days": max_horizon_days,
        "model_max_horizon_days": max_horizon_days,
        "properties": [
            {
                "property_id": "GRAND",
                "min_as_of": "2025-01-01",
                "max_as_of": "2026-12-31",
                "feature_max_as_of": "2026-08-28",
                "history_rows": 500,
            }
        ],
        "synthetic_training_data": synthetic_training_data,
        "history_source": {
            "table": "pms.ml_evaluation.approved_history",
            "row_count": 500,
            "property_count": 1,
            "series_count": 1,
            "min_date": "2024-01-01",
            "max_date": "2026-08-28",
            "synthetic_only": synthetic_training_data,
            "summary_query_id": "summary-query",
            "continuity_query_id": "continuity-query",
        },
        "query_id": "capability-query",
    }


class _MLService:
    def __init__(
        self,
        *,
        max_horizon_days: int = 90,
        approval: str = "APPROVED",
        approval_status: str = "APPROVED",
        synthetic_training_data: bool = False,
    ) -> None:
        self._capability = _ml_capability(
            max_horizon_days=max_horizon_days,
            approval=approval,
            approval_status=approval_status,
            synthetic_training_data=synthetic_training_data,
        )
        self.capability_calls = 0

    async def capabilities(self) -> dict[str, object]:
        self.capability_calls += 1
        return self._capability


class ConversationAgentRegistryTest(unittest.IsolatedAsyncioTestCase):
    """선택 Agent가 feature·capability 계약을 통해야만 등록되게 한다."""

    def test_registry_excludes_disabled_optional_agents(self) -> None:
        ml_factory_calls = 0

        def ml_factory() -> _MLService:
            nonlocal ml_factory_calls
            ml_factory_calls += 1
            return _MLService()

        with patch.dict(
            "os.environ",
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "0"},
        ):
            supervisor = build_conversation_agent_supervisor(
                orchestrator=object(),
                execution_gate=ConcurrentExecutionGate(),
                internal_manual_query_service_factory=lambda: None,
                ml_prediction_service_factory=ml_factory,
            )

        self.assertEqual(
            supervisor.registered_agents,
            frozenset({AgentKind.ANALYSIS_WORKFLOW}),
        )
        self.assertNotIsInstance(
            supervisor._ports[AgentKind.ANALYSIS_WORKFLOW],
            CallableAgentPort,
        )
        self.assertEqual(ml_factory_calls, 0)

    def test_registry_adds_enabled_rag_and_ml_agents(self) -> None:
        with patch.dict("os.environ", {
            "RAG_FEATURE_ENABLED": "1",
            "ML_FEATURE_ENABLED": "1",
        }):
            supervisor = build_conversation_agent_supervisor(
                orchestrator=object(),
                execution_gate=ConcurrentExecutionGate(),
                internal_manual_query_service_factory=lambda: None,
                ml_prediction_service_factory=_MLService,
            )

        self.assertEqual(
            supervisor.registered_agents,
            frozenset(
                {
                    AgentKind.ANALYSIS_WORKFLOW,
                    AgentKind.INTERNAL_GUIDELINE,
                    AgentKind.ML_PREDICTION,
                }
            ),
        )
        self.assertIsInstance(
            supervisor._ports[AgentKind.INTERNAL_GUIDELINE],
            ReadinessGuardedAgentPort,
        )
        self.assertIsInstance(
            supervisor._ports[AgentKind.ML_PREDICTION],
            ReadinessGuardedAgentPort,
        )

    async def test_enabled_ml_keeps_general_input_on_governed_analysis(self) -> None:
        service = _MLService()
        conversation_id = uuid4()
        request = AgentRequest(
            conversation_id=conversation_id,
            command=ConversationCommandRequest(
                user_message="지난달 객실 매출을 분석해줘",
                idempotency_key=uuid4().hex,
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
        with patch.dict(
            "os.environ",
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "1"},
        ):
            supervisor = build_conversation_agent_supervisor(
                orchestrator=object(),
                execution_gate=ConcurrentExecutionGate(),
                internal_manual_query_service_factory=lambda: None,
                ml_prediction_service_factory=lambda: service,
            )

        routing = await supervisor.route_with_state(request)

        self.assertEqual(routing.decision.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(
            routing.decision.source,
            AgentDecisionSource.GOVERNED_DEFAULT,
        )
        self.assertEqual(service.capability_calls, 0)

    async def test_explicit_ml_requires_matching_runtime_capability(self) -> None:
        service = _MLService(max_horizon_days=7)
        conversation_id = uuid4()
        user_id = uuid4()
        invocation = MLPredictionInvocation(
            property_id="GRAND",
            as_of="2026-08-28",
            horizon_days=30,
        )
        request = AgentRequest(
            conversation_id=conversation_id,
            command=ConversationCommandRequest(
                user_message="30일 객실 수요를 예측해줘",
                idempotency_key=uuid4().hex,
                expected_head_turn_id=None,
                requested_route="ML_PREDICTION",
                ml_prediction={
                    "property_id": invocation.property_id,
                    "as_of": invocation.as_of,
                    "horizon_days": invocation.horizon_days,
                },
            ),
            context=RequestContext(
                conversation_id=conversation_id,
                user_id=user_id,
                role=Role.ANALYST,
                command_id=uuid4(),
                permission_snapshot_id=permission_snapshot_id(
                    user_id,
                    Role.ANALYST,
                ),
                product_release_id="product-release-v1",
                semantic_release_id="semantic-release-v1",
            ),
            target_agent=AgentKind.ML_PREDICTION,
            invocation=invocation,
        )
        with patch.dict(
            "os.environ",
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "1"},
        ):
            supervisor = build_conversation_agent_supervisor(
                orchestrator=object(),
                execution_gate=ConcurrentExecutionGate(),
                internal_manual_query_service_factory=lambda: None,
                ml_prediction_service_factory=lambda: service,
            )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.route_with_state(request)

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_NOT_RESOLVED")
        self.assertEqual(service.capability_calls, 1)

    async def test_explicit_ml_route_rejects_conditional_candidate_registry(self) -> None:
        service = _MLService(
            approval="CONDITIONAL_PASS",
            approval_status="VALIDATED_SYNTHETIC",
            synthetic_training_data=True,
        )
        conversation_id = uuid4()
        user_id = uuid4()
        invocation = MLPredictionInvocation(
            property_id="GRAND",
            as_of="2026-08-28",
            horizon_days=7,
        )
        request = AgentRequest(
            conversation_id=conversation_id,
            command=ConversationCommandRequest(
                user_message="7일 객실 수요를 예측해줘",
                idempotency_key=uuid4().hex,
                expected_head_turn_id=None,
                requested_route="ML_PREDICTION",
                ml_prediction={
                    "property_id": invocation.property_id,
                    "as_of": invocation.as_of,
                    "horizon_days": invocation.horizon_days,
                },
            ),
            context=RequestContext(
                conversation_id=conversation_id,
                user_id=user_id,
                role=Role.ANALYST,
                command_id=uuid4(),
                permission_snapshot_id=permission_snapshot_id(
                    user_id,
                    Role.ANALYST,
                ),
                product_release_id="product-release-v1",
                semantic_release_id="semantic-release-v1",
            ),
            target_agent=AgentKind.ML_PREDICTION,
            invocation=invocation,
        )
        with patch.dict(
            "os.environ",
            {
                "RAG_FEATURE_ENABLED": "0",
                "ML_FEATURE_ENABLED": "1",
                "ML_ALLOW_CONDITIONAL": "true",
            },
        ):
            supervisor = build_conversation_agent_supervisor(
                orchestrator=object(),
                execution_gate=ConcurrentExecutionGate(),
                internal_manual_query_service_factory=lambda: None,
                ml_prediction_service_factory=lambda: service,
            )

        with self.assertRaises(AgentDispatchError) as raised:
            await supervisor.route_with_state(request)

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_NOT_RESOLVED")
        self.assertEqual(service.capability_calls, 1)

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
