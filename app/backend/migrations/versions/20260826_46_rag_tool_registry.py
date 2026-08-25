"""인용 기반 RAG와 승인 ML 예측 Tool을 기존 Registry 체인 뒤에 등록한다."""

import json

from alembic import op


revision = "20260826_46"
down_revision = "20260826_45"
branch_labels = None
depends_on = None

RAG_TOOL_ID = "8edce655-e454-5b76-b56f-5e49aa2884d4"
ML_TOOL_ID = "e3b9a137-8a4c-5a32-b6dc-41e7c324df72"
REQUIRED_ROLES = '["analyst","platform_admin"]'


def _upsert_tool(
    tool_id: str,
    code: str,
    version: str,
    description: str,
    input_schema: dict,
    output_schema: dict,
    timeout_seconds: int,
) -> None:
    op.execute(
        f"""
        INSERT INTO tooling.tool_registry
            (tool_id,tool_code,semantic_version,description,input_schema_json,
             output_schema_json,transport,timeout_seconds,required_roles_json,
             is_enabled)
        VALUES (
            '{tool_id}','{code}','{version}','{description}',
            '{json.dumps(input_schema)}'::jsonb,
            '{json.dumps(output_schema)}'::jsonb,
            'MCP_STREAMABLE_HTTP',{timeout_seconds},
            '{REQUIRED_ROLES}'::jsonb,true
        )
        ON CONFLICT (tool_id) DO UPDATE SET
            tool_code=EXCLUDED.tool_code,
            semantic_version=EXCLUDED.semantic_version,
            description=EXCLUDED.description,
            input_schema_json=EXCLUDED.input_schema_json,
            output_schema_json=EXCLUDED.output_schema_json,
            transport=EXCLUDED.transport,
            timeout_seconds=EXCLUDED.timeout_seconds,
            required_roles_json=EXCLUDED.required_roles_json,
            is_enabled=true
        """
    )


def upgrade() -> None:
    """RAG·ML Tool의 schema, 역할, timeout을 멱등 upsert로 활성화한다."""

    _upsert_tool(
        RAG_TOOL_ID,
        "rag.answer",
        "1.0.0",
        "Answer from approved internal manuals and return citation-bound evidence.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 500}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "status": {"enum": ["ANSWER", "NO_EVIDENCE", "CONFLICT"]},
                "trace_id": {"type": "string"},
                "citations": {"type": "array"},
                "evidence_bundle": {"type": "array"},
            },
            "required": ["status", "trace_id"],
        },
        30,
    )
    _upsert_tool(
        ML_TOOL_ID,
        "ml.predict",
        "1.0.0",
        "Run an approved occupancy forecast with live PMS model provenance.",
        {
            "type": "object",
            "properties": {
                "hotel_scope": {
                    "type": "string",
                    "pattern": "^[A-Z0-9_]+$",
                    "minLength": 1,
                    "maxLength": 32,
                },
                "metric": {"const": "OCCUPANCY_RATE"},
                "horizon": {"type": "integer", "minimum": 1, "maximum": 7},
            },
            "required": ["hotel_scope", "metric", "horizon"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "status": {"const": "SUCCESS"},
                "request_id": {"type": "string"},
                "trace_id": {"type": "string"},
                "summary": {"type": "object"},
                "daily": {"type": "array"},
                "evidence": {"type": "object"},
            },
            "required": [
                "status",
                "request_id",
                "trace_id",
                "summary",
                "daily",
                "evidence",
            ],
        },
        30,
    )


def downgrade() -> None:
    """이 migration이 등록한 두 Tool만 식별자로 제거한다."""

    op.execute(
        f"DELETE FROM tooling.tool_registry "
        f"WHERE tool_id IN ('{RAG_TOOL_ID}','{ML_TOOL_ID}')"
    )
