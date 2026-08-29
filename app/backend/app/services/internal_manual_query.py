"""FastAPI와 분리된 승인 내부지침 검색 use case를 제공한다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any, Literal, Protocol
from uuid import UUID

from app.authorization import has_capability
from app.contracts import Capability, RequestContext
from app.services.rag_gateway import RagToolError


_MANUAL_ID = re.compile(r"[A-Z][A-Z0-9-]{1,99}")


class InternalManualQueryError(RuntimeError):
    """내부지침 use case 실패를 HTTP와 무관한 공개 오류 계약으로 전달한다."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class InternalManualQuery:
    """검증된 API·Agent 입력을 내부지침 use case에 전달하는 명령이다."""

    question: str
    mode: Literal["AUTO", "DOCUMENT_ONLY"]
    conversation_id: UUID | None = None
    expected_head_turn_id: UUID | None = None
    expected_head_turn_id_is_set: bool = False
    inherit_previous_context: bool = False


class ConversationRagRepository(Protocol):
    """내부지침 실행에 필요한 Conversation 저장소의 최소 계약이다."""

    async def get_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any] | None:
        """사용자 소유 범위에서 대화방을 조회한다."""

        ...

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        """대화방의 불변 턴 목록을 순서대로 조회한다."""

        ...

    async def append_rag_turn(
        self,
        conversation_id: UUID,
        user_id: UUID,
        question: str,
        result: dict[str, Any],
        expected_head_turn_id: UUID | None,
        expected_head_turn_id_is_set: bool,
    ) -> UUID | None:
        """승인 RAG 결과를 CAS 조건과 함께 새 턴으로 저장한다."""

        ...


class InternalManualExecutor(Protocol):
    """승인된 내부지침 Gateway 실행기의 최소 계약이다."""

    async def execute(
        self,
        query: str,
        actor_id: UUID,
        app_role: str,
        trace_id: str,
        recent_utterances: tuple[str, ...] = (),
        resolved_question: str | None = None,
        domains: tuple[str, ...] = (),
        intent: str = "REGULATION_CHECK",
        selected_document_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """승인 문서 검색과 근거 답변 생성을 실행한다."""

        ...


def rag_document_ids(rag_result: dict[str, Any]) -> tuple[str, ...]:
    """저장된 서버 RAG 결과에서 검증 가능한 문서 ID를 최대 두 개 복원한다."""

    candidates: list[Any] = []
    routing = rag_result.get("routing")
    if isinstance(routing, dict) and isinstance(
        routing.get("selected_document_ids"),
        list,
    ):
        candidates.extend(routing["selected_document_ids"])
    evidence = rag_result.get("evidence_bundle")
    if isinstance(evidence, list):
        candidates.extend(
            item.get("document_id") or item.get("manual_id")
            for item in evidence
            if isinstance(item, dict)
        )
    normalized = (
        str(value).strip()
        for value in candidates
        if isinstance(value, str) and _MANUAL_ID.fullmatch(value.strip())
    )
    return tuple(dict.fromkeys(normalized))[:2]


def approved_rag_snapshot(
    previous_turns: list[dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """직전 RAG 턴의 승인된 질문·문서 snapshot만 후속 실행 입력으로 복원한다."""

    if not previous_turns:
        return (), ()
    latest = previous_turns[-1]
    if latest.get("route") != "INTERNAL_GUIDELINE":
        return (), ()
    slots = latest.get("resolved_slots") or {}
    rag_result = slots.get("rag") if isinstance(slots, dict) else None
    if not isinstance(rag_result, dict):
        return (), ()
    routing = rag_result.get("routing")
    if not isinstance(routing, dict):
        return (), ()
    snapshot_question = routing.get("snapshot_question") or routing.get(
        "context_question"
    )
    if not isinstance(snapshot_question, str) or not snapshot_question.strip():
        return (), ()
    document_ids = rag_document_ids(rag_result)
    if not document_ids:
        return (), ()
    return (snapshot_question.strip(),), document_ids


class InternalManualQueryService:
    """권한·승인 snapshot·Gateway·Turn 저장을 한 use case로 실행한다."""

    def __init__(
        self,
        repository: ConversationRagRepository | None,
        executor_factory: Callable[[], InternalManualExecutor] | None,
        *,
        enabled: bool,
    ) -> None:
        self._repository = repository
        self._executor_factory = executor_factory
        self._enabled = enabled

    async def execute(
        self,
        query: InternalManualQuery,
        context: RequestContext,
    ) -> dict[str, Any]:
        """승인된 문서 문맥만 사용해 RAG 결과와 선택적 Conversation Turn을 반환한다."""

        if not has_capability(context.role, Capability.RUN_ANALYSIS):
            raise InternalManualQueryError(
                "RAG_ACCESS_DENIED",
                "RAG 검색 권한이 없습니다.",
                403,
            )

        recent_utterances: tuple[str, ...] = ()
        selected_document_ids: tuple[str, ...] = ()
        if query.conversation_id is not None:
            if self._repository is None:
                raise InternalManualQueryError(
                    "RAG_CONVERSATION_REPOSITORY_UNAVAILABLE",
                    "대화 저장소를 사용할 수 없습니다.",
                    503,
                )
            conversation = await self._repository.get_conversation(
                query.conversation_id,
                context.user_id,
            )
            if conversation is None:
                raise InternalManualQueryError(
                    "RAG_CONVERSATION_NOT_FOUND",
                    "대화방을 찾을 수 없습니다.",
                    404,
                )
            if query.inherit_previous_context:
                previous_turns = await self._repository.list_turns(
                    query.conversation_id
                )
                recent_utterances, selected_document_ids = approved_rag_snapshot(
                    previous_turns
                )
                if not recent_utterances or not selected_document_ids:
                    raise InternalManualQueryError(
                        "RAG_APPROVED_CONTEXT_MISSING",
                        "승인된 직전 내부지침 문맥이 없어 후속 질문을 실행할 수 없습니다.",
                        409,
                    )

        if not self._enabled:
            raise InternalManualQueryError(
                "RAG_FEATURE_DISABLED",
                "내부지침 검색 기능이 비활성화되었습니다.",
                503,
            )
        if self._repository is None or self._executor_factory is None:
            raise InternalManualQueryError(
                "RAG_REGISTRY_UNAVAILABLE",
                "RAG Tool Registry를 사용할 수 없습니다.",
                503,
            )

        try:
            result = await self._executor_factory().execute(
                query=query.question,
                actor_id=context.user_id,
                app_role=context.role.value,
                trace_id=context.trace_id,
                recent_utterances=recent_utterances,
                selected_document_ids=selected_document_ids,
            )
        except RagToolError as error:
            raise InternalManualQueryError(
                error.code,
                str(error),
                error.status_code,
            ) from error

        result = dict(result)
        result["route"] = "DOCUMENT_ONLY"
        existing_routing = (
            result.get("routing") if isinstance(result.get("routing"), dict) else {}
        )
        result["routing"] = {
            **existing_routing,
            "domains": [],
            "intent": "REGULATION_CHECK",
            "decision_source": "EXPLICIT_RAG_ENDPOINT",
            "requested_mode": query.mode,
            "requires_context": query.inherit_previous_context,
            "context_source": (
                "APPROVED_RAG_SNAPSHOT"
                if query.inherit_previous_context
                else "NONE"
            ),
        }

        if query.conversation_id is not None:
            try:
                turn_id = await self._repository.append_rag_turn(
                    query.conversation_id,
                    context.user_id,
                    query.question,
                    result,
                    query.expected_head_turn_id,
                    query.expected_head_turn_id_is_set,
                )
            except ValueError as error:
                raise InternalManualQueryError(
                    "RAG_TURN_CONFLICT",
                    str(error),
                    409,
                ) from error
            if turn_id is None:
                raise InternalManualQueryError(
                    "RAG_CONVERSATION_NOT_FOUND",
                    "대화방을 찾을 수 없습니다.",
                    404,
                )
            result["turn_id"] = str(turn_id)
        return result
