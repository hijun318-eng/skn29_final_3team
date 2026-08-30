"""현재 연결된 대화 Agent가 공유하는 typed 실행 경계를 정의한다."""

from __future__ import annotations

from datetime import date
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.contract_core import ContractModel, RequestContext
from app.conversation_contracts import ConversationCommandRequest


AGENT_REQUEST_VERSION = "AgentRequest.v1"
AGENT_RESULT_VERSION = "AgentResult.v1"
AGENT_PORT_READINESS_VERSION = "AgentPortReadiness.v1"
ML_PREDICTION_INVOCATION_VERSION = "MLPredictionInvocation.v1"
ML_ABSOLUTE_MAX_HORIZON_DAYS = 366


class AgentKind(str, Enum):
    """Conversation Supervisor가 식별할 수 있는 Agent 실행 종류다.

    ML 종류는 교체 runtime의 ``AgentPort``와 capability probe가 승인되기 전까지
    production registry에 등록하지 않는다. 종류를 미리 고정해 두면 교체 시 공통
    AgentRequest·상태·LangGraph 계약을 다시 변경하지 않고 port만 추가할 수 있다.
    """

    ANALYSIS_WORKFLOW = "ANALYSIS_WORKFLOW"
    INTERNAL_GUIDELINE = "INTERNAL_GUIDELINE"
    ML_PREDICTION = "ML_PREDICTION"


class MLPredictionInvocation(ContractModel):
    """승인 resolver가 ML Agent에 전달할 구조화된 예측 요청이다.

    사용자 자연어를 이 모델로 바꾸는 책임은 이 계약에 없다. Runtime capability가
    property·기간·horizon을 다시 검증하므로 특정 질문이나 호텔 이름을 코드에 넣지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["MLPredictionInvocation.v1"] = (
        ML_PREDICTION_INVOCATION_VERSION
    )
    agent: Literal[AgentKind.ML_PREDICTION] = AgentKind.ML_PREDICTION
    task: Literal["ROOM_DEMAND_FORECAST"] = "ROOM_DEMAND_FORECAST"
    property_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    as_of: date
    horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)


class AgentRequest(ContractModel):
    """Supervisor가 한 Agent에 전달하는 immutable command·identity 봉투다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentRequest.v1"] = AGENT_REQUEST_VERSION
    conversation_id: UUID
    command: ConversationCommandRequest
    context: RequestContext
    target_agent: AgentKind | None = None
    invocation: MLPredictionInvocation | None = None

    @model_validator(mode="after")
    def validate_conversation_identity(self) -> "AgentRequest":
        """Conversation과 구조화 invocation 종류를 immutable request에 결속한다."""

        if self.context.conversation_id not in {None, self.conversation_id}:
            raise ValueError("AgentRequest conversation identity가 일치하지 않습니다.")
        has_ml_invocation = self.invocation is not None
        if (self.target_agent is AgentKind.ML_PREDICTION) != has_ml_invocation:
            raise ValueError(
                "ML target Agent와 prediction invocation은 함께 지정해야 합니다."
            )
        if self.invocation is not None and self.invocation.agent is not self.target_agent:
            raise ValueError("AgentRequest invocation 종류가 target Agent와 다릅니다.")
        return self


def canonical_agent_request_fingerprint(request: AgentRequest) -> str:
    """전체 immutable AgentRequest를 결정론적 SHA-256으로 봉인한다."""

    canonical = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class AgentPortReadiness(ContractModel):
    """한 AgentPort가 현재 실행 가능한 capability release인지 나타내는 영수증이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentPortReadiness.v1"] = AGENT_PORT_READINESS_VERSION
    agent: AgentKind
    status: Literal["ready", "not_ready"]
    capability_version: str = Field(min_length=1, max_length=160)
    release_refs: tuple[str, ...] = ()
    reason: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_receipt(self) -> "AgentPortReadiness":
        """ready 판정은 중복 없는 불변 release reference가 있을 때만 허용한다."""

        if (
            len(self.release_refs) != len(set(self.release_refs))
            or any(not item.strip() for item in self.release_refs)
        ):
            raise ValueError("AgentPort readiness release reference is invalid")
        if self.status == "ready" and not self.release_refs:
            raise ValueError("ready AgentPort requires release references")
        if self.status == "not_ready" and self.reason is None:
            raise ValueError("not-ready AgentPort requires a reason")
        return self


class AgentResult(ContractModel):
    """Agent가 기존 공개 응답을 바꾸지 않고 반환하는 typed 내부 봉투다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentResult.v1"] = AGENT_RESULT_VERSION
    agent: AgentKind
    payload: dict[str, Any]


class AgentPort(Protocol):
    """Supervisor가 구체 구현이나 향후 graph node와 분리되어 호출하는 포트다."""

    @property
    def agent(self) -> AgentKind:
        """이 포트가 실행하는 단일 Agent 종류를 반환한다."""

        ...

    async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
        """요청 주체와 현재 release에 결속된 실행 가능 상태를 반환한다."""

        ...

    async def execute(self, request: AgentRequest) -> AgentResult:
        """typed 요청을 실행하고 같은 Agent 종류의 typed 결과를 반환한다."""

        ...
