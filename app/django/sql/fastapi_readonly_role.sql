-- ==========================================================================
-- SensePlace DSG v2.0 — FastAPI Read-Only Role (PostgreSQL)
--
-- FastAPI 앱이 사용할 전용 read-only 역할을 생성한다.
-- fact, dim, metric_catalog 테이블과 analytics view에만 접근 가능하며,
-- platform 테이블(query_run, analysis_run, report 등)은 쓰기 불가.
--
-- 사용 전 생성:
--   CREATE ROLE senseplace_readonly WITH LOGIN PASSWORD '<password>';
--
-- 이 스크립트는 GRANT만 수행한다.
-- ==========================================================================

-- --------------------------------------------------------------------------
-- 1. 스키마 사용 권한
-- --------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO senseplace_readonly;

-- --------------------------------------------------------------------------
-- 2. 메타데이터 테이블 — 읽기 전용
-- --------------------------------------------------------------------------
GRANT SELECT ON TABLE dataset_manifest   TO senseplace_readonly;
GRANT SELECT ON TABLE dim_date            TO senseplace_readonly;
GRANT SELECT ON TABLE dim_service_area    TO senseplace_readonly;

-- --------------------------------------------------------------------------
-- 3. Fact 테이블 — 읽기 전용
-- --------------------------------------------------------------------------
GRANT SELECT ON TABLE fact_rooms_daily     TO senseplace_readonly;
GRANT SELECT ON TABLE fact_breakfast_15m   TO senseplace_readonly;
GRANT SELECT ON TABLE fact_breakfast_daily TO senseplace_readonly;
GRANT SELECT ON TABLE fact_staff_shift     TO senseplace_readonly;
GRANT SELECT ON TABLE fact_voc             TO senseplace_readonly;

-- --------------------------------------------------------------------------
-- 4. Platform 테이블 — metric_catalog 읽기만 허용
--    query_run, analysis_run, evidence, report 등은 FastAPI가 직접
--    수정하지 않으므로 SELECT만 허용. field_note는 Django가 소유.
-- --------------------------------------------------------------------------
GRANT SELECT ON TABLE metric_catalog   TO senseplace_readonly;
GRANT SELECT ON TABLE role_scope        TO senseplace_readonly;
GRANT SELECT ON TABLE query_run         TO senseplace_readonly;
GRANT SELECT ON TABLE analysis_run      TO senseplace_readonly;
GRANT SELECT ON TABLE evidence          TO senseplace_readonly;
GRANT SELECT ON TABLE report            TO senseplace_readonly;
GRANT SELECT ON TABLE report_decision   TO senseplace_readonly;
GRANT SELECT ON TABLE field_note        TO senseplace_readonly;

-- --------------------------------------------------------------------------
-- 5. Analytics View — 읽기 전용
-- --------------------------------------------------------------------------
GRANT SELECT ON TABLE v_rooms_daily         TO senseplace_readonly;
GRANT SELECT ON TABLE v_breakfast_15m       TO senseplace_readonly;
GRANT SELECT ON TABLE v_breakfast_daily     TO senseplace_readonly;
GRANT SELECT ON TABLE v_staff_shift         TO senseplace_readonly;
GRANT SELECT ON TABLE v_voc_summary         TO senseplace_readonly;
GRANT SELECT ON TABLE v_incident_evidence   TO senseplace_readonly;

-- --------------------------------------------------------------------------
-- 6. future table 권한 (ALTER DEFAULT)
--    이후 새로 생성되는 테이블에도 자동으로 SELECT 권한 부여
-- --------------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO senseplace_readonly;
