"""인증된 메인 질의화면에 승인된 RAG Tool 실행 경계를 제공한다."""

from __future__ import annotations

import os
import re
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field

from app.adapters.conversation_repository import ConversationRepository
from app.authorization import has_capability
from app.context import session_context
from app.contracts import Capability, ContractModel, RequestContext
from app.database import get_sessionmaker
from app.services.rag_gateway import InternalManualAgent, RagGatewayTool, RagToolError


class RagQueryRequest(ContractModel):
    """내부 매뉴얼 검색에 허용되는 질문과 대화 문맥 입력을 제한한다."""

    question: str = Field(min_length=2, max_length=500)
    mode: Literal["AUTO", "DOCUMENT_ONLY"] = "DOCUMENT_ONLY"
    conversation_id: UUID | None = None
    expected_head_turn_id: UUID | None = None
    inherit_previous_context: bool = False


rag_router = APIRouter()


_MANUAL_ID = re.compile(r"[A-Z][A-Z0-9-]{1,99}")


def _rag_document_ids(rag_result: dict[str, Any]) -> tuple[str, ...]:
    """저장된 서버 RAG 결과에서 검증 가능한 문서 ID를 최대 두 개 복원한다."""
    candidates: list[Any] = []
    routing = rag_result.get("routing")
    if isinstance(routing, dict) and isinstance(routing.get("selected_document_ids"), list):
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


def _approved_rag_snapshot(
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
    snapshot_question = routing.get("snapshot_question") or routing.get("context_question")
    if not isinstance(snapshot_question, str) or not snapshot_question.strip():
        return (), ()
    document_ids = _rag_document_ids(rag_result)
    if not document_ids:
        return (), ()
    return (snapshot_question.strip(),), document_ids


@rag_router.post("/rag/query", operation_id="queryInternalManual")
async def query_internal_manual(
    payload: RagQueryRequest,
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict:
    """사용자 권한과 대화 head를 확인해 내부 매뉴얼 검색 결과를 반환한다."""
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 검색 권한이 없습니다.")
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    repository = ConversationRepository(get_sessionmaker(database_url)) if database_url else None
    recent_utterances: tuple[str, ...] = ()
    selected_document_ids: tuple[str, ...] = ()
    if payload.conversation_id is not None:
        if repository is None:
            raise HTTPException(status_code=503, detail="대화 저장소를 사용할 수 없습니다.")
        conversation = await repository.get_conversation(payload.conversation_id, context.user_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        if payload.inherit_previous_context:
            previous_turns = await repository.list_turns(payload.conversation_id)
            recent_utterances, selected_document_ids = _approved_rag_snapshot(
                previous_turns
            )
            if not recent_utterances or not selected_document_ids:
                raise HTTPException(
                    status_code=409,
                    detail="승인된 직전 내부지침 문맥이 없어 후속 질문을 실행할 수 없습니다.",
                )
    enabled = os.getenv("RAG_FEATURE_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    if not enabled:
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
            selected_document_ids=selected_document_ids,
        )
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    result["route"] = "DOCUMENT_ONLY"
    existing_routing = result.get("routing") if isinstance(result.get("routing"), dict) else {}
    result["routing"] = {
        **existing_routing,
        "domains": [],
        "intent": "REGULATION_CHECK",
        "decision_source": "EXPLICIT_RAG_ENDPOINT",
        "requested_mode": payload.mode,
        "requires_context": payload.inherit_previous_context,
        "context_source": (
            "APPROVED_RAG_SNAPSHOT"
            if payload.inherit_previous_context
            else "NONE"
        ),
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


@rag_router.get("/rag/documents", operation_id="listInternalManuals")
async def list_internal_manuals(
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict:
    """현재 역할이 열람할 수 있는 승인 문서 목록을 동적으로 반환한다."""
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 문서 열람 권한이 없습니다.")
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not database_url:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        documents = await RagGatewayTool(database_url).fetch_catalog(context.role.value)
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"status": "SUCCESS", "data": {"documents": documents}}


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
