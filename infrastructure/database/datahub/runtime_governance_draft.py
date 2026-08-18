"""Trino serving SQL의 구조적 근거만으로 비권위 runtime governance 검토안을 만든다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import sqlglot
from sqlglot import exp


REVIEW_BLOCKERS = (
    "이벤트 발생량 연결 기준",
    "객실·식음·연회·시설 통합 매출의 세금·봉사료·인식 기준",
    "VOC 데이터의 학습·평가 사용 적합성",
    "연회 취소 수수료와 환입의 인식 기준",
)


@dataclass(frozen=True)
class FieldEvidence:
    """한 출력 필드의 SQL 식·참조 컬럼·구조적 역할을 승인 전 근거로 보존한다."""

    name: str
    description: str
    expression_sql: str
    source_columns: tuple[str, ...]
    structural_role: str
    review_flags: tuple[str, ...]


@dataclass(frozen=True)
class ViewEvidence:
    """한 serving view의 source 관계·grain 후보·출력 근거를 묶는다."""

    fqn: str
    description: str
    source_file: str
    source_relations: tuple[str, ...]
    grain_candidates: tuple[str, ...]
    fields: tuple[FieldEvidence, ...]


@dataclass(frozen=True)
class GovernanceDraft:
    """DataHub에 쓰기 전 사람의 결정을 요구하는 release 단위 검토 증거를 표현한다."""

    release_version: str
    serving_schema: str
    source_sha256: str
    views: tuple[ViewEvidence, ...]


def build_draft(
    sql_directory: Path,
    serving_schema: str,
    release_version: str,
) -> GovernanceDraft:
    """Trino SQL 전체를 파싱하고 주석이 완전한 serving view만 DRAFT에 포함한다."""

    directory = sql_directory.resolve()
    if not directory.is_dir():
        raise ValueError("serving SQL directory is unavailable")
    schema = _qualified_schema(serving_schema)
    version = _required_text(release_version, "release version")
    paths = tuple(sorted(directory.glob("*.sql")))
    if not paths:
        raise ValueError("serving SQL directory contains no SQL files")

    creates: dict[str, tuple[exp.Create, Path]] = {}
    view_comments: dict[str, str] = {}
    column_comments: dict[tuple[str, str], str] = {}
    digest = hashlib.sha256()
    for path in paths:
        content = path.read_text(encoding="utf-8")
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")
        try:
            statements = sqlglot.parse(content, read="trino")
        except sqlglot.errors.ParseError as error:
            raise ValueError(f"serving SQL is not parseable: {path.name}") from error
        for statement in statements:
            if isinstance(statement, exp.Create) and _is_view(statement):
                target = statement.this.sql(dialect="trino")
                if target.startswith(f"{schema}."):
                    if target in creates:
                        raise ValueError(f"serving view is defined more than once: {target}")
                    creates[target] = (statement, path)
            elif isinstance(statement, exp.Comment):
                _collect_comment(statement, schema, view_comments, column_comments)
    if not creates:
        raise ValueError("no serving views were found for the requested schema")

    views = tuple(
        _view_evidence(target, statement, path, view_comments, column_comments)
        for target, (statement, path) in sorted(creates.items())
    )
    return GovernanceDraft(version, schema, digest.hexdigest(), views)


def render_markdown(draft: GovernanceDraft) -> str:
    """승인 상태를 만들지 않는 결정론적 Markdown 검토 문서를 반환한다."""

    fields = [field for view in draft.views for field in view.fields]
    role_counts = {
        role: sum(field.structural_role == role for field in fields)
        for role in sorted({field.structural_role for field in fields})
    }
    lines = [
        "# Runtime governance 승인 검토안",
        "",
        "> **DRAFT / DATAHUB 발행 금지 / 승인 전 비권위 자료**",
        "> 이 문서는 SQL AST와 SQL `COMMENT ON`만으로 구조적 근거를 정리한다. "
        "metric 의미·별칭·단위·집계·권한을 자동 승인하지 않는다.",
        "",
        "## 생성 근거",
        "",
        f"- catalog release: `{draft.release_version}`",
        f"- serving schema: `{draft.serving_schema}`",
        f"- SQL source SHA-256: `{draft.source_sha256}`",
        f"- view: {len(draft.views)}개",
        f"- 출력 필드: {len(fields)}개",
        "- 구조 분류: "
        + ", ".join(f"`{role}` {count}개" for role, count in role_counts.items()),
        "- 상태: 모든 항목 `REVIEW_REQUIRED`; 승인 metadata 발행 0건",
        "",
        "## 릴리스 문서가 명시한 선결 결정",
        "",
    ]
    lines.extend(f"- [ ] {item}" for item in REVIEW_BLOCKERS)
    lines.extend(
        [
            "",
            "위 네 항목은 release의 `데이터_구조_요약.md`와 `품질_보고서.md`가 "
            "후속 승인을 요구한다. 이 문서는 해당 결정을 대신하지 않는다.",
            "",
            "## 승인자가 view마다 확정할 계약",
            "",
            "- 업무 metric ID·표시명·별칭·단위와 소유자",
            "- 원본 grain, 허용 dimension, 기준 time field와 timezone",
            "- 기본 aggregation과 상위 grain reduction; 비율의 분자·분모·0 처리",
            "- 필수 filter, 허용 join edge, synthetic 데이터 표시 방식",
            "- 조회 가능한 role·domain과 최소/최대 query 기간·행 수",
            "- pass-through 값이 upstream pre-aggregation을 보존하는지 여부",
            "",
            "## 구조적 근거",
        ]
    )
    for view in draft.views:
        lines.extend(_render_view(view))
    lines.extend(
        [
            "",
            "## 승인 기록란",
            "",
            "- 승인 release/version:",
            "- 승인 주체와 역할:",
            "- 승인 시각:",
            "- 승인된 view/field 목록:",
            "- 보류 또는 거절 목록과 사유:",
            "- DataHub read-back 검증 결과:",
            "",
            "승인 전에는 이 문서를 runtime governance bundle이나 DataHub custom property로 변환하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)


def _view_evidence(
    target: str,
    statement: exp.Create,
    path: Path,
    view_comments: dict[str, str],
    column_comments: dict[tuple[str, str], str],
) -> ViewEvidence:
    query = statement.expression
    if not isinstance(query, exp.Query) or not query.selects:
        raise ValueError(f"serving view has no projected fields: {target}")
    description = view_comments.get(target)
    if not description:
        raise ValueError(f"serving view description is missing: {target}")
    grouped = _grouped_indexes(query)
    sources = _source_relations(query)
    fields = []
    names: set[str] = set()
    for index, selection in enumerate(query.selects):
        name = selection.alias_or_name
        if not name or name in names:
            raise ValueError(f"serving view output names are missing or duplicate: {target}")
        names.add(name)
        description = column_comments.get((target, name))
        if not description:
            raise ValueError(f"serving field description is missing: {target}.{name}")
        expression = selection.this if isinstance(selection, exp.Alias) else selection
        role = _structural_role(expression, index in grouped)
        fields.append(
            FieldEvidence(
                name=name,
                description=description,
                expression_sql=expression.sql(dialect="trino"),
                source_columns=tuple(
                    sorted({column.sql(dialect="trino") for column in expression.find_all(exp.Column)})
                ),
                structural_role=role,
                review_flags=_review_flags(expression, role, sources),
            )
        )
    return ViewEvidence(
        fqn=target,
        description=view_comments[target],
        source_file=path.name,
        source_relations=sources,
        grain_candidates=tuple(field.name for field in fields if field.structural_role == "GROUPING_KEY"),
        fields=tuple(fields),
    )


def _structural_role(expression: exp.Expression, grouped: bool) -> str:
    if grouped:
        return "GROUPING_KEY"
    has_aggregate = any(True for _ in expression.find_all(exp.AggFunc))
    has_arithmetic = any(
        True for _ in expression.find_all((exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod))
    )
    if has_aggregate and has_arithmetic:
        return "AGGREGATED_DERIVATION"
    if has_aggregate:
        return "AGGREGATE"
    if has_arithmetic or expression.find(exp.Case) is not None:
        return "DERIVED_EXPRESSION"
    if isinstance(expression, exp.Column):
        return "PASS_THROUGH"
    return "PASS_THROUGH_TRANSFORM"


def _review_flags(
    expression: exp.Expression,
    role: str,
    source_relations: tuple[str, ...],
) -> tuple[str, ...]:
    flags = {"BUSINESS_APPROVAL_REQUIRED"}
    if role == "GROUPING_KEY":
        flags.add("DIMENSION_AND_GRAIN_REQUIRED")
    elif role == "AGGREGATE":
        flags.add("AGGREGATION_AND_REDUCTION_REQUIRED")
    elif role in {"AGGREGATED_DERIVATION", "DERIVED_EXPRESSION"}:
        flags.add("NON_ADDITIVE_REDUCTION_REQUIRED")
    else:
        flags.add("UPSTREAM_SEMANTICS_REQUIRED")
    if expression.find(exp.Div) is not None:
        flags.add("DENOMINATOR_AND_ZERO_POLICY_REQUIRED")
    if expression.find(exp.Avg) is not None:
        flags.add("WEIGHTING_POLICY_REQUIRED")
    if expression.find(exp.Max) is not None or expression.find(exp.Min) is not None:
        flags.add("ROLLUP_POLICY_REQUIRED")
    if any(relation.startswith("serving.") for relation in source_relations):
        flags.add("PREAGGREGATED_SOURCE_REVIEW_REQUIRED")
    return tuple(sorted(flags))


def _grouped_indexes(query: exp.Query) -> set[int]:
    group = query.args.get("group")
    if not isinstance(group, exp.Group):
        return set()
    indexes: set[int] = set()
    selections = tuple(query.selects)
    for item in group.expressions:
        if isinstance(item, exp.Literal) and not item.is_string:
            position = int(item.this) - 1
            if position < 0 or position >= len(selections):
                raise ValueError("GROUP BY position is outside the select list")
            indexes.add(position)
            continue
        group_sql = item.sql(dialect="trino")
        matches = [
            index
            for index, selection in enumerate(selections)
            if (selection.this if isinstance(selection, exp.Alias) else selection).sql(dialect="trino")
            == group_sql
        ]
        if len(matches) != 1:
            raise ValueError("GROUP BY expression does not resolve to one output field")
        indexes.add(matches[0])
    return indexes


def _source_relations(query: exp.Query) -> tuple[str, ...]:
    aliases = {cte.alias_or_name for cte in query.find_all(exp.CTE)}
    relations = {
        ".".join(part for part in (table.catalog, table.db, table.name) if part)
        for table in query.find_all(exp.Table)
        if table.name not in aliases
    }
    if not relations or any(relation.count(".") != 2 for relation in relations):
        raise ValueError("every serving source relation must be fully qualified")
    return tuple(sorted(relations))


def _collect_comment(
    statement: exp.Comment,
    serving_schema: str,
    view_comments: dict[str, str],
    column_comments: dict[tuple[str, str], str],
) -> None:
    value = statement.expression
    if not isinstance(value, exp.Literal) or not value.is_string or not value.this.strip():
        raise ValueError("serving COMMENT must contain non-empty text")
    kind = str(statement.args.get("kind", "")).upper()
    if kind == "VIEW" and isinstance(statement.this, exp.Table):
        target = statement.this.sql(dialect="trino")
        if target.startswith(f"{serving_schema}."):
            view_comments[target] = value.this.strip()
    elif kind == "COLUMN" and isinstance(statement.this, exp.Column):
        column = statement.this
        target = ".".join((column.catalog, column.db, column.table))
        if target.startswith(f"{serving_schema}."):
            column_comments[(target, column.name)] = value.this.strip()


def _render_view(view: ViewEvidence) -> list[str]:
    lines = [
        "",
        f"### `{view.fqn}`",
        "",
        f"- 설명: {_escape(view.description)}",
        f"- SQL: `{view.source_file}`",
        "- 직접 upstream: " + ", ".join(f"`{source}`" for source in view.source_relations),
        "- grain 후보: "
        + (", ".join(f"`{name}`" for name in view.grain_candidates) or "없음 — 승인자가 명시해야 함"),
        "",
        "| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |",
        "|---|---|---|---|---|---|",
    ]
    for field in view.fields:
        columns = ", ".join(f"`{column}`" for column in field.source_columns) or "없음"
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{field.name}`",
                    f"`{field.structural_role}`",
                    f"`{_escape(field.expression_sql)}`",
                    columns,
                    _escape(field.description),
                    ", ".join(f"`{flag}`" for flag in field.review_flags),
                )
            )
            + " |"
        )
    return lines


def _is_view(statement: exp.Create) -> bool:
    return str(statement.args.get("kind", "")).upper() == "VIEW"


def _qualified_schema(value: str) -> str:
    parts = value.strip().split(".") if isinstance(value, str) else []
    if len(parts) != 2 or any(not part.isidentifier() for part in parts):
        raise ValueError("serving schema must be a catalog.schema identifier")
    return ".".join(parts)


def _required_text(value: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError(f"{context} must be non-empty printable text")
    return value.strip()


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
