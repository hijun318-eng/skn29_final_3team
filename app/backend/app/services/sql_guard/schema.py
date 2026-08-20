"""SQLGlot AST와 승인된 카탈로그 스키마의 대조 및 Trino 식별자 정규화 모듈.

[핵심 목적]
1. FQN 및 컬럼 식별자 표준화: Trino/DataHub의 물리적 테이블 명칭과 컬럼을 정규화된 형태(`catalog.schema.table.column`)로 표준화합니다.
2. 스키마 이탈(Schema Drift) 방지: SQL 쿼리에 사용된 컬럼과 테이블이 DataHub에서 승인된 스키마 범위(`schema_context`)를
   벗어나는지 엄격히 검증하여, 권한 없는 컬럼 접근이나 비인가 테이블 조회를 원천 차단합니다.
3. 비교 연산자 표준화: `a < b`와 `b > a`를 동등한 양방향 비교 증거로 정규화하여 거버넌스 검증에 활용합니다.
"""

from __future__ import annotations

from typing import Any

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from src.ai.sql_policy import SqlValidationResult


def approved_assets(package: Any) -> dict[str, tuple[Any, frozenset[str]]]:
    """ContextPackage 내의 승인 자산 목록을 표준 FQN 및 승인 컬럼 집합의 룩업 맵으로 변환합니다.

    Args:
        package: 런타임 ContextPackage 인스턴스

    Returns:
        dict[표준 FQN, tuple[자산 객체, 승인된 컬럼명 frozenset]]

    Raises:
        ValueError: FQN이 완전 수식되지 않았거나, 중복 자산이 있거나, 컬럼 목록이 비어 있는 경우
    """
    approved: dict[str, tuple[Any, frozenset[str]]] = {}
    for asset in package.assets:
        fqn = canonical_fqn(asset.fqn)
        columns = frozenset(canonical_identifier(item) for item in asset.columns)
        if fqn in approved or not columns:
            raise ValueError("schema_context 내의 자산은 고유하고 컬럼이 비어있지 않아야 합니다.")
        approved[fqn] = (asset, columns)
    return approved


def canonical_fqn(value: object) -> str:
    """FQN(Fully Qualified Name) 문자열을 비교 및 해시에 사용할 수 있는 표준 소문자 형태로 정규화합니다.

    Args:
        value: 'catalog.schema.table' 형태의 문자열 또는 식별자

    Returns:
        정규화된 3단계 FQN 문자열

    Raises:
        ValueError: 3단계(catalog, schema, table)가 온전히 갖춰지지 않은 경우
    """
    table = exp.to_table(str(value))
    if len(table.parts) != 3:
        raise ValueError(f"물리 테이블 FQN은 반드시 3단계(catalog.schema.table)여야 합니다: {value}")
    return ".".join(identifier_node(item) for item in table.parts)


def canonical_identifier(value: object) -> str:
    """컬럼 및 테이블 식별자 문자열을 표준 비교 형태로 정규화합니다.

    Quoted 식별자(큰따옴표로 감싸진 경우)는 대소문자를 보존하고, 일반 식별자는 소문자로 통일합니다.
    """
    text = str(value)
    if text.startswith('"') and text.endswith('"'):
        return text
    return text.casefold()


def identifier_node(value: exp.Expression) -> str:
    """SQLGlot 식별자 노드를 Trino 비교 규칙에 맞는 문자열로 변환합니다."""
    if isinstance(value, exp.Identifier) and value.args.get("quoted"):
        return value.sql(dialect="trino")
    return value.name.casefold()


def declared_assets(plan: dict[str, Any]) -> set[str] | None:
    """모델이 계획(Plan)에서 선언한 자산 FQN 목록을 표준 FQN 집합으로 추출합니다."""
    values = plan.get("declared_assets")
    if values is None:
        references = plan.get("references")
        if not isinstance(references, list):
            return None
        values = [item.get("fqn") for item in references if isinstance(item, dict)]
    if not isinstance(values, (list, tuple)) or any(not isinstance(item, str) for item in values):
        return set()
    try:
        return {canonical_fqn(item) for item in values}
    except ValueError:
        return set()


def declared_metrics(plan: dict[str, Any]) -> set[str] | None:
    """모델이 계획(Plan)에서 선언한 지표 ID 목록을 집합으로 추출합니다."""
    values = plan.get("declared_metrics")
    if values is None:
        return None
    if not isinstance(values, (list, tuple)) or any(not isinstance(item, str) for item in values):
        return set()
    return set(values)


def column_violation(
    result: SqlValidationResult,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> str | None:
    """SQL 쿼리 내의 모든 참조 컬럼이 승인된 스키마 범위 안에 존재하는지 검증합니다.

    Args:
        result: SQLGlot 파싱 및 정적 분석 결과
        assets: 승인된 자산 룩업 맵 (approved_assets)

    Returns:
        위반 설명 메시지 문자열 (모두 승인 범위 내이면 None)
    """
    all_columns = frozenset(column for _, columns in assets.values() for column in columns)
    aliases = {canonical_identifier(item) for item in result.projection_aliases}

    for column in result.columns:
        name = canonical_identifier(column.name)
        if column.source_table is not None:
            asset = assets.get(column.source_table)
            if asset is None or name not in asset[1]:
                return f"컬럼 {column.sql!r} 은(는) 승인된 schema_context 범위 밖입니다."
        elif name not in all_columns and name not in aliases:
            return f"미식별 컬럼 {column.sql!r} 은(는) 승인된 schema_context 범위 밖입니다."
    return None


def source_aliases(result: SqlValidationResult) -> dict[str, str]:
    """SQLGlot AST의 모든 스코프에서 테이블 alias와 표준 FQN의 매핑 사전을 추출합니다."""
    aliases: dict[str, str] = {}
    assert result.expression is not None
    for scope in traverse_scope(result.expression):
        for alias, (node, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table):
                continue
            fqn = ".".join(identifier_node(item) for item in source.parts)
            alias_node = node.args.get("alias")
            if isinstance(alias_node, exp.TableAlias):
                key = identifier_node(alias_node.this)
            else:
                key = canonical_identifier(alias)
            previous = aliases.get(key)
            aliases[key] = "" if previous is not None and previous != fqn else fqn
    return aliases


def comparisons(
    result: SqlValidationResult,
    aliases: dict[str, str],
) -> set[tuple[str, str, str]]:
    """검증된 SQL AST 루트에서 컬럼/파라미터 비교 표현식들을 양방향 (left, op, right) 튜플 집합으로 추출합니다."""
    assert result.expression is not None
    return comparison_evidence(result.expression, aliases, result.physical_tables)


def comparison_evidence(
    expression: exp.Expression,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
) -> set[tuple[str, str, str]]:
    """단일 쿼리 스코프의 비교 AST 노드들을 표준 operand 및 operator 증거 튜플로 변환합니다."""
    values: set[tuple[str, str, str]] = set()
    operators = {
        exp.EQ: "eq",
        exp.NEQ: "neq",
        exp.GT: "gt",
        exp.GTE: "gte",
        exp.LT: "lt",
        exp.LTE: "lte",
    }
    for node in expression.walk(
        prune=lambda item: item is not expression and isinstance(item, exp.Query)
    ):
        operator = next((name for kind, name in operators.items() if isinstance(node, kind)), None)
        if operator is None:
            continue
        left = operand_identity(node.this, aliases, physical_tables)
        right = operand_identity(node.expression, aliases, physical_tables)
        if left and right:
            values.add((left, operator, right))
            values.add((right, reverse_operator(operator), left))
    return values


def operand_identity(
    value: exp.Expression,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
) -> str | None:
    """비교 표현식의 피연산자(Operand)를 'FQN.column' 또는 ':named_param' 형태로 해석합니다."""
    while isinstance(value, (exp.Cast, exp.Paren, exp.FromISO8601Timestamp)):
        value = value.this
    if isinstance(value, exp.Placeholder):
        return f":{value.name}"
    if not isinstance(value, exp.Column):
        return None
    name = identifier_node(value.this)
    qualifier_node = value.args.get("table")
    if qualifier_node is not None:
        source = aliases.get(identifier_node(qualifier_node))
        return f"{source}.{name}" if source else None
    if len(physical_tables) == 1:
        return f"{physical_tables[0]}.{name}"
    return None


def reverse_operator(operator: str) -> str:
    """피연산자 순서가 바뀔 때 비교 연산자의 방향을 대칭적으로 반전합니다 (예: lt <-> gt)."""
    return {"lt": "gt", "lte": "gte", "gt": "lt", "gte": "lte"}.get(operator, operator)


def field_identity(
    value: object,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> str:
    """런타임 필드 표기를 승인된 표준 'FQN.column' 형태로 검증하고 변환합니다."""
    text = str(value)
    matches = [
        fqn
        for fqn, (asset, _) in assets.items()
        if text.startswith(f"{fqn}.") or text.startswith(f"{asset.fqn}.")
    ]
    if not matches:
        raise ValueError(f"필드 {text!r} 은(는) 승인된 schema_context 범위 밖입니다.")
    fqn = max(matches, key=len)
    asset = assets[fqn][0]
    prefix = str(asset.fqn) if text.startswith(f"{asset.fqn}.") else fqn
    column = canonical_identifier(text.removeprefix(f"{prefix}."))
    if column not in assets[fqn][1]:
        raise ValueError(f"필드 {text!r} 은(는) 승인된 schema_context 범위 밖입니다.")
    return f"{fqn}.{column}"
