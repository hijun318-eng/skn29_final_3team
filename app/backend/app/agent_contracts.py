"""Agent 실행 상태와 durable checkpoint가 공유할 versioned 내부 계약을 정의한다."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.contract_core import ContractModel
from app.ports.agent import AgentKind


AGENT_EXECUTION_STATE_VERSION = "AgentExecutionState.v2"
AGENT_CHECKPOINT_IDENTITY_VERSION = "AgentCheckpointIdentity.v1"
AGENT_CHECKPOINT_VERSION = "AgentCheckpoint.v2"
AGENT_CHECKPOINT_NAMESPACE = "conversation-command"


class AgentExecutionPhase(str, Enum):
    """현재 단일 Agent 실행에서 허용하는 순방향 상태만 열거한다."""

    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentDecisionSource(str, Enum):
    """Agent 선택을 만든 서버 신호의 종류를 제한한다."""

    EXPLICIT_COMMAND = "EXPLICIT_COMMAND"
    GOVERNED_DEFAULT = "GOVERNED_DEFAULT"
    CAPABILITY_EVIDENCE = "CAPABILITY_EVIDENCE"
    MODEL_SUPERVISOR = "MODEL_SUPERVISOR"


class AgentCheckpointIdentity(ContractModel):
    """Conversation과 idempotency key로 checkpoint 충돌 범위를 고정한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentCheckpointIdentity.v1"] = (
        AGENT_CHECKPOINT_IDENTITY_VERSION
    )
    thread_id: UUID
    checkpoint_ns: Literal["conversation-command"] = AGENT_CHECKPOINT_NAMESPACE
    idempotency_key: str = Field(min_length=1, max_length=128)
    command_id: UUID | None = None

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def strip_idempotency_key(cls, value: object) -> object:
        """공백 변형이 별도 checkpoint identity로 처리되지 않게 정규화한다."""

        if isinstance(value, str):
            return value.strip()
        return value


class AgentExecutionState(ContractModel):
    """LLM payload 없이 라우팅과 실행 수명주기만 보존하는 immutable 상태다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentExecutionState.v2"] = AGENT_EXECUTION_STATE_VERSION
    checkpoint: AgentCheckpointIdentity
    revision: int = Field(ge=0)
    phase: AgentExecutionPhase
    request_id: UUID
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace_id: str = Field(min_length=1, max_length=128)
    user_id: UUID
    expected_head_turn_id: UUID | None
    requested_route: str | None
    selected_agent: AgentKind | None = None
    decision_reason: str | None = None
    decision_source: AgentDecisionSource | None = None
    decision_evidence_refs: tuple[str, ...] = ()
    terminal_code: str | None = None
    terminal_evidence_refs: tuple[str, ...] = ()

    @field_validator("decision_evidence_refs", "terminal_evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """공백·중복 reference가 route 또는 terminal 감사 상태에 들어오지 못하게 한다."""

        if len(value) != len(set(value)) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError("Agent evidence reference가 올바르지 않습니다.")
        return value

    @model_validator(mode="after")
    def validate_phase_fields(self) -> "AgentExecutionState":
        """선택 Agent와 terminal code가 현재 phase에 맞을 때만 상태를 허용한다."""

        requires_decision = self.phase in {
            AgentExecutionPhase.ROUTED,
            AgentExecutionPhase.RUNNING,
            AgentExecutionPhase.COMPLETED,
        }
        has_decision = bool(
            self.selected_agent
            and self.decision_reason
            and self.decision_source
        )
        if (
            requires_decision != has_decision
            and self.phase is not AgentExecutionPhase.FAILED
        ):
            raise ValueError(
                "ROUTED 이후 상태는 Agent와 결정 근거·출처를 함께 가져야 합니다."
            )
        if self.phase is AgentExecutionPhase.FAILED:
            decision_fields = (
                self.selected_agent,
                self.decision_reason,
                self.decision_source,
            )
            if any(value is not None for value in decision_fields) and not all(
                value is not None for value in decision_fields
            ):
                raise ValueError("FAILED 상태의 route 결정은 완전하거나 없어야 합니다.")
        if self.decision_source in {
            AgentDecisionSource.CAPABILITY_EVIDENCE,
            AgentDecisionSource.MODEL_SUPERVISOR,
        }:
            if not self.decision_evidence_refs:
                raise ValueError("자동 route에는 증거 참조가 필요합니다.")
        elif self.decision_evidence_refs:
            raise ValueError("Capability route가 아니면 증거 참조를 가질 수 없습니다.")
        if (self.phase is AgentExecutionPhase.FAILED) != bool(self.terminal_code):
            raise ValueError("FAILED 상태만 terminal code를 가져야 합니다.")
        if (
            self.phase is not AgentExecutionPhase.FAILED
            and self.terminal_evidence_refs
        ):
            raise ValueError("FAILED 상태만 terminal evidence를 가질 수 있습니다.")
        return self


class AgentStateUpdate(ContractModel):
    """Reducer에 허용되는 route·start·complete·fail 이벤트를 제한한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ROUTE", "START", "COMPLETE", "FAIL"]
    agent: AgentKind | None = None
    reason: str | None = None
    source: AgentDecisionSource | None = None
    evidence_refs: tuple[str, ...] = ()
    code: str | None = None

    @field_validator("reason", "code", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        """공백뿐인 결정 근거와 terminal code를 유효한 이벤트로 보지 않는다."""

        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("evidence_refs")
    @classmethod
    def validate_update_evidence_refs(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Reducer event도 공백·중복 evidence reference를 즉시 거부한다."""

        if len(value) != len(set(value)) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError("Agent evidence reference가 올바르지 않습니다.")
        return value

    @model_validator(mode="after")
    def validate_event_payload(self) -> "AgentStateUpdate":
        """이벤트 종류에 필요하지 않은 payload가 checkpoint에 섞이지 않게 한다."""

        if self.event == "ROUTE":
            if (
                self.agent is None
                or not self.reason
                or self.source is None
                or self.code is not None
            ):
                raise ValueError("ROUTE는 Agent와 결정 근거·출처만 가져야 합니다.")
            if self.source in {
                AgentDecisionSource.CAPABILITY_EVIDENCE,
                AgentDecisionSource.MODEL_SUPERVISOR,
            }:
                if not self.evidence_refs:
                    raise ValueError("자동 ROUTE에는 증거 참조가 필요합니다.")
            elif self.evidence_refs:
                raise ValueError("Capability ROUTE가 아니면 증거 참조를 가질 수 없습니다.")
            return self
        if self.event == "FAIL":
            if (
                not self.code
                or self.agent is not None
                or self.reason is not None
                or self.source is not None
            ):
                raise ValueError("FAIL은 terminal code와 evidence reference만 가져야 합니다.")
            return self
        if (
            any(
                value is not None
                for value in (self.agent, self.reason, self.source, self.code)
            )
            or self.evidence_refs
        ):
            raise ValueError("START와 COMPLETE에는 추가 payload를 허용하지 않습니다.")
        return self


class AgentCheckpoint(ContractModel):
    """향후 checkpointer가 원자적으로 저장할 한 revision의 immutable snapshot이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentCheckpoint.v2"] = AGENT_CHECKPOINT_VERSION
    identity: AgentCheckpointIdentity
    revision: int = Field(ge=0)
    state: AgentExecutionState

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> "AgentCheckpoint":
        """checkpoint key·revision과 내부 상태가 다른 실행을 가리키지 않게 한다."""

        if self.identity != self.state.checkpoint or self.revision != self.state.revision:
            raise ValueError("Checkpoint identity 또는 revision이 Agent 상태와 다릅니다.")
        return self
