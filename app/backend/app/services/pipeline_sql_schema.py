"""runtime asset·column을 Trino 식별자로 표준화하고 SQLGlot column·alias·비교 operand와 모델 선언 lineage가 승인 schema 밖으로 벗어나는지 판정한다."""

from __future__ import annotations

from typing import Any

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from src.ai.sql_policy import SqlValidationResult


def approved_assets(package: Any) -> dict[str, tuple[Any, frozenset[str]]]:
    """ContextPackage asset을 표준 FQN과 승인 column 집합의 lookup으로 만든다.

    완전 수식되지 않은 FQN, 중복 asset, 빈 column 계약은 ``ValueError``로 거부해 이후 AST
    해석이 이름 충돌이나 암묵적 schema에 기대지 않도록 한다.
    """
    approved: dict[str, tuple[Any, frozenset[str]]] = {}
    for asset in package.assets:
        fqn = canonical_fqn(asset.fqn)
        columns = frozenset(canonical_identifier(item) for item in asset.columns)
        if fqn in approved or not columns:
            raise ValueError("schema_context assets must be unique and non-empty")
        approved[fqn] = (asset, columns)
    return approved


def canonical_fqn(value: object) -> str:
    """FQN 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다."""
    table = exp.to_table(str(value))
    if len(table.parts) != 3:
        raise ValueError("schema_context physical tables must be fully qualified")
    return ".".join(identifier_node(item) for item in table.parts)


def canonical_identifier(value: object) -> str:
    """identifier 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다."""
    text = str(value)
    if text.startswith('"') and text.endswith('"'):
        return text
    return text.casefold()


def identifier_node(value: exp.Expression) -> str:
    """SQLGlot identifier를 Trino 식별자 비교 규칙에 맞는 문자열로 반환한다.

    quoted identifier는 대소문자와 quoting을 보존하고, 일반 identifier만 case-folding해
    schema context와 AST가 같은 이름을 일관되게 가리키도록 한다.
    """
    if isinstance(value, exp.Identifier) and value.args.get("quoted"):
        return value.sql(dialect="trino")
    return value.name.casefold()


def declared_assets(plan: dict[str, Any]) -> set[str] | None:
    """모델 계획이 선언한 asset lineage를 표준 FQN 집합으로 읽는다.

    명시 선언이 없으면 구조화된 references를 사용하고 둘 다 없으면 ``None``을 반환한다.
    배열 타입이나 FQN이 잘못되면 빈 집합을 반환해 실제 AST lineage와의 비교가 fail-closed 된다.
    """
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
    """모델의 metric lineage 선언을 문자열 집합으로 정규화한다.

    선언 자체가 없으면 선택 사항임을 나타내는 ``None``을 반환하고, malformed 배열은 빈
    집합으로 만들어 runtime metric과 일치했다고 오인하지 않게 한다.
    """
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
    """공유 SQLGlot 분석 결과의 모든 column이 승인 schema 범위 안인지 검사한다.

    수식 column은 해당 source asset에, 비수식 column은 전체 승인 column 또는 projection
    alias에 있어야 한다. 범위 밖 첫 항목의 설명을 반환하고 모두 유효하면 ``None``이다.
    """
    all_columns = frozenset(column for _, columns in assets.values() for column in columns)
    aliases = {canonical_identifier(item) for item in result.projection_aliases}
    for column in result.columns:
        name = canonical_identifier(column.name)
        if column.source_table is not None:
            asset = assets.get(column.source_table)
            if asset is None or name not in asset[1]:
                return f"Column {column.sql!r} is outside schema_context."
        elif name not in all_columns and name not in aliases:
            return f"Unresolved column {column.sql!r} is outside schema_context."
    return None


def source_aliases(result: SqlValidationResult) -> dict[str, str]:
    """모든 SQLGlot scope에서 물리 table alias와 표준 FQN의 대응표를 수집한다.

    같은 alias가 서로 다른 FQN을 가리키면 빈 값으로 표시해 operand 해석이 모호한 source를
    임의 선택하지 못하게 한다. 호출 전 SQL parse 성공이 보장돼야 한다.
    """
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
    """검증된 SQL root에서 column·parameter 비교 근거를 양방향 tuple 집합으로 추출한다.

    parse 실패 결과는 허용하지 않으며 실제 처리는 동일 AST를 받는 ``comparison_evidence``에 위임한다.
    """
    assert result.expression is not None
    return comparison_evidence(result.expression, aliases, result.physical_tables)


def comparison_evidence(
    expression: exp.Expression,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
) -> set[tuple[str, str, str]]:
    """한 query scope의 비교 AST를 표준 operand·operator 증거로 변환한다.

    중첩 query는 별도 scope에서 검증되므로 순회를 멈추고, 양쪽 operand가 확정된 비교만
    정방향과 역방향으로 기록해 join·filter·time 규칙이 같은 근거를 공유하게 한다.
    """
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
    """비교식 operand를 ``FQN.column`` 또는 named parameter 신원으로 해석한다.

    무해한 cast·괄호를 벗기고 alias가 확정된 column만 반환한다. 비수식 column은 물리
    table이 하나일 때만 해석하며 literal·모호한 이름은 ``None``으로 남긴다.
    """
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
    """operand 순서를 바꿀 때 부등호 방향을 뒤집고 대칭 연산자는 그대로 반환한다.

    이 표준화로 ``a < b``와 ``b > a``가 동일한 governed predicate로 비교된다.
    """
    return {"lt": "gt", "lte": "gte", "gt": "lt", "gte": "lte"}.get(operator, operator)


def field_identity(
    value: object,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> str:
    """runtime field 표기를 승인된 표준 ``FQN.column`` 신원으로 검증·변환한다.

    원본 또는 canonical asset prefix 중 가장 긴 일치를 사용해 접두사 충돌을 피하고,
    asset이나 column이 schema context 밖이면 ``ValueError``로 차단한다.
    """
    text = str(value)
    matches = [
        fqn
        for fqn, (asset, _) in assets.items()
        if text.startswith(f"{fqn}.") or text.startswith(f"{asset.fqn}.")
    ]
    if not matches:
        raise ValueError(f"Field {text!r} is outside schema_context")
    fqn = max(matches, key=len)
    asset = assets[fqn][0]
    prefix = str(asset.fqn) if text.startswith(f"{asset.fqn}.") else fqn
    column = canonical_identifier(text.removeprefix(f"{prefix}."))
    if column not in assets[fqn][1]:
        raise ValueError(f"Field {text!r} is outside schema_context")
    return f"{fqn}.{column}"
