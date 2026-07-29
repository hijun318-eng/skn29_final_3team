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
-- owner=R1_박준희
-- work_card=R1-INTEGRATION-GATE
-- Application 영역 read-only gate. R1은 DDL을 생성하지 않는다.
\set ON_ERROR_STOP on
\connect answervice_app

SELECT 'p0_p1_table_count' check_name,
       count(*) actual_count, 19 expected_count,
       CASE WHEN count(*)=19 THEN 'PASS' ELSE 'FAILED' END status
FROM information_schema.tables
WHERE table_type='BASE TABLE'
  AND table_schema IN ('connection','context','chat','query','artifact','report','governance','model','reference');

SELECT 'p2_table_count' check_name,
       count(*) actual_count,0 expected_count,
       CASE WHEN count(*)=0 THEN 'PASS' ELSE 'P2_NOT_APPROVED' END status
FROM information_schema.tables
WHERE table_type='BASE TABLE' AND table_schema IN ('tooling','rag','ml');

SELECT 'alembic_head_count' check_name,
       CASE WHEN to_regclass('public.alembic_version') IS NULL THEN 0 ELSE (SELECT count(*) FROM public.alembic_version) END actual_count,
       1 expected_count,
       CASE WHEN to_regclass('public.alembic_version') IS NOT NULL AND (SELECT count(*) FROM public.alembic_version)=1
            THEN 'PASS' ELSE 'ALEMBIC_MULTI_HEAD_RISK' END status;
