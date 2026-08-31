"""모델 계획과 capability receipt가 결합된 route 계약을 검증한다."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.agent_contracts import AgentDecisionSource  # noqa: E402
from app.contracts import RequestContext  # noqa: E402
from app.conversation_contracts import ConversationCommandRequest  # noqa: E402
from app.ports.agent import AgentKind, AgentRequest  # noqa: E402
from app.services.agent_supervisor import (  # noqa: E402
    AgentCapabilityEvidence,
    AgentDispatchError,
    CapabilityEvidenceRouteResolver,
)


class _MatchedAnalysisProbe:
    agent = AgentKind.ANALYSIS_WORKFLOW

    async def probe(self, _request: AgentRequest) -> AgentCapabilityEvidence:
        return AgentCapabilityEvidence(
            agent=self.agent,
            matched=True,
            reason="ANALYSIS_CAPABILITY_MATCH",
            evidence_refs=("agent-capability:v1:analysis-workflow:test",),
        )


def _planned_request() -> AgentRequest:
    conversation_id = uuid4()
    return AgentRequest(
        conversation_id=conversation_id,
        command=ConversationCommandRequest(
            user_message="객실 매출을 분석해줘",
            idempotency_key=f"planned-{uuid4()}",
            expected_head_turn_id=None,
        ),
        context=RequestContext(
            conversation_id=conversation_id,
            user_id=uuid4(),
            command_id=uuid4(),
            permission_snapshot_id="permission-v1",
            product_release_id="product-v1",
            semantic_release_id="semantic-v1",
        ),
        target_agent=AgentKind.ANALYSIS_WORKFLOW,
        supervisor_plan_ref=f"model-supervisor:sha256:{'a' * 64}",
    )


def test_model_plan_requires_selected_capability_receipt() -> None:
    resolver = CapabilityEvidenceRouteResolver(
        {AgentKind.ANALYSIS_WORKFLOW: _MatchedAnalysisProbe()}
    )

    decision = asyncio.run(resolver.resolve(_planned_request()))

    assert decision.agent is AgentKind.ANALYSIS_WORKFLOW
    assert decision.source is AgentDecisionSource.MODEL_SUPERVISOR
    assert decision.evidence_refs == (
        f"model-supervisor:sha256:{'a' * 64}",
        "agent-capability:v1:analysis-workflow:test",
    )


def test_model_plan_fails_when_selected_probe_is_not_registered() -> None:
    request = _planned_request().model_copy(
        update={"target_agent": AgentKind.INTERNAL_GUIDELINE}
    )
    resolver = CapabilityEvidenceRouteResolver(
        {AgentKind.ANALYSIS_WORKFLOW: _MatchedAnalysisProbe()}
    )

    with pytest.raises(AgentDispatchError) as captured:
        asyncio.run(resolver.resolve(request))

    assert captured.value.code == "AGENT_CAPABILITY_NOT_CONFIGURED"
    assert captured.value.evidence_refs == (
        f"model-supervisor:sha256:{'a' * 64}",
    )
