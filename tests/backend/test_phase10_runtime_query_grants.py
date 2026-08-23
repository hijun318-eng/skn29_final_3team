from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "app"
    / "backend"
    / "migrations"
    / "versions"
    / "20260823_34_phase10_runtime_query_terminal_grants.py"
)


def test_phase10_runtime_grant_covers_terminal_query_evidence_update() -> None:
    module = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_TERMINAL_EVIDENCE_COLUMNS"
            for target in node.targets
        )
    )
    granted = set(ast.literal_eval(assignment.value))

    assert granted == {
        "generation_mode",
        "ast_validation_json",
        "join_validation_json",
        "permission_validation_json",
        "explain_json",
        "validation_status",
        "result_checksum",
        "source_urns_json",
        "source_cutoff_json",
    }
    source = MIGRATION.read_text(encoding="utf-8")
    assert "GRANT UPDATE ({columns}) ON query.query_executions" in source
    assert "GRANT UPDATE ON query.query_executions" not in source
