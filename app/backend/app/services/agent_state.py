"""AgentExecutionState를 순방향으로만 변경하는 결정론적 reducer를 제공한다."""

from __future__ import annotations

from app.agent_contracts import (
    AgentCheckpoint,
    AgentCheckpointIdentity,
    AgentExecutionPhase,
    AgentExecutionState,
    AgentStateUpdate,
)
from app.ports.agent import AgentRequest, canonical_agent_request_fingerprint


class AgentStateTransitionError(RuntimeError):
    """현재 phase에서 허용되지 않은 상태 전이를 안정적인 코드로 구분한다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_TRANSITIONS = {
    (AgentExecutionPhase.RECEIVED, "ROUTE"): AgentExecutionPhase.ROUTED,
    (AgentExecutionPhase.RECEIVED, "FAIL"): AgentExecutionPhase.FAILED,
    (AgentExecutionPhase.ROUTED, "START"): AgentExecutionPhase.RUNNING,
    (AgentExecutionPhase.ROUTED, "FAIL"): AgentExecutionPhase.FAILED,
    (AgentExecutionPhase.RUNNING, "COMPLETE"): AgentExecutionPhase.COMPLETED,
    (AgentExecutionPhase.RUNNING, "FAIL"): AgentExecutionPhase.FAILED,
}


def initial_agent_state(request: AgentRequest) -> AgentExecutionState:
    """typed AgentRequest에서 결과 payload가 없는 최초 checkpoint 상태를 만든다."""

    return AgentExecutionState(
        checkpoint=AgentCheckpointIdentity(
            thread_id=request.conversation_id,
            idempotency_key=request.command.idempotency_key,
            command_id=request.context.command_id,
        ),
        revision=0,
        phase=AgentExecutionPhase.RECEIVED,
        request_id=request.context.request_id,
        request_fingerprint=canonical_agent_request_fingerprint(request),
        trace_id=request.context.trace_id,
        user_id=request.context.user_id,
        expected_head_turn_id=request.command.expected_head_turn_id,
        requested_route=request.command.requested_route,
    )


def reduce_agent_state(
    state: AgentExecutionState,
    update: AgentStateUpdate,
) -> AgentExecutionState:
    """허용된 단일 이벤트를 적용하고 revision이 증가한 새 상태를 반환한다."""

    target = _TRANSITIONS.get((state.phase, update.event))
    if target is None:
        raise AgentStateTransitionError(
            "AGENT_STATE_TRANSITION_INVALID",
            f"Agent 상태를 {state.phase.value}에서 {update.event}로 전이할 수 없습니다.",
        )
    values: dict[str, object] = {
        "revision": state.revision + 1,
        "phase": target,
    }
    if update.event == "ROUTE":
        values.update(
            selected_agent=update.agent,
            decision_reason=update.reason,
            decision_source=update.source,
            decision_evidence_refs=update.evidence_refs,
        )
    elif update.event == "FAIL":
        values["terminal_code"] = update.code
        values["terminal_evidence_refs"] = update.evidence_refs
    return AgentExecutionState.model_validate(
        {
            **state.model_dump(mode="python"),
            **values,
        }
    )


def checkpoint_agent_state(state: AgentExecutionState) -> AgentCheckpoint:
    """현재 상태를 identity·revision이 결속된 immutable checkpoint로 투영한다."""

    return AgentCheckpoint(
        identity=state.checkpoint,
        revision=state.revision,
        state=state,
    )
