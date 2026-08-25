CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    manual_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    document_status TEXT NOT NULL DEFAULT 'WORKING_KNOWLEDGE',
    authority_level TEXT NOT NULL DEFAULT 'INTERNAL_WORKING_GUIDE',
    validity_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
    role_scope TEXT[] NOT NULL,
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    manual_id TEXT NOT NULL REFERENCES documents(manual_id),
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    section_title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    embedding vector(1024) NOT NULL,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS retrieval_audit_logs (
    audit_id BIGSERIAL PRIMARY KEY,
    query_hash TEXT NOT NULL,
    user_role TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_role_scope ON documents USING GIN (role_scope);
CREATE INDEX IF NOT EXISTS idx_documents_active ON documents (document_status, validity_status)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chunks_manual_active ON document_chunks (manual_id)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw ON document_chunks
    USING hnsw (embedding vector_cosine_ops);
