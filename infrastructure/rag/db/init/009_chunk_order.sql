ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS chunk_index INTEGER;

WITH ordered AS (
    SELECT chunk_id,
           ROW_NUMBER() OVER (
               PARTITION BY manual_id, page_start
               ORDER BY created_at, chunk_id
           ) - 1 AS inferred_index
    FROM document_chunks
)
UPDATE document_chunks AS chunk
SET chunk_index = ordered.inferred_index
FROM ordered
WHERE chunk.chunk_id = ordered.chunk_id
  AND chunk.chunk_index IS NULL;

ALTER TABLE document_chunks
    ALTER COLUMN chunk_index SET DEFAULT 0,
    ALTER COLUMN chunk_index SET NOT NULL;

ALTER TABLE document_chunk_versions
    ADD COLUMN IF NOT EXISTS chunk_index INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_chunks_source_order
    ON document_chunks(manual_id, page_start, chunk_index)
    WHERE deleted_at IS NULL;
