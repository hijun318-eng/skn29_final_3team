"""결정론적 Supervisor와 concrete AgentPort를 LangGraph 실행 그래프로 조립한다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.ports.agent import AgentKind, AgentRequest
from app.services.agent_supervisor import (
    AgentDispatchError,
    AgentExecutionOutcome,
    AgentRoutingOutcome,
    DeterministicAgentSupervisor,
)


SUPERVISOR_ROUTE_NODE = "supervisor_route"
ANALYSIS_AGENT_NODE = "analysis_workflow_agent"
INTERNAL_GUIDELINE_AGENT_NODE = "internal_guideline_agent"
ML_PREDICTION_AGENT_NODE = "ml_prediction_agent"


def _agent_node_name(agent: AgentKind) -> str:
    """Agent enum을 안정적인 LangGraph node 이름으로 변환한다."""

    return f"{agent.value.lower()}_agent"


class _AgentGraphState(TypedDict, total=False):
    """한 admitted command의 graph-local 객체만 전달하는 비영속 실행 상태다."""

    request: AgentRequest
    routing: AgentRoutingOutcome
    outcome: AgentExecutionOutcome


_AfterRouteHook = Callable[[AgentRoutingOutcome], Awaitable[None]]


class LangGraphAgentRuntime:
    """모델 추론 없이 Supervisor 결정에 따라 정확히 한 Agent node를 실행한다."""

    def __init__(
        self,
        supervisor: DeterministicAgentSupervisor,
        *,
        route_timeout_seconds: float | None = None,
        after_route: _AfterRouteHook | None = None,
    ) -> None:
        """현재 command용 graph를 구성하되 별도 checkpointer는 연결하지 않는다."""

        if not isinstance(supervisor, DeterministicAgentSupervisor):
            raise TypeError("LangGraph runtime에는 DeterministicAgentSupervisor가 필요합니다.")
        self._supervisor = supervisor
        self._route_timeout_seconds = route_timeout_seconds
        self._after_route = after_route

        builder = StateGraph(_AgentGraphState)
        builder.add_node(SUPERVISOR_ROUTE_NODE, self._route)
        self._agent_nodes = {
            agent: _agent_node_name(agent)
            for agent in AgentKind
        }
        for agent, node_name in self._agent_nodes.items():
            async def execute_agent(
                state: _AgentGraphState,
                *,
                expected_agent: AgentKind = agent,
            ) -> _AgentGraphState:
                return await self._execute_selected(state, expected_agent)

            builder.add_node(node_name, execute_agent)
        builder.add_edge(START, SUPERVISOR_ROUTE_NODE)
        builder.add_conditional_edges(
            SUPERVISOR_ROUTE_NODE,
            self._selected_agent_node,
            {node_name: node_name for node_name in self._agent_nodes.values()},
        )
        for node_name in self._agent_nodes.values():
            builder.add_edge(node_name, END)
        self._graph = builder.compile(name="answervice-agent-supervisor")

    async def execute(self, request: AgentRequest) -> AgentExecutionOutcome:
        """admission-bound 요청을 그래프로 실행하고 검증된 terminal outcome을 반환한다."""

        if not isinstance(request, AgentRequest):
            raise TypeError("LangGraph Agent 실행에는 AgentRequest가 필요합니다.")
        final_state = await self._graph.ainvoke({"request": request})
        outcome = final_state.get("outcome")
        if not isinstance(outcome, AgentExecutionOutcome):
            raise AgentDispatchError(
                "AGENT_GRAPH_OUTCOME_MISSING",
                "Agent graph가 terminal 실행 결과를 반환하지 않았습니다.",
            )
        return outcome

    async def _route(self, state: _AgentGraphState) -> _AgentGraphState:
        """Supervisor route node를 한 번 실행하고 선택 결과를 다음 node에 전달한다."""

        request = self._request(state)
        routing = await self._supervisor.route_with_state(
            request,
            timeout_seconds=self._route_timeout_seconds,
        )
        if self._after_route is not None:
            await self._after_route(routing)
        return {"routing": routing}

    def _selected_agent_node(self, state: _AgentGraphState) -> str:
        """ROUTED 상태의 Agent 종류를 등록된 graph node 이름으로만 변환한다."""

        routing = self._routing(state)
        node = self._agent_nodes.get(routing.decision.agent)
        if node is None:
            raise AgentDispatchError(
                "AGENT_GRAPH_ROUTE_NOT_REGISTERED",
                "선택된 Agent의 graph node가 등록되지 않았습니다.",
                state=routing.state,
            )
        return node

    async def _execute_selected(
        self,
        state: _AgentGraphState,
        expected_agent: AgentKind,
    ) -> _AgentGraphState:
        """조건부 edge와 Supervisor 결정이 같을 때만 routed 실행을 위임한다."""

        request = self._request(state)
        routing = self._routing(state)
        if routing.decision.agent is not expected_agent:
            raise AgentDispatchError(
                "AGENT_GRAPH_NODE_MISMATCH",
                "Agent graph node와 Supervisor 결정이 일치하지 않습니다.",
                state=routing.state,
            )
        outcome = await self._supervisor.execute_routed_with_state(
            request,
            routing,
        )
        return {"outcome": outcome}

    @staticmethod
    def _request(state: _AgentGraphState) -> AgentRequest:
        """graph state에서 admission-bound 요청만 허용한다."""

        request = state.get("request")
        if not isinstance(request, AgentRequest):
            raise AgentDispatchError(
                "AGENT_GRAPH_REQUEST_MISSING",
                "Agent graph 요청 상태가 올바르지 않습니다.",
            )
        return request

    @staticmethod
    def _routing(state: _AgentGraphState) -> AgentRoutingOutcome:
        """graph state에서 검증된 ROUTED outcome만 허용한다."""

        routing = state.get("routing")
        if not isinstance(routing, AgentRoutingOutcome):
            raise AgentDispatchError(
                "AGENT_GRAPH_ROUTING_MISSING",
                "Agent graph route 상태가 올바르지 않습니다.",
            )
        return routing
