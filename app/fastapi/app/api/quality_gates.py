"""POST /internal/v1/quality-gates — 배치 품질 Gate 실행.

AIC v2.0 API-AI-001: Django worker가 데이터 품질 검사를 요청하면
src/analysis/quality의 순수 함수를 호출하여 결정론적 판정을 반환한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §8
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api._envelope import elapsed_ms, error, new_request_id, ok, start_timer
from app.api._internal_ctx import InternalContext

router = APIRouter(prefix="/internal/v1", tags=["quality-gates"])


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------

class QualityGatesRequest(BaseModel):
    """품질 Gate 실행 요청 (AIC §8)."""

    context: InternalContext = Field(..., description="공통 내부 컨텍스트")
    dataset_version: str = Field(
        default="gw-synthetic-1.0.0",
        description="데이터셋 버전",
    )
    gate_version: str = Field(
        default="dq-v1",
        description="품질 게이트 규칙 버전",
    )
    voc_items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="VOC 레코드 리스트 (fact_voc 기반)",
    )
    numeric_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="숫자형 레코드 리스트 (fact_breakfast_15m 등)",
    )
    expected_buckets: int | None = Field(
        default=None,
        description="기대 bucket 수",
    )
    actual_buckets: int | None = Field(
        default=None,
        description="실제 유효 bucket 수",
    )
    valid_area_ids: list[str] | None = Field(
        default=None,
        description="유효한 service_area_id 목록",
    )
    room_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="객실 레코드 리스트 (fact_rooms_daily 기반)",
    )
    bucket_15m_totals: dict[str, float] | None = Field(
        default=None,
        description="service_area_id → 15분 actual_arrivals 합계",
    )
    daily_arrivals: dict[str, float] | None = Field(
        default=None,
        description="service_area_id → daily arrivals_total",
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post("/quality-gates")
async def run_quality_gates(
    body: QualityGatesRequest,
    request: Request,
) -> dict[str, Any]:
    """배치 품질 Gate를 실행한다.

    결정론적: 동일 입력 → 동일 출력.
    """
    rid = new_request_id()
    start_timer(rid)

    try:
        from src.analysis.quality import run_quality_gate

        result = run_quality_gate(
            voc_items=body.voc_items,
            numeric_items=body.numeric_items,
            expected_buckets=body.expected_buckets,
            actual_buckets=body.actual_buckets,
            valid_area_ids=set(body.valid_area_ids) if body.valid_area_ids else None,
            room_items=body.room_items,
            bucket_15m_totals=body.bucket_15m_totals,
            daily_arrivals=body.daily_arrivals,
        )

        checks = [
            {
                "check_id": c.gate.upper(),
                "status": "PASSED" if c.passed else "FAILED",
                "message": c.message,
                "details": c.details,
            }
            for c in result.checks
        ]

        gate_status = "PASSED" if result.passed else "NEEDS_DATA"
        data = {
            "job_status": "SUCCEEDED",
            "gate_status": gate_status,
            "gate_version": body.gate_version,
            "dataset_version": body.dataset_version,
            "checks": checks,
            "summary": result.summary,
            "limitations": [],
        }
        return ok(data, rid)

    except Exception as exc:
        return error(
            code="INTERNAL_ERROR",
            message=f"품질 게이트 실행 중 오류: {exc}",
            request_id=rid,
            status_code=500,
        )
