-- Isolated P2 RAG PoC contract foundation. This migration does not approve the P2 gate.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS document_type TEXT NOT NULL DEFAULT 'MANUAL',
    ADD COLUMN IF NOT EXISTS owner_team TEXT NOT NULL DEFAULT 'UNASSIGNED',
    ADD COLUMN IF NOT EXISTS effective_from DATE,
    ADD COLUMN IF NOT EXISTS expires_at DATE,
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'NOT_APPROVED';

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_validity_window_check;
ALTER TABLE documents ADD CONSTRAINT documents_validity_window_check
    CHECK (expires_at IS NULL OR effective_from IS NULL OR expires_at >= effective_from);

ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS document_type TEXT NOT NULL DEFAULT 'MANUAL',
    ADD COLUMN IF NOT EXISTS owner_team TEXT NOT NULL DEFAULT 'UNASSIGNED',
    ADD COLUMN IF NOT EXISTS effective_from DATE,
    ADD COLUMN IF NOT EXISTS expires_at DATE,
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'NOT_APPROVED';

ALTER TABLE retrieval_audit_logs
    ADD COLUMN IF NOT EXISTS request_id TEXT,
    ADD COLUMN IF NOT EXISTS trace_id TEXT,
    ADD COLUMN IF NOT EXISTS session_id TEXT,
    ADD COLUMN IF NOT EXISTS actor_hash TEXT,
    ADD COLUMN IF NOT EXISTS tool_code TEXT,
    ADD COLUMN IF NOT EXISTS tool_version TEXT,
    ADD COLUMN IF NOT EXISTS as_of TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS router_decision_id TEXT,
    ADD COLUMN IF NOT EXISTS parent_artifact_id TEXT,
    ADD COLUMN IF NOT EXISTS report_run_id TEXT,
    ADD COLUMN IF NOT EXISTS error_code TEXT;

CREATE TABLE IF NOT EXISTS tool_registry (
    tool_code TEXT PRIMARY KEY,
    tool_type TEXT NOT NULL CHECK (tool_type IN ('SQL', 'DATAHUB', 'RAG', 'ML')),
    semantic_version TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_team TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    input_schema_json JSONB NOT NULL,
    output_schema_json JSONB NOT NULL,
    transport TEXT NOT NULL,
    endpoint_ref TEXT,
    timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds > 0),
    maximum_retries INTEGER NOT NULL DEFAULT 0 CHECK (maximum_retries >= 0),
    required_roles TEXT[] NOT NULL,
    data_scope TEXT NOT NULL,
    read_only BOOLEAN NOT NULL,
    destructive BOOLEAN NOT NULL,
    idempotent BOOLEAN NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('SQL_EVIDENCE', 'DOCUMENT_EVIDENCE')),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    approval_status TEXT NOT NULL DEFAULT 'NOT_APPROVED',
    health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (NOT enabled OR approval_status = 'APPROVED')
);

CREATE TABLE IF NOT EXISTS tool_runs (
    tool_run_id UUID PRIMARY KEY,
    tool_code TEXT NOT NULL REFERENCES tool_registry(tool_code),
    request_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'DENIED', 'TIMEOUT')
    ),
    latency_ms DOUBLE PRECISION CHECK (latency_ms >= 0),
    result_count INTEGER CHECK (result_count >= 0),
    error_code TEXT,
    error_message_redacted TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE tool_registry
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_documents_validity_window
    ON documents (effective_from, expires_at) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_retrieval_audit_request
    ON retrieval_audit_logs (request_id);
CREATE INDEX IF NOT EXISTS idx_tool_runs_request
    ON tool_runs (request_id, created_at DESC);

INSERT INTO tool_registry(
    tool_code, tool_type, semantic_version, name, description, owner_team, risk_level,
    input_schema_json, output_schema_json, transport, endpoint_ref,
    timeout_seconds, maximum_retries, required_roles, data_scope,
    read_only, destructive, idempotent, evidence_type, enabled, approval_status
) VALUES (
    'internal-manual-search', 'RAG', '2.0.0', 'Internal manual search',
    'Resolve business-domain context and search approved internal manuals with evidence.',
    'UNASSIGNED', 'INTERNAL_RESTRICTED',
    '{"type":"object","additionalProperties":false,"required":["query","resolved_question","domains","intent"],"properties":{"query":{"type":"string","minLength":2,"maxLength":500},"resolved_question":{"type":"string","minLength":2,"maxLength":500},"domains":{"type":"array","maxItems":3,"items":{"type":"string"}},"intent":{"type":"string"},"recent_utterances":{"type":"array","maxItems":3,"items":{"type":"string","minLength":1,"maxLength":500}},"selected_document_ids":{"type":"array","maxItems":10,"items":{"type":"string","minLength":1,"maxLength":100}}}}'::jsonb,
    '{"type":"object","required":["request_id","document_evidence","warnings"]}'::jsonb,
    'INTERNAL_HTTP', '/v1/tools/internal-manual-search', 30, 0,
    ARRAY['hotel_analyst','report_admin','data_admin'], 'INTERNAL_MANUALS',
    TRUE, FALSE, TRUE, 'DOCUMENT_EVIDENCE', FALSE, 'NOT_APPROVED'
) ON CONFLICT (tool_code) DO UPDATE SET
    semantic_version=EXCLUDED.semantic_version,
    name=EXCLUDED.name,
    description=EXCLUDED.description,
    input_schema_json=EXCLUDED.input_schema_json,
    output_schema_json=EXCLUDED.output_schema_json,
    required_roles=EXCLUDED.required_roles,
    enabled=tool_registry.enabled,
    approval_status=tool_registry.approval_status,
    updated_at=CURRENT_TIMESTAMP;
