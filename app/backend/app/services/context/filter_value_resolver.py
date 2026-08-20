"""Trino 실데이터를 통한 사용자 필터 값의 존재성 및 정확성 확인(Value Resolution) 모듈.

[핵심 목적]
사용자가 발화에서 언급한 필터 값(예: "비스타", "디럭스")을 LLM이 추정한 텍스트 그대로 SQL에 넣지 않고,
서버가 직접 바인딩된 읽기 전용 Trino 쿼리(`SELECT DISTINCT ... WHERE lower(col) = lower(:val) LIMIT 2`)를 실행하여
실제 데이터베이스에 존재하는 고유한 실데이터 값으로 정밀 검증 및 승격(Promote)합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.ports.data_platform import DataPlatformAdapter
from app.query_capability import issue_query_capability
from src.ai.sql_binding import bind_sql_parameters
from src.ai.sql_policy import validate_sql


class FilterValueUnresolvedError(ValueError):
    """사용자가 지목한 값이 실제 데이터베이스에서 정확히 1개로 특정되지 않을 때 발생하는 예외."""


@dataclass(frozen=True)
class ResolvedFilterValue:
    """실제 데이터베이스 조회를 통해 확인된 확정 필터 값 데이터 클래스.

    Attributes:
        asset_fqn: 대상 테이블 FQN
        column: 대상 컬럼명
        operator: 비교 연산자 ('eq' | 'neq')
        value: 실제 DB에 저장된 정확한 대소문자/문자열 값
    """

    asset_fqn: str
    column: str
    operator: str
    value: str


_MAX_DISCOVERED_VALUES = 64


async def discover_dimension_values(
    adapter: DataPlatformAdapter,
    asset_fqn: str,
    column: str,
) -> tuple[str, ...]:
    """승인된 저카디널리티 차원 필드의 실제 값 후보를 제한된 범위로 조회한다.

    의미 기반 BI 도구의 실데이터 값 추천 방식처럼 최대 64개까지만 언어 해석기에
    전달한다. 65번째 값이 확인되면 일부 목록을 전체 후보처럼 오인하지 않도록 빈
    결과를 반환한다.
    """

    sql = (
        f'SELECT DISTINCT "{column}" AS candidate_value '
        f"FROM {asset_fqn} "
        f'WHERE "{column}" IS NOT NULL '
        f"LIMIT {_MAX_DISCOVERED_VALUES + 1}"
    )
    validation = validate_sql(sql)
    validation.raise_for_violations()
    executable_sql = bind_sql_parameters(validation.expression, {})
    scope_hash = sha256(
        f"dimension-value-domain:{asset_fqn}:{column}".encode()
    ).hexdigest()
    gate_token = issue_query_capability(scope_hash, executable_sql)
    submitted = await adapter.execute_query(executable_sql, {}, gate_token)
    query = await adapter.get_query_status(str(submitted["query_id"]))
    rows = query.get("rows")
    if query.get("status") not in {"SUCCEEDED", "PARTIAL"} or not isinstance(rows, list):
        return ()
    values = tuple(
        str(row["candidate_value"])
        for row in rows
        if isinstance(row, dict)
        and row.get("candidate_value") is not None
        and str(row["candidate_value"]).strip()
    )
    if len(values) > _MAX_DISCOVERED_VALUES or len(values) != len(set(values)):
        return ()
    return values


async def resolve_filter_value(
    adapter: DataPlatformAdapter,
    asset_fqn: str,
    column: str,
    operator: str,
    value_text: str,
) -> ResolvedFilterValue:
    """승인된 자산/컬럼에서 value_text와 대소문자 무관 일치하는 단일 실제 값을 조회하여 반환합니다.

    Args:
        adapter: Trino 실행 어댑터
        asset_fqn: 승인된 테이블 FQN
        column: 승인된 컬럼명
        operator: 비교 연산자
        value_text: 사용자가 입력한 필터 텍스트

    Returns:
        DB에서 확인된 ResolvedFilterValue 객체

    Raises:
        FilterValueUnresolvedError: 매칭되는 값이 없거나 2개 이상 모호한 경우
    """
    candidate = value_text.strip()
    if not candidate:
        raise FilterValueUnresolvedError("필터 값 후보가 비어 있습니다.")
    sql = (
        f'SELECT DISTINCT "{column}" AS matched_value '
        f"FROM {asset_fqn} "
        f'WHERE lower(CAST("{column}" AS VARCHAR)) = lower(:candidate_value) '
        "LIMIT 2"
    )
    validation = validate_sql(sql)
    validation.raise_for_violations()
    executable_sql = bind_sql_parameters(
        validation.expression,
        {"candidate_value": {"value_type": "string", "value": candidate}},
    )
    scope_hash = sha256(f"filter-value-check:{asset_fqn}:{column}".encode()).hexdigest()
    gate_token = issue_query_capability(scope_hash, executable_sql)
    submitted = await adapter.execute_query(executable_sql, {}, gate_token)
    query = await adapter.get_query_status(str(submitted["query_id"]))

    if query.get("status") not in {"SUCCEEDED", "PARTIAL"}:
        raise FilterValueUnresolvedError(
            f"{value_text!r} 값을 확인하는 조회가 정상 종료되지 않았습니다."
        )
    rows = query.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise FilterValueUnresolvedError(
            f"{value_text!r} 값이 {asset_fqn}.{column}에서 정확히 하나로 확인되지 않았습니다."
        )
    matched = rows[0].get("matched_value")
    if not isinstance(matched, str) or not matched:
        raise FilterValueUnresolvedError(
            f"{value_text!r} 값이 {asset_fqn}.{column}에서 확인되지 않았습니다."
        )
    return ResolvedFilterValue(asset_fqn=asset_fqn, column=column, operator=operator, value=matched)
