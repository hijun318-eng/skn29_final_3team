-- Bind each answer request to the exact active release and evidence returned by search.
CREATE TABLE IF NOT EXISTS retrieval_evidence_receipts (
    receipt_id UUID PRIMARY KEY,
    release_id UUID NOT NULL REFERENCES corpus_releases(release_id),
    user_role TEXT NOT NULL CHECK (length(btrim(user_role)) > 0),
    answer_intent TEXT NOT NULL CHECK (length(btrim(answer_intent)) > 0),
    trace_id VARCHAR(128) NOT NULL
        CHECK (length(btrim(trace_id)) BETWEEN 1 AND 128),
    actor_hash TEXT NOT NULL CHECK (actor_hash ~ '^[0-9a-f]{64}$'),
    answer_query_sha256 TEXT NOT NULL
        CHECK (answer_query_sha256 ~ '^[0-9a-f]{64}$'),
    evidence_ids TEXT[] NOT NULL
        CHECK (cardinality(evidence_ids) <= 50),
    evidence_payload JSONB NOT NULL
        CHECK (jsonb_typeof(evidence_payload) = 'array'),
    evidence_payload_sha256 TEXT NOT NULL
        CHECK (evidence_payload_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL
        DEFAULT (CURRENT_TIMESTAMP + INTERVAL '5 minutes'),
    consumed_at TIMESTAMPTZ,
    CHECK (expires_at > created_at),
    CHECK (consumed_at IS NULL OR consumed_at < expires_at)
);

-- Development environments may have executed the earlier receipt draft.
-- Never silently delete an unbound receipt during migration: operators must
-- let its TTL elapse or remove it explicitly, then replay this script.
ALTER TABLE retrieval_evidence_receipts
    ADD COLUMN IF NOT EXISTS answer_intent TEXT,
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS actor_hash TEXT,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
        DEFAULT (CURRENT_TIMESTAMP + INTERVAL '5 minutes'),
    ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMPTZ;
ALTER TABLE retrieval_evidence_receipts
    ALTER COLUMN trace_id TYPE VARCHAR(128) USING trace_id::text;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM retrieval_evidence_receipts
        WHERE answer_intent IS NULL OR trace_id IS NULL OR actor_hash IS NULL
    ) THEN
        RAISE EXCEPTION
            'unbound retrieval receipts require explicit expiry or cleanup before migration';
    END IF;
END;
$$;
ALTER TABLE retrieval_evidence_receipts
    ALTER COLUMN answer_intent SET NOT NULL,
    ALTER COLUMN trace_id SET NOT NULL,
    ALTER COLUMN actor_hash SET NOT NULL,
    ALTER COLUMN expires_at SET DEFAULT (CURRENT_TIMESTAMP + INTERVAL '5 minutes'),
    ALTER COLUMN expires_at SET NOT NULL;
ALTER TABLE retrieval_evidence_receipts
    DROP CONSTRAINT IF EXISTS retrieval_evidence_receipts_answer_intent_check;
ALTER TABLE retrieval_evidence_receipts
    ADD CONSTRAINT retrieval_evidence_receipts_answer_intent_check
    CHECK (length(btrim(answer_intent)) > 0);
ALTER TABLE retrieval_evidence_receipts
    DROP CONSTRAINT IF EXISTS retrieval_evidence_receipts_trace_id_check;
ALTER TABLE retrieval_evidence_receipts
    ADD CONSTRAINT retrieval_evidence_receipts_trace_id_check
    CHECK (length(btrim(trace_id)) BETWEEN 1 AND 128);
ALTER TABLE retrieval_evidence_receipts
    DROP CONSTRAINT IF EXISTS retrieval_evidence_receipts_actor_hash_check;
ALTER TABLE retrieval_evidence_receipts
    ADD CONSTRAINT retrieval_evidence_receipts_actor_hash_check
    CHECK (actor_hash ~ '^[0-9a-f]{64}$');
ALTER TABLE retrieval_evidence_receipts
    DROP CONSTRAINT IF EXISTS retrieval_evidence_receipts_expires_at_check;
ALTER TABLE retrieval_evidence_receipts
    ADD CONSTRAINT retrieval_evidence_receipts_expires_at_check
    CHECK (expires_at > created_at);
ALTER TABLE retrieval_evidence_receipts
    DROP CONSTRAINT IF EXISTS retrieval_evidence_receipts_consumed_at_check;
ALTER TABLE retrieval_evidence_receipts
    ADD CONSTRAINT retrieval_evidence_receipts_consumed_at_check
    CHECK (consumed_at IS NULL OR consumed_at < expires_at);

CREATE INDEX IF NOT EXISTS idx_retrieval_evidence_receipts_release
    ON retrieval_evidence_receipts (release_id, created_at DESC);
DROP INDEX IF EXISTS idx_retrieval_evidence_receipts_expires;
CREATE INDEX idx_retrieval_evidence_receipts_expires
    ON retrieval_evidence_receipts (expires_at);
