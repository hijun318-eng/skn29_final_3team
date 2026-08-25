"""Release serving SQL의 namespace와 connector type 경계를 SQLGlot AST로 컴파일한다."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel


_DECIMAL_TYPED_LITERAL = re.compile(
    r"\bDECIMAL\s*'([+-]?(?:\d+(?:\.\d*)?|\.\d+))'",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ViewCoercion:
    """Connector가 표현하지 못하는 View 출력 타입의 명시적 경계 계약."""

    view: tuple[str, str, str]
    column: str
    source_type: str
    target_type: str


def _namespace(value: str) -> tuple[str, str]:
    """catalog.schema 형식의 안전한 namespace를 반환한다."""

    parts = tuple(value.split("."))
    if len(parts) != 2 or any(not part.isidentifier() or not part.islower() for part in parts):
        raise ValueError("namespace must use lowercase catalog.schema identifiers")
    return parts[0], parts[1]


def _qualified_view(value: str) -> tuple[str, str, str]:
    """catalog.schema.view 형식의 안전한 View identity를 반환한다."""

    parts = tuple(value.split("."))
    if len(parts) != 3 or any(
        not part.isidentifier() or not part.islower() for part in parts
    ):
        raise ValueError("view must use lowercase catalog.schema.view identifiers")
    return parts[0], parts[1], parts[2]


def load_coercions(path: Path | None) -> tuple[ViewCoercion, ...]:
    """versioned JSON에서 connector 출력 타입 coercion 계약을 읽는다."""

    if path is None:
        return ()
    document: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("view coercion contract schema_version must be 1")
    raw_rules = document.get("coercions")
    if not isinstance(raw_rules, list):
        raise ValueError("view coercion contract must contain a coercions array")

    rules: list[ViewCoercion] = []
    identities: set[tuple[tuple[str, str, str], str]] = set()
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise ValueError("each view coercion must be an object")
        view = _qualified_view(str(raw.get("view") or ""))
        column = str(raw.get("column") or "")
        source_type = str(raw.get("source_type") or "")
        target_type = str(raw.get("target_type") or "")
        if not column.isidentifier() or not column.islower():
            raise ValueError("coercion column must be a lowercase identifier")
        if not source_type or not target_type:
            raise ValueError("coercion source_type and target_type are required")
        # SQLGlot이 모르는 타입 문자열이 실행 SQL에 그대로 섞이지 않게 여기서 거부한다.
        exp.DataType.build(source_type, dialect="trino")
        exp.DataType.build(target_type, dialect="trino")
        identity = (view, column)
        if identity in identities:
            raise ValueError("duplicate view coercion identity")
        identities.add(identity)
        rules.append(ViewCoercion(view, column, source_type, target_type))
    return tuple(rules)


def _preserve_decimal_typed_literals(text: str) -> str:
    """SQLGlot 직렬화 전에 DECIMAL 리터럴의 precision과 scale을 고정한다."""

    def replace(match: re.Match[str]) -> str:
        value = match.group(1)
        unsigned = value.lstrip("+-")
        integer, dot, fraction = unsigned.partition(".")
        scale = len(fraction) if dot else 0
        integer_digits = len(integer.lstrip("0"))
        precision = max(1, integer_digits + scale)
        return f"CAST('{value}' AS DECIMAL({precision}, {scale}))"

    return _DECIMAL_TYPED_LITERAL.sub(replace, text)


def _view_identity(statement: exp.Expression) -> tuple[str, str, str] | None:
    """CREATE VIEW statement의 원본 fully-qualified identity를 반환한다."""

    if not isinstance(statement, exp.Create) or str(statement.args.get("kind")) != "VIEW":
        return None
    target = statement.this
    if not isinstance(target, exp.Table):
        return None
    catalog = str(target.args.get("catalog") or "")
    database = str(target.args.get("db") or "")
    name = target.name
    if not catalog or not database or not name:
        raise ValueError("release CREATE VIEW target must be fully qualified")
    return catalog, database, name


def _apply_view_coercions(
    statement: exp.Expression, coercions: Iterable[ViewCoercion]
) -> exp.Expression:
    """명시된 View 출력 열만 connector 지원 타입으로 AST cast한다."""

    identity = _view_identity(statement)
    matched = tuple(rule for rule in coercions if rule.view == identity)
    if not matched:
        return statement
    query = statement.expression
    if not isinstance(query, exp.Select):
        raise ValueError("coercion target CREATE VIEW must have a top-level SELECT")

    replacement = statement.copy()
    target_query = replacement.expression
    assert isinstance(target_query, exp.Select)
    expressions = list(target_query.expressions)
    for rule in matched:
        positions = [
            index
            for index, expression in enumerate(expressions)
            if expression.alias_or_name == rule.column
        ]
        if len(positions) != 1:
            raise ValueError(
                f"coercion target {'.'.join(rule.view)}.{rule.column} "
                "must match exactly one SELECT output"
            )
        index = positions[0]
        source_expression = expressions[index]
        if isinstance(source_expression, exp.Alias):
            source_expression = source_expression.this
        expressions[index] = exp.alias_(
            exp.Cast(
                this=source_expression.copy(),
                to=exp.DataType.build(rule.target_type, dialect="trino"),
            ),
            rule.column,
            quoted=False,
        )
    target_query.set("expressions", expressions)
    return replacement


def _rewrite_identifier(
    node: exp.Expression,
    source: tuple[str, str],
    target: tuple[str, str],
) -> exp.Expression:
    """Table·COMMENT column target의 source namespace만 exact 변경한다."""

    if not isinstance(node, (exp.Table, exp.Column)):
        return node
    catalog = str(node.args.get("catalog") or "")
    database = str(node.args.get("db") or "")
    if (catalog, database) != source:
        return node
    replacement = node.copy()
    replacement.set("catalog", exp.to_identifier(target[0]))
    replacement.set("db", exp.to_identifier(target[1]))
    return replacement


def render(
    text: str,
    source_schema: str,
    target_schema: str,
    coercions: Iterable[ViewCoercion] = (),
) -> str:
    """모든 statement를 Trino SQL로 직렬화하고 재파싱 가능한 결과만 반환한다."""

    source = _namespace(source_schema)
    target = _namespace(target_schema)
    statements = tuple(
        statement
        for statement in parse(
            _preserve_decimal_typed_literals(text),
            read="trino",
            error_level=ErrorLevel.RAISE,
        )
        if statement is not None
    )
    if not statements:
        raise ValueError("release SQL contains no statements")
    rendered = ";\n\n".join(
        _apply_view_coercions(statement, coercions)
        .transform(_rewrite_identifier, source, target)
        .sql(
            dialect="trino", pretty=True
        )
        for statement in statements
    ) + ";\n"
    parse(rendered, read="trino", error_level=ErrorLevel.RAISE)
    return rendered


def main() -> int:
    """입력 SQL을 읽고 target namespace SQL을 UTF-8 파일로 기록한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-schema", required=True)
    parser.add_argument("--target-schema", required=True)
    parser.add_argument("--coercions", type=Path)
    args = parser.parse_args()
    output = render(
        args.input.read_text(encoding="utf-8-sig"),
        args.source_schema,
        args.target_schema,
        load_coercions(args.coercions),
    )
    args.output.write_text(output, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
