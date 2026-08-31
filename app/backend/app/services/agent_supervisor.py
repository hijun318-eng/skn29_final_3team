"""모델 추론 없이 승인된 conversation route를 AgentPort에 전달한다."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import math
from typing import Any, Protocol

from app.agent_contracts import (
    AgentDecisionSource,
    AgentExecutionPhase,
    AgentExecutionState,
    AgentStateUpdate,
)
from app.ports.agent import (
    AgentKind,
    AgentPort,
    AgentPortReadiness,
    AgentRequest,
    AgentResult,
    canonical_agent_request_fingerprint,
)
from app.services.agent_state import initial_agent_state, reduce_agent_state


class AgentDispatchError(RuntimeError):
    """Supervisor가 안전하게 실행할 수 없는 route·port·result를 구분한다."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        state: AgentExecutionState | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        """안정적인 오류 코드와 공개 가능한 메시지를 보존한다."""

        super().__init__(message)
        self.code = code
        self.state = state
        self.evidence_refs = evidence_refs


@dataclass(frozen=True)
class SupervisorDecision:
    """서버가 확정한 단일 Agent와 결정 근거를 기록한다."""

    agent: AgentKind
    reason: str
    source: AgentDecisionSource
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """자동 capability route가 근거 없이 생성되지 않게 차단한다."""

        if (
            not isinstance(self.agent, AgentKind)
            or not isinstance(self.source, AgentDecisionSource)
            or not isinstance(self.reason, str)
            or not self.reason.strip()
        ):
            raise AgentDispatchError(
                "AGENT_ROUTE_DECISION_INVALID",
                "Agent route 결정 계약이 올바르지 않습니다.",
            )
        if any(
            not isinstance(ref, str) or not ref.strip()
            for ref in self.evidence_refs
        ):
            raise AgentDispatchError(
                "AGENT_ROUTE_EVIDENCE_INVALID",
                "Agent route 증거 참조가 올바르지 않습니다.",
            )
        if self.source in {
            AgentDecisionSource.CAPABILITY_EVIDENCE,
            AgentDecisionSource.MODEL_SUPERVISOR,
        }:
            if not self.evidence_refs:
                raise AgentDispatchError(
                    "AGENT_ROUTE_EVIDENCE_REQUIRED",
                    "자동 Agent route에는 승인된 capability 근거가 필요합니다.",
                )
        elif self.evidence_refs:
            raise AgentDispatchError(
                "AGENT_ROUTE_EVIDENCE_INVALID",
                "Capability route가 아닌 결정에는 증거 참조를 붙일 수 없습니다.",
            )


class AgentRouteResolver(Protocol):
    """명시 신호 또는 향후 capability probe로 한 Agent를 선택하는 비동기 경계다."""

    @property
    def decision_sources(self) -> frozenset[AgentDecisionSource]:
        """resolver가 생성할 수 있는 결정 출처를 실행 전에 선언한다."""

        ...

    async def resolve(self, request: AgentRequest) -> SupervisorDecision:
        """서버 소유 근거를 포함한 단일 route 결정을 반환한다."""

        ...


@dataclass(frozen=True)
class AgentCapabilityEvidence:
    """한 Agent의 search-only probe가 발급한 재사용 가능한 판정 근거다."""

    agent: AgentKind
    matched: bool
    reason: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        """match 여부와 무관하게 서버가 발급한 고유 receipt를 요구한다."""

        if (
            not isinstance(self.agent, AgentKind)
            or type(self.matched) is not bool
            or not isinstance(self.reason, str)
            or not self.reason.strip()
            or not self.evidence_refs
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(
                not isinstance(ref, str) or not ref.strip()
                for ref in self.evidence_refs
            )
        ):
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "Agent capability probe 근거가 올바르지 않습니다.",
            )


class AgentCapabilityProbe(Protocol):
    """답변을 생성하지 않고 한 Agent의 승인 capability 적합성만 판정한다."""

    @property
    def agent(self) -> AgentKind:
        """이 probe가 판정하는 Agent 종류를 반환한다."""

        ...

    async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
        """권한·버전·유효기간이 적용된 판정과 receipt를 반환한다."""

        ...


class ExplicitAgentRouteResolver:
    """현재 공개 계약의 명시 RAG와 governed analysis 기본 경로만 해석한다."""

    decision_sources = frozenset(
        {
            AgentDecisionSource.EXPLICIT_COMMAND,
            AgentDecisionSource.GOVERNED_DEFAULT,
        }
    )

    async def resolve(self, request: AgentRequest) -> SupervisorDecision:
        """모델·키워드 판정 없이 기존 route 동작을 보존한다."""

        if request.command.requested_route == "INTERNAL_GUIDELINE":
            return SupervisorDecision(
                agent=AgentKind.INTERNAL_GUIDELINE,
                reason="EXPLICIT_INTERNAL_GUIDELINE_ROUTE",
                source=AgentDecisionSource.EXPLICIT_COMMAND,
            )
        if request.command.requested_route == "ML_PREDICTION":
            return SupervisorDecision(
                agent=AgentKind.ML_PREDICTION,
                reason="EXPLICIT_ML_PREDICTION_ROUTE",
                source=AgentDecisionSource.EXPLICIT_COMMAND,
            )
        return SupervisorDecision(
            agent=AgentKind.ANALYSIS_WORKFLOW,
            reason="GOVERNED_CONVERSATION_ROUTE",
            source=(
                AgentDecisionSource.EXPLICIT_COMMAND
                if request.command.requested_route is not None
                else AgentDecisionSource.GOVERNED_DEFAULT
            ),
        )


class CapabilityEvidenceRouteResolver:
    """승인 probe가 정확히 하나 매칭될 때만 일반 입력의 Agent를 선택한다."""

    decision_sources = frozenset(AgentDecisionSource)

    def __init__(
        self,
        probes: Mapping[AgentKind, AgentCapabilityProbe],
        explicit_resolver: AgentRouteResolver | None = None,
        *,
        automatic_routing_enabled: bool = True,
    ) -> None:
        """빈 registry와 key·probe identity 불일치를 시작 전에 차단한다."""

        self._probes = dict(probes)
        self._explicit_resolver = explicit_resolver or ExplicitAgentRouteResolver()
        if type(automatic_routing_enabled) is not bool:
            raise AgentDispatchError(
                "AGENT_CAPABILITY_ROUTING_FLAG_INVALID",
                "자동 capability route 설정이 올바르지 않습니다.",
            )
        self._automatic_routing_enabled = automatic_routing_enabled
        if not self._probes or any(
            kind is not probe.agent for kind, probe in self._probes.items()
        ):
            raise AgentDispatchError(
                "AGENT_CAPABILITY_REGISTRY_INVALID",
                "Agent capability probe registry 구성이 올바르지 않습니다.",
            )

    async def resolve(self, request: AgentRequest) -> SupervisorDecision:
        """명시 route를 우선하고 일반 입력만 probe receipt로 fail-closed 판정한다."""

        if request.command.requested_route is not None:
            explicit = await self._explicit_resolver.resolve(request)
            if request.target_agent is None:
                return explicit
            if explicit.agent is not request.target_agent:
                raise AgentDispatchError(
                    "AGENT_INVOCATION_MISMATCH",
                    "명시 route와 구조화 실행 요청이 일치하지 않습니다.",
                )
            probe = self._probes.get(explicit.agent)
            if probe is None:
                raise AgentDispatchError(
                    "AGENT_CAPABILITY_NOT_CONFIGURED",
                    "요청한 기능의 capability 검증 경계가 구성되지 않았습니다.",
                )
            return await self._resolve_probe_entries(
                request,
                ((explicit.agent, probe),),
            )
        if request.supervisor_plan_ref is not None:
            selected_agent = request.target_agent
            if selected_agent is None:
                raise AgentDispatchError(
                    "AGENT_MODEL_PLAN_INVALID",
                    "Supervisor 계획에 실행 Agent가 없습니다.",
                )
            probe = self._probes.get(selected_agent)
            if probe is None:
                raise AgentDispatchError(
                    "AGENT_CAPABILITY_NOT_CONFIGURED",
                    "Supervisor가 선택한 기능의 capability 검증 경계가 없습니다.",
                    evidence_refs=(request.supervisor_plan_ref,),
                )
            return await self._resolve_probe_entries(
                request,
                ((selected_agent, probe),),
                source=AgentDecisionSource.MODEL_SUPERVISOR,
                reason=f"MODEL_SUPERVISOR_{selected_agent.value}",
                additional_evidence_refs=(request.supervisor_plan_ref,),
            )
        if not self._automatic_routing_enabled:
            return await self._explicit_resolver.resolve(request)
        return await self._resolve_probe_entries(request, tuple(self._probes.items()))

    async def _resolve_probe_entries(
        self,
        request: AgentRequest,
        probe_entries: tuple[tuple[AgentKind, AgentCapabilityProbe], ...],
        *,
        source: AgentDecisionSource = AgentDecisionSource.CAPABILITY_EVIDENCE,
        reason: str | None = None,
        additional_evidence_refs: tuple[str, ...] = (),
    ) -> SupervisorDecision:
        """선택 가능한 probe 집합에서 정확히 한 receipt-backed 결정을 만든다."""

        context = request.context
        if (
            context.conversation_id != request.conversation_id
            or context.command_id is None
            or not context.permission_snapshot_id
            or not context.product_release_id
            or not context.semantic_release_id
        ):
            raise AgentDispatchError(
                "AGENT_CAPABILITY_CONTEXT_INCOMPLETE",
                "자동 Agent route에는 승인된 command context가 필요합니다.",
            )

        try:
            results = await asyncio.gather(
                *(probe.probe(request) for _agent, probe in probe_entries),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            raise

        cancellation = next(
            (
                result
                for result in results
                if isinstance(result, asyncio.CancelledError)
            ),
            None,
        )
        if cancellation is not None:
            raise cancellation
        failure = next(
            (result for result in results if isinstance(result, Exception)),
            None,
        )
        if failure is not None:
            raise AgentDispatchError(
                "AGENT_CAPABILITY_PROBE_FAILED",
                "Agent capability를 확인하지 못했습니다.",
            ) from failure

        evidence: list[AgentCapabilityEvidence] = []
        for (expected_agent, _probe), result in zip(
            probe_entries,
            results,
            strict=True,
        ):
            if (
                not isinstance(result, AgentCapabilityEvidence)
                or result.agent is not expected_agent
            ):
                raise AgentDispatchError(
                    "AGENT_CAPABILITY_EVIDENCE_INVALID",
                    "Agent capability probe 결과가 registry와 일치하지 않습니다.",
                )
            evidence.append(result)

        matches = [item for item in evidence if item.matched]
        all_refs = additional_evidence_refs + tuple(
            ref for item in evidence for ref in item.evidence_refs
        )
        if len(all_refs) != len(set(all_refs)):
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "Agent capability probe 근거가 중복되었습니다.",
            )
        if not matches:
            raise AgentDispatchError(
                "AGENT_ROUTE_NOT_RESOLVED",
                "요청을 처리할 승인된 Agent를 확정하지 못했습니다.",
                evidence_refs=all_refs,
            )
        if len(matches) > 1:
            raise AgentDispatchError(
                "AGENT_ROUTE_AMBIGUOUS",
                "요청에 맞는 Agent가 여러 개여서 추가 확인이 필요합니다.",
                evidence_refs=tuple(
                    ref for item in matches for ref in item.evidence_refs
                ),
            )
        selected = matches[0]
        return SupervisorDecision(
            agent=selected.agent,
            reason=reason or selected.reason,
            source=source,
            evidence_refs=additional_evidence_refs + selected.evidence_refs,
        )


@dataclass(frozen=True)
class AgentExecutionOutcome:
    """성공한 단일 Agent 결과와 최종 공통 상태를 함께 반환한다."""

    decision: SupervisorDecision
    result: AgentResult
    state: AgentExecutionState


@dataclass(frozen=True)
class AgentRoutingOutcome:
    """route node가 확정한 결정과 ROUTED 상태를 다음 실행 node에 전달한다."""

    decision: SupervisorDecision
    state: AgentExecutionState
    request_fingerprint: str

    def __post_init__(self) -> None:
        """결정과 reducer 상태가 같은 Agent·근거를 가리킬 때만 허용한다."""

        if (
            self.state.phase is not AgentExecutionPhase.ROUTED
            or self.state.selected_agent is not self.decision.agent
            or self.state.decision_reason != self.decision.reason
            or self.state.decision_source is not self.decision.source
            or self.state.decision_evidence_refs != self.decision.evidence_refs
            or self.request_fingerprint != self.state.request_fingerprint
        ):
            raise AgentDispatchError(
                "AGENT_ROUTING_OUTCOME_INVALID",
                "Agent route 결과와 실행 상태가 일치하지 않습니다.",
                state=self.state,
            )


class CallableAgentPort:
    """테스트·전환 조립에서만 기존 use case 함수를 감싸는 최소 adapter다."""

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

    async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
        """주입된 handler 자체가 test/transition capability임을 명시적으로 고정한다."""

        return AgentPortReadiness(
            agent=self._agent,
            status="ready",
            capability_version="CallableAgentPort.test.v1",
            release_refs=(f"agent-port:test-callable:v1:{self._agent.value.lower()}",),
        )

    async def execute(self, request: AgentRequest) -> AgentResult:
        """기존 응답 mapping을 검증 가능한 AgentResult로 감싼다."""

        payload = await self._handler(request)
        if not isinstance(payload, Mapping):
            raise AgentDispatchError(
                "AGENT_RESULT_INVALID",
                "Agent가 올바른 결과 계약을 반환하지 않았습니다.",
            )
        return AgentResult(agent=self._agent, payload=dict(payload))


class ReadinessGuardedAgentPort:
    """선택 Agent의 typed readiness receipt를 실행 직전에 재검증하는 wrapper다."""

    def __init__(self, port: AgentPort) -> None:
        self._port = port

    @property
    def agent(self) -> AgentKind:
        """하위 Port가 소유한 불변 Agent 종류를 반환한다."""

        return self._port.agent

    async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
        """하위 Port의 readiness가 종류·release 계약과 일치할 때만 반환한다."""

        readiness = await self._port.readiness(request)
        if (
            not isinstance(readiness, AgentPortReadiness)
            or readiness.agent is not self.agent
        ):
            raise AgentDispatchError(
                "AGENT_PORT_READINESS_INVALID",
                "Agent 실행 준비 상태 계약이 올바르지 않습니다.",
            )
        return readiness

    async def execute(self, request: AgentRequest) -> AgentResult:
        """ready receipt가 없는 선택 기능은 하위 Port 호출 전에 fail-closed한다."""

        readiness = await self.readiness(request)
        if readiness.status != "ready":
            raise AgentDispatchError(
                "AGENT_PORT_NOT_READY",
                "요청한 기능의 실행 서비스가 준비되지 않았습니다.",
                evidence_refs=readiness.release_refs,
            )
        return await self._port.execute(request)


class DeterministicAgentSupervisor:
    """검증된 resolver 결정으로 한 Agent만 실행하며 LLM fallback을 하지 않는다."""

    def __init__(
        self,
        ports: Mapping[AgentKind, AgentPort],
        route_resolver: AgentRouteResolver | None = None,
        *,
        allowed_decision_sources: frozenset[AgentDecisionSource] | None = None,
    ) -> None:
        """등록 key와 실제 port 종류가 일치하는 registry만 허용한다."""

        self._ports = dict(ports)
        self._route_resolver = route_resolver or ExplicitAgentRouteResolver()
        self._allowed_decision_sources = (
            frozenset(AgentDecisionSource)
            if allowed_decision_sources is None
            else frozenset(allowed_decision_sources)
        )
        if any(kind is not port.agent for kind, port in self._ports.items()):
            raise AgentDispatchError(
                "AGENT_REGISTRY_INVALID",
                "Agent registry 구성이 올바르지 않습니다.",
            )
        if not self._allowed_decision_sources or any(
            not isinstance(source, AgentDecisionSource)
            for source in self._allowed_decision_sources
        ):
            raise AgentDispatchError(
                "AGENT_DECISION_SOURCE_POLICY_INVALID",
                "Agent route 결정 출처 정책이 올바르지 않습니다.",
            )

    @property
    def registered_agents(self) -> frozenset[AgentKind]:
        """실제 실행 port가 구성된 Agent 종류만 불변 집합으로 반환한다."""

        return frozenset(self._ports)

    async def resolve(self, request: AgentRequest) -> SupervisorDecision:
        """주입된 resolver의 서버 소유 결정을 검증해 반환한다."""

        decision = await self._route_resolver.resolve(request)
        if not isinstance(decision, SupervisorDecision):
            raise AgentDispatchError(
                "AGENT_ROUTE_DECISION_INVALID",
                "Agent route resolver가 올바른 결정 계약을 반환하지 않았습니다.",
            )
        declared_sources = getattr(self._route_resolver, "decision_sources", None)
        if (
            isinstance(declared_sources, frozenset)
            and decision.source not in declared_sources
        ):
            raise AgentDispatchError(
                "AGENT_ROUTE_RESOLVER_SOURCE_MISMATCH",
                "Agent route resolver 결정이 선언된 출처 범위를 벗어났습니다.",
                evidence_refs=decision.evidence_refs,
            )
        if decision.source not in self._allowed_decision_sources:
            raise AgentDispatchError(
                "AGENT_DECISION_SOURCE_NOT_APPROVED",
                "현재 실행 경로에서 자동 capability route가 승인되지 않았습니다.",
                evidence_refs=decision.evidence_refs,
            )
        return decision

    async def route_with_state(
        self,
        request: AgentRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentRoutingOutcome:
        """resolver 결정만 수행해 LangGraph route node와 같은 경계를 제공한다."""

        state = initial_agent_state(request)

        def _record_route_failure(
            error: BaseException,
            fallback_code: str,
        ) -> None:
            nonlocal state
            raw_code = getattr(error, "code", fallback_code)
            code = (
                raw_code.value
                if hasattr(raw_code, "value")
                else str(raw_code or fallback_code)
            )
            state = reduce_agent_state(
                state,
                AgentStateUpdate(
                    event="FAIL",
                    code=code,
                    evidence_refs=self._error_evidence_refs(error),
                ),
            )
            try:
                setattr(error, "agent_execution_state", state)
            except (AttributeError, TypeError):
                pass

        try:
            if timeout_seconds is None:
                decision = await self.resolve(request)
            else:
                if (
                    isinstance(timeout_seconds, bool)
                    or not isinstance(timeout_seconds, (int, float))
                    or not math.isfinite(float(timeout_seconds))
                    or timeout_seconds <= 0
                ):
                    raise AgentDispatchError(
                        "AGENT_ROUTE_TIMEOUT_INVALID",
                        "Agent route 제한 시간이 올바르지 않습니다.",
                    )
                async with asyncio.timeout(float(timeout_seconds)):
                    decision = await self.resolve(request)
        except TimeoutError as cause:
            error = AgentDispatchError(
                "AGENT_ROUTE_TIMEOUT",
                "Agent route 결정 시간이 초과되었습니다.",
            )
            _record_route_failure(error, "AGENT_ROUTE_TIMEOUT")
            raise error from cause
        except asyncio.CancelledError as error:
            _record_route_failure(error, "AGENT_ROUTE_CANCELLED")
            raise
        except Exception as error:
            _record_route_failure(error, "AGENT_ROUTE_RESOLUTION_FAILED")
            raise
        state = reduce_agent_state(
            state,
            AgentStateUpdate(
                event="ROUTE",
                agent=decision.agent,
                reason=decision.reason,
                source=decision.source,
                evidence_refs=decision.evidence_refs,
            ),
        )
        return AgentRoutingOutcome(
            decision=decision,
            state=state,
            request_fingerprint=canonical_agent_request_fingerprint(request),
        )

    async def execute_routed_with_state(
        self,
        request: AgentRequest,
        routing: AgentRoutingOutcome,
    ) -> AgentExecutionOutcome:
        """같은 admitted command의 ROUTED 상태에서 선택된 port 하나만 실행한다."""

        expected = initial_agent_state(request)
        state = routing.state
        expected_routed = reduce_agent_state(
            expected,
            AgentStateUpdate(
                event="ROUTE",
                agent=routing.decision.agent,
                reason=routing.decision.reason,
                source=routing.decision.source,
                evidence_refs=routing.decision.evidence_refs,
            ),
        )
        if (
            state != expected_routed
            or routing.request_fingerprint != expected.request_fingerprint
        ):
            failed_state = reduce_agent_state(
                expected,
                AgentStateUpdate(
                    event="FAIL",
                    code="AGENT_ROUTE_REQUEST_MISMATCH",
                ),
            )
            raise AgentDispatchError(
                "AGENT_ROUTE_REQUEST_MISMATCH",
                "Agent route 결과가 다른 command를 가리킵니다.",
                state=failed_state,
            )

        decision = routing.decision
        has_ml_invocation = request.invocation is not None
        if (
            (decision.agent is AgentKind.ML_PREDICTION) != has_ml_invocation
            or (
                request.target_agent is not None
                and decision.agent is not request.target_agent
            )
        ):
            state = reduce_agent_state(
                state,
                AgentStateUpdate(event="FAIL", code="AGENT_INVOCATION_MISMATCH"),
            )
            raise AgentDispatchError(
                "AGENT_INVOCATION_MISMATCH",
                "선택된 Agent와 구조화 실행 요청이 일치하지 않습니다.",
                state=state,
            )
        port = self._ports.get(decision.agent)
        if port is None:
            state = reduce_agent_state(
                state,
                AgentStateUpdate(event="FAIL", code="AGENT_NOT_CONFIGURED"),
            )
            raise AgentDispatchError(
                "AGENT_NOT_CONFIGURED",
                "요청한 기능의 Agent가 구성되지 않았습니다.",
                state=state,
            )
        state = reduce_agent_state(state, AgentStateUpdate(event="START"))

        def _record_execution_failure(error: BaseException) -> None:
            nonlocal state
            raw_code = getattr(error, "code", "AGENT_EXECUTION_FAILED")
            code = (
                raw_code.value
                if hasattr(raw_code, "value")
                else str(raw_code or "AGENT_EXECUTION_FAILED")
            )
            if not code.strip():
                code = "AGENT_EXECUTION_FAILED"
            state = reduce_agent_state(
                state,
                AgentStateUpdate(
                    event="FAIL",
                    code=code,
                    evidence_refs=self._error_evidence_refs(error),
                ),
            )
            try:
                setattr(error, "agent_execution_state", state)
            except (AttributeError, TypeError):
                pass

        try:
            result = await port.execute(request)
        except asyncio.CancelledError as error:
            _record_execution_failure(error)
            raise
        except Exception as error:
            _record_execution_failure(error)
            raise
        if result.agent is not decision.agent:
            state = reduce_agent_state(
                state,
                AgentStateUpdate(event="FAIL", code="AGENT_RESULT_MISMATCH"),
            )
            raise AgentDispatchError(
                "AGENT_RESULT_MISMATCH",
                "선택된 Agent와 실행 결과가 일치하지 않습니다.",
                state=state,
            )
        state = reduce_agent_state(state, AgentStateUpdate(event="COMPLETE"))
        return AgentExecutionOutcome(
            decision=decision,
            result=result,
            state=state,
        )

    async def execute_with_state(self, request: AgentRequest) -> AgentExecutionOutcome:
        """route와 단일 port 실행 node를 조합해 기존 호출 계약을 유지한다."""

        routing = await self.route_with_state(request)
        return await self.execute_routed_with_state(request, routing)

    async def execute(self, request: AgentRequest) -> AgentResult:
        """기존 호출 계약을 유지하면서 공통 상태 reducer를 거쳐 결과를 반환한다."""

        return (await self.execute_with_state(request)).result

    @staticmethod
    def _error_evidence_refs(error: BaseException) -> tuple[str, ...]:
        """신뢰할 수 있는 문자열 tuple만 terminal 상태의 실패 근거로 보존한다."""

        raw = getattr(error, "evidence_refs", ())
        if not isinstance(raw, tuple) or len(raw) != len(set(raw)) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            return ()
        return raw
