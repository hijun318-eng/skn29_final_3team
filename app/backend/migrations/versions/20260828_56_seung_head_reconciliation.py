"""Seung Report Assistant head를 현행 Daesung schema로 안전하게 승격한다."""

from __future__ import annotations

import json
from pathlib import Path
import runpy
from typing import Callable

from alembic import op
from sqlalchemy import text


revision = "20260828_56"
down_revision = "20260827_41"
branch_labels = None
depends_on = None


_SOURCE_REVISION = "20260827_41"
_RECONCILIATION_ID = "seung-head-20260827-41-to-daesung-20260828-56"
_RAG_TOOL_ID = "8edce655-e454-5b76-b56f-5e49aa2884d4"

# Seung 29~41과 동등한 Report Assistant DDL은 의도적으로 제외한다.
# 아래 목록은 Daesung에만 존재했던 revision이며 원래 순서를 보존한다.
_DAESUNG_ONLY_REVISIONS = (
    "20260822_29_capability_evidence_contract",
    "20260822_30_conversation_safety_foundation",
    "20260822_31_runtime_catalog_projection",
    "20260822_32_report_release_receipts",
    "20260822_33_bounded_multi_turn_focus",
    "20260823_34_phase10_runtime_query_terminal_grants",
    "20260823_35_phase10_runtime_audit_grants",
    "20260825_36_catalog_publisher_role",
    "20260826_45_runtime_context_receipts",
    "20260826_46_database_auth_accounts",
    "20260828_47_query_generation_mode_compiler",
    "20260828_48_rag_integration",
    "20260828_49_ml_prediction_audit",
    "20260828_55_admin_control_plane",
)


def _scalar(statement: str, parameters: dict[str, object] | None = None) -> object:
    return op.get_bind().execute(text(statement), parameters or {}).scalar_one()


def _table_exists(schema: str, table: str) -> bool:
    return bool(
        _scalar(
            "SELECT to_regclass(:qualified_name) IS NOT NULL",
            {"qualified_name": f"{schema}.{table}"},
        )
    )


def _column_exists(schema: str, table: str, column: str) -> bool:
    return bool(
        _scalar(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = :schema
                  AND table_name = :table
                  AND column_name = :column
            )
            """,
            {"schema": schema, "table": table, "column": column},
        )
    )


def _constraint_contains(schema: str, table: str, name: str, token: str) -> bool:
    return bool(
        _scalar(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint constraint_row
                JOIN pg_class table_row
                  ON table_row.oid = constraint_row.conrelid
                JOIN pg_namespace schema_row
                  ON schema_row.oid = table_row.relnamespace
                WHERE schema_row.nspname = :schema
                  AND table_row.relname = :table
                  AND constraint_row.conname = :name
                  AND pg_get_constraintdef(constraint_row.oid) LIKE :token
            )
            """,
            {
                "schema": schema,
                "table": table,
                "name": name,
                "token": f"%{token}%",
            },
        )
    )


def _rag_tool_exists() -> bool:
    return bool(
        _scalar(
            "SELECT EXISTS (SELECT 1 FROM tooling.tool_registry WHERE tool_id = :tool_id)",
            {"tool_id": _RAG_TOOL_ID},
        )
    )


def _schema_sentinels() -> dict[str, Callable[[], bool]]:
    """Daesung 전용 revision마다 최소 한 개의 구조·계약 증거를 확인한다."""

    return {
        "capability_evidence": lambda: _table_exists(
            "governance", "product_release_manifests"
        ),
        "conversation_safety": lambda: _table_exists("chat", "turns"),
        "conversation_preexisting_receipt": lambda: _table_exists(
            "governance", "phase_20260822_30_preexisting_objects"
        ),
        "runtime_catalog_projection": lambda: _table_exists(
            "governance", "runtime_catalog_projections"
        ),
        "report_release_receipt": lambda: _column_exists(
            "report_v1", "report_definition_versions", "product_release_id"
        ),
        "bounded_multi_turn_focus": lambda: _column_exists(
            "artifact", "view_specs", "spec_sha256"
        ),
        "runtime_context_receipt": lambda: _constraint_contains(
            "context",
            "context_packages",
            "context_package_semantic_receipt_required",
            "product_release_id",
        ),
        "database_auth_accounts": lambda: _table_exists(
            "security", "auth_accounts"
        ),
        "compiler_generation_mode": lambda: _constraint_contains(
            "query",
            "query_executions",
            "query_executions_generation_mode_check",
            "COMPILER",
        ),
        "rag_registry_contract": _rag_tool_exists,
        "ml_prediction_audit": lambda: _table_exists(
            "governance", "ml_prediction_audit_events"
        ),
        "admin_control_plane": lambda: _column_exists(
            "security", "auth_accounts", "deleted_at"
        ),
    }


def _source_state() -> str:
    results = {name: check() for name, check in _schema_sentinels().items()}
    if all(results.values()):
        return "DAESUNG_CURRENT"
    if not any(results.values()):
        return "SEUNG_LEGACY"

    present = sorted(name for name, value in results.items() if value)
    missing = sorted(name for name, value in results.items() if not value)
    raise RuntimeError(
        "SEUNG_DAESUNG_RECONCILIATION_AMBIGUOUS: "
        f"present={present}; missing={missing}"
    )


def _run_revision(module_stem: str, operation: str) -> None:
    path = Path(__file__).with_name(f"{module_stem}.py")
    if not path.is_file():
        raise RuntimeError(f"reconciliation revision source is missing: {path.name}")
    namespace = runpy.run_path(str(path))
    handler = namespace.get(operation)
    if not callable(handler):
        raise RuntimeError(f"{path.name} does not define callable {operation}()")
    handler()


def _create_receipt_table() -> None:
    op.execute(
        """
        CREATE TABLE governance.migration_reconciliation_receipts (
            reconciliation_id varchar(96) PRIMARY KEY,
            source_revision varchar(64) NOT NULL,
            target_revision varchar(64) NOT NULL,
            applied_revisions_json jsonb NOT NULL
                CHECK (jsonb_typeof(applied_revisions_json) = 'array'),
            reconciled_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def upgrade() -> None:
    """정확한 Seung head만 보충하고 현행 Daesung DB에서는 DDL을 재실행하지 않는다."""

    source_state = _source_state()
    _create_receipt_table()
    if source_state == "DAESUNG_CURRENT":
        return

    for module_stem in _DAESUNG_ONLY_REVISIONS:
        _run_revision(module_stem, "upgrade")
    op.get_bind().execute(
        text(
            """
            INSERT INTO governance.migration_reconciliation_receipts (
                reconciliation_id, source_revision, target_revision,
                applied_revisions_json
            ) VALUES (
                :reconciliation_id, :source_revision, :target_revision,
                CAST(:applied_revisions_json AS jsonb)
            )
            """
        ),
        {
            "reconciliation_id": _RECONCILIATION_ID,
            "source_revision": _SOURCE_REVISION,
            "target_revision": revision,
            "applied_revisions_json": json.dumps(_DAESUNG_ONLY_REVISIONS),
        },
    )


def downgrade() -> None:
    """이 migration이 실제로 보충한 Daesung 전용 변경만 역순으로 제거한다."""

    reconciled_legacy = bool(
        _scalar(
            """
            SELECT EXISTS (
                SELECT 1
                FROM governance.migration_reconciliation_receipts
                WHERE reconciliation_id = :reconciliation_id
                  AND source_revision = :source_revision
                  AND target_revision = :target_revision
            )
            """,
            {
                "reconciliation_id": _RECONCILIATION_ID,
                "source_revision": _SOURCE_REVISION,
                "target_revision": revision,
            },
        )
    )
    if reconciled_legacy:
        for module_stem in reversed(_DAESUNG_ONLY_REVISIONS):
            _run_revision(module_stem, "downgrade")
    op.execute("DROP TABLE governance.migration_reconciliation_receipts")
