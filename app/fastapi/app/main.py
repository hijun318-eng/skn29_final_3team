"""SensePlace Analysis API — FastAPI 진입점."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.llm.gateway import LLMGateway
from app.settings import DATABASE_URL, DJANGO_API_URL, SENSEPLACE_LLM_PROVIDER

# ---------------------------------------------------------------------------
# lifespan: 앱 기동 시 LLM gateway 초기화
# ---------------------------------------------------------------------------

llm_gateway: LLMGateway | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global llm_gateway  # noqa: PLW0603
    llm_gateway = LLMGateway()
    yield


# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SensePlace Analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

# Django에서 호출할 때 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 헬스 체크
# ---------------------------------------------------------------------------


async def _check_db() -> str:
    """PostgreSQL 연결을 시도하고 상태 문자열을 반환한다. 실패 시에도 healthy."""
    if not DATABASE_URL:
        return "not_configured"
    try:
        import psycopg  # noqa: F401

        conn = psycopg.connect(DATABASE_URL, connect_timeout=3)
        conn.close()
        return "connected"
    except Exception:
        return "unreachable"


@app.get("/internal/v1/health")
async def health() -> dict[str, str | dict[str, str]]:
    """서비스 상태 확인 — DB 없이도 응답한다.

    계약: API-AI-005 (GET /internal/v1/health)
    """
    db_status = await _check_db()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "llm_provider": SENSEPLACE_LLM_PROVIDER,
        "db": db_status,
        "django_api_url": DJANGO_API_URL,
    }
