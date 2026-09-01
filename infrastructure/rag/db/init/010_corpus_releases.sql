-- Stage immutable corpus releases separately and publish exactly one active release.
-- Existing live tables are intentionally not promoted: an upgraded database remains
-- fail-closed until a complete manifest-backed release is ingested and published.

CREATE TABLE IF NOT EXISTS corpus_releases (
    release_id UUID PRIMARY KEY REFERENCES ingestion_runs(run_id),
    status TEXT NOT NULL CHECK (status IN ('STAGING', 'ACTIVE', 'RETIRED', 'FAILED')),
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    embedding_version TEXT NOT NULL,
    corpus_manifest_sha256 TEXT NOT NULL,
    processing_profile_sha256 TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0 CHECK (document_count >= 0),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ
);

-- Keep rerunning the ordered init directory safe for an upgrade that first saw
-- an earlier pre-release shape of this table. No legacy row is auto-promoted.
ALTER TABLE corpus_releases
    ADD COLUMN IF NOT EXISTS corpus_manifest_sha256 TEXT;
ALTER TABLE corpus_releases
    ADD COLUMN IF NOT EXISTS processing_profile_sha256 TEXT;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM corpus_releases
        WHERE corpus_manifest_sha256 IS NULL
           OR processing_profile_sha256 IS NULL
    ) THEN
        RAISE EXCEPTION 'existing corpus release has no validated manifest hash';
    END IF;
END $$;
ALTER TABLE corpus_releases
    ALTER COLUMN corpus_manifest_sha256 SET NOT NULL,
    ALTER COLUMN processing_profile_sha256 SET NOT NULL;
ALTER TABLE corpus_releases
    DROP CONSTRAINT IF EXISTS corpus_releases_manifest_sha256_check;
ALTER TABLE corpus_releases
    ADD CONSTRAINT corpus_releases_manifest_sha256_check
    CHECK (corpus_manifest_sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE corpus_releases
    DROP CONSTRAINT IF EXISTS corpus_releases_processing_profile_sha256_check;
ALTER TABLE corpus_releases
    ADD CONSTRAINT corpus_releases_processing_profile_sha256_check
    CHECK (processing_profile_sha256 ~ '^[0-9a-f]{64}$');

CREATE UNIQUE INDEX IF NOT EXISTS uq_corpus_releases_one_active
    ON corpus_releases ((status)) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS corpus_active_release (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    release_id UUID UNIQUE REFERENCES corpus_releases(release_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO corpus_active_release(singleton, release_id)
VALUES (TRUE, NULL)
ON CONFLICT(singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS corpus_release_documents (
    release_id UUID NOT NULL REFERENCES corpus_releases(release_id) ON DELETE CASCADE,
    manual_id TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    document_status TEXT NOT NULL DEFAULT 'WORKING_KNOWLEDGE',
    authority_level TEXT NOT NULL DEFAULT 'INTERNAL_WORKING_GUIDE',
    validity_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
    role_scope TEXT[] NOT NULL,
    document_type TEXT NOT NULL DEFAULT 'MANUAL',
    owner_team TEXT NOT NULL DEFAULT 'UNASSIGNED',
    effective_from DATE,
    expires_at DATE,
    approval_status TEXT NOT NULL DEFAULT 'NOT_APPROVED',
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (release_id, manual_id),
    UNIQUE (release_id, source_path),
    CHECK (expires_at IS NULL OR effective_from IS NULL OR expires_at >= effective_from)
);

CREATE TABLE IF NOT EXISTS corpus_release_chunks (
    release_id UUID NOT NULL,
    chunk_id TEXT NOT NULL,
    manual_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    section_title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    embedding vector(1024) NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    embedding_version TEXT NOT NULL,
    source_document_hash TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ,
    PRIMARY KEY (release_id, chunk_id),
    FOREIGN KEY (release_id, manual_id)
        REFERENCES corpus_release_documents(release_id, manual_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_corpus_release_documents_role_scope
    ON corpus_release_documents USING GIN (role_scope);
CREATE INDEX IF NOT EXISTS idx_corpus_release_documents_active
    ON corpus_release_documents (release_id, document_status, validity_status)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_corpus_release_chunks_manual
    ON corpus_release_chunks (release_id, manual_id, page_start, chunk_index)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_corpus_release_chunks_metadata
    ON corpus_release_chunks (
        release_id, embedding_provider, embedding_model,
        embedding_dimensions, embedding_version
    ) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_corpus_release_chunks_embedding_hnsw
    ON corpus_release_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_corpus_release_documents_title_trgm
    ON corpus_release_documents USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_corpus_release_chunks_content_trgm
    ON corpus_release_chunks USING GIN (content gin_trgm_ops);

-- Published corpus rows are immutable. The only legal mutation of a published
-- release is the atomic ACTIVE -> RETIRED transition performed while publishing
-- its successor; every other field must remain byte-for-byte identical.
CREATE OR REPLACE FUNCTION guard_published_corpus_release_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status IN ('ACTIVE', 'RETIRED') THEN
            RAISE EXCEPTION 'published corpus release % must be activated from staging', NEW.release_id;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('ACTIVE', 'RETIRED') THEN
            RAISE EXCEPTION 'published corpus release % is immutable', OLD.release_id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.status = 'RETIRED' THEN
        RAISE EXCEPTION 'retired corpus release % is immutable', OLD.release_id;
    END IF;

    IF OLD.status = 'ACTIVE' AND (
        NEW.status <> 'RETIRED'
        OR (to_jsonb(NEW) - 'status') IS DISTINCT FROM
           (to_jsonb(OLD) - 'status')
    ) THEN
        RAISE EXCEPTION 'active corpus release % only permits retirement', OLD.release_id;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_published_corpus_release_mutation
    ON corpus_releases;
CREATE TRIGGER trg_guard_published_corpus_release_mutation
BEFORE INSERT OR UPDATE OR DELETE ON corpus_releases
FOR EACH ROW EXECUTE FUNCTION guard_published_corpus_release_mutation();

CREATE OR REPLACE FUNCTION guard_published_corpus_content_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    source_status TEXT;
    target_status TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT status INTO target_status
        FROM corpus_releases
        WHERE release_id = NEW.release_id
        FOR UPDATE;

        IF target_status IN ('ACTIVE', 'RETIRED') THEN
            RAISE EXCEPTION 'published corpus content for release % is immutable', NEW.release_id;
        END IF;
        RETURN NEW;
    END IF;

    SELECT status INTO source_status
    FROM corpus_releases
    WHERE release_id = OLD.release_id
    FOR UPDATE;

    IF source_status IN ('ACTIVE', 'RETIRED') THEN
        RAISE EXCEPTION 'published corpus content for release % is immutable', OLD.release_id;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    IF NEW.release_id IS DISTINCT FROM OLD.release_id THEN
        RAISE EXCEPTION 'corpus content cannot move between releases';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_published_corpus_documents_mutation
    ON corpus_release_documents;
CREATE TRIGGER trg_guard_published_corpus_documents_mutation
BEFORE INSERT OR UPDATE OR DELETE ON corpus_release_documents
FOR EACH ROW EXECUTE FUNCTION guard_published_corpus_content_mutation();

DROP TRIGGER IF EXISTS trg_guard_published_corpus_chunks_mutation
    ON corpus_release_chunks;
CREATE TRIGGER trg_guard_published_corpus_chunks_mutation
BEFORE INSERT OR UPDATE OR DELETE ON corpus_release_chunks
FOR EACH ROW EXECUTE FUNCTION guard_published_corpus_content_mutation();
