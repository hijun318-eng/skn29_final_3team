-- Answervice P2 optional PostgreSQL DDL
-- prerequisite=vector; embedding_dimension=1024; schema_version=1.0.0
\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tooling.tool_registry (
    tool_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_code varchar(96) NOT NULL UNIQUE,
    tool_type varchar(16) NOT NULL CHECK (tool_type IN ('SQL','DATAHUB','RAG','ML')),
    semantic_version varchar(32) NOT NULL,
    name varchar(160) NOT NULL,
    description text NOT NULL,
    input_schema_json jsonb NOT NULL,
    output_schema_json jsonb NOT NULL,
    transport varchar(24) NOT NULL CHECK (transport IN ('INTERNAL','HTTP','MCP_STDIO','MCP_SSE')),
    endpoint_ref varchar(255),
    timeout_seconds integer NOT NULL CHECK (timeout_seconds > 0),
    required_roles_json jsonb NOT NULL,
    tool_hints_json jsonb NOT NULL,
    is_enabled boolean NOT NULL DEFAULT false,
    health_status varchar(16) NOT NULL CHECK (health_status IN ('HEALTHY','DEGRADED','DOWN','UNKNOWN'))
);

CREATE TABLE IF NOT EXISTS tooling.tool_runs (
    tool_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id uuid NOT NULL REFERENCES tooling.tool_registry(tool_id),
    request_id uuid REFERENCES chat.analysis_requests(request_id),
    caller_user_id uuid,
    input_hash varchar(64) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','DENIED','TIMEOUT')),
    latency_ms integer CHECK (latency_ms >= 0),
    output_ref_json jsonb NOT NULL,
    error_code varchar(64),
    error_message_redacted text
);

CREATE TABLE IF NOT EXISTS rag.rag_documents (
    document_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_key varchar(128) NOT NULL,
    title varchar(255) NOT NULL,
    version_label varchar(64) NOT NULL,
    document_type varchar(24) NOT NULL CHECK (document_type IN ('MANUAL','POLICY','PROMOTION','CONTRACT')),
    owner_team varchar(100) NOT NULL,
    access_roles_json jsonb NOT NULL,
    effective_from date NOT NULL,
    expires_at date,
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','ACTIVE','EXPIRED','RETIRED')),
    source_uri_ref varchar(512) NOT NULL,
    content_checksum varchar(64) NOT NULL,
    UNIQUE (document_key, version_label),
    CHECK (expires_at IS NULL OR expires_at >= effective_from)
);

CREATE TABLE IF NOT EXISTS rag.rag_chunks (
    chunk_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES rag.rag_documents(document_version_id),
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    section_path varchar(255) NOT NULL,
    content_text text NOT NULL,
    embedding_model_id uuid NOT NULL REFERENCES model.model_versions(model_version_id),
    embedding vector(1024) NOT NULL,
    metadata_json jsonb NOT NULL,
    UNIQUE (document_version_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS ml.feature_sets (
    feature_set_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_set_key varchar(128) NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    name varchar(160) NOT NULL,
    owner_team varchar(100) NOT NULL,
    feature_schema_json jsonb NOT NULL,
    source_asset_urns_json jsonb NOT NULL,
    feature_query_sql_hash varchar(64) NOT NULL,
    sql_policy_version varchar(64) NOT NULL,
    event_time_field varchar(255) NOT NULL,
    as_of_rule_json jsonb NOT NULL,
    missing_value_policy_json jsonb NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('DRAFT','APPROVED','RETIRED')),
    UNIQUE (feature_set_key, version_no)
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_tool ON tooling.tool_runs(tool_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document ON rag.rag_chunks(document_version_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_model ON rag.rag_chunks(embedding_model_id);

COMMENT ON TABLE tooling.tool_registry IS 'P2 versioned tool contract; disabled before gate approval';
COMMENT ON TABLE tooling.tool_runs IS 'P2 tool execution evidence';
COMMENT ON TABLE rag.rag_documents IS 'P2 synthetic document versions';
COMMENT ON TABLE rag.rag_chunks IS 'P2 retrieval chunks with vector(1024)';
COMMENT ON TABLE ml.feature_sets IS 'P2 feature-set registration payload target';

SELECT count(*) AS application_p2_table_count
FROM information_schema.tables
WHERE table_schema IN ('tooling','rag','ml')
  AND table_type = 'BASE TABLE';
