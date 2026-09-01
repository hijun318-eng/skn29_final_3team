from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from scripts.lint_architectural_invariants import (
    ArchitecturalInvariantVisitor,
    REPOSITORY_ROOT,
    _is_source_file,
)


def test_services_namespace_has_no_eager_domain_imports() -> None:
    """Fresh adapter/MCP import를 깨는 서비스 package 초기화 side effect를 금지한다."""

    source = REPOSITORY_ROOT / "app/backend/app/services/__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    eager_domain_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert eager_domain_imports == []

    environment = os.environ.copy()
    backend = str(REPOSITORY_ROOT / "app/backend")
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (backend, str(REPOSITORY_ROOT), environment.get("PYTHONPATH", ""))
        if value
    )
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import app.api.mcp_router; "
                "from app.services import AnalysisService; "
                "assert AnalysisService.__name__ == 'AnalysisService'"
            ),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr


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


def test_rag_and_ml_production_code_is_inside_the_lint_boundary() -> None:
    """교체형 runtime도 질문·SQL 하드코딩 금지 검사를 우회하지 못하게 한다."""

    assert _is_source_file(REPOSITORY_ROOT / "src/rag/api.py")
    assert _is_source_file(REPOSITORY_ROOT / "src/ml/room_demand_timeseries/runtime_api.py")


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
