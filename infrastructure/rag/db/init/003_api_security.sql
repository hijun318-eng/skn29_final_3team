CREATE TABLE IF NOT EXISTS api_security_audit_logs (
    event_id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    presented_role TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('AUTHORIZED', 'DENIED', 'ERROR')),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_security_audit_created
    ON api_security_audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_security_audit_request
    ON api_security_audit_logs (request_id);

CREATE TABLE IF NOT EXISTS api_request_nonces (
    request_id UUID PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_request_nonces_expiry
    ON api_request_nonces (expires_at);

ALTER TABLE api_security_audit_logs
    DROP CONSTRAINT IF EXISTS api_security_audit_logs_outcome_check;
ALTER TABLE api_security_audit_logs
    ADD CONSTRAINT api_security_audit_logs_outcome_check
    CHECK (outcome IN ('AUTHORIZED', 'DENIED', 'ERROR'));
