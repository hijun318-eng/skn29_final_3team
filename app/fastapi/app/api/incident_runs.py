"""POST /internal/v1/incident-runs — 근거 조사 실행.

AIC v2.0 API-AI-004: 감지 결과를 evidence 구조로 변환하고
LLM gateway stub의 결정론적 브리프를 생성한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §10
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api._envelope import elapsed_ms, error, new_request_id, ok, start_timer
from app.api._internal_ctx import InternalContext

router = APIRouter(prefix="/internal/v1", tags=["incident-runs"])


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class IncidentRunsRequest(BaseModel):
    """근거 조사 요청 (AIC §10)."""

    context: InternalContext = Field(..., description="공통 내부 컨텍스트")
    analysis_run_id: str = Field(
        default="",
        description="분석 실행 식별자",
    )
    dataset_version: str = Field(
        default="gw-synthetic-1.0.0",
        description="데이터셋 버전",
    )
    detection_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="감지 요약 정보",
    )
    anomalies: list[dict[str, Any]] = Field(
        default_factory=list,
        description="감지된 이상 목록 (detection 결과)",
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post("/incident-runs")
async def run_incident(
    body: IncidentRunsRequest,
    request: Request,
) -> dict[str, Any]:
    """근거 조사를 실행한다.

    감지 결과를 evidence 구조로 변환하고, LLM stub으로 브리프를 생성한다.
    결정론적: 동일 입력 → 동일 출력.
    """
    rid = new_request_id()
    start_timer(rid)

    try:
        from src.analysis.evidence import build_evidence

        # evidence 구축
        analysis_id = body.analysis_run_id or rid
        bundle = build_evidence(
            analysis_run_id=analysis_id,
            anomalies=body.anomalies,
        )

        # LLM stub으로 브리프 생성
        brief_text = ""
        model_version = "stub-v1"
        try:
            from app.llm.gateway import LLMGateway

            gw = LLMGateway()
            provider = gw.get_provider("stub")
            evidence_summary = bundle.summary
            llm_response = await provider.complete(
                prompt=(
                    f"이슈 브리프 작성: {analysis_id}, "
                    f"근거 {len(bundle.evidence_ids)}건, "
                    f"{evidence_summary}"
                )
            )
            brief_text = llm_response.text
            model_version = llm_response.model_name
        except Exception:
            brief_text = (
                f"근거 {len(bundle.evidence_ids)}건 기반 이슈 브리프. "
                f"{bundle.summary}"
            )

        # evidence records를 dict로 변환
        evidence_records = [
            {
                "evidence_id": r.evidence_id,
                "evidence_type": r.evidence_type,
                "source_table": r.source_table,
                "source_key": r.source_key,
                "metric_code": r.metric_code,
                "observed_window": r.observed_window,
                "comparison_window": r.comparison_window,
                "value": r.value,
                "unit": r.unit,
                "sample_size": r.sample_size,
                "is_counter_evidence": r.is_counter_evidence,
                "limitations": r.limitations,
            }
            for r in bundle.records
        ]

        data = {
            "analysis_run_id": analysis_id,
            "job_status": "SUCCEEDED",
            "incident_status": "READY_FOR_REVIEW",
            "detection_summary": body.detection_summary,
            "observed_facts": [
                r.metric_code for r in bundle.records
            ],
            "cause_candidates": [],
            "supporting_evidence": evidence_records,
            "counter_evidence": [],
            "missing_data": [],
            "recommended_checks": [],
            "response_options": [],
            "limitations": [
                "합성 데이터 기반 분석",
                "실제 원인 확정 불가 (AIC §10 AI 금지 항목 준수)",
            ],
            "evidence_ids": list(bundle.evidence_ids),
            "report_draft": {
                "brief": brief_text,
                "model_version": model_version,
            },
            "model_version": model_version,
            "prompt_version": "stub-v1",
            "analysis_version": "analysis-v1",
        }
        return ok(data, rid)

    except Exception as exc:
        return error(
            code="INTERNAL_ERROR",
            message=f"근거 조사 실행 중 오류: {exc}",
            request_id=rid,
            status_code=500,
        )
