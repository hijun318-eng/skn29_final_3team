"""Node 1/2/2'/3 — 기획서 §10.2 역할 분리 LLM Node.

각 Node는 stub로 동작하며, 실제 LLM 연동은 RunPod vLLM 도입 후 교체된다.
Node 1은 질문 정규화, Node 2/2'는 SQL 생성·수정, Node 3은 근거 설명을 담당한다.
권한·합격 판정·실행·수치 계산은 LLM이 아닌 결정론적 계층이 담당한다.
"""

from __future__ import annotations

import hashlib

from .types import ContextPackage, ExplanationResult, GeneratedSQL, NormalizedQuestion, ShapedResult

# ---------------------------------------------------------------------------
# Node 1 — 질문 정규화
# ---------------------------------------------------------------------------


async def node1_normalize(question: str, role: str, as_of: str) -> NormalizedQuestion:
    """사용자 질문을 지표·기간·검색어로 구조화한다.

    stub: 키워드 매칭으로 의도를 추정한다.
    실제 구현에서는 RunPod vLLM Base 모델이 담당한다.
    """
    q_lower = question.lower()

    # 지표 추출 (stub)
    metrics: list[str] = []
    if any(w in q_lower for w in ["대기", "wait", "대기시간"]):
        metrics.append("wait_p90_min")
    if any(w in q_lower for w in ["매출", "revenue", "객실매출"]):
        metrics.append("room_revenue")
    if any(w in q_lower for w in ["voc", "고객", "불만"]):
        metrics.append("voc_count")
    if not metrics:
        metrics = ["wait_p90_min"]

    # 기간 추출 (stub)
    period = "last_completed_week"
    if "이번 달" in question or "this month" in q_lower:
        period = "month_to_date"
    elif "지난달" in question or "last month" in q_lower:
        period = "last_month"

    return NormalizedQuestion(
        intent="compare_metric",
        metrics=metrics,
        dimensions=["time_bucket"],
        period=period,
        search_terms=[question[:30]],
        is_ambiguous=len(metrics) == 0,
        clarify_question="어떤 지표를 분석할까요?" if len(metrics) == 0 else "",
    )


# ---------------------------------------------------------------------------
# Node 2 — SQL 생성
# ---------------------------------------------------------------------------


async def node2_generate_sql(context: ContextPackage) -> GeneratedSQL:
    """Context Package 기반 Trino SQL을 생성한다.

    stub: 컨텍스트의 첫 번째 자산·지표를 사용해 기본 SELECT를 만든다.
    실제 구현에서는 RunPod vLLM SQL LoRA adapter가 담당한다.
    """
    asset = context.assets[0] if context.assets else None
    metric = context.metrics[0] if context.metrics else None

    table = asset.trino_fqn if asset else "analytics.v_breakfast_15m"
    metric_field = metric.field if metric and metric.field else "wait_p90_min"
    time_field = metric.time_field if metric and metric.time_field else "time_bucket"

    sql = (
        f"SELECT {time_field}, {metric_field} "
        f"FROM {table} "
        f"WHERE {time_field} >= TIMESTAMP '{context.period_start}' "
        f"AND {time_field} < TIMESTAMP '{context.period_end_exclusive}' "
        f"ORDER BY {time_field} LIMIT 100;"
    )

    return GeneratedSQL(
        sql=sql,
        sql_hash=hashlib.sha256(sql.encode()).hexdigest(),
        source="node2",
    )


# ---------------------------------------------------------------------------
# Node 2' — SQL 수정 (G2 실패 시 1회)
# ---------------------------------------------------------------------------


async def node2_fix(
    failed_sql: GeneratedSQL,
    g2_error: str,
    context: ContextPackage,
) -> GeneratedSQL:
    """G2 거절 SQL을 승인 범위 안에서 1회 수정한다.

    stub: error_code에 따라 LIMIT 추가 또는 쓰기 구문 제거.
    기획서: 반복 self-repair 금지, 1회만 허용.
    """
    sql = failed_sql.sql

    if "NO_LIMIT" in g2_error:
        if "LIMIT" not in sql.upper():
            sql = sql.rstrip(";") + " LIMIT 100;"
    elif "WRITE_BLOCKED" in g2_error:
        # 쓰기 구문을 SELECT로 강제 (stub)
        sql = f"SELECT 1 LIMIT 1;"

    return GeneratedSQL(
        sql=sql,
        sql_hash=hashlib.sha256(sql.encode()).hexdigest(),
        source="node2prime",
    )


# ---------------------------------------------------------------------------
# Node 3 — 근거 기반 설명
# ---------------------------------------------------------------------------


async def node3_explain(
    result: ShapedResult,
    context: ContextPackage,
) -> ExplanationResult:
    """검증된 shaped result를 LLM으로 설명한다 (G3 통과 결과만).

    LLM Gateway의 기본 provider(stub/ollama/openai)를 사용한다.
    Node 2의 추론 과정은 전달받지 않는다 (기획서 §10.2).
    LLM 실패 시 결정론적 fallback 설명을 반환한다.
    """
    metric_names = ", ".join(m.metric_id for m in context.metrics) or "지표"

    try:
        from app.llm.gateway import LLMGateway

        gw = LLMGateway()
        provider = gw.get_provider()
        prompt = (
            f"다음 호텔 운영 데이터 분석 결과를 한국어로 간략히 설명하세요.\n"
            f"기간: {context.period_start} ~ {context.period_end_exclusive}\n"
            f"지표: {metric_names}\n"
            f"데이터 건수: {result.row_count}건\n"
            f"샘플 데이터: {result.rows[:3]}"
        )
        llm_response = await provider.complete(prompt)
        return ExplanationResult(
            explanation=llm_response.text,
            evidence_summary=f"자산 {len(context.assets)}개, JOIN {len(context.joins)}개 사용",
            limitations=["관리자 검토 필요"],
            model_version=llm_response.model_name,
        )
    except Exception:
        return ExplanationResult(
            explanation=(
                f"{context.period_start} ~ {context.period_end_exclusive} 기간의 "
                f"{metric_names} 분석 결과 {result.row_count}건을 확인했습니다."
            ),
            evidence_summary=f"자산 {len(context.assets)}개 사용",
            limitations=["LLM 미연결 (fallback)", "관리자 검토 필요"],
            model_version="fallback-v1",
        )
