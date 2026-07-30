"""SensePlace Analysis API — FastAPI 진입점."""

from __future__ import annotations

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

# 프로젝트 루트와 src/를 sys.path에 추가하여 src.* import 가능
# main.py 위치: skn29_final_3team/app/fastapi/app/main.py → 3번 parent = skn29_final_3team/
_root = Path(__file__).resolve().parent.parent.parent.parent
_src = _root / "src"
for p in (_root, _src):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.agent_query import router as agent_query_router
from app.api.detections import router as detections_router
from app.api.incident_runs import router as incident_runs_router
from app.api.public import router as public_router
from app.api.quality_gates import router as quality_gates_router
from app.api.query_runs import router as query_runs_router
from app.api.report_runs import router as report_runs_router
from app.database import Base, SessionLocal, engine
from app.llm.gateway import LLMGateway
from app.models import AuditEvent
from app.settings import DATABASE_URL, DJANGO_API_URL, SENSEPLACE_LLM_PROVIDER

# ---------------------------------------------------------------------------
# lifespan: 앱 기동 시 LLM gateway 초기화
# ---------------------------------------------------------------------------

llm_gateway: LLMGateway | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global llm_gateway  # noqa: PLW0603
    llm_gateway = LLMGateway()
    # 감사 로그 등 신규 테이블 자동 생성
    Base.metadata.create_all(engine)
    yield


# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 감사 미들웨어 (기획서 §17.2)
# ---------------------------------------------------------------------------


class AuditMiddleware(BaseHTTPMiddleware):
    """모든 /api/v1/ 요청을 audit_event 테이블에 기록한다."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        if request.url.path.startswith("/api/v1/"):
            session = request.scope.get("session", {})
            db = SessionLocal()
            try:
                db.add(AuditEvent(
                    event_id=str(uuid4()),
                    request_id=response.headers.get("x-request-id", str(uuid4())),
                    user_id=session.get("user_id", ""),
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    duration_ms=duration_ms,
                ))
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

        return response


# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SensePlace Analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

# 미들웨어 (등록 역순 실행: Session → CORS → Audit → 앱)
app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key="answervice-dev-secret-key")


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


# ---------------------------------------------------------------------------
# 내부 API 라우터 등록
# ---------------------------------------------------------------------------

app.include_router(public_router)
app.include_router(agent_query_router)
app.include_router(report_runs_router)
app.include_router(quality_gates_router)
app.include_router(detections_router)
app.include_router(query_runs_router)
app.include_router(incident_runs_router)
