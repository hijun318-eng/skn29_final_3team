"""결정론적 Pipeline Controller — 기획서 §9.3 처리 흐름.

Router → Node 1 → Context → G1 → SQL 출처 → G2 → (Node 2' → G2') → 실행 → G3 → Node 3 순서로
직렬 실행하며, 각 단계 실패 시 즉시 종료한다. LLM은 self-declare하지 않고 Gate만 합격을 판정한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .gates import gate_g1, gate_g2, gate_g2_prime, gate_g3
from .nodes import node1_normalize, node2_fix, node2_generate_sql, node3_explain
from .trino_executor import execute_trino
from .types import (
    AssetRef,
    ContextPackage,
    MetricRef,
    PipelineResult,
    PipelineState,
    RouteType,
)


def _build_context_stub(
    metrics: list[str],
    role: str,
    as_of: str,
    question: str,
) -> ContextPackage:
    """DataHub 검색·업무 정책 병합 stub."""
    now = datetime.now(timezone.utc).isoformat()
    return ContextPackage(
        context_release="ctx-stub-v1",
        policy_version="sql-policy-stub",
        question=question,
        as_of=as_of or now,
        timezone="Asia/Seoul",
        period_start="2026-07-20T00:00:00+09:00",
        period_end_exclusive="2026-07-27T00:00:00+09:00",
        user_role=role,
        assets=[
            AssetRef(
                urn="urn:li:dataset:stub,analytics.v_breakfast_15m,PROD",
                trino_fqn="analytics.v_breakfast_15m",
                columns=["time_bucket", "wait_p90_min"],
            ),
        ],
        metrics=[
            MetricRef(
                metric_id=m,
                field=f"analytics.v_breakfast_15m.{m}",
                time_field="time_bucket",
            )
            for m in metrics
        ],
        joins=[],
        token_count=500,
        hash="stub-hash-v1",
    )


async def run_pipeline(
    question: str,
    role: str = "OPERATIONS_MANAGER",
    as_of: str = "",
) -> PipelineResult:
    """Guarded Text-to-SQL Pipeline을 결정론적으로 실행한다."""
    rid = str(uuid.uuid4())
    result = PipelineResult(
        request_id=rid,
        state=PipelineState.INIT,
        question=question,
    )

    # 1. Router (stub: 항상 GENERAL 경로)
    result.state = PipelineState.ROUTER
    result.route_type = RouteType.GENERAL

    # 2. Node 1 — 질문 정규화
    result.state = PipelineState.NODE1_NORMALIZE
    normalized = await node1_normalize(question, role, as_of)
    if normalized.is_ambiguous:
        result.state = PipelineState.FAILED
        result.error = normalized.clarify_question or "질문이 모호합니다. 지표와 기간을 명시해 주세요."
        return result

    # 3. Context Build
    result.state = PipelineState.CONTEXT_BUILD
    context = _build_context_stub(normalized.metrics, role, as_of, question)
    result.context = context

    # 4. G1 — Context Gate
    result.state = PipelineState.G1_CONTEXT
    result.g1 = gate_g1(context, role)
    if not result.g1.passed:
        result.state = PipelineState.FAILED
        result.error = result.g1.message
        return result

    # 5. Node 2 — SQL 생성
    result.state = PipelineState.SQL_SOURCE_SELECT
    result.sql = await node2_generate_sql(context)

    # 6. G2 — SQL Policy Gate
    result.state = PipelineState.G2_SQL_POLICY
    result.g2 = gate_g2(result.sql, context)
    if not result.g2.passed:
        # Node 2' — SQL 수정 (1회만 허용)
        result.state = PipelineState.NODE2_FIX
        result.sql = await node2_fix(result.sql, result.g2.error_code, context)

        # G2' — 재검증
        result.state = PipelineState.G2_PRIME
        result.g2 = gate_g2_prime(result.sql, context)
        if not result.g2.passed:
            result.state = PipelineState.FAILED
            result.error = f"SQL 수정 후에도 정책을 통과하지 못했습니다: {result.g2.message}"
            return result

    # 7. 실행 + Result Shaper (Trino 연합 쿼리, 미연결 시 stub fallback)
    result.state = PipelineState.EXECUTE
    result.result = await execute_trino(result.sql.sql)

    # 8. G3 — Result Check
    result.state = PipelineState.G3_RESULT
    result.g3 = gate_g3(result.result)
    if not result.g3.passed:
        result.state = PipelineState.FAILED
        result.error = result.g3.message
        return result

    # 9. Node 3 — 근거 기반 설명
    result.state = PipelineState.NODE3_EXPLAIN
    result.explanation = await node3_explain(result.result, context)

    # 10. artifact 저장 (stub)
    result.state = PipelineState.DONE
    result.artifact_id = str(uuid.uuid4())
    return result
