"""Conversation command admission과 server canonical hash의 versioned 계약을 정의한다."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.contract_core import ContractModel, RequestContext


CONVERSATION_COMMAND_VERSION = "ConversationCommand.v1"
CONVERSATION_CAPABILITY_VERSION = "1.0.0"


class ConversationCommandRequest(ContractModel):
    """head를 변경하는 모든 command가 명시해야 하는 client 입력이다.

    첫 턴도 ``expected_head_turn_id: null``을 보내야 한다. 필드 생략과 서버가 확인한 빈 head를
    구분해 오래된 client가 CAS를 우회하지 못하게 한다.
    """

    user_message: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_head_turn_id: UUID | None
    requested_route: Literal[
        "ANALYSIS", "PRESENTATION", "REPORT_ACTION", "INTERNAL_GUIDELINE"
    ] | None = None
    presentation_type: Literal[
        "SUMMARY", "TABLE", "BAR", "LINE", "PIE", "HORIZONTAL_BAR", "DONUT"
    ] | None = None

    @field_validator("user_message", "idempotency_key", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        """필수 문자열의 가장자리 공백을 제거해 빈 값과 idempotency 변형을 차단한다."""

        if isinstance(value, str):
            return value.strip()
        return value


def canonical_command_input_hash(
    command: ConversationCommandRequest,
    conversation_id: UUID,
    context: RequestContext,
) -> str:
    """server가 확정한 path·subject·permission·release까지 포함해 command hash를 만든다."""

    if context.conversation_id != conversation_id:
        raise ValueError("RequestContext conversation_id가 path identity와 일치하지 않습니다.")
    required = (
        context.permission_snapshot_id,
        context.product_release_id,
        context.semantic_release_id,
    )
    if any(not value for value in required):
        raise ValueError("server-owned command admission receipt가 완전하지 않습니다.")
    payload = {
        "schema_version": CONVERSATION_COMMAND_VERSION,
        "capability": "conversation.command",
        "capability_version": CONVERSATION_CAPABILITY_VERSION,
        "path": {"conversation_id": str(conversation_id)},
        "effective_subject_id": str(context.user_id),
        "permission_snapshot_id": context.permission_snapshot_id,
        "product_release_id": context.product_release_id,
        "semantic_release_id": context.semantic_release_id,
        "request_context": {
            "as_of": context.as_of.isoformat(),
            "timezone": context.timezone,
            "contract_version": context.contract_version,
        },
        "expected_head_turn_id": (
            str(command.expected_head_turn_id)
            if command.expected_head_turn_id is not None
            else None
        ),
        "payload": {
            "user_message": command.user_message,
            "requested_route": command.requested_route,
            "presentation_type": command.presentation_type,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
