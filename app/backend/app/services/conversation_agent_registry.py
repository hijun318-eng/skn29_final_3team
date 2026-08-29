"""Conversation API에 실제 구현된 AgentPort registry를 조립한다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agent_contracts import AgentDecisionSource
from app.ports.agent import AgentKind
from app.services.agent_supervisor import (
    AgentDispatchError,
    AgentRouteResolver,
    DeterministicAgentSupervisor,
)
from app.services.conversation_agent_ports import (
    AnalysisWorkflowAgentPort,
    InternalGuidelineAgentPort,
)
from app.services.execution_control import ConcurrentExecutionGate
from app.services.internal_manual_query import InternalManualQueryService


def build_conversation_agent_supervisor(
    orchestrator: Any,
    execution_gate: ConcurrentExecutionGate,
    internal_manual_query_service_factory: Callable[
        [], InternalManualQueryService
    ],
    *,
    route_resolver: AgentRouteResolver | None = None,
    admission: Any | None = None,
    capability_routing_enabled: bool = False,
) -> DeterministicAgentSupervisor:
    """현재 완성된 분석·내부지침 port만 등록하고 미구현 Agent는 제외한다."""

    if type(capability_routing_enabled) is not bool:
        raise AgentDispatchError(
            "AGENT_CAPABILITY_ROUTING_FLAG_INVALID",
            "자동 capability route 활성화 설정이 올바르지 않습니다.",
        )
    allowed_decision_sources = {
        AgentDecisionSource.EXPLICIT_COMMAND,
        AgentDecisionSource.GOVERNED_DEFAULT,
    }
    if capability_routing_enabled:
        allowed_decision_sources.add(AgentDecisionSource.CAPABILITY_EVIDENCE)
    if route_resolver is not None:
        declared_sources = getattr(route_resolver, "decision_sources", None)
        if (
            not isinstance(declared_sources, frozenset)
            or not declared_sources
            or any(
                not isinstance(source, AgentDecisionSource)
                for source in declared_sources
            )
        ):
            raise AgentDispatchError(
                "AGENT_ROUTE_RESOLVER_POLICY_UNDECLARED",
                "Agent route resolver의 결정 출처 선언이 올바르지 않습니다.",
            )
        if not declared_sources.issubset(allowed_decision_sources):
            raise AgentDispatchError(
                "AGENT_ROUTE_RESOLVER_NOT_APPROVED",
                "현재 registry에서 자동 capability resolver가 승인되지 않았습니다.",
            )

    return DeterministicAgentSupervisor(
        {
            AgentKind.ANALYSIS_WORKFLOW: AnalysisWorkflowAgentPort(
                orchestrator,
                execution_gate,
                admission=admission,
            ),
            AgentKind.INTERNAL_GUIDELINE: InternalGuidelineAgentPort(
                orchestrator,
                internal_manual_query_service_factory,
                admission=admission,
            ),
        },
        route_resolver=route_resolver,
        allowed_decision_sources=frozenset(allowed_decision_sources),
    )
