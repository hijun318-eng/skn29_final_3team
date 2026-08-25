ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS embedding_provider TEXT,
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER,
    ADD COLUMN IF NOT EXISTS embedding_version TEXT,
    ADD COLUMN IF NOT EXISTS source_document_hash TEXT,
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

UPDATE document_chunks
SET embedding_provider=COALESCE(embedding_provider, 'qwen'),
    embedding_model=COALESCE(embedding_model, 'Qwen/Qwen3-Embedding-0.6B'),
    embedding_dimensions=COALESCE(embedding_dimensions, 1024),
    embedding_version=COALESCE(embedding_version, 'legacy-qwen3-0.6b'),
    source_document_hash=COALESCE(source_document_hash, content_checksum),
    embedded_at=COALESCE(embedded_at, created_at);

ALTER TABLE ingestion_runs
    ADD COLUMN IF NOT EXISTS embedding_provider TEXT,
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER,
    ADD COLUMN IF NOT EXISTS embedding_version TEXT;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_version
    ON document_chunks (embedding_provider, embedding_model, embedding_version)
    WHERE deleted_at IS NULL;
