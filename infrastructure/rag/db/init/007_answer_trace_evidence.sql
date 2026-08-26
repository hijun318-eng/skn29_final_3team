-- Link final answers to their retrieval request and cited evidence.
ALTER TABLE answer_traces
ADD COLUMN IF NOT EXISTS retrieval_request_id UUID,
ADD COLUMN IF NOT EXISTS answer_hash VARCHAR(64),
ADD COLUMN IF NOT EXISTS answer_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS citation_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS citation_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_answer_traces_retrieval_request_id
ON answer_traces(retrieval_request_id);
