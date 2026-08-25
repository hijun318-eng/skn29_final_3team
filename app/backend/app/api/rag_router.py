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
from app.services.rag_routing import RagQueryRouter, RagRoute


class RagQueryRequest(BaseModel):
    """내부 문서 질의와 선택 모드, 저장 대상 대화 식별자를 제한한다."""

    question: str = Field(min_length=2, max_length=500)
    mode: Literal["AUTO", "DOCUMENT_ONLY"] = "AUTO"
    conversation_id: UUID | None = None
    expected_head_turn_id: UUID | None = None


rag_router = APIRouter()

_HELP_EXAMPLES = (
    "고객 불만은 어떻게 처리해?",
    "시설 문제가 발생하면 먼저 뭘 해야 해?",
    "환불 기준 알려줘",
    "개인정보가 잘못 전달됐을 때 어떻게 해야 해?",
    "안전사고 발생 시 대응 절차 알려줘",
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
            f"- {example}" for example in _HELP_EXAMPLES
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


@rag_router.post("/rag/query", operation_id="queryInternalManual")
async def query_internal_manual(
    payload: RagQueryRequest,
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict:
    """세션 권한과 RAG Registry를 확인해 근거 답변을 생성하고 선택적으로 Turn을 저장한다."""

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
    if payload.conversation_id is not None:
        if repository is None:
            raise HTTPException(status_code=503, detail="대화 저장소를 사용할 수 없습니다.")
        conversation = await repository.get_conversation(payload.conversation_id, context.user_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        previous_turns = await repository.list_turns(payload.conversation_id)
        recent_utterances = tuple(
            str(turn.get("user_message") or "").strip()
            for turn in previous_turns[-3:]
            if str(turn.get("user_message") or "").strip()
        )
    decision = RagQueryRouter().classify(payload.question, payload.mode, recent_utterances)
    if decision.route is RagRoute.DATA_ONLY:
        return {"status": "SUCCESS", "data": {"status": "NO_EVIDENCE", "route": decision.route.value, "trace_id": context.trace_id}}
    enabled = os.getenv("RAG_FEATURE_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        if payload.mode == "AUTO":
            return {"status": "SUCCESS", "data": {"status": "NO_EVIDENCE", "route": "DATA_ONLY", "trace_id": context.trace_id}}
        raise HTTPException(status_code=503, detail="내부지침 검색 기능이 비활성화되었습니다.")
    if not database_url or repository is None:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        result = await InternalManualAgent(database_url).execute(
            payload.question,
            context.user_id,
            context.role.value,
            context.trace_id,
            recent_utterances,
            decision.resolved_question,
            decision.domains,
            decision.intent.value,
        )
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    result["route"] = decision.route.value
    result["routing"] = {"domains": list(decision.domains), "intent": decision.intent.value, "confidence": decision.confidence, "requires_context": decision.requires_context}
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
    """문서 식별자와 열람 권한을 검증해 원본 PDF를 캐시 금지 응답으로 전달한다."""

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
