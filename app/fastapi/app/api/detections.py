"""POST /internal/v1/detections — versioned rule 감지 실행.

AIC v2.0 API-AI-002: KPI와 메트릭 기반 이상 감지를 실행한다.
src/analysis/detection의 순수 함수를 호출하여 결정론적 결과를 반환한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §9
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api._envelope import elapsed_ms, error, new_request_id, ok, start_timer
from app.api._internal_ctx import InternalContext

router = APIRouter(prefix="/internal/v1", tags=["detections"])


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class DetectionsRequest(BaseModel):
    """이상 감지 실행 요청 (AIC §9)."""

    context: InternalContext = Field(..., description="공통 내부 컨텍스트")
    dataset_version: str = Field(
        default="gw-synthetic-1.0.0",
        description="데이터셋 버전",
    )
    rule_version: str = Field(
        default="rule-v1",
        description="감지 규칙 버전",
    )
    kpis: dict[str, Any] = Field(
        default_factory=dict,
        description="KPI 딕셔너리 (metrics.calculate_kpis 출력)",
    )
    zone_voc_counts: dict[str, int] | None = Field(
        default=None,
        description="구역별 VOC 건수",
    )
    baseline_zone_avg: float = Field(
        default=0.0,
        description="구역별 기준 평균 VOC 건수",
    )
    breakfast_15m_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="15분 조식 레코드 리스트",
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post("/detections")
async def run_detections(
    body: DetectionsRequest,
    request: Request,
) -> dict[str, Any]:
    """versioned rule 기반 이상 감지를 실행한다.

    결정론적: 동일 입력 → 동일 출력.
    """
    rid = new_request_id()
    start_timer(rid)

    try:
        from src.analysis.detection import detect_anomalies

        anomalies = detect_anomalies(
            kpis=body.kpis,
            zone_voc_counts=body.zone_voc_counts,
            baseline_zone_avg=body.baseline_zone_avg,
            breakfast_15m_items=body.breakfast_15m_items,
        )

        results = [
            {
                "rule_id": a.rule_id,
                "rule_version": body.rule_version,
                "calibration_label": "PROJECT_CALIBRATION",
                "triggered": True,
                "severity": a.severity,
                "message": a.message,
                "details": a.details,
                "evidence_ids": [],
            }
            for a in anomalies
        ]

        data = {
            "job_status": "SUCCEEDED",
            "dataset_version": body.dataset_version,
            "rule_version": body.rule_version,
            "anomaly_count": len(results),
            "anomalies": results,
            "limitations": [],
        }
        return ok(data, rid)

    except Exception as exc:
        return error(
            code="INTERNAL_ERROR",
            message=f"이상 감지 실행 중 오류: {exc}",
            request_id=rid,
            status_code=500,
        )
