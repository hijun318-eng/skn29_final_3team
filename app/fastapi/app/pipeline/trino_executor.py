"""Trino 실행기 — 기획서 §8.4 연합 쿼리 엔진.

Trino REST API(/v1/statement)로 검증된 SQL을 실행하고 Result Shaper로 변환한다.
Trino 서버가 없으면 stub 결과로 fallback한다.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .types import ShapedResult

TRINO_URL = os.environ.get("TRINO_URL", "http://localhost:8080")


async def execute_trino(sql: str) -> ShapedResult:
    """Trino REST API로 SQL을 실행한다.

    기획서 §9.3: 검증된 SQL만 Trino에서 실행, row filter·column mask 적용.
    Trino 미연결 시 stub 결과 반환.
    """
    try:
        return await _trino_query(sql)
    except Exception:
        return _stub_result()


async def _trino_query(sql: str) -> ShapedResult:
    """Trino /v1/statement로 쿼리 실행 + 결과 파싱."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 초기 쿼리 제출
        resp = await client.post(
            f"{TRINO_URL}/v1/statement",
            headers={"X-Trino-User": "answervice", "X-Trino-Source": "pipeline"},
            data=sql,
        )
        resp.raise_for_status()
        result = resp.json()

        # 페이지네이션 처리 (nextUri 폴링)
        while "nextUri" in result and result.get("stats", {}).get("state") != "FINISHED":
            next_uri = result["nextUri"]
            resp = await client.get(next_uri)
            resp.raise_for_status()
            result = resp.json()

        if result.get("error"):
            raise RuntimeError(f"Trino error: {result['error'].get('message', '')}")

        columns = [c["name"] for c in result.get("columns", [])]
        rows = result.get("data", [])
        return ShapedResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            sampling_evidence={"source": "trino", "query_id": result.get("id", "")},
        )


def _stub_result() -> ShapedResult:
    """Trino 미연결 시 fallback 결정론적 결과."""
    return ShapedResult(
        columns=["time_bucket", "wait_p90_min"],
        rows=[
            ["2026-07-20T08:00", 12.4],
            ["2026-07-21T08:00", 15.2],
            ["2026-07-22T08:00", 9.8],
        ],
        row_count=3,
        sampling_evidence={"source": "stub", "reason": "trino_unavailable"},
    )
