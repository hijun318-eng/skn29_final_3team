"""POST /api/v1/agent/query — Guarded Text-to-SQL Pipeline 실행.

엔터프라이즈 프론트엔드 AgentPage에서 질문을 받아 Pipeline을 실행한다.
기획서 §9.3의 결정론적 처리 흐름을 따른다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.pipeline.controller import run_pipeline

router = APIRouter(prefix="/api/v1", tags=["agent"])


class QueryRequest(BaseModel):
    question: str


@router.post("/agent/query/")
async def agent_query(body: QueryRequest, request: Request):
    """Guarded Text-to-SQL Pipeline을 실행한다.

    Router → Node 1 → G1 → Node 2 → G2 → 실행 → G3 → Node 3 순서로 처리하고,
    각 Gate 결과와 최종 분석 결과를 반환한다.
    """
    role = request.session.get("role_code")
    if not role:
        return JSONResponse(
            {
                "data": None,
                "meta": {},
                "error": {
                    "code": "NOT_AUTHENTICATED",
                    "message": "로그인이 필요합니다.",
                    "details": [],
                },
            },
            status_code=401,
        )

    result = await run_pipeline(body.question, role=role)
    return {
        "data": result.model_dump(),
        "meta": {
            "request_id": result.request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "error": None if result.state.value == "DONE" else result.error,
    }
