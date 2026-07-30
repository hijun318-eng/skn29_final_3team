"""보고서 실행 API — 기획서 §11 자동 리포팅.

POST /api/v1/reports/{report_id}/run/ — 수동 실행
GET  /api/v1/reports/runs/          — 실행 이력
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select

from app.database import SessionLocal
from app.models import Report, ReportRun

router = APIRouter(prefix="/api/v1", tags=["report-runs"])


def _ok(data, total=None):
    meta = {"request_id": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat()}
    if total is not None:
        meta["total"] = total
    return {"data": data, "meta": meta, "error": None}


def _unauth():
    return JSONResponse(
        {"data": None, "meta": {}, "error": {"code": "NOT_AUTHENTICATED", "message": "로그인이 필요합니다.", "details": []}},
        status_code=401,
    )


@router.post("/reports/{report_id}/run/")
async def run_report(report_id: str, request: Request):
    """보고서 수동 실행 — 기획서 §11.5.

    stub: Pipeline 실행 없이 즉시 SUCCEEDED 상태로 ReportRun을 생성한다.
    실제 구현에서는 Pipeline을 호출하고 Block Run 결과를 저장한다.
    """
    if not request.session.get("role_code"):
        return _unauth()

    db = SessionLocal()
    try:
        report = db.execute(
            select(Report).where(Report.report_id == report_id)
        ).scalar_one_or_none()
        if not report:
            return JSONResponse(
                {"data": None, "meta": {}, "error": {"code": "NOT_FOUND", "message": "보고서를 찾을 수 없습니다.", "details": []}},
                status_code=404,
            )

        now = datetime.now(timezone.utc).isoformat()
        run = ReportRun(
            run_id=str(uuid4()),
            report_id=report_id,
            trigger_type="MANUAL",
            triggered_by=request.session.get("user_id", ""),
            status="SUCCEEDED",
            period_start=now,
            period_end=now,
            created_at=now,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        return _ok({
            "run_id": run.run_id,
            "report_id": report_id,
            "status": run.status,
            "trigger_type": run.trigger_type,
            "triggered_by": run.triggered_by,
            "created_at": run.created_at,
        })
    finally:
        db.close()


@router.get("/reports/runs/")
async def report_run_list(request: Request):
    """보고서 실행 이력 — 최근 20건."""
    if not request.session.get("role_code"):
        return _unauth()

    db = SessionLocal()
    try:
        rows = db.execute(
            select(ReportRun).order_by(desc(ReportRun.created_at)).limit(20)
        ).scalars().all()
        data = [
            {
                "run_id": r.run_id,
                "report_id": r.report_id,
                "trigger_type": r.trigger_type,
                "triggered_by": r.triggered_by,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return _ok(data, total=len(data))
    finally:
        db.close()
