"""POST /internal/v1/query-runs — 대화형 조회 실행.

AIC v2.0 API-AI-003: 질의 계획·SQL·표·차트·설명을 생성한다.
LLM gateway stub의 결정론적 응답과 확정적 차트 데이터를 반환한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §6
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api._envelope import elapsed_ms, error, new_request_id, ok, start_timer
from app.api._internal_ctx import InternalContext

router = APIRouter(prefix="/internal/v1", tags=["query-runs"])


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class QueryRunsRequest(BaseModel):
    """대화형 조회 요청 (AIC §6)."""

    context: InternalContext = Field(..., description="공통 내부 컨텍스트")
    question: str = Field(..., min_length=1, description="사용자 질문")
    dataset_version: str = Field(
        default="gw-synthetic-1.0.0",
        description="데이터셋 버전",
    )


# ---------------------------------------------------------------------------
# 결정론적 응답 생성 (LLM stub 연동)
# ---------------------------------------------------------------------------

# 질문 해시 → 고정 차트 유형 매핑
_CHART_TYPES: tuple[str, ...] = ("line", "bar", "pie", "scatter", "heatmap")


def _deterministic_chart_spec(question: str) -> dict[str, Any]:
    """질문 해시 기반 결정론적 차트 스펙을 생성한다."""
    digest = hashlib.sha256(question.encode()).hexdigest()
    chart_type = _CHART_TYPES[int(digest[:8], 16) % len(_CHART_TYPES)]

    return {
        "type": chart_type,
        "x": "time_bucket",
        "y": "wait_p90_min",
        "title": f"질문 분석: {question[:40]}",
        "palette": "senseplace-v1",
    }


def _deterministic_table(question: str) -> dict[str, Any]:
    """질문 해시 기반 결정론적 테이블 데이터를 생성한다."""
    digest = hashlib.sha256(question.encode()).hexdigest()
    seed = int(digest[:8], 16)

    columns = ["time_bucket", "wait_p90_min", "actual_arrivals", "zone"]
    rows = [
        [
            f"2026-08-{10 + (seed % 7):02d}T{h:02d}:00",
            round(5.0 + (seed % 20) * 0.5, 1),
            50 + (seed % 100),
            "GW_BREAKFAST_DEMO",
        ]
        for h in range(7, 11)
    ]
    return {"columns": columns, "rows": rows}


def _deterministic_sql_preview(question: str) -> str:
    """질문 해시 기반 결정론적 SQL 미리보기를 생성한다."""
    digest = hashlib.sha256(question.encode()).hexdigest()
    grain = "15min" if int(digest[:4], 16) % 2 == 0 else "daily"
    return (
        "SELECT time_bucket, wait_p90_min, actual_arrivals, service_area_id "
        "FROM analytics.v_breakfast_15m "
        f"WHERE service_area_id = 'GW_BREAKFAST_DEMO' "
        f"AND grain = '{grain}' "
        "ORDER BY time_bucket;"
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post("/query-runs")
async def run_query(
    body: QueryRunsRequest,
    request: Request,
) -> dict[str, Any]:
    """대화형 조회를 실행한다.

    LLM gateway stub의 결정론적 설명과 확정적 차트 데이터를 반환한다.
    실제 DB 쿼리는 수행하지 않는다 (read-only DB 연결은 P2).

    결정론적: 동일 질문 → 동일 응답.
    """
    rid = new_request_id()
    start_timer(rid)

    try:
        # LLM gateway stub에서 설명 생성
        llm_text = ""
        provider_name = "stub-v1"
        try:
            from app.llm.gateway import LLMGateway

            gw = LLMGateway()
            provider = gw.get_provider("stub")
            llm_response = await provider.complete(
                prompt=f"질문 분석: {body.question} (dataset: {body.dataset_version})"
            )
            llm_text = llm_response.text
            provider_name = llm_response.model_name
        except Exception:
            llm_text = f"합성 데이터 기반 분석: {body.question}"

        chart_spec = _deterministic_chart_spec(body.question)
        table = _deterministic_table(body.question)
        sql_preview = _deterministic_sql_preview(body.question)

        data = {
            "job_status": "SUCCEEDED",
            "dataset_version": body.dataset_version,
            "query_plan": {
                "intent": "compare_metric",
                "metrics": ["wait_p90_min"],
                "dimensions": ["time_bucket"],
                "period": "last_completed_week",
                "comparison": "previous_4_weeks",
                "filters": {"service_area_id": "GW_BREAKFAST_DEMO"},
            },
            "sql_preview": sql_preview,
            "sql_hash": hashlib.sha256(sql_preview.encode()).hexdigest(),
            "table": table,
            "chart_spec": chart_spec,
            "explanation": llm_text,
            "evidence": [],
            "limitations": [
                "합성 데이터 기반 조회",
                "실제 DB 미연결 (read-only adapter P2)",
            ],
            "period": {
                "start": "2026-08-10T00:00:00Z",
                "end": "2026-08-16T23:59:59Z",
            },
            "unit": "minutes",
            "sample_size": len(table["rows"]),
            "timezone": "Asia/Seoul",
            "data_cutoff": "2026-08-16T14:59:59Z",
            "model_version": provider_name,
        }
        return ok(data, rid)

    except Exception as exc:
        return error(
            code="INTERNAL_ERROR",
            message=f"대화형 조회 실행 중 오류: {exc}",
            request_id=rid,
            status_code=500,
        )
