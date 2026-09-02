"""인증된 메인 질의화면에 승인된 RAG Tool 실행 경계를 제공한다."""

from __future__ import annotations

import asyncio
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field

from app.authorization import has_capability
from app.api.rag_router_runtime import internal_manual_query_service
from app.context import session_context
from app.contracts import Capability, ContractModel, RequestContext, RuntimeFeature
from app.runtime_features import runtime_feature_enabled
from app.services.internal_manual_query import (
    InternalManualQuery,
    InternalManualQueryError,
    approved_rag_snapshot as _approved_rag_snapshot,
    rag_document_ids as _rag_document_ids,
)
from app.services.rag_gateway import RagGatewayTool, RagToolError
from app.services.rag_document_preview import (
    RagDocumentPreviewError,
    render_docx_preview_html,
)


class RagQueryRequest(ContractModel):
    """내부 매뉴얼 검색에 허용되는 질문과 대화 문맥 입력을 제한한다."""

    question: str = Field(min_length=2, max_length=500)
    mode: Literal["AUTO", "DOCUMENT_ONLY"] = "DOCUMENT_ONLY"
    conversation_id: UUID | None = None
    expected_head_turn_id: UUID | None = None
    inherit_previous_context: bool = False


rag_router = APIRouter()


def _require_internal_guideline_enabled() -> None:
    """비활성 RAG API가 Gateway나 Registry에 접근하지 못하게 차단한다."""

    if not runtime_feature_enabled(RuntimeFeature.INTERNAL_GUIDELINE):
        raise HTTPException(
            status_code=503,
            detail="내부지침 검색 기능이 비활성화되었습니다.",
        )


@rag_router.post("/rag/query", operation_id="queryInternalManual")
async def query_internal_manual(
    payload: RagQueryRequest,
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict:
    """사용자 권한과 대화 head를 확인해 내부 매뉴얼 검색 결과를 반환한다."""
    try:
        result = await internal_manual_query_service().execute(
            InternalManualQuery(
                question=payload.question,
                mode=payload.mode,
                conversation_id=payload.conversation_id,
                expected_head_turn_id=payload.expected_head_turn_id,
                expected_head_turn_id_is_set=(
                    "expected_head_turn_id" in payload.model_fields_set
                ),
                inherit_previous_context=payload.inherit_previous_context,
            ),
            context,
        )
    except InternalManualQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"status": "SUCCESS", "data": result}


@rag_router.get("/rag/documents", operation_id="listInternalManuals")
async def list_internal_manuals(
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict:
    """현재 역할이 열람할 수 있는 승인 문서 목록을 동적으로 반환한다."""
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 문서 열람 권한이 없습니다.")
    _require_internal_guideline_enabled()
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not database_url:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        documents = await RagGatewayTool(database_url).fetch_catalog(context.role.value)
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"status": "SUCCESS", "data": {"documents": documents}}


@rag_router.get(
    "/rag/documents/{manual_id}/source",
    operation_id="getInternalManualSource",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
            }
        }
    },
)
async def get_internal_manual_source(
    manual_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> Response:
    """요청 주체가 열람할 수 있는 PDF 또는 DOCX 원문을 형식 그대로 중계한다."""

    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 문서 열람 권한이 없습니다.")
    _require_internal_guideline_enabled()
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not database_url:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        content, disposition, media_type = await RagGatewayTool(
            database_url
        ).fetch_document(manual_id, context.role.value)
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@rag_router.get("/rag/documents/{manual_id}/source.pdf", operation_id="getInternalManualPdf")
async def get_internal_manual_pdf(
    manual_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> Response:
    """요청 주체가 열람할 수 있는 내부 매뉴얼 PDF만 중계한다."""
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 문서 열람 권한이 없습니다.")
    _require_internal_guideline_enabled()
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


@rag_router.get(
    "/rag/documents/{manual_id}/preview",
    operation_id="previewInternalManual",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "text/html": {},
            }
        }
    },
)
async def get_internal_manual_preview(
    manual_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> Response:
    """승인된 PDF는 그대로, DOCX는 안전한 HTML로 변환해 화면 내 열람을 제공한다."""

    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="RAG 문서 열람 권한이 없습니다.")
    _require_internal_guideline_enabled()
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not database_url:
        raise HTTPException(status_code=503, detail="RAG Tool Registry를 사용할 수 없습니다.")
    try:
        content, _disposition, media_type = await RagGatewayTool(
            database_url
        ).fetch_document(manual_id, context.role.value)
    except RagToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    common_headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if media_type == "application/pdf":
        return Response(
            content=content,
            media_type=media_type,
            headers={
                **common_headers,
                "Content-Disposition": f'inline; filename="{manual_id}.pdf"',
            },
        )
    try:
        html = await asyncio.to_thread(render_docx_preview_html, content, manual_id)
    except RagDocumentPreviewError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return Response(
        content=html,
        media_type="text/html",
        headers={
            **common_headers,
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )
