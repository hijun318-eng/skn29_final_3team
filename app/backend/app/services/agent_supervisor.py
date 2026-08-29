"""모델 추론 없이 승인된 conversation route를 AgentPort에 전달한다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.ports.agent import AgentKind, AgentPort, AgentRequest, AgentResult


class AgentDispatchError(RuntimeError):
    """Supervisor가 안전하게 실행할 수 없는 route·port·result를 구분한다."""

    def __init__(self, code: str, message: str) -> None:
        """안정적인 오류 코드와 공개 가능한 메시지를 보존한다."""

        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SupervisorDecision:
    """서버가 확정한 단일 Agent와 결정 근거를 기록한다."""

    agent: AgentKind
    reason: str


class CallableAgentPort:
    """전환 기간의 기존 use case 함수를 AgentPort로 감싸는 최소 adapter다."""

    def __init__(
        self,
        agent: AgentKind,
        handler: Callable[[AgentRequest], Awaitable[Mapping[str, Any]]],
    ) -> None:
        """한 종류의 Agent와 그 비동기 handler를 결속한다."""

        self._agent = agent
        self._handler = handler

    @property
    def agent(self) -> AgentKind:
        """이 adapter에 결속된 Agent 종류를 반환한다."""

        return self._agent

    async def execute(self, request: AgentRequest) -> AgentResult:
        """기존 응답 mapping을 검증 가능한 AgentResult로 감싼다."""

        payload = await self._handler(request)
        if not isinstance(payload, Mapping):
            raise AgentDispatchError(
                "AGENT_RESULT_INVALID",
                "Agent가 올바른 결과 계약을 반환하지 않았습니다.",
            )
        return AgentResult(agent=self._agent, payload=dict(payload))


class DeterministicAgentSupervisor:
    """명시 route만 사용해 한 Agent를 선택하며 LLM fallback이나 재계획을 하지 않는다."""

    def __init__(self, ports: Mapping[AgentKind, AgentPort]) -> None:
        """등록 key와 실제 port 종류가 일치하는 registry만 허용한다."""

        self._ports = dict(ports)
        if any(kind is not port.agent for kind, port in self._ports.items()):
            raise AgentDispatchError(
                "AGENT_REGISTRY_INVALID",
                "Agent registry 구성이 올바르지 않습니다.",
            )

    @staticmethod
    def decide(request: AgentRequest) -> SupervisorDecision:
        """내부지침 명시 요청만 RAG로 보내고 나머지는 기존 거버넌스 분석으로 보낸다."""

        if request.command.requested_route == "INTERNAL_GUIDELINE":
            return SupervisorDecision(
                agent=AgentKind.INTERNAL_GUIDELINE,
                reason="EXPLICIT_INTERNAL_GUIDELINE_ROUTE",
            )
        # PRESENTATION과 REPORT_ACTION은 기존 승인 Artifact를 다루는 Conversation
        # workflow다. 별도 Report Assistant session으로 암묵 전환하지 않는다.
        return SupervisorDecision(
            agent=AgentKind.ANALYSIS_WORKFLOW,
            reason="GOVERNED_CONVERSATION_ROUTE",
        )

    async def execute(self, request: AgentRequest) -> AgentResult:
        """결정된 단일 port를 한 번 실행하고 교차 Agent 결과를 fail-closed로 차단한다."""

        decision = self.decide(request)
        port = self._ports.get(decision.agent)
        if port is None:
            raise AgentDispatchError(
                "AGENT_NOT_CONFIGURED",
                "요청한 기능의 Agent가 구성되지 않았습니다.",
            )
        result = await port.execute(request)
        if result.agent is not decision.agent:
            raise AgentDispatchError(
                "AGENT_RESULT_MISMATCH",
                "선택된 Agent와 실행 결과가 일치하지 않습니다.",
            )
        return result
