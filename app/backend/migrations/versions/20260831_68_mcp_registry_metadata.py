"""MCP registry 공개 metadata와 client cancellation terminal receipt를 보존한다."""

import json

from alembic import op


revision = "20260831_68"
down_revision = "20260831_67"
branch_labels = None
depends_on = None

ANALYSIS_GET_RUN_TOOL_ID = "c4454392-2f92-54a4-ad13-b8cdaba45732"
ANALYSIS_RUN_TOOL_ID = "399e1d6e-54d9-5061-b3ee-555dc3666c45"
RAG_ANSWER_TOOL_ID = "8edce655-e454-5b76-b56f-5e49aa2884d4"
ML_PREDICT_TOOL_ID = "3002d1d6-f681-5b5d-b0b6-0de795fb4c5c"

READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
ANALYSIS_RUN_INPUT_SCHEMA_JSON = "{\"additionalProperties\": false, \"properties\": {\"idempotency_key\": {\"maxLength\": 128, \"minLength\": 16, \"pattern\": \"^[A-Za-z0-9._:-]+$\", \"type\": \"string\"}, \"semantic_snapshot_id\": {\"format\": \"uuid\", \"type\": \"string\"}}, \"required\": [\"semantic_snapshot_id\", \"idempotency_key\"], \"type\": \"object\"}"
ANALYSIS_RUN_OUTPUT_SCHEMA_JSON = "{\"additionalProperties\": false, \"properties\": {\"artifact_id\": {\"format\": \"uuid\", \"type\": [\"string\", \"null\"]}, \"request_id\": {\"format\": \"uuid\", \"type\": \"string\"}, \"status\": {\"enum\": [\"RECEIVED\", \"CLARIFYING\", \"CONTEXT_BUILDING\", \"GENERATING\", \"VALIDATING\", \"RUNNING\", \"SUCCEEDED\", \"PARTIAL\", \"FAILED\", \"DENIED\", \"CANCELLED\"], \"type\": \"string\"}, \"trace_id\": {\"maxLength\": 128, \"minLength\": 1, \"type\": \"string\"}}, \"required\": [\"request_id\", \"status\", \"trace_id\", \"artifact_id\"], \"type\": \"object\"}"
RAG_ANSWER_INPUT_SCHEMA_JSON = "{\"additionalProperties\": false, \"properties\": {\"query\": {\"maxLength\": 500, \"minLength\": 2, \"type\": \"string\"}, \"recent_utterances\": {\"items\": {\"maxLength\": 500, \"minLength\": 1, \"type\": \"string\"}, \"maxItems\": 3, \"type\": \"array\"}, \"selected_document_ids\": {\"items\": {\"maxLength\": 100, \"minLength\": 1, \"type\": \"string\"}, \"maxItems\": 10, \"type\": \"array\", \"uniqueItems\": true}}, \"required\": [\"query\"], \"type\": \"object\"}"
RAG_ANSWER_OUTPUT_SCHEMA_JSON = "{\"additionalProperties\": false, \"allOf\": [{\"if\": {\"properties\": {\"status\": {\"enum\": [\"ANSWER\", \"NO_EVIDENCE\"]}}}, \"then\": {\"not\": {\"required\": [\"conflicts\"]}, \"required\": [\"answer\", \"citations\"]}}, {\"if\": {\"properties\": {\"status\": {\"const\": \"CONFLICT\"}}}, \"then\": {\"not\": {\"anyOf\": [{\"required\": [\"answer\"]}, {\"required\": [\"citations\"]}]}, \"required\": [\"conflicts\"]}}], \"properties\": {\"answer\": {\"additionalProperties\": false, \"properties\": {\"text\": {\"type\": \"string\"}}, \"required\": [\"text\"], \"type\": \"object\"}, \"citations\": {\"items\": {\"additionalProperties\": false, \"properties\": {\"citation\": {\"type\": \"string\"}, \"evidence_id\": {\"minLength\": 1, \"type\": \"string\"}}, \"required\": [\"evidence_id\", \"citation\"], \"type\": \"object\"}, \"type\": \"array\"}, \"conflicts\": {\"items\": {\"additionalProperties\": false, \"properties\": {\"description\": {\"minLength\": 1, \"type\": \"string\"}, \"evidence_ids\": {\"items\": {\"minLength\": 1, \"type\": \"string\"}, \"minItems\": 2, \"type\": \"array\", \"uniqueItems\": true}}, \"required\": [\"description\", \"evidence_ids\"], \"type\": \"object\"}, \"minItems\": 1, \"type\": \"array\"}, \"evidence_bundle\": {\"items\": {\"additionalProperties\": false, \"properties\": {\"document_id\": {\"minLength\": 1, \"type\": \"string\"}, \"document_name\": {\"type\": \"string\"}, \"evidence_id\": {\"minLength\": 1, \"type\": \"string\"}, \"score\": {\"minimum\": 0, \"type\": \"number\"}, \"section\": {\"type\": \"string\"}, \"snippet\": {\"type\": \"string\"}}, \"required\": [\"evidence_id\", \"document_id\", \"document_name\", \"section\", \"snippet\", \"score\"], \"type\": \"object\"}, \"type\": \"array\"}, \"status\": {\"enum\": [\"ANSWER\", \"NO_EVIDENCE\", \"CONFLICT\"], \"type\": \"string\"}, \"trace_id\": {\"maxLength\": 128, \"minLength\": 1, \"type\": \"string\"}}, \"required\": [\"status\", \"trace_id\", \"evidence_bundle\"], \"type\": \"object\"}"
ML_PREDICT_INPUT_SCHEMA_JSON = "{\"additionalProperties\": false, \"properties\": {\"as_of\": {\"format\": \"date\", \"type\": \"string\"}, \"horizon_days\": {\"maximum\": 366, \"minimum\": 1, \"type\": \"integer\"}, \"property_id\": {\"maxLength\": 64, \"minLength\": 1, \"pattern\": \"^[A-Za-z0-9_-]+$\", \"type\": \"string\"}}, \"required\": [\"property_id\", \"as_of\", \"horizon_days\"], \"type\": \"object\"}"
ML_PREDICT_OUTPUT_SCHEMA_JSON = "{\"additionalProperties\": false, \"properties\": {\"as_of\": {\"format\": \"date\", \"type\": \"string\"}, \"daily_forecasts\": {\"items\": {\"additionalProperties\": false, \"properties\": {\"predicted_available_rooms\": {\"minimum\": 0, \"type\": \"number\"}, \"predicted_occupancy_rate\": {\"maximum\": 1, \"minimum\": 0, \"type\": \"number\"}, \"predicted_occupied_rooms\": {\"minimum\": 0, \"type\": \"number\"}, \"target_date\": {\"format\": \"date\", \"type\": \"string\"}, \"total_available_rooms\": {\"exclusiveMinimum\": 0, \"type\": \"number\"}}, \"required\": [\"target_date\", \"total_available_rooms\", \"predicted_occupied_rooms\", \"predicted_available_rooms\", \"predicted_occupancy_rate\"], \"type\": \"object\"}, \"minItems\": 1, \"type\": \"array\"}, \"execution_id\": {\"format\": \"uuid\", \"type\": \"string\"}, \"feature_as_of\": {\"format\": \"date\", \"type\": \"string\"}, \"horizon_days\": {\"maximum\": 366, \"minimum\": 1, \"type\": \"integer\"}, \"model_hash\": {\"pattern\": \"^[0-9a-f]{64}$\", \"type\": \"string\"}, \"model_version\": {\"maxLength\": 160, \"minLength\": 1, \"type\": \"string\"}, \"property_id\": {\"maxLength\": 64, \"minLength\": 1, \"pattern\": \"^[A-Za-z0-9_-]+$\", \"type\": \"string\"}, \"provenance\": {\"additionalProperties\": false, \"properties\": {\"feature_as_of\": {\"format\": \"date\", \"type\": \"string\"}, \"history_table\": {\"maxLength\": 256, \"minLength\": 5, \"pattern\": \"^[A-Za-z_][A-Za-z0-9_]*\\\\.[A-Za-z_][A-Za-z0-9_]*\\\\.[A-Za-z_][A-Za-z0-9_]*$\", \"type\": \"string\"}, \"rag_called\": {\"const\": false, \"type\": \"boolean\"}, \"request_as_of\": {\"format\": \"date\", \"type\": \"string\"}, \"source\": {\"const\": \"TRINO_HISTORICAL_DAILY_FACTS\", \"type\": \"string\"}, \"trino_query_id\": {\"maxLength\": 256, \"minLength\": 1, \"type\": \"string\"}}, \"required\": [\"source\", \"history_table\", \"trino_query_id\", \"feature_as_of\", \"request_as_of\", \"rag_called\"], \"type\": \"object\"}, \"schema_version\": {\"const\": \"MLRoomDemandPrediction.v1\", \"type\": \"string\"}, \"status\": {\"const\": \"SUCCEEDED\", \"type\": \"string\"}}, \"required\": [\"schema_version\", \"status\", \"execution_id\", \"property_id\", \"as_of\", \"feature_as_of\", \"horizon_days\", \"model_version\", \"model_hash\", \"daily_forecasts\", \"provenance\"], \"type\": \"object\"}"


def _json(value: dict[str, object]) -> str:
    """SQL literal에 사용할 결정론적 canonical JSON을 만든다."""

    return json.dumps(value, sort_keys=True)


def upgrade() -> None:
    """기존 4행 receipt를 검증하고 metadata·취소 terminal 상태를 추가한다."""

    annotations = _json(READ_ONLY_ANNOTATIONS)
    op.execute(
        """
        ALTER TABLE tooling.tool_registry
            ADD COLUMN title varchar(160),
            ADD COLUMN annotations_json jsonb
        """
    )
    op.execute(
        f"""
        LOCK TABLE tooling.tool_registry IN SHARE ROW EXCLUSIVE MODE;
        DO $$
        DECLARE
            affected integer;
        BEGIN
            IF (SELECT count(*) FROM tooling.tool_registry) <> 4 THEN
                RAISE EXCEPTION 'MCP registry row set is not the expected four receipts';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ANALYSIS_GET_RUN_TOOL_ID}'
                  AND tool_code = 'analysis.get_run'
                  AND semantic_version = '1.0.0'
                  AND description = 'Get one persisted Analysis Run owned by the authenticated user.'
                  AND input_schema_json = '{{
                    "type": "object",
                    "properties": {{"request_id": {{"type": "string", "format": "uuid"}}}},
                    "required": ["request_id"],
                    "additionalProperties": false
                  }}'::jsonb
                  AND output_schema_json = '{{
                    "type": "object",
                    "properties": {{
                      "request_id": {{"type": "string"}},
                      "status": {{"type": "string"}},
                      "trace_id": {{"type": "string"}},
                      "query_id": {{"type": ["string", "null"]}},
                      "artifact_id": {{"type": ["string", "null"]}}
                    }},
                    "required": ["request_id", "status", "trace_id", "query_id", "artifact_id"],
                    "additionalProperties": false
                  }}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 5
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = true
            ) THEN
                RAISE EXCEPTION 'analysis.get_run registry receipt drifted before metadata backfill';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ANALYSIS_RUN_TOOL_ID}'
                  AND tool_code = 'analysis.run'
                  AND semantic_version = '0.1.0-candidate'
                  AND description = 'Execute one approved Semantic Request snapshot.'
                  AND input_schema_json = '{ANALYSIS_RUN_INPUT_SCHEMA_JSON}'::jsonb
                  AND output_schema_json = '{ANALYSIS_RUN_OUTPUT_SCHEMA_JSON}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = false
            ) OR NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{RAG_ANSWER_TOOL_ID}'
                  AND tool_code = 'rag.answer'
                  AND semantic_version = '1.2.0-candidate'
                  AND description = 'Answer only from approved internal documents with citation-bound evidence.'
                  AND input_schema_json = '{RAG_ANSWER_INPUT_SCHEMA_JSON}'::jsonb
                  AND output_schema_json = '{RAG_ANSWER_OUTPUT_SCHEMA_JSON}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = false
            ) OR NOT EXISTS (
                SELECT 1 FROM tooling.tool_registry
                WHERE tool_id = '{ML_PREDICT_TOOL_ID}'
                  AND tool_code = 'ml.predict'
                  AND semantic_version = '0.1.0-candidate'
                  AND description = 'Predict governed room demand for a typed property and date horizon.'
                  AND input_schema_json = '{ML_PREDICT_INPUT_SCHEMA_JSON}'::jsonb
                  AND output_schema_json = '{ML_PREDICT_OUTPUT_SCHEMA_JSON}'::jsonb
                  AND transport = 'MCP_STREAMABLE_HTTP'
                  AND timeout_seconds = 30
                  AND required_roles_json = '["analyst"]'::jsonb
                  AND is_enabled = false
            ) THEN
                RAISE EXCEPTION 'disabled MCP candidate receipt drifted before metadata backfill';
            END IF;

            UPDATE tooling.tool_registry
            SET title = CASE tool_id
                    WHEN '{ANALYSIS_GET_RUN_TOOL_ID}'::uuid THEN 'Get Analysis Run'
                    WHEN '{ANALYSIS_RUN_TOOL_ID}'::uuid THEN 'Run Approved Analysis'
                    WHEN '{RAG_ANSWER_TOOL_ID}'::uuid THEN 'Answer from Internal Documents'
                    WHEN '{ML_PREDICT_TOOL_ID}'::uuid THEN 'Predict Room Demand'
                END,
                annotations_json = '{annotations}'::jsonb
            WHERE tool_id IN (
                '{ANALYSIS_GET_RUN_TOOL_ID}',
                '{ANALYSIS_RUN_TOOL_ID}',
                '{RAG_ANSWER_TOOL_ID}',
                '{ML_PREDICT_TOOL_ID}'
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 4 THEN
                RAISE EXCEPTION 'MCP registry metadata backfill did not update four receipts';
            END IF;
        END $$
        """
    )
    op.execute(
        f"""
        ALTER TABLE tooling.tool_registry
            ALTER COLUMN title SET NOT NULL,
            ALTER COLUMN annotations_json SET NOT NULL,
            ADD CONSTRAINT tool_registry_title_check CHECK (
                length(btrim(title)) BETWEEN 1 AND 160 AND title = btrim(title)
            ),
            ADD CONSTRAINT tool_registry_annotations_check CHECK (
                annotations_json = '{annotations}'::jsonb
            );
        ALTER TABLE tooling.tool_runs
            DROP CONSTRAINT tool_runs_status_check,
            ADD CONSTRAINT tool_runs_status_check CHECK (
                status IN ('SUCCEEDED','FAILED','DENIED','CANCELLED')
            )
        """
    )


def downgrade() -> None:
    """새 취소 receipt·registry metadata drift가 있으면 정보를 삭제하지 않는다."""

    annotations = _json(READ_ONLY_ANNOTATIONS)
    op.execute(
        f"""
        LOCK TABLE tooling.tool_runs IN SHARE ROW EXCLUSIVE MODE;
        LOCK TABLE tooling.tool_registry IN SHARE ROW EXCLUSIVE MODE;
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tooling.tool_runs WHERE status = 'CANCELLED'
            ) THEN
                RAISE EXCEPTION 'MCP cancelled Tool receipts must be preserved';
            END IF;
            IF (SELECT count(*) FROM tooling.tool_registry) <> 4
               OR EXISTS (
                    SELECT 1 FROM tooling.tool_registry
                    WHERE annotations_json <> '{annotations}'::jsonb
                       OR (tool_id = '{ANALYSIS_GET_RUN_TOOL_ID}' AND title <> 'Get Analysis Run')
                       OR (tool_id = '{ANALYSIS_RUN_TOOL_ID}' AND title <> 'Run Approved Analysis')
                       OR (tool_id = '{RAG_ANSWER_TOOL_ID}' AND title <> 'Answer from Internal Documents')
                       OR (tool_id = '{ML_PREDICT_TOOL_ID}' AND title <> 'Predict Room Demand')
                       OR tool_id NOT IN (
                            '{ANALYSIS_GET_RUN_TOOL_ID}',
                            '{ANALYSIS_RUN_TOOL_ID}',
                            '{RAG_ANSWER_TOOL_ID}',
                            '{ML_PREDICT_TOOL_ID}'
                       )
               ) THEN
                RAISE EXCEPTION 'MCP registry metadata must be preserved before downgrade';
            END IF;
        END $$;
        ALTER TABLE tooling.tool_runs
            DROP CONSTRAINT tool_runs_status_check,
            ADD CONSTRAINT tool_runs_status_check CHECK (
                status IN ('SUCCEEDED','FAILED','DENIED')
            );
        ALTER TABLE tooling.tool_registry
            DROP CONSTRAINT tool_registry_annotations_check,
            DROP CONSTRAINT tool_registry_title_check,
            DROP COLUMN annotations_json,
            DROP COLUMN title
        """
    )
