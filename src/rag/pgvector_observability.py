from __future__ import annotations

from uuid import uuid4

import psycopg


class PgVectorObservabilityMixin:
    _database_url: str

    def audit_search(
        self,
        query_hash: str,
        role: str,
        count: int,
        latency_ms: float,
        request_id: str | None = None,
        trace_id: str | None = None,
        tool_code: str | None = None,
        tool_version: str | None = None,
        as_of: str | None = None,
        session_id: str | None = None,
        actor_hash: str | None = None,
        router_decision_id: str | None = None,
        parent_artifact_id: str | None = None,
        report_run_id: str | None = None,
    ) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO retrieval_audit_logs(
                    query_hash, user_role, result_count, latency_ms,
                    request_id, trace_id, tool_code, tool_version, as_of,
                    session_id, actor_hash, router_decision_id,
                    parent_artifact_id, report_run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    query_hash, role, count, latency_ms, request_id,
                    trace_id or request_id, tool_code, tool_version,
                    as_of, session_id, actor_hash, router_decision_id,
                    parent_artifact_id, report_run_id,
                ),
            )
            if request_id and tool_code:
                connection.execute(
                    """
                    INSERT INTO tool_runs(
                        tool_run_id, tool_code, request_id, trace_id, input_hash,
                        status, latency_ms, result_count
                    ) VALUES (%s, %s, %s, %s, %s, 'SUCCEEDED', %s, %s)
                    """,
                    (
                        uuid4(), tool_code, request_id, trace_id or request_id,
                        query_hash, latency_ms, count,
                    ),
                )

    def status(self) -> dict[str, object]:
        with psycopg.connect(self._database_url) as connection:
            extension = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).fetchone()
            documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
            audits = connection.execute("SELECT COUNT(*) FROM retrieval_audit_logs").fetchone()[0]
            dimension = connection.execute(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid='document_chunks'::regclass AND attname='embedding'"
            ).fetchone()[0]
            embeddings = connection.execute(
                """SELECT embedding_provider, embedding_model, embedding_dimensions, embedding_version, COUNT(*)
                   FROM document_chunks WHERE deleted_at IS NULL
                   GROUP BY embedding_provider, embedding_model, embedding_dimensions, embedding_version
                   ORDER BY embedding_provider, embedding_model"""
            ).fetchall()
        return {
            "pgvector_version": extension[0] if extension else None,
            "documents": documents,
            "chunks": chunks,
            "audits": audits,
            "embedding_dimension": dimension,
            "embedding_sets": [{"provider": row[0], "model": row[1], "dimensions": row[2], "version": row[3], "chunks": row[4]} for row in embeddings],
        }
