"""Conversation API에 실제 구현된 AgentPort registry를 조립한다."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from app.agent_contracts import AgentDecisionSource
from app.contracts import RuntimeFeature
from app.ports.agent import AgentKind
from app.runtime_features import runtime_feature_enabled
from app.ports.data_platform import DataPlatformAdapter
from app.services.agent_capability_probes import (
    GovernedAnalysisCapabilityProbe,
    InternalGuidelineCapabilityProbe,
    InternalGuidelineCapabilitySearcher,
    MLPredictionCapabilityProbe,
)
from app.services.agent_supervisor import (
    AgentDispatchError,
    AgentRouteResolver,
    CapabilityEvidenceRouteResolver,
    DeterministicAgentSupervisor,
    ReadinessGuardedAgentPort,
)
from app.services.conversation_agent_ports import (
    AnalysisWorkflowAgentPort,
    InternalGuidelineAgentPort,
    MLPredictionAgentPort,
)
from app.services.execution_control import ConcurrentExecutionGate
from app.services.internal_manual_query import InternalManualQueryService
from app.services.ml_prediction_service import MLPredictionService
from app.services.mcp_agent_tools import MCPMLPredictionExecutor


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
    data_platform: DataPlatformAdapter | None = None,
    internal_guideline_capability_searcher_factory: Callable[
        [], InternalGuidelineCapabilitySearcher
    ]
    | None = None,
    ml_prediction_service_factory: Callable[[], MLPredictionService] | None = None,
    ml_prediction_executor_factory: Callable[[MLPredictionService], Any] | None = None,
    composite_augmentation: Any | None = None,
) -> DeterministicAgentSupervisor:
    """필수 분석 Port와 명시적으로 활성화된 선택 Port만 production에 등록한다."""

    if type(capability_routing_enabled) is not bool:
        raise AgentDispatchError(
            "AGENT_CAPABILITY_ROUTING_FLAG_INVALID",
            "자동 capability route 활성화 설정이 올바르지 않습니다.",
        )
    rag_enabled = runtime_feature_enabled(RuntimeFeature.INTERNAL_GUIDELINE)
    ml_enabled = runtime_feature_enabled(RuntimeFeature.ML_PREDICTION)
    ml_service = (
        (ml_prediction_service_factory or MLPredictionService)()
        if ml_enabled
        else None
    )
    ml_executor = None
    if ml_service is not None:
        if ml_prediction_executor_factory is not None:
            ml_executor = ml_prediction_executor_factory(ml_service)
        else:
            database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
            if not database_url:
                raise AgentDispatchError(
                    "AGENT_PORT_NOT_READY",
                    "ML MCP 실행에 APP_RUNTIME_DATABASE_URL이 필요합니다.",
                )
            ml_executor = MCPMLPredictionExecutor(database_url, ml_service)
        if not callable(getattr(ml_executor, "readiness", None)) or not callable(
            getattr(ml_executor, "execute", None)
        ):
            raise AgentDispatchError(
                "AGENT_PORT_NOT_READY",
                "ML MCP executor 계약이 올바르지 않습니다.",
            )
    effective_route_resolver = route_resolver
    effective_capability_routing = capability_routing_enabled
    probes = {}
    if effective_route_resolver is None and capability_routing_enabled:
        if data_platform is None or not callable(
            getattr(data_platform, "search_asset_candidates", None)
        ):
            raise AgentDispatchError(
                "AGENT_CAPABILITY_REGISTRY_INVALID",
                "분석 capability probe 의존성이 구성되지 않았습니다.",
            )
        probes[AgentKind.ANALYSIS_WORKFLOW] = GovernedAnalysisCapabilityProbe(
            data_platform
        )
        if rag_enabled:
            if internal_guideline_capability_searcher_factory is None:
                raise AgentDispatchError(
                    "AGENT_CAPABILITY_REGISTRY_INVALID",
                    "RAG capability probe 의존성이 구성되지 않았습니다.",
                )
            searcher = internal_guideline_capability_searcher_factory()
            if not callable(getattr(searcher, "search_capability", None)):
                raise AgentDispatchError(
                    "AGENT_CAPABILITY_REGISTRY_INVALID",
                    "RAG capability searcher 계약이 올바르지 않습니다.",
                )
            probes[AgentKind.INTERNAL_GUIDELINE] = (
                InternalGuidelineCapabilityProbe(searcher)
            )
        if ml_service is not None:
            probes[AgentKind.ML_PREDICTION] = MLPredictionCapabilityProbe(
                ml_service
            )
    elif effective_route_resolver is None and ml_service is not None:
        probes[AgentKind.ML_PREDICTION] = MLPredictionCapabilityProbe(ml_service)

    if effective_route_resolver is None and probes:
        effective_route_resolver = CapabilityEvidenceRouteResolver(
            probes,
            automatic_routing_enabled=capability_routing_enabled,
        )
        effective_capability_routing = True

    allowed_decision_sources = {
        AgentDecisionSource.EXPLICIT_COMMAND,
        AgentDecisionSource.GOVERNED_DEFAULT,
    }
    if effective_capability_routing:
        allowed_decision_sources.add(AgentDecisionSource.CAPABILITY_EVIDENCE)
        allowed_decision_sources.add(AgentDecisionSource.MODEL_SUPERVISOR)
    if effective_route_resolver is not None:
        declared_sources = getattr(
            effective_route_resolver,
            "decision_sources",
            None,
        )
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

    ports = {
        AgentKind.ANALYSIS_WORKFLOW: ReadinessGuardedAgentPort(
            AnalysisWorkflowAgentPort(
                orchestrator,
                execution_gate,
                admission=admission,
                composite_augmentation=composite_augmentation,
            )
        ),
    }
    if rag_enabled:
        ports[AgentKind.INTERNAL_GUIDELINE] = ReadinessGuardedAgentPort(
            InternalGuidelineAgentPort(
                orchestrator,
                internal_manual_query_service_factory,
                admission=admission,
                composite_augmentation=composite_augmentation,
            )
        )
    if ml_executor is not None:
        ports[AgentKind.ML_PREDICTION] = ReadinessGuardedAgentPort(
            MLPredictionAgentPort(
                orchestrator,
                ml_executor,
                admission=admission,
            )
        )

    return DeterministicAgentSupervisor(
        ports,
        route_resolver=effective_route_resolver,
        allowed_decision_sources=frozenset(allowed_decision_sources),
    )
