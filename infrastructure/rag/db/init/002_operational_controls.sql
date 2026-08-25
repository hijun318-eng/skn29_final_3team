CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS document_versions (
    version_id BIGSERIAL PRIMARY KEY,
    manual_id TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    document_status TEXT NOT NULL,
    authority_level TEXT NOT NULL,
    validity_status TEXT NOT NULL,
    role_scope TEXT[] NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archive_reason TEXT NOT NULL,
    UNIQUE (manual_id, content_checksum)
);

CREATE TABLE IF NOT EXISTS document_chunk_versions (
    version_id BIGINT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    section_title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    embedding vector(1024) NOT NULL,
    PRIMARY KEY (version_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS document_lifecycle_logs (
    event_id BIGSERIAL PRIMARY KEY,
    manual_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('VERSION_ARCHIVED', 'UPSERT', 'SOFT_DELETE', 'RESTORE')),
    actor_role TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_document_versions_manual
    ON document_versions (manual_id, archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_lifecycle_logs_manual
    ON document_lifecycle_logs (manual_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
    ON documents USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm
    ON document_chunks USING GIN (content gin_trgm_ops);
