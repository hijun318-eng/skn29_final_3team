"""현재 연결된 대화 Agent가 공유하는 typed 실행 경계를 정의한다."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import ConfigDict, model_validator

from app.contract_core import ContractModel, RequestContext
from app.conversation_contracts import ConversationCommandRequest


AGENT_REQUEST_VERSION = "AgentRequest.v1"
AGENT_RESULT_VERSION = "AgentResult.v1"


class AgentKind(str, Enum):
    """현재 실제 conversation command에 연결된 Agent 실행 종류다."""

    ANALYSIS_WORKFLOW = "ANALYSIS_WORKFLOW"
    INTERNAL_GUIDELINE = "INTERNAL_GUIDELINE"


class AgentRequest(ContractModel):
    """Supervisor가 한 Agent에 전달하는 immutable command·identity 봉투다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["AgentRequest.v1"] = AGENT_REQUEST_VERSION
    conversation_id: UUID
    command: ConversationCommandRequest
    context: RequestContext

    @model_validator(mode="after")
    def validate_conversation_identity(self) -> "AgentRequest":
        """이미 결속된 RequestContext가 다른 Conversation으로 넘어가는 것을 차단한다."""

        if self.context.conversation_id not in {None, self.conversation_id}:
            raise ValueError("AgentRequest conversation identity가 일치하지 않습니다.")
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

    async def execute(self, request: AgentRequest) -> AgentResult:
        """typed 요청을 실행하고 같은 Agent 종류의 typed 결과를 반환한다."""

        ...
