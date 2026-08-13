"""Add the first approved MCP tool and immutable run evidence."""

import json
import os
import re

from alembic import op


revision = "20260812_12"
down_revision = "20260812_11"
branch_labels = None
depends_on = None

TOOL_ID = "c4454392-2f92-54a4-ad13-b8cdaba45732"


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS tooling")
    op.execute(
        """
        CREATE TABLE tooling.tool_registry (
            tool_id uuid PRIMARY KEY,
            tool_code varchar(96) NOT NULL UNIQUE,
            semantic_version varchar(32) NOT NULL,
            description text NOT NULL,
            input_schema_json jsonb NOT NULL,
            output_schema_json jsonb NOT NULL,
            transport varchar(24) NOT NULL CHECK (transport = 'MCP_STREAMABLE_HTTP'),
            timeout_seconds integer NOT NULL CHECK (timeout_seconds BETWEEN 1 AND 30),
            required_roles_json jsonb NOT NULL,
            is_enabled boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tooling.tool_runs (
            tool_run_id uuid PRIMARY KEY,
            tool_id uuid NOT NULL REFERENCES tooling.tool_registry(tool_id),
            caller_user_id uuid NOT NULL,
            caller_role varchar(32) NOT NULL,
            trace_id varchar(128) NOT NULL,
            input_hash varchar(64) NOT NULL CHECK (length(input_hash) = 64),
            status varchar(16) NOT NULL CHECK (status IN ('SUCCEEDED','FAILED','DENIED')),
            latency_ms integer NOT NULL CHECK (latency_ms >= 0),
            output_ref_json jsonb NOT NULL,
            error_code varchar(64),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((status = 'SUCCEEDED' AND error_code IS NULL) OR (status <> 'SUCCEEDED' AND error_code IS NOT NULL))
        );
        CREATE INDEX idx_tool_runs_tool_created ON tooling.tool_runs(tool_id, created_at DESC)
        """
    )
    input_schema = {
        "type": "object",
        "properties": {"request_id": {"type": "string", "format": "uuid"}},
        "required": ["request_id"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "status": {"type": "string"},
            "trace_id": {"type": "string"},
            "query_id": {"type": ["string", "null"]},
            "artifact_id": {"type": ["string", "null"]},
        },
        "required": ["request_id", "status", "trace_id", "query_id", "artifact_id"],
    }
    op.execute(
        f"""
        INSERT INTO tooling.tool_registry
            (tool_id, tool_code, semantic_version, description,
             input_schema_json, output_schema_json, transport,
             timeout_seconds, required_roles_json, is_enabled)
        VALUES (
            '{TOOL_ID}', 'analysis.get_run', '1.0.0',
            'Get one persisted Analysis Run owned by the authenticated user.',
            '{json.dumps(input_schema)}'::jsonb,
            '{json.dumps(output_schema)}'::jsonb,
            'MCP_STREAMABLE_HTTP', 5, '[\"hotel_analyst\"]'::jsonb, true
        )
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA tooling TO {role}")
    op.execute(f"GRANT SELECT ON tooling.tool_registry TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON tooling.tool_runs TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE tooling.tool_runs")
    op.execute("DROP TABLE tooling.tool_registry")
    op.execute("DROP SCHEMA tooling")
