-- 005_rag_model_trace.sql
-- Add tracing columns to capture model versions and chunks used for ingestion/retrieval

ALTER TABLE ingestion_runs
ADD COLUMN IF NOT EXISTS chunking_schema_version VARCHAR(50),
ADD COLUMN IF NOT EXISTS embedding_profile_id VARCHAR(100);

ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS token_count INTEGER DEFAULT 0;

-- Optional: Create a table for answer tracing
CREATE TABLE IF NOT EXISTS answer_traces (
    request_id UUID PRIMARY KEY,
    trace_id UUID NOT NULL,
    query_hash VARCHAR(64) NOT NULL,
    status VARCHAR(50) NOT NULL,
    latency_ms REAL,
    model_id VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
