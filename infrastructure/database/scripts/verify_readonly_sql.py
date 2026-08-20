"""Release 검증 SQL이 조회와 명시적 database 선택만 포함하는지 SQLGlot AST로 검사한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel


MUTATING_NODE_NAMES = (
    "Alter",
    "Cache",
    "Commit",
    "Copy",
    "Create",
    "Delete",
    "Drop",
    "Grant",
    "Insert",
    "Into",
    "LoadData",
    "Merge",
    "Revoke",
    "Rollback",
    "Set",
    "Transaction",
    "TruncateTable",
    "Uncache",
    "Update",
)
MUTATING_NODES = tuple(
    node
    for name in MUTATING_NODE_NAMES
    if isinstance((node := getattr(exp, name, None)), type)
)


def _sql_text(path: Path, dialect: str) -> str:
    """sqlcmd의 독립 batch separator인 ``GO``만 AST 입력에서 제거하고 SQL은 보존한다."""

    text = path.read_text(encoding="utf-8")
    if dialect == "tsql":
        return "\n".join(
            line for line in text.splitlines() if line.strip().upper() != "GO"
        )
    return text


def verify(path: Path, dialect: str) -> int:
    """한 파일의 모든 statement를 파싱하고 조회가 아닌 AST가 있으면 즉시 실패한다."""

    statements = [
        statement
        for statement in parse(
            _sql_text(path, dialect),
            read=dialect,
            error_level=ErrorLevel.RAISE,
        )
        if statement is not None
    ]
    if not statements:
        raise ValueError(f"SQL file contains no statements: {path}")
    for statement in statements:
        if not isinstance(statement, (exp.Query, exp.Use)):
            raise ValueError(
                f"non-query statement {type(statement).__name__}: {path}"
            )
        for node_type in MUTATING_NODES:
            if statement.find(node_type) is not None:
                raise ValueError(
                    f"mutating node {node_type.__name__}: {path}"
                )
    return len(statements)


def main() -> int:
    """CLI 인자를 검증하고 파일별 statement 수가 포함된 결정적 marker를 출력한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--dialect", required=True)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    total = sum(verify(path.resolve(strict=True), args.dialect) for path in args.paths)
    print(f"READ_ONLY_SQL_VERIFIED|files={len(args.paths)}|statements={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
