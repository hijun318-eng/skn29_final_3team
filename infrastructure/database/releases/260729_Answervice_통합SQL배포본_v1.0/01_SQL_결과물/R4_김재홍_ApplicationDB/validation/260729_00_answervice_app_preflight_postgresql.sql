-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=R4_김재홍
-- work_card=R4-APP-DB
-- 목적: Application DDL 실행 전에 기존 19개 P0/P1 테이블의 컬럼·타입·NULL 계약을 일괄 검사한다.
-- 주의: 이 파일은 CREATE TABLE을 수행하지 않는다. SCHEMA_CONTRACT_MISMATCH 발생 시 DDL을 실행하지 않는다.
\set ON_ERROR_STOP on
\connect answervice_app

CREATE OR REPLACE FUNCTION pg_temp.assert_table_contract(
    p_schema text,
    p_table text,
    p_expected text[]
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_actual text[];
    v_reg regclass;
BEGIN
    v_reg := to_regclass(format('%I.%I', p_schema, p_table));
    IF v_reg IS NULL THEN
        RETURN;
    END IF;

    SELECT array_agg(
               a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull::text
               ORDER BY a.attnum
           )
      INTO v_actual
      FROM pg_attribute a
     WHERE a.attrelid = v_reg
       AND a.attnum > 0
       AND NOT a.attisdropped;

    IF v_actual IS DISTINCT FROM p_expected THEN
        RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH %.% expected %, actual %',
            p_schema, p_table, p_expected, v_actual;
    END IF;
END
$$;

SELECT pg_temp.assert_table_contract('connection', 'data_sources', ARRAY['data_source_id:uuid:true', 'source_code:character varying(32):true', 'source_name:character varying(120):true', 'engine_type:character varying(24):true', 'platform_instance:character varying(128):true', 'trino_catalog:character varying(128):true', 'datahub_recipe_ref:character varying(255):true', 'connection_ref:character varying(255):true', 'owner_team:character varying(100):true', 'status:character varying(16):true', 'last_health_status:character varying(16):false', 'last_health_at:timestamp with time zone:false', 'created_at:timestamp with time zone:true', 'updated_at:timestamp with time zone:true']::text[]);
SELECT pg_temp.assert_table_contract('connection', 'ingestion_runs', ARRAY['ingestion_run_id:uuid:true', 'data_source_id:uuid:true', 'datahub_run_id:character varying(160):false', 'recipe_version:character varying(64):true', 'status:character varying(16):true', 'asset_count:integer:true', 'column_count:integer:true', 'started_at:timestamp with time zone:false', 'completed_at:timestamp with time zone:false', 'error_code:character varying(64):false', 'error_message_redacted:text:false']::text[]);
SELECT pg_temp.assert_table_contract('context', 'context_records', ARRAY['context_record_id:uuid:true', 'record_type:character varying(32):true', 'record_key:character varying(160):true', 'version_no:integer:true', 'payload_json:jsonb:true', 'status:character varying(16):true', 'owner_role:character varying(64):true', 'approved_by:uuid:false', 'approved_at:timestamp with time zone:false', 'valid_from:timestamp with time zone:true', 'valid_to:timestamp with time zone:false', 'checksum:character varying(64):true']::text[]);
SELECT pg_temp.assert_table_contract('context', 'context_releases', ARRAY['context_release_id:uuid:true', 'release_key:character varying(128):true', 'version_no:integer:true', 'included_record_refs_json:jsonb:true', 'status:character varying(16):true', 'release_hash:character varying(64):true', 'published_by:uuid:false', 'published_at:timestamp with time zone:false', 'rollback_release_id:uuid:false']::text[]);
SELECT pg_temp.assert_table_contract('context', 'context_packages', ARRAY['context_package_id:uuid:true', 'request_id:uuid:true', 'context_release_id:uuid:true', 'user_scope_json:jsonb:true', 'assets_json:jsonb:true', 'metrics_json:jsonb:true', 'joins_json:jsonb:true', 'policies_json:jsonb:true', 'dataset_count:smallint:true', 'column_count:smallint:true', 'token_count:integer:true', 'package_hash:character varying(64):true', 'created_at:timestamp with time zone:true']::text[]);
SELECT pg_temp.assert_table_contract('chat', 'conversations', ARRAY['conversation_id:uuid:true', 'owner_user_id:uuid:true', 'title:character varying(255):true', 'status:character varying(16):true', 'created_at:timestamp with time zone:true', 'updated_at:timestamp with time zone:true']::text[]);
SELECT pg_temp.assert_table_contract('chat', 'analysis_requests', ARRAY['request_id:uuid:true', 'conversation_id:uuid:false', 'request_type:character varying(24):true', 'user_id:uuid:true', 'user_role:character varying(64):true', 'question_text_redacted:text:true', 'question_hash:character varying(64):true', 'ambiguity_status:character varying(16):true', 'context_release_id:uuid:false', 'context_package_id:uuid:false', 'sql_generation_model_id:uuid:false', 'sql_policy_version:character varying(64):true', 'status:character varying(20):true', 'error_type:character varying(24):false', 'trace_id:character varying(128):true', 'started_at:timestamp with time zone:true', 'completed_at:timestamp with time zone:false']::text[]);
SELECT pg_temp.assert_table_contract('query', 'query_executions', ARRAY['query_execution_id:uuid:true', 'request_id:uuid:true', 'attempt_no:smallint:true', 'generation_mode:character varying(20):true', 'generated_sql_redacted:text:true', 'sql_hash:character varying(64):true', 'ast_validation_json:jsonb:true', 'join_validation_json:jsonb:true', 'permission_validation_json:jsonb:true', 'explain_json:jsonb:true', 'validation_status:character varying(16):true', 'trino_query_id:character varying(128):false', 'execution_status:character varying(16):true', 'row_count:integer:true', 'scan_bytes:bigint:true', 'duration_ms:integer:false', 'result_checksum:character varying(64):false', 'source_urns_json:jsonb:true', 'source_cutoff_json:jsonb:true', 'error_code:character varying(64):false', 'error_message_redacted:text:false']::text[]);
SELECT pg_temp.assert_table_contract('artifact', 'analysis_artifacts', ARRAY['artifact_id:uuid:true', 'request_id:uuid:true', 'query_execution_id:uuid:false', 'artifact_type:character varying(20):true', 'title:character varying(255):true', 'data_snapshot_json:jsonb:true', 'chart_spec_json:jsonb:true', 'narrative_markdown:text:false', 'evidence_json:jsonb:true', 'freshness_status:character varying(16):true', 'status:character varying(16):true', 'artifact_checksum:character varying(64):true']::text[]);
SELECT pg_temp.assert_table_contract('report', 'report_definitions', ARRAY['report_definition_id:uuid:true', 'report_key:character varying(128):true', 'version_no:integer:true', 'title:character varying(255):true', 'period_type:character varying(16):true', 'owner_user_id:uuid:true', 'timezone_name:character varying(64):true', 'layout_columns:smallint:true', 'schedule_cron:character varying(64):false', 'schedule_enabled:boolean:true', 'status:character varying(16):true', 'approved_by:uuid:false', 'approved_at:timestamp with time zone:false']::text[]);
SELECT pg_temp.assert_table_contract('report', 'report_blocks', ARRAY['report_block_id:uuid:true', 'report_definition_id:uuid:true', 'block_key:character varying(128):true', 'block_type:character varying(16):true', 'source_mode:character varying(16):true', 'source_artifact_id:uuid:false', 'question_text_redacted:text:false', 'filter_json:jsonb:true', 'grid_x:smallint:true', 'grid_y:smallint:true', 'grid_w:smallint:true', 'grid_h:smallint:true', 'display_config_json:jsonb:true', 'approval_status:character varying(16):true']::text[]);
SELECT pg_temp.assert_table_contract('report', 'report_runs', ARRAY['report_run_id:uuid:true', 'report_definition_id:uuid:true', 'trigger_type:character varying(16):true', 'triggered_by:uuid:false', 'status:character varying(16):true', 'context_release_id:uuid:true', 'sql_policy_version:character varying(64):true', 'period_start:timestamp with time zone:true', 'period_end:timestamp with time zone:true', 'source_cutoff_json:jsonb:true', 'snapshot_checksum:character varying(64):false']::text[]);
SELECT pg_temp.assert_table_contract('report', 'block_runs', ARRAY['block_run_id:uuid:true', 'report_run_id:uuid:true', 'report_block_id:uuid:true', 'request_id:uuid:false', 'query_execution_id:uuid:false', 'artifact_id:uuid:false', 'status:character varying(16):true', 'fallback_mode:character varying(24):true', 'source_cutoff_json:jsonb:true', 'result_checksum:character varying(64):false', 'error_code:character varying(64):false', 'error_message_redacted:text:false']::text[]);
SELECT pg_temp.assert_table_contract('governance', 'audit_events', ARRAY['audit_event_id:uuid:true', 'request_id:uuid:false', 'actor_user_id:uuid:false', 'actor_role:character varying(64):true', 'action_code:character varying(96):true', 'object_type:character varying(64):true', 'object_id:character varying(128):true', 'context_release_id:uuid:false', 'model_version_id:uuid:false', 'sql_policy_version:character varying(64):false', 'query_execution_id:uuid:false', 'artifact_id:uuid:false', 'report_run_id:uuid:false', 'details_json_redacted:jsonb:true', 'trace_id:character varying(128):false', 'created_at:timestamp with time zone:true']::text[]);
SELECT pg_temp.assert_table_contract('model', 'model_versions', ARRAY['model_version_id:uuid:true', 'model_role:character varying(24):true', 'model_name:character varying(160):true', 'checkpoint_ref:character varying(255):true', 'model_revision:character varying(128):true', 'variant_type:character varying(16):true', 'parent_model_version_id:uuid:false', 'license_name:character varying(128):true', 'runtime_name:character varying(64):true', 'container_image_digest:character varying(255):true', 'precision_quantization:character varying(64):false', 'artifact_ref:character varying(512):false', 'status:character varying(16):true']::text[]);
SELECT pg_temp.assert_table_contract('model', 'evaluation_runs', ARRAY['evaluation_run_id:uuid:true', 'model_version_id:uuid:true', 'comparison_group_id:uuid:false', 'evaluation_set_version:character varying(64):true', 'context_release_id:uuid:true', 'sql_policy_version:character varying(64):true', 'runpod_environment_json:jsonb:true', 'generation_config_json:jsonb:true', 'metrics_json:jsonb:true', 'failure_counts_json:jsonb:true', 'pod_runtime_seconds:integer:false', 'experiment_cost:numeric(14,2):false', 'status:character varying(16):true']::text[]);
SELECT pg_temp.assert_table_contract('reference', 'market_benchmark_annual', ARRAY['benchmark_id:uuid:true', 'benchmark_year:smallint:true', 'population_code:character varying(64):true', 'occupancy_rate:numeric(9,6):false', 'adr_krw:numeric(14,2):false', 'revpar_krw:numeric(14,2):false', 'reference_status:character varying(32):true', 'source_name:character varying(255):true', 'source_url:text:true', 'published_at:date:false', 'extracted_at:timestamp with time zone:true', 'notes:text:false']::text[]);
SELECT pg_temp.assert_table_contract('reference', 'demand_index_monthly', ARRAY['demand_index_id:uuid:true', 'year:smallint:true', 'month:smallint:true', 'demand_type:character varying(24):true', 'index_value:numeric(12,6):true', 'yoy_growth_rate:numeric(12,6):false', 'influence_weight:numeric(12,6):true', 'population_code:character varying(64):true', 'data_status:character varying(32):true', 'source_name:character varying(255):true', 'source_url:text:true', 'published_at:date:false', 'extracted_at:timestamp with time zone:true']::text[]);
SELECT pg_temp.assert_table_contract('reference', 'calendar_daily', ARRAY['business_date:date:true', 'year:smallint:true', 'quarter:smallint:true', 'month:smallint:true', 'week_of_year:smallint:true', 'day_of_week:smallint:true', 'is_weekend:boolean:true', 'is_public_holiday:boolean:true', 'is_holiday_eve:boolean:true', 'season_code:character varying(24):true', 'school_vacation_code:character varying(24):false', 'domestic_travel_index:numeric(12,6):true', 'inbound_travel_index:numeric(12,6):true', 'event_demand_index:numeric(12,6):true', 'weather_scenario_code:character varying(32):true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'created_at:timestamp with time zone:true']::text[]);

SELECT 'APPLICATION_COLUMN_PREFLIGHT_PASS' AS status,
       current_database() AS database_name,
       19 AS expected_p0_p1_tables,
       0 AS expected_p2_tables;
