"""내부지침 RAG 도구와 대화 턴 route를 현재 migration head에 연결한다."""

import json

from alembic import op


revision = "20260828_48"
down_revision = "20260828_47"
branch_labels = None
depends_on = None

RAG_TOOL_ID = "8edce655-e454-5b76-b56f-5e49aa2884d4"


def _replace_route_check(values: tuple[str, ...]) -> None:
    allowed = ",".join(f"'{value}'" for value in values)
    op.execute("ALTER TABLE chat.turns DROP CONSTRAINT IF EXISTS turns_route_check")
    op.execute(
        "ALTER TABLE chat.turns "
        f"ADD CONSTRAINT turns_route_check CHECK (route IN ({allowed}))"
    )


def upgrade() -> None:
    """RAG registry 계약을 upsert하고 내부지침 턴을 독립 route로 저장한다."""
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 2, "maxLength": 500}
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status": {
                "enum": [
                    "ANSWER",
                    "NO_EVIDENCE",
                    "POTENTIAL_CONFLICT",
                    "GENERATION_FAILED",
                ]
            },
            "trace_id": {"type": "string"},
            "citations": {"type": "array"},
            "evidence_bundle": {"type": "array"},
        },
        "required": ["status", "trace_id"],
    }
    op.execute(
        f"""
        INSERT INTO tooling.tool_registry
            (tool_id,tool_code,semantic_version,description,input_schema_json,
             output_schema_json,transport,timeout_seconds,required_roles_json,
             is_enabled)
        VALUES (
            '{RAG_TOOL_ID}','rag.answer','1.1.0',
            'Answer from approved internal manuals with citation-bound evidence.',
            '{json.dumps(input_schema)}'::jsonb,
            '{json.dumps(output_schema)}'::jsonb,
            'MCP_STREAMABLE_HTTP',30,
            '["analyst","platform_admin"]'::jsonb,false
        )
        """
    )
    _replace_route_check(
        ("ANALYSIS", "PRESENTATION", "REPORT_ACTION", "INTERNAL_GUIDELINE")
    )


def downgrade() -> None:
    """저장된 RAG 턴이 없을 때만 route와 registry 계약을 제거한다."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM chat.turns
                WHERE route = 'INTERNAL_GUIDELINE'
            ) THEN
                RAISE EXCEPTION
                    'INTERNAL_GUIDELINE turns must be preserved before downgrade';
            END IF;
        END $$
        """
    )
    _replace_route_check(("ANALYSIS", "PRESENTATION", "REPORT_ACTION"))
    op.execute(
        f"DELETE FROM tooling.tool_registry WHERE tool_id = '{RAG_TOOL_ID}'"
    )
