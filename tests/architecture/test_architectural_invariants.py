from __future__ import annotations

import ast
from pathlib import Path

from scripts.lint_architectural_invariants import (
    ArchitecturalInvariantVisitor,
    REPOSITORY_ROOT,
    _is_source_file,
)


def _bans(source: str, path: str = "app/backend/app/example.py") -> set[str]:
    visitor = ArchitecturalInvariantVisitor(Path(path))
    visitor.visit(ast.parse(source))
    return {violation.ban for violation in visitor.violations}


def test_detects_question_branch_sync_io_and_regex_sql_validation() -> None:
    source = """
from urllib.request import urlopen
import re

_KOREAN_HINTS = {"매출": "revenue"}

def unsafe(question, sql):
    if "전월 대비" in question:
        return re.search("select", sql) or urlopen("https://example.invalid")
"""

    assert _bans(source) == {"BAN-02", "BAN-04", "BAN-05"}


def test_allows_unrelated_domain_mapping() -> None:
    assert _bans('STATE_MAPPING = {"RUNNING": "RUNNING"}') == set()
    assert _bans('mappings = {"source_column": "target_column"}') == set()


def test_operational_database_code_is_inside_the_lint_boundary() -> None:
    assert _is_source_file(
        REPOSITORY_ROOT / "infrastructure/database/datahub/publish_semantic_catalog.py"
    )
    assert _is_source_file(REPOSITORY_ROOT / "scripts/lint_architectural_invariants.py")


def test_detects_long_multitable_generation_template() -> None:
    joins = " ".join(f"JOIN catalog.schema.table_{index} ON TRUE" for index in range(20))
    source = f"QUERY = '''SELECT * FROM catalog.schema.base {joins}'''"

    assert _bans(source, "src/ai/prompt_registry.py") == {"BAN-03"}


def test_detects_multitable_template_split_into_short_fragments() -> None:
    source = '''
def generated_answer():
    return " ".join((
        "SELECT a.id",
        "FROM catalog.schema.a a",
        "JOIN catalog.schema.b b ON a.id = b.id",
        "JOIN catalog.schema.c c ON b.id = c.id",
    ))
'''

    assert _bans(source, "src/ai/node2.py") == {"BAN-03"}
