"""공개 API 라우트 — 엔터프라이즈 프론트엔드용.

Django에서 FastAPI로 이관한 10개 엔드포인트를 /api/v1/ prefix로 제공한다.
데이터는 Django가 생성한 db.sqlite3에서 sqlite3 모듈로 직접 읽는다.
향후 FastAPI 자체 DB(PostgreSQL)로 이전 예정.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["public"])

# ---------------------------------------------------------------------------
# DB 경로 (Django db.sqlite3)
# ---------------------------------------------------------------------------

# public.py: app/fastapi/app/api/public.py → parent x4 = app/ (skn29_final_3team/app/)
_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DB_PATH = _APP_DIR / "django" / "db.sqlite3"


def _db() -> sqlite3.Connection:
    """db.sqlite3 읽기 전용 연결을 반환한다."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Envelope 헬퍼
# ---------------------------------------------------------------------------


def _ok(data: Any, total: int | None = None) -> dict[str, Any]:
    """성공 응답 envelope ({data, meta, error})."""
    meta: dict[str, Any] = {
        "request_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if total is not None:
        meta["total"] = total
    return {"data": data, "meta": meta, "error": None}


def _err(code: str, message: str, status: int) -> JSONResponse:
    """오류 응답 envelope."""
    return JSONResponse(
        {
            "data": None,
            "meta": {
                "request_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "error": {"code": code, "message": message, "details": []},
        },
        status_code=status,
    )


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

_DEMO_CREDENTIALS: dict[str, dict[str, str]] = {
    "staff.ops": {"password": "demo1234", "role_code": "OPERATIONS_MANAGER", "user_id": "ops-001", "display_name": "운영관리자"},
    "staff.fac": {"password": "demo1234", "role_code": "FACILITY_MANAGER", "user_id": "fac-001", "display_name": "시설관리자"},
    "ext.review": {"password": "demo1234", "role_code": "EXTERNAL_REVIEWER", "user_id": "rev-001", "display_name": "외부관계자"},
}

_ROLE_METRIC_GROUPS: dict[str, list[str]] = {
    "OPERATIONS_MANAGER": ["BREAKFAST", "FNB_VOC", "GUEST_ROOM", "STAFF", "INCIDENTS", "REPORTS"],
    "FACILITY_MANAGER": ["BREAKFAST", "FNB_VOC"],
    "EXTERNAL_REVIEWER": ["GUEST_ROOM_SUMMARY"],
}


class LoginRequest(BaseModel):
    username: str
    password: str


def _build_scope(role_code: str) -> dict[str, Any]:
    groups = _ROLE_METRIC_GROUPS.get(role_code, [])
    return {"property_ids": ["GRAND_WALKERHILL_SEOUL"], "metric_groups": groups}


def _check_auth(request: Request) -> bool:
    """세션에 role_code가 있으면 인증됨."""
    return request.session.get("role_code") is not None


@router.post("/auth/login/")
async def login(body: LoginRequest, request: Request):
    cred = _DEMO_CREDENTIALS.get(body.username)
    if cred is None or cred["password"] != body.password:
        return _err("AUTH_FAILED", "아이디 또는 비밀번호가 올바르지 않습니다.", 401)

    scope = _build_scope(cred["role_code"])
    request.session["user_id"] = cred["user_id"]
    request.session["username"] = body.username
    request.session["role_code"] = cred["role_code"]
    request.session["display_name"] = cred["display_name"]
    request.session["scope_snapshot"] = scope

    return _ok({
        "user_id": cred["user_id"],
        "username": body.username,
        "role_code": cred["role_code"],
        "display_name": cred["display_name"],
        "scope_snapshot": scope,
    })


@router.post("/auth/logout/")
async def logout(request: Request):
    request.session.clear()
    return _ok({"message": "로그아웃되었습니다."})


# ---------------------------------------------------------------------------
# 매핑 헬퍼
# ---------------------------------------------------------------------------

_ENGINE_LABELS = {"POSTGRESQL": "PostgreSQL", "MYSQL": "MySQL", "SQLSERVER": "SQL Server", "CLICKHOUSE": "ClickHouse"}
_DOMAIN_MAP = {"PMS": "예약·투숙", "POS": "식음·구매", "CRM": "고객·멤버십", "FACILITY": "시설 운영", "BANQUET": "연회·매출"}
_HEALTH_SCORE = {"HEALTHY": 99, "DEGRADED": 78, "DOWN": 0, "UNKNOWN": None}
_DS_STATUS_MAP = {"ACTIVE": "connected", "ERROR": "error", "DISABLED": "disabled", "DRAFT": "connected"}
_SOURCE_RECORDS = {"PMS": "4.2M", "POS": "18.7M", "CRM": "620K", "FACILITY": "2.1M", "BANQUET": "340K"}
_TOOL_TYPE_LABELS = {"SQL": "Data", "DATAHUB": "Metadata", "RAG": "Knowledge", "ML": "ML · ONNX"}
_TOOL_HEALTH_MAP = {"HEALTHY": "healthy", "DEGRADED": "degraded", "DOWN": "down", "UNKNOWN": "unknown"}
_SENSITIVITY_LABELS = {"INTERNAL": "Internal", "RESTRICTED": "Restricted", "CONFIDENTIAL": "Confidential"}
_REPORT_TYPE_LABELS = {"WEEKLY": "주간", "MONTHLY": "월간", "QUARTERLY": "분기"}
_REPORT_STATUS_LABELS = {"DRAFT": "초안", "READY_FOR_REVIEW": "검토 중", "APPROVED": "확정", "REJECTED": "반려"}


def _relative_time(dt_str: str | None) -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = datetime.now(timezone.utc) - dt
    minutes = int(diff.total_seconds() / 60)
    if minutes < 1:
        return "방금 전"
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    return f"{hours // 24}일 전"


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _format_report_period(report_type: str, virtual_week_id: str) -> str:
    if report_type == "WEEKLY":
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT service_date FROM dim_date WHERE virtual_week_id = ? ORDER BY service_date",
                (virtual_week_id,),
            ).fetchall()
            if rows:
                start = datetime.strptime(rows[0]["service_date"], "%Y-%m-%d")
                end = datetime.strptime(rows[-1]["service_date"], "%Y-%m-%d")
                return f"{start.month:02d}/{start.day:02d}~{end.month:02d}/{end.day:02d}"
        finally:
            conn.close()
        return virtual_week_id
    if report_type == "MONTHLY":
        parts = virtual_week_id.split("-")
        return f"{parts[0]}년 {parts[1]}월" if len(parts) == 2 else virtual_week_id
    return virtual_week_id


@router.get("/reports/")
async def report_list(request: Request):
    if not _check_auth(request):
        return _err("NOT_AUTHENTICATED", "로그인이 필요합니다.", 401)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM report ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        data = [
            {
                "report_id": str(r["report_id"]),
                "report_version": r["report_version"],
                "virtual_week_id": r["virtual_week_id"],
                "report_type": r["report_type"],
                "report_type_label": _REPORT_TYPE_LABELS.get(r["report_type"], r["report_type"]),
                "period": _format_report_period(r["report_type"], r["virtual_week_id"]),
                "status": r["status"],
                "status_label": _REPORT_STATUS_LABELS.get(r["status"], r["status"]),
                "author": r["author_name"] or "",
                "is_synthetic": bool(r["is_synthetic"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


@router.get("/connections/")
async def connection_list(request: Request):
    if not _check_auth(request):
        return _err("NOT_AUTHENTICATED", "로그인이 필요합니다.", 401)
    conn = _db()
    try:
        rows = conn.execute("SELECT * FROM data_sources ORDER BY source_code").fetchall()
        data = [
            {
                "data_source_id": str(r["data_source_id"]),
                "source_code": r["source_code"],
                "name": r["source_name"],
                "vendor": _ENGINE_LABELS.get(r["engine_type"], r["engine_type"]),
                "catalog": r["trino_catalog"],
                "domain": _DOMAIN_MAP.get(r["source_code"], r["source_code"]),
                "status": _DS_STATUS_MAP.get(r["status"], "connected"),
                "health_status": r["last_health_status"],
                "health": _HEALTH_SCORE.get(r["last_health_status"]),
                "records": _SOURCE_RECORDS.get(r["source_code"], "—"),
                "owner": r["owner_team"],
                "endpoint": f"{r['trino_catalog']}••••.internal",
                "sync": _relative_time(r["last_health_at"]),
            }
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@router.get("/tools/")
async def tool_list(request: Request):
    if not _check_auth(request):
        return _err("NOT_AUTHENTICATED", "로그인이 필요합니다.", 401)
    conn = _db()
    try:
        rows = conn.execute("SELECT * FROM tool_registry ORDER BY tool_code").fetchall()
        data = [
            {
                "tool_id": str(r["tool_id"]),
                "name": r["name"],
                "category": _TOOL_TYPE_LABELS.get(r["tool_type"], r["tool_type"]),
                "version": r["semantic_version"],
                "health": _TOOL_HEALTH_MAP.get(r["health_status"], "unknown"),
                "success": f"{r['success_rate']}%" if r["success_rate"] is not None else "—",
                "agents": "—",
                "permission": "Read only",
                "last": _relative_time(r["last_run_at"]),
                "is_enabled": bool(r["is_enabled"]),
            }
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Data Products
# ---------------------------------------------------------------------------


@router.get("/data-products/")
async def data_product_list(request: Request):
    if not _check_auth(request):
        return _err("NOT_AUTHENTICATED", "로그인이 필요합니다.", 401)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM data_products ORDER BY domain, product_name"
        ).fetchall()
        data = [
            {
                "data_product_id": str(r["data_product_id"]),
                "product": r["product_name"],
                "source": r["source_name"],
                "catalog": r["catalog_ref"],
                "domain": r["domain"],
                "owner": r["owner_team"],
                "freshness": r["freshness_label"],
                "quality": r["quality_score"],
                "sensitivity": _SENSITIVITY_LABELS.get(r["sensitivity"], r["sensitivity"]),
                "tool": r["tool_name"],
            }
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


@router.get("/customers/")
async def customer_list(request: Request):
    if not _check_auth(request):
        return _err("NOT_AUTHENTICATED", "로그인이 필요합니다.", 401)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM customer_profile ORDER BY revisit_score DESC"
        ).fetchall()
        data = [
            {
                "id": r["customer_id"],
                "name": r["display_name"],
                "tier": r["tier_label"],
                "stays": r["stays_count"],
                "revenue": r["revenue_display"],
                "revisit": r["revisit_score"],
                "sentiment": r["sentiment_label"],
                "issue": r["last_issue"],
                "last": r["last_stay_date"],
                "room": r["preferred_room"],
            }
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Agent Workflow
# ---------------------------------------------------------------------------


@router.get("/agent/workflow/")
async def agent_workflow(request: Request):
    if not _check_auth(request):
        return _err("NOT_AUTHENTICATED", "로그인이 필요합니다.", 401)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_workflow_step ORDER BY step_order"
        ).fetchall()
        status_map = {"COMPLETED": "완료", "IN_PROGRESS": "진행 중", "PENDING": "대기"}
        data = [
            [r["step_name"], status_map.get(r["status"], r["status"]), r["description"]]
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        conn.close()
