"""Analysis·RAG·ML 실행 Tool의 비활성 strict candidate 계약을 등록한다.

Handler·release receipt·feature flag가 조립되기 전에는 어떤 candidate도 활성화하지
않는다. 기존 ``rag.answer``도 schema를 닫는 forward update만 수행한다.
"""

import json

from alembic import op


revision = "20260831_64"
down_revision = "20260831_63"
branch_labels = None
depends_on = None

ANALYSIS_RUN_TOOL_ID = "399e1d6e-54d9-5061-b3ee-555dc3666c45"
RAG_ANSWER_TOOL_ID = "8edce655-e454-5b76-b56f-5e49aa2884d4"
ML_PREDICT_TOOL_ID = "3002d1d6-f681-5b5d-b0b6-0de795fb4c5c"

_OLD_RAG_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "maxLength": 500},
    },
    "required": ["query"],
    "additionalProperties": False,
}
_OLD_RAG_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "enum": [
                "ANSWER",
                "NO_EVIDENCE",
                "POTENTIAL_CONFLICT",
                "GENERATION_FAILED",
            ],
        },
        "trace_id": {"type": "string"},
        "citations": {"type": "array"},
        "evidence_bundle": {"type": "array"},
    },
    "required": ["status", "trace_id"],
}

ANALYSIS_RUN_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "semantic_snapshot_id": {"type": "string", "format": "uuid"},
        "idempotency_key": {
            "type": "string",
            "minLength": 16,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9._:-]+$",
        },
    },
    "required": ["semantic_snapshot_id", "idempotency_key"],
    "additionalProperties": False,
}
ANALYSIS_RUN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string", "format": "uuid"},
        "status": {
            "type": "string",
            "enum": [
                "RECEIVED",
                "CLARIFYING",
                "CONTEXT_BUILDING",
                "GENERATING",
                "VALIDATING",
                "RUNNING",
                "SUCCEEDED",
                "PARTIAL",
                "FAILED",
                "DENIED",
                "CANCELLED",
            ],
        },
        "trace_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "artifact_id": {"type": ["string", "null"], "format": "uuid"},
    },
    "required": ["request_id", "status", "trace_id", "artifact_id"],
    "additionalProperties": False,
}

RAG_ANSWER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "maxLength": 500},
        "selected_document_ids": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
            },
            "maxItems": 10,
            "uniqueItems": True,
        },
        "recent_utterances": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
            "maxItems": 3,
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}
RAG_ANSWER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ANSWER", "NO_EVIDENCE", "CONFLICT"],
        },
        "trace_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "answer": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_id": {"type": "string", "minLength": 1},
                    "citation": {"type": "string"},
                },
                "required": ["evidence_id", "citation"],
                "additionalProperties": False,
            },
        },
        "evidence_bundle": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_id": {"type": "string", "minLength": 1},
                    "document_id": {"type": "string", "minLength": 1},
                    "document_name": {"type": "string"},
                    "section": {"type": "string"},
                    "snippet": {"type": "string"},
                    "score": {"type": "number", "minimum": 0},
                },
                "required": [
                    "evidence_id",
                    "document_id",
                    "document_name",
                    "section",
                    "snippet",
                    "score",
                ],
                "additionalProperties": False,
            },
        },
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "minLength": 1},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 2,
                        "uniqueItems": True,
                    },
                },
                "required": ["description", "evidence_ids"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
    },
    "required": ["status", "trace_id", "evidence_bundle"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"status": {"enum": ["ANSWER", "NO_EVIDENCE"]}}},
            "then": {
                "required": ["answer", "citations"],
                "not": {"required": ["conflicts"]},
            },
        },
        {
            "if": {"properties": {"status": {"const": "CONFLICT"}}},
            "then": {
                "required": ["conflicts"],
                "not": {
                    "anyOf": [
                        {"required": ["answer"]},
                        {"required": ["citations"]},
                    ]
                },
            },
        },
    ],
}

ML_PREDICT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "property_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z0-9_-]+$",
        },
        "as_of": {"type": "string", "format": "date"},
        "horizon_days": {"type": "integer", "minimum": 1, "maximum": 366},
    },
    "required": ["property_id", "as_of", "horizon_days"],
    "additionalProperties": False,
}
ML_PREDICT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "const": "MLRoomDemandPrediction.v1"},
        "status": {"type": "string", "const": "SUCCEEDED"},
        "execution_id": {"type": "string", "format": "uuid"},
        "property_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z0-9_-]+$",
        },
        "as_of": {"type": "string", "format": "date"},
        "feature_as_of": {"type": "string", "format": "date"},
        "horizon_days": {"type": "integer", "minimum": 1, "maximum": 366},
        "model_version": {"type": "string", "minLength": 1, "maxLength": 160},
        "model_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "daily_forecasts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "format": "date"},
                    "total_available_rooms": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                    "predicted_occupied_rooms": {"type": "number", "minimum": 0},
                    "predicted_available_rooms": {"type": "number", "minimum": 0},
                    "predicted_occupancy_rate": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
                "required": [
                    "target_date",
                    "total_available_rooms",
                    "predicted_occupied_rooms",
                    "predicted_available_rooms",
                    "predicted_occupancy_rate",
                ],
                "additionalProperties": False,
            },
        },
        "provenance": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "const": "TRINO_HISTORICAL_DAILY_FACTS",
                },
                "history_table": {
                    "type": "string",
                    "minLength": 5,
                    "maxLength": 256,
                    "pattern": "^[A-Za-z_][A-Za-z0-9_]*\\.[A-Za-z_][A-Za-z0-9_]*\\.[A-Za-z_][A-Za-z0-9_]*$",
                },
                "trino_query_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "feature_as_of": {"type": "string", "format": "date"},
                "request_as_of": {"type": "string", "format": "date"},
                "rag_called": {"type": "boolean", "const": False},
            },
            "required": [
                "source",
                "history_table",
                "trino_query_id",
                "feature_as_of",
                "request_as_of",
                "rag_called",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "schema_version",
        "status",
        "execution_id",
        "property_id",
        "as_of",
        "feature_as_of",
        "horizon_days",
        "model_version",
        "model_hash",
        "daily_forecasts",
        "provenance",
    ],
    "additionalProperties": False,
}


def _json(value: dict[str, object]) -> str:
    """SQLAlchemy bind 오인을 막는 공백 포함 결정론적 JSON을 만든다."""

    return json.dumps(value, sort_keys=True)


def upgrade() -> None:
    """신규 candidate 두 건과 RAG forward candidate를 모두 비활성 등록한다."""

    analysis_input = _json(ANALYSIS_RUN_INPUT_SCHEMA)
    analysis_output = _json(ANALYSIS_RUN_OUTPUT_SCHEMA)
    ml_input = _json(ML_PREDICT_INPUT_SCHEMA)
    ml_output = _json(ML_PREDICT_OUTPUT_SCHEMA)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ANALYSIS_RUN_TOOL_ID}' OR tool_code = 'analysis.run'
            ) THEN
                RAISE EXCEPTION 'analysis.run candidate identity already exists';
            END IF;
            INSERT INTO tooling.tool_registry
                (tool_id, tool_code, semantic_version, description,
                 input_schema_json, output_schema_json, transport,
                 timeout_seconds, required_roles_json, is_enabled)
            VALUES (
                '{ANALYSIS_RUN_TOOL_ID}', 'analysis.run', '0.1.0-candidate',
                'Execute one approved Semantic Request snapshot.',
                '{analysis_input}'::jsonb, '{analysis_output}'::jsonb,
                'MCP_STREAMABLE_HTTP', 30, '["analyst"]'::jsonb, false
            );
        END $$
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ML_PREDICT_TOOL_ID}' OR tool_code = 'ml.predict'
            ) THEN
                RAISE EXCEPTION 'ml.predict candidate identity already exists';
            END IF;
            INSERT INTO tooling.tool_registry
                (tool_id, tool_code, semantic_version, description,
                 input_schema_json, output_schema_json, transport,
                 timeout_seconds, required_roles_json, is_enabled)
            VALUES (
                '{ML_PREDICT_TOOL_ID}', 'ml.predict', '0.1.0-candidate',
                'Predict governed room demand for a typed property and date horizon.',
                '{ml_input}'::jsonb, '{ml_output}'::jsonb,
                'MCP_STREAMABLE_HTTP', 30, '["analyst"]'::jsonb, false
            );
        END $$
        """
    )
    old_input = _json(_OLD_RAG_INPUT_SCHEMA)
    old_output = _json(_OLD_RAG_OUTPUT_SCHEMA)
    rag_input = _json(RAG_ANSWER_INPUT_SCHEMA)
    rag_output = _json(RAG_ANSWER_OUTPUT_SCHEMA)
    op.execute(
        f"""
        DO $$
        DECLARE
            affected integer;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_runs
                WHERE tool_id = '{RAG_ANSWER_TOOL_ID}'
            ) THEN
                RAISE EXCEPTION 'rag.answer historical runs must be preserved';
            END IF;
            UPDATE tooling.tool_registry
            SET semantic_version = '1.2.0-candidate',
                description = 'Answer only from approved internal documents with citation-bound evidence.',
                input_schema_json = '{rag_input}'::jsonb,
                output_schema_json = '{rag_output}'::jsonb,
                timeout_seconds = 30,
                required_roles_json = '["analyst"]'::jsonb,
                is_enabled = false
            WHERE tool_id = '{RAG_ANSWER_TOOL_ID}'
              AND tool_code = 'rag.answer'
              AND semantic_version = '1.1.0'
              AND description = 'Answer from approved internal manuals with citation-bound evidence.'
              AND input_schema_json = '{old_input}'::jsonb
              AND output_schema_json = '{old_output}'::jsonb
              AND transport = 'MCP_STREAMABLE_HTTP'
              AND timeout_seconds = 30
              AND required_roles_json = '["analyst","platform_admin"]'::jsonb
              AND is_enabled = false;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'rag.answer candidate predecessor receipt is invalid';
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    """활성화·실행·계약 변경이 없는 candidate만 직전 상태로 되돌린다."""

    rag_input = _json(RAG_ANSWER_INPUT_SCHEMA)
    rag_output = _json(RAG_ANSWER_OUTPUT_SCHEMA)
    old_input = _json(_OLD_RAG_INPUT_SCHEMA)
    old_output = _json(_OLD_RAG_OUTPUT_SCHEMA)
    op.execute(
        f"""
        DO $$
        DECLARE
            affected integer;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_runs
                WHERE tool_id = '{RAG_ANSWER_TOOL_ID}'
            ) THEN
                RAISE EXCEPTION 'rag.answer candidate runs must be preserved';
            END IF;
            UPDATE tooling.tool_registry
            SET semantic_version = '1.1.0',
                description = 'Answer from approved internal manuals with citation-bound evidence.',
                input_schema_json = '{old_input}'::jsonb,
                output_schema_json = '{old_output}'::jsonb,
                timeout_seconds = 30,
                required_roles_json = '["analyst","platform_admin"]'::jsonb,
                is_enabled = false
            WHERE tool_id = '{RAG_ANSWER_TOOL_ID}'
              AND tool_code = 'rag.answer'
              AND semantic_version = '1.2.0-candidate'
              AND description = 'Answer only from approved internal documents with citation-bound evidence.'
              AND input_schema_json = '{rag_input}'::jsonb
              AND output_schema_json = '{rag_output}'::jsonb
              AND transport = 'MCP_STREAMABLE_HTTP'
              AND timeout_seconds = 30
              AND required_roles_json = '["analyst"]'::jsonb
              AND is_enabled = false;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'rag.answer candidate cannot be downgraded safely';
            END IF;
        END $$
        """
    )
    for tool_id, tool_code, version, description, input_schema, output_schema in (
        (
            ML_PREDICT_TOOL_ID,
            "ml.predict",
            "0.1.0-candidate",
            "Predict governed room demand for a typed property and date horizon.",
            ML_PREDICT_INPUT_SCHEMA,
            ML_PREDICT_OUTPUT_SCHEMA,
        ),
        (
            ANALYSIS_RUN_TOOL_ID,
            "analysis.run",
            "0.1.0-candidate",
            "Execute one approved Semantic Request snapshot.",
            ANALYSIS_RUN_INPUT_SCHEMA,
            ANALYSIS_RUN_OUTPUT_SCHEMA,
        ),
    ):
        expected_input = _json(input_schema)
        expected_output = _json(output_schema)
        op.execute(
            f"""
            DO $$
            DECLARE
                affected integer;
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM tooling.tool_runs
                    WHERE tool_id = '{tool_id}'
                ) THEN
                    RAISE EXCEPTION '{tool_code} candidate runs must be preserved';
                END IF;
                DELETE FROM tooling.tool_registry
                WHERE tool_id = '{tool_id}'
                  AND tool_code = '{tool_code}'
                  AND semantic_version = '{version}'
                  AND description = '{description}'
                  AND input_schema_json = '{expected_input}'::jsonb
                  AND output_schema_json = '{expected_output}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = false;
                GET DIAGNOSTICS affected = ROW_COUNT;
                IF affected <> 1 THEN
                    RAISE EXCEPTION '{tool_code} candidate cannot be removed safely';
                END IF;
            END $$
            """
        )
