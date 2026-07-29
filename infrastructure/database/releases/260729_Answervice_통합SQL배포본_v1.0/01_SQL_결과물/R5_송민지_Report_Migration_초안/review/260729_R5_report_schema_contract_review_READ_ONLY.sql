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
-- owner=R5_송민지
-- work_card=R5-REPORT-MIGRATION-DRAFT
-- READ_ONLY_REVIEW_ONLY=true
-- 이 파일은 migration이 아니며 CREATE/ALTER/DROP/INSERT/UPDATE/DELETE를 수행하지 않는다.
-- R4가 최종 Alembic chain에 통합하기 전까지 실행 가능한 schema 변경 산출물로 간주하지 않는다.
\set ON_ERROR_STOP on
\connect answervice_app

WITH expected(table_name, column_name, ordinal_no) AS (
  VALUES
  ('report_definitions','report_definition_id',1),('report_definitions','report_key',2),
  ('report_definitions','version_no',3),('report_definitions','title',4),
  ('report_definitions','period_type',5),('report_definitions','owner_user_id',6),
  ('report_definitions','timezone_name',7),('report_definitions','layout_columns',8),
  ('report_definitions','schedule_cron',9),('report_definitions','schedule_enabled',10),
  ('report_definitions','status',11),('report_definitions','approved_by',12),('report_definitions','approved_at',13),
  ('report_blocks','report_block_id',1),('report_blocks','report_definition_id',2),
  ('report_blocks','block_key',3),('report_blocks','block_type',4),('report_blocks','source_mode',5),
  ('report_blocks','source_artifact_id',6),('report_blocks','question_text_redacted',7),
  ('report_blocks','filter_json',8),('report_blocks','grid_x',9),('report_blocks','grid_y',10),
  ('report_blocks','grid_w',11),('report_blocks','grid_h',12),('report_blocks','display_config_json',13),
  ('report_blocks','approval_status',14),
  ('report_runs','report_run_id',1),('report_runs','report_definition_id',2),('report_runs','trigger_type',3),
  ('report_runs','triggered_by',4),('report_runs','status',5),('report_runs','context_release_id',6),
  ('report_runs','sql_policy_version',7),('report_runs','period_start',8),('report_runs','period_end',9),
  ('report_runs','source_cutoff_json',10),('report_runs','snapshot_checksum',11),
  ('block_runs','block_run_id',1),('block_runs','report_run_id',2),('block_runs','report_block_id',3),
  ('block_runs','request_id',4),('block_runs','query_execution_id',5),('block_runs','artifact_id',6),
  ('block_runs','status',7),('block_runs','fallback_mode',8),('block_runs','source_cutoff_json',9),
  ('block_runs','result_checksum',10),('block_runs','error_code',11),('block_runs','error_message_redacted',12)
), actual AS (
  SELECT table_name,column_name,ordinal_position
  FROM information_schema.columns WHERE table_schema='report'
)
SELECT 'missing_report_column' check_name,count(*) violation_count
FROM expected e LEFT JOIN actual a USING(table_name,column_name)
WHERE a.column_name IS NULL
UNION ALL
SELECT 'unexpected_report_column',count(*)
FROM actual a LEFT JOIN expected e USING(table_name,column_name)
WHERE e.column_name IS NULL
UNION ALL
SELECT 'report_column_order_mismatch',count(*)
FROM expected e JOIN actual a USING(table_name,column_name)
WHERE e.ordinal_no<>a.ordinal_position;

SELECT tc.table_name,tc.constraint_name,tc.constraint_type
FROM information_schema.table_constraints tc
WHERE tc.table_schema='report'
ORDER BY tc.table_name,tc.constraint_type,tc.constraint_name;

SELECT 'NO_SCHEMA_DELTA_REQUIRED_UNLESS_REVIEW_FINDS_VIOLATION' AS draft_status;
