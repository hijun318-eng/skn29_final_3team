from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from jsonschema import Draft202012Validator

from app.services.mcp_agent_tools import (
    ML_PREDICT_INPUT_SCHEMA,
    ML_PREDICT_OUTPUT_SCHEMA,
)
from app.services.rag_gateway import (
    RAG_TOOL_INPUT_SCHEMA,
    RAG_TOOL_OUTPUT_SCHEMA,
    RAG_TOOL_SEMANTIC_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    ROOT
    / "app/backend/migrations/versions/20260901_72_activate_rag_ml_mcp_tools.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mcp_activation_72", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("MCP activation migration module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_activation_receipts_exactly_match_runtime_descriptors() -> None:
    migration = _load_migration()

    assert migration.revision == "20260901_72"
    assert migration.down_revision == "20260901_71"
    assert RAG_TOOL_SEMANTIC_VERSION == "1.2.0"
    assert migration.RAG_INPUT_SCHEMA == RAG_TOOL_INPUT_SCHEMA
    assert migration.RAG_OUTPUT_SCHEMA == RAG_TOOL_OUTPUT_SCHEMA
    assert migration.ML_INPUT_SCHEMA == ML_PREDICT_INPUT_SCHEMA
    assert migration.STABLE_ML_OUTPUT_SCHEMA == ML_PREDICT_OUTPUT_SCHEMA
    Draft202012Validator.check_schema(migration.STABLE_ML_OUTPUT_SCHEMA)


def test_activation_and_rollback_are_fail_closed_around_tool_history() -> None:
    migration = _load_migration()
    statements: list[str] = []
    with patch.object(migration.op, "execute", side_effect=statements.append):
        migration.upgrade()
        migration.downgrade()

    rendered = " ".join(statements).lower()
    assert rendered.count("lock table tooling.tool_registry") == 2
    assert rendered.count("lock table tooling.tool_runs") == 2
    assert "add column tool_semantic_version" in rendered
    assert "candidate rag or ml tool history version drifted" in rendered
    assert "active rag or ml tool runs must be preserved" in rendered
    assert "semantic_version = '1.2.0', is_enabled = true" in rendered
    assert "semantic_version = '1.0.0'" in rendered
    assert "semantic_version = '1.2.0-candidate', is_enabled = false" in rendered
    assert "semantic_version = '0.1.0-candidate'" in rendered
    assert "drop column tool_semantic_version" in rendered
