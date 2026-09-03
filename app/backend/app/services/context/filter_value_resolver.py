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


async def _execute_auxiliary_query(
    adapter: DataPlatformAdapter,
    sql: str,
    gate_token: str,
) -> dict[str, object]:
    """제품 adapter에서는 본 분석 lifecycle과 분리하고 단순 test double은 호환한다."""

    execute = getattr(adapter, "execute_auxiliary_query", None)
    if not callable(execute):
        execute = adapter.execute_query
    return await execute(sql, {}, gate_token)


async def discover_dimension_values(
    adapter: DataPlatformAdapter,
    asset_fqn: str,
    column: str,
) -> tuple[str, ...]:
    """[책임] 저카디널리티 차원 컬럼에 대해 실제 DB에 존재하는 고유 값 후보를 안전하게 조회한다.
    - 입출력: DataPlatformAdapter, asset_fqn, column 수신 → 최대 64개의 고유 문자열 값 튜플 반환
    - 주의조건: 카디널리티 한도(64개) 초과 시 부분 추천으로 인한 왜곡을 방지하기 위해 빈 튜플 반환
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
    submitted = await _execute_auxiliary_query(adapter, executable_sql, gate_token)
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
    """[책임] 사용자가 입력한 필터 텍스트를 실제 DB 값과 대소문자 무관 대조하여 정확한 단일 값으로 바인딩한다.
    - 입출력: 어댑터, 테이블 FQN, 컬럼, 연산자, 사용자 입력 텍스트 수신 → 확정된 ResolvedFilterValue 반환
    - 주의조건: 일치하는 값이 없거나 2개 이상 모호하게 매칭되는 경우 FilterValueUnresolvedError 발생
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
    submitted = await _execute_auxiliary_query(adapter, executable_sql, gate_token)
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
