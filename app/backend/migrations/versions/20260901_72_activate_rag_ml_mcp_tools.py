"""검증된 RAG·HGBR ML handler 계약을 활성 MCP Tool로 승격한다."""

import json

from alembic import op


revision = "20260901_72"
down_revision = "20260901_71"
branch_labels = None
depends_on = None

RAG_TOOL_ID = "8edce655-e454-5b76-b56f-5e49aa2884d4"
ML_TOOL_ID = "3002d1d6-f681-5b5d-b0b6-0de795fb4c5c"

READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
RAG_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "maxLength": 500},
        "selected_document_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 100},
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
RAG_OUTPUT_SCHEMA = {
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
ML_INPUT_SCHEMA = {
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
OLD_ML_OUTPUT_SCHEMA = {
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


def _stable_ml_output_schema() -> dict[str, object]:
    daily = OLD_ML_OUTPUT_SCHEMA["properties"]["daily_forecasts"]
    provenance = OLD_ML_OUTPUT_SCHEMA["properties"]["provenance"]
    return {
        "type": "object",
        "properties": {
            **OLD_ML_OUTPUT_SCHEMA["properties"],
            "feature_contract_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "daily_forecasts": daily,
            "room_type_forecasts": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "target_date": {"type": "string", "format": "date"},
                        "room_type_code": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 64,
                        },
                        "available_rooms": {"type": "number", "exclusiveMinimum": 0},
                        "predicted_rooms_raw": {"type": "number"},
                        "predicted_rooms": {"type": "number", "minimum": 0},
                        "occupancy_rate": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": [
                        "target_date",
                        "room_type_code",
                        "available_rooms",
                        "predicted_rooms_raw",
                        "predicted_rooms",
                        "occupancy_rate",
                    ],
                    "additionalProperties": False,
                },
            },
            "provenance": provenance,
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
            "feature_contract_sha256",
            "daily_forecasts",
            "room_type_forecasts",
            "provenance",
        ],
        "additionalProperties": False,
    }


STABLE_ML_OUTPUT_SCHEMA = _stable_ml_output_schema()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def upgrade() -> None:
    """실행 당시 version을 고정한 뒤 검증된 RAG·ML candidate를 활성화한다."""

    rag_input = _json(RAG_INPUT_SCHEMA)
    rag_output = _json(RAG_OUTPUT_SCHEMA)
    ml_input = _json(ML_INPUT_SCHEMA)
    old_ml_output = _json(OLD_ML_OUTPUT_SCHEMA)
    stable_ml_output = _json(STABLE_ML_OUTPUT_SCHEMA)
    annotations = _json(READ_ONLY_ANNOTATIONS)
    op.execute(
        """
        ALTER TABLE tooling.tool_runs
            ADD COLUMN tool_semantic_version varchar(32);
        UPDATE tooling.tool_runs AS runs
        SET tool_semantic_version = registry.semantic_version
        FROM tooling.tool_registry AS registry
        WHERE registry.tool_id = runs.tool_id;
        ALTER TABLE tooling.tool_runs
            ALTER COLUMN tool_semantic_version SET NOT NULL;
        ALTER TABLE tooling.tool_runs
            ADD CONSTRAINT ck_tool_runs_semantic_version
            CHECK (
                tool_semantic_version ~ '^[0-9A-Za-z][0-9A-Za-z._+-]{0,31}$'
            );
        """
    )
    op.execute(
        f"""
        LOCK TABLE tooling.tool_registry IN SHARE ROW EXCLUSIVE MODE;
        LOCK TABLE tooling.tool_runs IN SHARE ROW EXCLUSIVE MODE;
        DO $$
        DECLARE
            affected integer;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_runs
                WHERE (tool_id = '{RAG_TOOL_ID}'
                       AND tool_semantic_version <> '1.2.0-candidate')
                   OR (tool_id = '{ML_TOOL_ID}'
                       AND tool_semantic_version <> '0.1.0-candidate')
            ) THEN
                RAISE EXCEPTION 'candidate RAG or ML Tool history version drifted';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{RAG_TOOL_ID}'
                  AND tool_code = 'rag.answer'
                  AND semantic_version = '1.2.0-candidate'
                  AND title = 'Answer from Internal Documents'
                  AND description = 'Answer only from approved internal documents with citation-bound evidence.'
                  AND input_schema_json = '{rag_input}'::jsonb
                  AND output_schema_json = '{rag_output}'::jsonb
                  AND annotations_json = '{annotations}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
            ) OR NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ML_TOOL_ID}'
                  AND tool_code = 'ml.predict'
                  AND semantic_version = '0.1.0-candidate'
                  AND title = 'Predict Room Demand'
                  AND description = 'Predict governed room demand for a typed property and date horizon.'
                  AND input_schema_json = '{ml_input}'::jsonb
                  AND output_schema_json = '{old_ml_output}'::jsonb
                  AND annotations_json = '{annotations}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
            ) THEN
                RAISE EXCEPTION 'RAG or ML MCP candidate receipt drifted before activation';
            END IF;

            UPDATE tooling.tool_registry
            SET semantic_version = '1.2.0', is_enabled = true
            WHERE tool_id = '{RAG_TOOL_ID}'
              AND semantic_version = '1.2.0-candidate';
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'rag.answer activation did not update one receipt';
            END IF;

            UPDATE tooling.tool_registry
            SET semantic_version = '1.0.0',
                output_schema_json = '{stable_ml_output}'::jsonb,
                is_enabled = true
            WHERE tool_id = '{ML_TOOL_ID}'
              AND semantic_version = '0.1.0-candidate';
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'ml.predict activation did not update one receipt';
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    """stable 실행 이력이 없을 때 candidate로 복원하고 version snapshot을 제거한다."""

    rag_input = _json(RAG_INPUT_SCHEMA)
    rag_output = _json(RAG_OUTPUT_SCHEMA)
    ml_input = _json(ML_INPUT_SCHEMA)
    old_ml_output = _json(OLD_ML_OUTPUT_SCHEMA)
    stable_ml_output = _json(STABLE_ML_OUTPUT_SCHEMA)
    annotations = _json(READ_ONLY_ANNOTATIONS)
    op.execute(
        f"""
        LOCK TABLE tooling.tool_registry IN SHARE ROW EXCLUSIVE MODE;
        LOCK TABLE tooling.tool_runs IN SHARE ROW EXCLUSIVE MODE;
        DO $$
        DECLARE
            affected integer;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_runs
                WHERE tool_id IN ('{RAG_TOOL_ID}', '{ML_TOOL_ID}')
            ) THEN
                RAISE EXCEPTION 'active RAG or ML Tool runs must be preserved';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{RAG_TOOL_ID}'
                  AND tool_code = 'rag.answer'
                  AND semantic_version = '1.2.0'
                  AND title = 'Answer from Internal Documents'
                  AND description = 'Answer only from approved internal documents with citation-bound evidence.'
                  AND input_schema_json = '{rag_input}'::jsonb
                  AND output_schema_json = '{rag_output}'::jsonb
                  AND annotations_json = '{annotations}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = true
            ) OR NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ML_TOOL_ID}'
                  AND tool_code = 'ml.predict'
                  AND semantic_version = '1.0.0'
                  AND title = 'Predict Room Demand'
                  AND description = 'Predict governed room demand for a typed property and date horizon.'
                  AND input_schema_json = '{ml_input}'::jsonb
                  AND output_schema_json = '{stable_ml_output}'::jsonb
                  AND annotations_json = '{annotations}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = true
            ) THEN
                RAISE EXCEPTION 'active RAG or ML MCP receipt drifted before downgrade';
            END IF;

            UPDATE tooling.tool_registry
            SET semantic_version = '1.2.0-candidate', is_enabled = false
            WHERE tool_id = '{RAG_TOOL_ID}' AND is_enabled = true;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'rag.answer downgrade did not update one receipt';
            END IF;

            UPDATE tooling.tool_registry
            SET semantic_version = '0.1.0-candidate',
                output_schema_json = '{old_ml_output}'::jsonb,
                is_enabled = false
            WHERE tool_id = '{ML_TOOL_ID}' AND is_enabled = true;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'ml.predict downgrade did not update one receipt';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        ALTER TABLE tooling.tool_runs
            DROP CONSTRAINT ck_tool_runs_semantic_version;
        ALTER TABLE tooling.tool_runs
            DROP COLUMN tool_semantic_version;
        """
    )
