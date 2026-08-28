-- 책임: application control-plane의 빈 schema와 데이터 무결성 제약만 생성한다.
-- 요청별 seed를 넣지 않으며 DDL 하나라도 실패하면 ON_ERROR_STOP으로 bootstrap을 중단한다.
-- Answervice Application PostgreSQL DDL
-- schema_version=1.0.0; PostgreSQL>=15; required_extension=pgcrypto
\set ON_ERROR_STOP on
SET client_encoding = 'UTF8';
SET timezone = 'Asia/Seoul';

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS connection;
CREATE SCHEMA IF NOT EXISTS context;
CREATE SCHEMA IF NOT EXISTS chat;
CREATE SCHEMA IF NOT EXISTS query;
CREATE SCHEMA IF NOT EXISTS artifact;
CREATE SCHEMA IF NOT EXISTS report;
CREATE SCHEMA IF NOT EXISTS governance;
CREATE SCHEMA IF NOT EXISTS model;
CREATE SCHEMA IF NOT EXISTS tooling;
CREATE SCHEMA IF NOT EXISTS rag;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS connection.data_sources (
    data_source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code varchar(32) NOT NULL UNIQUE,
    source_name varchar(120) NOT NULL,
    engine_type varchar(24) NOT NULL CHECK (engine_type IN ('POSTGRESQL','MYSQL','SQLSERVER','CLICKHOUSE')),
    platform_instance varchar(128) NOT NULL UNIQUE,
    trino_catalog varchar(128) NOT NULL UNIQUE,
    datahub_recipe_ref varchar(255) NOT NULL,
    connection_ref varchar(255) NOT NULL CHECK (connection_ref !~* '(password|token|secret)='),
    owner_team varchar(100) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','ACTIVE','ERROR','DISABLED')),
    last_health_status varchar(16) CHECK (last_health_status IN ('HEALTHY','DEGRADED','DOWN','UNKNOWN')),
    last_health_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connection.ingestion_runs (
    ingestion_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_source_id uuid NOT NULL REFERENCES connection.data_sources(data_source_id),
    datahub_run_id varchar(160),
    recipe_version varchar(64) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','PARTIAL','FAILED')),
    asset_count integer NOT NULL CHECK (asset_count >= 0),
    column_count integer NOT NULL CHECK (column_count >= 0),
    started_at timestamptz,
    completed_at timestamptz,
    error_code varchar(64),
    error_message_redacted text,
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS context.context_records (
    context_record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_type varchar(32) NOT NULL CHECK (record_type IN (
        'ASSET_BINDING','METRIC_DEFINITION','TIME_POLICY','DIMENSION_HISTORY_POLICY',
        'JOIN_POLICY','TERM_ALIAS','COLUMN_POLICY_REF'
    )),
    record_key varchar(160) NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    payload_json jsonb NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','APPROVED','DEPRECATED')),
    owner_role varchar(64) NOT NULL,
    approved_by uuid,
    approved_at timestamptz,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    checksum varchar(64) NOT NULL,
    UNIQUE (record_type, record_key, version_no),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE IF NOT EXISTS context.context_releases (
    context_release_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_key varchar(128) NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    included_record_refs_json jsonb NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','PUBLISHED','RETIRED')),
    release_hash varchar(64) NOT NULL,
    published_by uuid,
    published_at timestamptz,
    rollback_release_id uuid REFERENCES context.context_releases(context_release_id),
    UNIQUE (release_key, version_no)
);

CREATE TABLE IF NOT EXISTS chat.conversations (
    conversation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL,
    title varchar(255) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('ACTIVE','ARCHIVED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model.model_versions (
    model_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_role varchar(24) NOT NULL CHECK (model_role IN ('SQL_GENERATION','EXPLANATION','EMBEDDING','RERANKER','ML_PREDICT')),
    model_name varchar(160) NOT NULL,
    checkpoint_ref varchar(255) NOT NULL,
    model_revision varchar(128) NOT NULL,
    variant_type varchar(16) NOT NULL CHECK (variant_type IN ('BASELINE','LORA','QLORA','ONNX')),
    parent_model_version_id uuid REFERENCES model.model_versions(model_version_id),
    license_name varchar(128) NOT NULL,
    runtime_name varchar(64) NOT NULL,
    container_image_digest varchar(255) NOT NULL,
    precision_quantization varchar(64),
    artifact_ref varchar(512),
    status varchar(16) NOT NULL CHECK (status IN ('CANDIDATE','APPROVED','REJECTED','DEPLOYED'))
);

CREATE TABLE IF NOT EXISTS chat.analysis_requests (
    request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid REFERENCES chat.conversations(conversation_id),
    request_type varchar(24) NOT NULL CHECK (request_type IN ('CHAT','BLOCK_PREVIEW','REPORT_BLOCK','MODEL_EVAL')),
    user_id uuid NOT NULL,
    user_role varchar(64) NOT NULL,
    question_text_redacted text NOT NULL,
    question_hash varchar(64) NOT NULL,
    ambiguity_status varchar(16) NOT NULL CHECK (ambiguity_status IN ('CLEAR','NEEDS_CLARIFICATION','RESOLVED')),
    context_release_id uuid REFERENCES context.context_releases(context_release_id),
    context_package_id uuid,
    sql_generation_model_id uuid REFERENCES model.model_versions(model_version_id),
    sql_policy_version varchar(64) NOT NULL,
    status varchar(20) NOT NULL,
    error_type varchar(24),
    trace_id varchar(128) NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS context.context_packages (
    context_package_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL UNIQUE REFERENCES chat.analysis_requests(request_id),
    context_release_id uuid NOT NULL REFERENCES context.context_releases(context_release_id),
    user_scope_json jsonb NOT NULL,
    assets_json jsonb NOT NULL,
    metrics_json jsonb NOT NULL,
    joins_json jsonb NOT NULL,
    policies_json jsonb NOT NULL,
    dataset_count smallint NOT NULL CHECK (dataset_count BETWEEN 0 AND 8),
    column_count smallint NOT NULL CHECK (column_count BETWEEN 0 AND 60),
    token_count integer NOT NULL CHECK (token_count BETWEEN 0 AND 6000),
    package_hash varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_analysis_request_context_package'
    ) THEN
        ALTER TABLE chat.analysis_requests
        ADD CONSTRAINT fk_analysis_request_context_package
        FOREIGN KEY (context_package_id)
        REFERENCES context.context_packages(context_package_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS query.query_executions (
    query_execution_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL REFERENCES chat.analysis_requests(request_id),
    attempt_no smallint NOT NULL CHECK (attempt_no > 0),
    generation_mode varchar(20) NOT NULL CHECK (generation_mode IN ('LLM','TEMPLATE','COMPILER')),
    generated_sql_redacted text NOT NULL,
    sql_hash varchar(64) NOT NULL,
    ast_validation_json jsonb NOT NULL,
    join_validation_json jsonb NOT NULL,
    permission_validation_json jsonb NOT NULL,
    explain_json jsonb NOT NULL,
    validation_status varchar(16) NOT NULL CHECK (validation_status IN ('PENDING','ALLOWED','BLOCKED','FAILED')),
    trino_query_id varchar(128),
    execution_status varchar(16) NOT NULL CHECK (execution_status IN ('NOT_STARTED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    row_count integer NOT NULL CHECK (row_count >= 0),
    scan_bytes bigint NOT NULL CHECK (scan_bytes >= 0),
    duration_ms integer CHECK (duration_ms >= 0),
    result_checksum varchar(64),
    source_urns_json jsonb NOT NULL,
    source_cutoff_json jsonb NOT NULL,
    error_code varchar(64),
    error_message_redacted text,
    UNIQUE (request_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS artifact.analysis_artifacts (
    artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL REFERENCES chat.analysis_requests(request_id),
    query_execution_id uuid REFERENCES query.query_executions(query_execution_id),
    artifact_type varchar(20) NOT NULL CHECK (artifact_type IN ('TABLE','CHART','KPI','TEXT','COMPOSITE')),
    title varchar(255) NOT NULL,
    data_snapshot_json jsonb NOT NULL,
    chart_spec_json jsonb NOT NULL,
    narrative_markdown text,
    evidence_json jsonb NOT NULL,
    freshness_status varchar(16) NOT NULL CHECK (freshness_status IN ('FRESH','STALE','PARTIAL')),
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','APPROVED','INVALIDATED')),
    artifact_checksum varchar(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS report.report_definitions (
    report_definition_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_key varchar(128) NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    title varchar(255) NOT NULL,
    period_type varchar(16) NOT NULL CHECK (period_type IN ('DAILY','WEEKLY','MONTHLY')),
    owner_user_id uuid NOT NULL,
    timezone_name varchar(64) NOT NULL,
    layout_columns smallint NOT NULL CHECK (layout_columns = 12),
    schedule_cron varchar(64),
    schedule_enabled boolean NOT NULL DEFAULT false,
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','APPROVED','RETIRED')),
    approved_by uuid,
    approved_at timestamptz,
    UNIQUE (report_key, version_no)
);

CREATE TABLE IF NOT EXISTS report.report_blocks (
    report_block_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_definition_id uuid NOT NULL REFERENCES report.report_definitions(report_definition_id),
    block_key varchar(128) NOT NULL,
    block_type varchar(16) NOT NULL CHECK (block_type IN ('TEXT','KPI','TABLE','CHART')),
    source_mode varchar(16) NOT NULL CHECK (source_mode IN ('ARTIFACT','QUESTION')),
    source_artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
    question_text_redacted text,
    filter_json jsonb NOT NULL,
    grid_x smallint NOT NULL CHECK (grid_x BETWEEN 0 AND 11),
    grid_y smallint NOT NULL CHECK (grid_y >= 0),
    grid_w smallint NOT NULL CHECK (grid_w BETWEEN 1 AND 12),
    grid_h smallint NOT NULL CHECK (grid_h >= 1),
    display_config_json jsonb NOT NULL,
    approval_status varchar(16) NOT NULL CHECK (approval_status IN ('DRAFT','APPROVED','REJECTED')),
    UNIQUE (report_definition_id, block_key)
);

CREATE TABLE IF NOT EXISTS report.report_runs (
    report_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_definition_id uuid NOT NULL REFERENCES report.report_definitions(report_definition_id),
    trigger_type varchar(16) NOT NULL CHECK (trigger_type IN ('MANUAL','SCHEDULE')),
    triggered_by uuid,
    status varchar(16) NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED')),
    context_release_id uuid NOT NULL REFERENCES context.context_releases(context_release_id),
    sql_policy_version varchar(64) NOT NULL,
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL,
    source_cutoff_json jsonb NOT NULL,
    snapshot_checksum varchar(64),
    CHECK (period_end > period_start)
);

CREATE TABLE IF NOT EXISTS report.block_runs (
    block_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_run_id uuid NOT NULL REFERENCES report.report_runs(report_run_id),
    report_block_id uuid NOT NULL REFERENCES report.report_blocks(report_block_id),
    request_id uuid REFERENCES chat.analysis_requests(request_id),
    query_execution_id uuid REFERENCES query.query_executions(query_execution_id),
    artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
    status varchar(16) NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED')),
    fallback_mode varchar(24) NOT NULL CHECK (fallback_mode IN ('NONE','LAST_SUCCESS','TEMPLATE')),
    source_cutoff_json jsonb NOT NULL,
    result_checksum varchar(64),
    error_code varchar(64),
    error_message_redacted text
);

CREATE TABLE IF NOT EXISTS governance.audit_events (
    audit_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid REFERENCES chat.analysis_requests(request_id),
    actor_user_id uuid,
    actor_role varchar(64) NOT NULL,
    action_code varchar(96) NOT NULL,
    object_type varchar(64) NOT NULL,
    object_id varchar(128) NOT NULL,
    context_release_id uuid REFERENCES context.context_releases(context_release_id),
    model_version_id uuid REFERENCES model.model_versions(model_version_id),
    sql_policy_version varchar(64),
    query_execution_id uuid REFERENCES query.query_executions(query_execution_id),
    artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
    report_run_id uuid REFERENCES report.report_runs(report_run_id),
    details_json_redacted jsonb NOT NULL,
    trace_id varchar(128),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model.evaluation_runs (
    evaluation_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES model.model_versions(model_version_id),
    comparison_group_id uuid,
    evaluation_set_version varchar(64) NOT NULL,
    context_release_id uuid NOT NULL REFERENCES context.context_releases(context_release_id),
    sql_policy_version varchar(64) NOT NULL,
    runpod_environment_json jsonb NOT NULL,
    generation_config_json jsonb NOT NULL,
    metrics_json jsonb NOT NULL,
    failure_counts_json jsonb NOT NULL,
    pod_runtime_seconds integer CHECK (pod_runtime_seconds >= 0),
    experiment_cost numeric(14,2) CHECK (experiment_cost >= 0),
    status varchar(16) NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','CANCELLED'))
);

CREATE TABLE IF NOT EXISTS reference.market_benchmark_annual (
    benchmark_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 데이터 유효기간은 runtime catalog가 판단한다. 배포 연도로 상한을 고정하면
    -- 다음 연도의 정상 데이터가 schema 단계에서 영구 거절되므로 달력 범위만 검증한다.
    benchmark_year smallint NOT NULL CHECK (benchmark_year BETWEEN 1 AND 9999),
    population_code varchar(64) NOT NULL,
    occupancy_rate numeric(9,6) CHECK (occupancy_rate BETWEEN 0 AND 1),
    adr_krw numeric(14,2) CHECK (adr_krw >= 0),
    revpar_krw numeric(14,2) CHECK (revpar_krw >= 0),
    reference_status varchar(32) NOT NULL CHECK (reference_status IN ('PUBLISHED','NOT_AVAILABLE')),
    source_name varchar(255) NOT NULL,
    source_url text NOT NULL,
    published_at date,
    extracted_at timestamptz NOT NULL,
    notes text,
    UNIQUE (benchmark_year, population_code)
);

CREATE TABLE IF NOT EXISTS reference.demand_index_monthly (
    demand_index_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 특정 시연 기간이 아닌 ISO-8601의 일반적인 4자리 달력 연도를 허용한다.
    year smallint NOT NULL CHECK (year BETWEEN 1 AND 9999),
    month smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    demand_type varchar(24) NOT NULL CHECK (demand_type IN ('DOMESTIC','INBOUND','EVENT')),
    index_value numeric(12,6) NOT NULL CHECK (index_value >= 0),
    yoy_growth_rate numeric(12,6),
    influence_weight numeric(12,6) NOT NULL CHECK (influence_weight BETWEEN 0 AND 1),
    population_code varchar(64) NOT NULL,
    data_status varchar(32) NOT NULL CHECK (data_status IN ('FINAL','PRELIMINARY','FORECAST')),
    source_name varchar(255) NOT NULL,
    source_url text NOT NULL,
    published_at date,
    extracted_at timestamptz NOT NULL,
    UNIQUE (year, month, demand_type)
);

CREATE TABLE IF NOT EXISTS reference.calendar_daily (
    business_date date PRIMARY KEY,
    year smallint NOT NULL,
    quarter smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    week_of_year smallint NOT NULL CHECK (week_of_year BETWEEN 1 AND 53),
    day_of_week smallint NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    is_weekend boolean NOT NULL,
    is_public_holiday boolean NOT NULL,
    is_holiday_eve boolean NOT NULL,
    season_code varchar(24) NOT NULL CHECK (season_code IN ('SPRING','SUMMER','AUTUMN','WINTER')),
    school_vacation_code varchar(24),
    domestic_travel_index numeric(12,6) NOT NULL,
    inbound_travel_index numeric(12,6) NOT NULL,
    event_demand_index numeric(12,6) NOT NULL,
    weather_scenario_code varchar(32) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source ON connection.ingestion_runs(data_source_id);
CREATE INDEX IF NOT EXISTS idx_context_records_lookup ON context.context_records(record_type, status, record_key, version_no);
CREATE INDEX IF NOT EXISTS idx_analysis_requests_status ON chat.analysis_requests(status, started_at);
CREATE INDEX IF NOT EXISTS idx_query_executions_request ON query.query_executions(request_id, execution_status);
CREATE INDEX IF NOT EXISTS idx_artifacts_request ON artifact.analysis_artifacts(request_id, status);
CREATE INDEX IF NOT EXISTS idx_report_runs_period ON report.report_runs(report_definition_id, period_start, status);
CREATE INDEX IF NOT EXISTS idx_audit_request_time ON governance.audit_events(request_id, created_at);

CREATE TABLE IF NOT EXISTS governance.schema_version (version varchar(32) PRIMARY KEY);
-- The application schema version is a reproducible compatibility boundary.
-- No dataset seed is asserted by schema bootstrap.
INSERT INTO governance.schema_version(version) VALUES ('1.0.0') ON CONFLICT (version) DO NOTHING;

COMMENT ON TABLE connection.data_sources IS 'v4.6 source, DataHub recipe, and Trino catalog binding';
COMMENT ON TABLE connection.ingestion_runs IS 'DataHub ingestion execution evidence';
COMMENT ON TABLE context.context_records IS 'Versioned approved context records';
COMMENT ON TABLE context.context_releases IS 'Immutable context release';
COMMENT ON TABLE context.context_packages IS 'Per-request approved context package';
COMMENT ON TABLE chat.conversations IS 'Analysis conversation';
COMMENT ON TABLE chat.analysis_requests IS 'Analysis request and trace root';
COMMENT ON TABLE query.query_executions IS 'Guarded SQL execution attempt';
COMMENT ON TABLE artifact.analysis_artifacts IS 'Evidence-backed analysis artifact';
COMMENT ON TABLE report.report_definitions IS 'Versioned report definition';
COMMENT ON TABLE report.report_blocks IS 'Report block definition';
COMMENT ON TABLE report.report_runs IS 'Report execution';
COMMENT ON TABLE report.block_runs IS 'Report block execution';
COMMENT ON TABLE governance.audit_events IS 'Append-only governance audit event';
COMMENT ON TABLE model.model_versions IS 'Registered model version';
COMMENT ON TABLE model.evaluation_runs IS 'Model evaluation execution';
COMMENT ON TABLE reference.market_benchmark_annual IS 'Published annual market calibration anchor';
COMMENT ON TABLE reference.demand_index_monthly IS 'Monthly external demand index';
COMMENT ON TABLE reference.calendar_daily IS 'Daily calendar and period-state contract';

SELECT count(*) AS application_p0_p1_table_count
FROM information_schema.tables
WHERE table_schema IN ('connection','context','chat','query','artifact','report','governance','model','reference')
  AND table_type = 'BASE TABLE';
