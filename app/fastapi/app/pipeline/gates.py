"""Gate G1/G2/G3 — 기획서 §9.5 검증 순서.

G1: Context Gate (역할·권한·context_release·as_of)
G2: SQL Policy Gate (AST·read-only·JOIN·LIMIT)
G3: Result Check (schema·mask·범위·이상치)
"""

from __future__ import annotations

import re

from .types import ContextPackage, GeneratedSQL, GateResult, ShapedResult

_WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE")


def gate_g1(context: ContextPackage, role: str) -> GateResult:
    """G1 Context Gate — 컨텍스트 유효성 검증."""
    if not context.assets:
        return GateResult(
            passed=False, gate="G1",
            error_code="NO_ASSETS",
            message="컨텍스트에 승인된 자산이 없습니다.",
        )
    if not context.as_of:
        return GateResult(
            passed=False, gate="G1",
            error_code="NO_AS_OF",
            message="기준 시각(as_of)이 확정되지 않았습니다.",
        )
    if not context.metrics:
        return GateResult(
            passed=False, gate="G1",
            error_code="NO_METRICS",
            message="승인된 지표가 없습니다.",
        )
    return GateResult(passed=True, gate="G1")


def gate_g2(sql: GeneratedSQL, context: ContextPackage) -> GateResult:
    """G2 SQL Policy Gate — SQL 정책 검증 (SQLGlot AST stub)."""
    sql_upper = sql.sql.upper()

    # 1. 쓰기 SQL 차단
    for kw in _WRITE_KEYWORDS:
        if re.search(rf"\b{kw}\b", sql_upper):
            return GateResult(
                passed=False, gate="G2",
                error_code="WRITE_BLOCKED",
                message=f"{kw} 구문은 차단됩니다. 읽기 전용만 허용됩니다.",
            )

    # 2. LIMIT 필수
    if "LIMIT" not in sql_upper:
        return GateResult(
            passed=False, gate="G2",
            error_code="NO_LIMIT",
            message="hard LIMIT이 필요합니다. 결과 행 수 상한을 초과할 수 없습니다.",
        )

    # 3. system catalog 차단
    if "SYSTEM." in sql_upper or "INFORMATION_SCHEMA" in sql_upper:
        return GateResult(
            passed=False, gate="G2",
            error_code="SYSTEM_CATALOG_BLOCKED",
            message="system catalog 접근은 차단됩니다.",
        )

    return GateResult(passed=True, gate="G2")


def gate_g2_prime(sql: GeneratedSQL, context: ContextPackage) -> GateResult:
    """G2' — Node 2' 수정 후 재검증 (G2와 동일 로직)."""
    return gate_g2(sql, context)


def gate_g3(result: ShapedResult) -> GateResult:
    """G3 Result Check — 결과 증적 검증."""
    if result.row_count == 0:
        return GateResult(
            passed=False, gate="G3",
            error_code="EMPTY_RESULT",
            message="결과가 비어 있습니다. 데이터 범위를 확인하세요.",
        )
    if not result.columns:
        return GateResult(
            passed=False, gate="G3",
            error_code="NO_SCHEMA",
            message="결과 schema 증적이 없습니다.",
        )
    return GateResult(passed=True, gate="G3")
