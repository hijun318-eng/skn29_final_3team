from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

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
        corpus_release_id: str | None = None,
        answer_query_sha256: str | None = None,
        answer_intent: str | None = None,
        answer_evidence: list[dict[str, str]] | None = None,
    ) -> None:
        if request_id is None or tool_code is None:
            raise ValueError("RAG search audit requires a request and tool identity")
        try:
            receipt_id = UUID(request_id)
            release_id = UUID(str(corpus_release_id))
        except (TypeError, ValueError) as error:
            raise ValueError("RAG retrieval receipt identity is invalid") from error
        resolved_trace_id = trace_id or request_id
        if (
            not role.strip()
            or not resolved_trace_id.strip()
            or len(resolved_trace_id) > 128
            or actor_hash is None
            or len(actor_hash) != 64
            or any(character not in "0123456789abcdef" for character in actor_hash)
            or answer_intent is None
            or not answer_intent.strip()
            or answer_query_sha256 is None
            or len(answer_query_sha256) != 64
            or any(character not in "0123456789abcdef" for character in answer_query_sha256)
            or answer_evidence is None
            or len(answer_evidence) > 50
        ):
            raise ValueError("RAG retrieval receipt contract is invalid")
        evidence_ids = [str(item.get("evidence_id") or "") for item in answer_evidence]
        if any(not evidence_id for evidence_id in evidence_ids) or len(
            evidence_ids
        ) != len(set(evidence_ids)):
            raise ValueError("RAG retrieval receipt evidence identity is invalid")
        canonical_evidence = json.dumps(
            answer_evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        evidence_sha256 = hashlib.sha256(
            canonical_evidence.encode("utf-8")
        ).hexdigest()
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                DELETE FROM retrieval_evidence_receipts
                WHERE expires_at<=CURRENT_TIMESTAMP
                """
            )
            active = connection.execute(
                """
                SELECT release.release_id
                FROM corpus_active_release active
                JOIN corpus_releases release ON release.release_id=active.release_id
                WHERE active.singleton=TRUE
                  AND release.release_id=%s
                  AND release.status='ACTIVE'
                  AND release.embedding_provider=%s
                  AND release.embedding_model=%s
                  AND release.embedding_dimensions=%s
                  AND release.embedding_version=%s
                  AND release.corpus_manifest_sha256=%s
                  AND release.processing_profile_sha256=%s
                  AND (SELECT COALESCE(
                          jsonb_object_agg(d.manual_id, d.content_checksum),
                          '{}'::jsonb
                       ) FROM corpus_release_documents d
                       WHERE d.release_id=release.release_id)=%s::jsonb
                FOR SHARE OF active, release
                """,
                (
                    release_id,
                    *self._active_release_parameters(),
                    json.dumps(self._required_documents(), sort_keys=True),
                ),
            ).fetchone()
            if active is None:
                raise RuntimeError(
                    "RAG active release changed before retrieval receipt commit"
                )
            connection.execute(
                """
                INSERT INTO retrieval_evidence_receipts(
                    receipt_id, release_id, user_role, answer_intent, trace_id,
                    actor_hash, answer_query_sha256, evidence_ids,
                    evidence_payload, evidence_payload_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    receipt_id,
                    release_id,
                    role,
                    answer_intent.strip(),
                    resolved_trace_id,
                    actor_hash,
                    answer_query_sha256,
                    evidence_ids,
                    canonical_evidence,
                    evidence_sha256,
                ),
            )
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
                    resolved_trace_id, tool_code, tool_version,
                    as_of, session_id, actor_hash, router_decision_id,
                    parent_artifact_id, report_run_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO tool_runs(
                    tool_run_id, tool_code, request_id, trace_id, input_hash,
                    status, latency_ms, result_count
                ) VALUES (%s, %s, %s, %s, %s, 'SUCCEEDED', %s, %s)
                """,
                (
                    uuid4(), tool_code, request_id, resolved_trace_id,
                    query_hash, latency_ms, count,
                ),
            )

    def status(self) -> dict[str, object]:
        with psycopg.connect(self._database_url) as connection:
            extension = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).fetchone()
            documents = connection.execute(
                """
                SELECT COUNT(*)
                FROM corpus_active_release active
                JOIN corpus_release_documents document
                  ON document.release_id=active.release_id
                WHERE active.singleton=TRUE
                """
            ).fetchone()[0]
            chunks = connection.execute(
                """
                SELECT COUNT(*)
                FROM corpus_active_release active
                JOIN corpus_release_chunks chunk
                  ON chunk.release_id=active.release_id
                WHERE active.singleton=TRUE
                """
            ).fetchone()[0]
            audits = connection.execute("SELECT COUNT(*) FROM retrieval_audit_logs").fetchone()[0]
            dimension = connection.execute(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid='corpus_release_chunks'::regclass AND attname='embedding'"
            ).fetchone()[0]
            embeddings = connection.execute(
                """SELECT embedding_provider, embedding_model, embedding_dimensions, embedding_version, COUNT(*)
                   FROM corpus_active_release active
                   JOIN corpus_release_chunks chunk
                     ON chunk.release_id=active.release_id
                   WHERE active.singleton=TRUE AND chunk.deleted_at IS NULL
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
