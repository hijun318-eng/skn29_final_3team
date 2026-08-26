"""인증된 메인 질의화면에 승인된 RAG Tool 실행 경계를 제공한다."""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.adapters.conversation_repository import ConversationRepository
from app.authorization import has_capability
from app.context import session_context
from app.contracts import Capability, RequestContext
from app.database import get_sessionmaker
from app.services.rag_gateway import InternalManualAgent, RagGatewayTool, RagToolError
from app.services.rag_routing import RagIntent, RagQueryRouter, RagRoute


class RagQueryRequest(BaseModel):
    """내부 매뉴얼 검색에 허용되는 질문과 대화 문맥 입력을 제한한다."""

    question: str = Field(min_length=2, max_length=500)
    mode: Literal["AUTO", "DOCUMENT_ONLY"] = "AUTO"
    conversation_id: UUID | None = None
    expected_head_turn_id: UUID | None = None


rag_router = APIRouter()

_HELP_EXAMPLES = (
    ("처리 방법", "객실 청결 불만이 들어오면 어떻게 처리해?"),
    ("즉시 대응", "고객이 객실에서 쓰러졌어. 지금 뭘 해야 해?"),
    ("판단 기준", "시설 문제를 '위험'으로 분류하는 기준이 뭐야?"),
    ("규정 확인", "예약 취소하면 환불 가능한가?"),
    ("비교", "시설 장애와 안전사고 대응은 어떻게 달라?"),
    ("요약", "고객응대 지침에서 중요한 내용만 알려줘."),
)


def _help_kind(question: str) -> str | None:
    compact = "".join(question.lower().split())
    if any(term in compact for term in ("어떤문서", "문서목록", "문서가있")):
        return "catalog"
    if any(term in compact for term in ("뭘물어", "무엇을물어", "질문예시")):
        return "examples"
    if "관련문서" in compact or "관련해서어떤내용" in compact:
        return "topic"
    return None


def _help_result(question: str, documents: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    titles = [
        str(item.get("title") or item.get("manual_id") or "").strip()
        for item in documents
    ]
    titles = [title for title in titles if title]
    if kind == "examples":
        text = "이렇게 질문할 수 있습니다.\n\n" + "\n".join(
            f"- {label}: {example}" for label, example in _HELP_EXAMPLES
        )
    elif kind == "topic":
        keyword = next(
            (
                word
                for word in ("안전", "환불", "취소", "개인정보", "시설", "예약", "결제")
                if word in question
            ),
            "",
        )
        matched = [title for title in titles if keyword and keyword in title]
        text = f"{keyword or '요청한'} 관련 문서입니다.\n\n" + "\n".join(
            f"- {title}" for title in (matched or titles)
        )
    else:
        text = "확인할 수 있는 업무 문서입니다.\n\n" + "\n".join(
            f"- {title}" for title in titles
        )
    return {
        "status": "ANSWER",
        "answer_type": "SUMMARY",
        "answer": {"text": text},
        "document": {"body": text},
        "citations": [],
    }


def _rag_document_ids(rag_result: dict[str, Any]) -> tuple[str, ...]:
    """저장된 RAG 턴에서 실제 답변에 사용된 문서 ID를 순서대로 복원한다."""
    document = rag_result.get("document")
    candidates: list[Any] = []
    if isinstance(document, dict):
        candidates.append(document.get("document_id"))
    evidence = rag_result.get("evidence_bundle")
    if isinstance(evidence, list):
        candidates.extend(
            item.get("document_id")
            for item in evidence
            if isinstance(item, dict)
        )
    return tuple(dict.fromkeys(
        str(value).strip() for value in candidates if str(value or "").strip()
    ))


@rag_router.post("/rag/query", operation_id="queryInternalManual")
async def query_internal_manual(
    payload: RagQueryRequest,
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict:
    """사용자 권한과 대화 head를 확인해 내부 매뉴얼 검색 결과를 반환한다."""
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 검색 권한이 없습니다.")
    help_kind = _help_kind(payload.question)
    if help_kind:
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
        if not database_url:
            raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
        try:
            documents = await RagGatewayTool(database_url).fetch_catalog(context.role.value)
        except RagToolError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        result = _help_result(payload.question, documents, help_kind)
        result["route"] = "DOCUMENT_HELP"
        result["trace_id"] = context.trace_id
        if payload.conversation_id is not None:
            repository = ConversationRepository(get_sessionmaker(database_url))
            try:
                turn_id = await repository.append_rag_turn(
                    payload.conversation_id,
                    context.user_id,
                    payload.question,
                    result,
                    payload.expected_head_turn_id,
                    "expected_head_turn_id" in payload.model_fields_set,
                )
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            if turn_id is None:
                raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
            result["turn_id"] = str(turn_id)
        return {"status": "SUCCESS", "data": result}
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    repository = ConversationRepository(get_sessionmaker(database_url)) if database_url else None
    recent_utterances: tuple[str, ...] = ()
    previous_document_ids: tuple[str, ...] = ()
    if payload.conversation_id is not None:
        if repository is None:
            raise HTTPException(status_code=503, detail="대화 저장소를 사용할 수 없습니다.")
        conversation = await repository.get_conversation(payload.conversation_id, context.user_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        previous_turns = await repository.list_turns(payload.conversation_id)
        context_items: list[str] = []
        for turn in previous_turns[-6:]:
            slots = turn.get("resolved_slots") or {}
            rag_result = slots.get("rag") if isinstance(slots, dict) else None
            if isinstance(rag_result, dict):
                document_ids = _rag_document_ids(rag_result)
                if document_ids:
                    previous_document_ids = document_ids
            routing = rag_result.get("routing") if isinstance(rag_result, dict) else None
            context_question = routing.get("context_question") if isinstance(routing, dict) else None
            if isinstance(context_question, str) and context_question.strip():
                context_items.append(context_question.strip())
            user_message = str(turn.get("user_message") or "").strip()
            if user_message:
                context_items.append(user_message)
        recent_utterances = tuple(context_items[-12:])
    decision = RagQueryRouter().classify(payload.question, payload.mode, recent_utterances)
    selected_document_ids: tuple[str, ...] = ()
    if decision.requires_context and previous_document_ids:
        limit = 2 if decision.intent is RagIntent.COMPARISON else 1
        selected_document_ids = previous_document_ids[:limit]
    if decision.route is RagRoute.DATA_ONLY:
        return {"status": "SUCCESS", "data": {"status": "NO_EVIDENCE", "route": decision.route.value, "trace_id": context.trace_id}}
    if decision.clarification:
        result = {
            "status": "NEEDS_CLARIFICATION",
            "response_status": "NEEDS_CLARIFICATION",
            "answer_type": "SUMMARY",
            "answer": {"text": decision.clarification},
            "document": {"body": decision.clarification},
            "citations": [],
            "evidence_bundle": [],
            "clarification_options": list(decision.clarification_options),
            "route": decision.route.value,
            "trace_id": context.trace_id,
            "routing": {
                "domains": list(decision.domains),
                "intent": decision.intent.value,
                "confidence": decision.confidence,
                "requires_context": decision.requires_context,
            },
        }
        if payload.conversation_id is not None:
            if repository is None:
                raise HTTPException(status_code=503, detail="대화 저장소를 사용할 수 없습니다.")
            try:
                turn_id = await repository.append_rag_turn(
                    payload.conversation_id,
                    context.user_id,
                    payload.question,
                    result,
                    payload.expected_head_turn_id,
                    "expected_head_turn_id" in payload.model_fields_set,
                )
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            if turn_id is None:
                raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
            result["turn_id"] = str(turn_id)
        return {"status": "SUCCESS", "data": result}
    enabled = os.getenv("RAG_FEATURE_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        if payload.mode == "AUTO":
            return {"status": "SUCCESS", "data": {"status": "NO_EVIDENCE", "route": "DATA_ONLY", "trace_id": context.trace_id}}
        raise HTTPException(status_code=503, detail="내부지침 검색 기능이 비활성화되었습니다.")
    if not database_url or repository is None:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        result = await InternalManualAgent(database_url).execute(
            query=payload.question,
            actor_id=context.user_id,
            app_role=context.role.value,
            trace_id=context.trace_id,
            recent_utterances=recent_utterances,
            resolved_question=decision.resolved_question,
            domains=decision.domains,
            intent=decision.intent.value,
            selected_document_ids=selected_document_ids,
        )
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    result["route"] = decision.route.value
    existing_routing = result.get("routing") if isinstance(result.get("routing"), dict) else {}
    result["routing"] = {
        **existing_routing,
        "domains": list(decision.domains),
        "intent": decision.intent.value,
        "confidence": decision.confidence,
        "requires_context": decision.requires_context,
        "selected_document_ids": list(selected_document_ids),
    }
    if payload.conversation_id is not None:
        try:
            turn_id = await repository.append_rag_turn(
                payload.conversation_id,
                context.user_id,
                payload.question,
                result,
                payload.expected_head_turn_id,
                "expected_head_turn_id" in payload.model_fields_set,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if turn_id is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        result["turn_id"] = str(turn_id)
    return {"status": "SUCCESS", "data": result}


@rag_router.get("/rag/documents/{manual_id}/source.pdf", operation_id="getInternalManualPdf")
async def get_internal_manual_pdf(
    manual_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> Response:
    """요청 주체가 열람할 수 있는 내부 매뉴얼 PDF만 중계한다."""
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 문서 열람 권한이 없습니다.")
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not database_url:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        content, disposition = await RagGatewayTool(database_url).fetch_pdf(
            manual_id, context.role.value
        )
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )
