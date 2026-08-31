"""활성 corpus release의 source·평가·ingestion 증적을 read-only 조회한다."""

from __future__ import annotations

import json
import re

import psycopg


class RagEvidenceRepository:
    """embedding·manifest·처리 profile이 일치하는 활성 release만 증적으로 노출한다."""

    def __init__(
        self,
        database_url: str,
        expected_embedding: dict[str, object],
        corpus_manifest_sha256: str,
        expected_documents: dict[str, str],
        processing_profile_sha256: str,
    ) -> None:
        self._database_url = database_url
        if (
            set(expected_embedding) != {"provider", "model", "dimensions", "version"}
            or not isinstance(expected_embedding["provider"], str)
            or not expected_embedding["provider"]
            or not isinstance(expected_embedding["model"], str)
            or not expected_embedding["model"]
            or type(expected_embedding["dimensions"]) is not int
            or int(expected_embedding["dimensions"]) <= 0
            or not isinstance(expected_embedding["version"], str)
            or not expected_embedding["version"]
        ):
            raise ValueError("RAG evidence embedding metadata is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", corpus_manifest_sha256) is None:
            raise ValueError("RAG evidence corpus manifest hash is invalid")
        self._expected_embedding = dict(expected_embedding)
        self._corpus_manifest_sha256 = corpus_manifest_sha256
        if not expected_documents or any(
            re.fullmatch(r"[A-Z][A-Z0-9-]{2,99}", manual_id) is None
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
            for manual_id, checksum in expected_documents.items()
        ):
            raise ValueError("RAG evidence corpus documents are invalid")
        self._expected_documents = dict(expected_documents)
        if re.fullmatch(r"[0-9a-f]{64}", processing_profile_sha256) is None:
            raise ValueError("RAG evidence processing profile is invalid")
        self._processing_profile_sha256 = processing_profile_sha256

    def _active_release_id(self, connection: object) -> object:
        metadata = self._expected_embedding
        row = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT release.release_id
            FROM corpus_active_release active
            JOIN corpus_releases release ON release.release_id=active.release_id
            WHERE active.singleton=TRUE
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
              AND release.document_count>0
              AND release.chunk_count>0
              AND EXISTS (
                  SELECT 1 FROM ingestion_runs run
                  WHERE run.run_id=release.release_id
                    AND run.status='SUCCESS'
                    AND run.document_count=release.document_count
                    AND run.chunk_count=release.chunk_count
              )
              AND EXISTS (
                  SELECT 1 FROM corpus_release_documents eligible
                  WHERE eligible.release_id=release.release_id
                    AND eligible.deleted_at IS NULL
                    AND eligible.document_status='WORKING_KNOWLEDGE'
                    AND eligible.approval_status='APPROVED'
                    AND eligible.validity_status!='UNRESOLVED'
                    AND 'STAFF'=ANY(eligible.role_scope)
                    AND (eligible.effective_from IS NULL
                      OR eligible.effective_from<=CURRENT_DATE)
                    AND (eligible.expires_at IS NULL
                      OR eligible.expires_at>=CURRENT_DATE)
              )
              AND release.document_count=(
                  SELECT COUNT(*) FROM corpus_release_documents d
                  WHERE d.release_id=release.release_id
              )
              AND release.chunk_count=(
                  SELECT COUNT(*) FROM corpus_release_chunks c
                  WHERE c.release_id=release.release_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM corpus_release_documents d
                  WHERE d.release_id=release.release_id AND d.deleted_at IS NOT NULL
              )
              AND NOT EXISTS (
                  SELECT 1 FROM corpus_release_chunks c
                  WHERE c.release_id=release.release_id
                    AND (c.deleted_at IS NOT NULL
                      OR c.embedding_provider<>release.embedding_provider
                      OR c.embedding_model<>release.embedding_model
                      OR c.embedding_dimensions<>release.embedding_dimensions
                      OR c.embedding_version<>release.embedding_version
                      OR c.source_document_hash<>(
                          SELECT d.content_checksum
                          FROM corpus_release_documents d
                          WHERE d.release_id=c.release_id
                            AND d.manual_id=c.manual_id
                      ))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM corpus_release_documents d
                  WHERE d.release_id=release.release_id
                    AND NOT EXISTS (
                        SELECT 1 FROM corpus_release_chunks c
                        WHERE c.release_id=d.release_id
                          AND c.manual_id=d.manual_id
                          AND c.deleted_at IS NULL
                    )
              )
            FOR SHARE OF active, release
            """,
            (
                metadata["provider"],
                metadata["model"],
                metadata["dimensions"],
                metadata["version"],
                self._corpus_manifest_sha256,
                self._processing_profile_sha256,
                json.dumps(self._expected_documents, sort_keys=True),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Active RAG corpus release is not ready for evidence")
        return row[0]

    def source_inventory(self) -> list[dict[str, object]]:
        """활성 문서별 checksum·형식·chunk·locator 수를 inventory로 반환한다."""

        with psycopg.connect(self._database_url) as connection:
            release_id = self._active_release_id(connection)
            rows = connection.execute(
                """
                SELECT d.manual_id, d.title, d.version, d.source_path, d.content_checksum,
                       d.document_type, COUNT(c.chunk_id), MAX(c.page_end)
                FROM corpus_release_documents d
                JOIN corpus_release_chunks c
                  ON c.release_id=d.release_id AND c.manual_id=d.manual_id
                WHERE d.release_id=%s
                  AND d.deleted_at IS NULL AND c.deleted_at IS NULL
                  AND d.document_status='WORKING_KNOWLEDGE'
                  AND d.approval_status='APPROVED'
                  AND d.validity_status!='UNRESOLVED'
                  AND 'STAFF'=ANY(d.role_scope)
                  AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
                  AND (d.expires_at IS NULL OR d.expires_at>=CURRENT_DATE)
                GROUP BY d.manual_id, d.title, d.version, d.source_path,
                         d.content_checksum, d.document_type
                ORDER BY d.manual_id
                """,
                (release_id,),
            ).fetchall()
        return [
            {
                "manual_id": row[0], "title": row[1], "version": row[2],
                "source_path": row[3], "sha256": row[4],
                "document_type": row[5], "chunk_count": row[6],
                "locator_kind": (
                    "PAGE" if row[5] == "MANUAL" else "EXPLICIT_BREAK_SEGMENT"
                ),
                "location_count": row[7],
                "page_count": row[7] if row[5] == "MANUAL" else None,
            }
            for row in rows
        ]

    def evaluation_sources(self) -> list[dict[str, str]]:
        """승인·유효·STAFF 접근 문서의 chunk를 평가용 원문으로 순서 결합한다."""

        with psycopg.connect(self._database_url) as connection:
            release_id = self._active_release_id(connection)
            rows = connection.execute(
                """
                SELECT d.manual_id, d.title, STRING_AGG(c.content, E'\n' ORDER BY c.page_start, c.chunk_id)
                FROM corpus_release_documents d
                JOIN corpus_release_chunks c
                  ON c.release_id=d.release_id AND c.manual_id=d.manual_id
                WHERE d.release_id=%s
                  AND d.deleted_at IS NULL AND c.deleted_at IS NULL
                  AND d.document_status='WORKING_KNOWLEDGE'
                  AND d.approval_status='APPROVED'
                  AND d.validity_status!='UNRESOLVED'
                  AND 'STAFF'=ANY(d.role_scope)
                  AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
                  AND (d.expires_at IS NULL OR d.expires_at>=CURRENT_DATE)
                GROUP BY d.manual_id, d.title ORDER BY d.manual_id
                """,
                (release_id,),
            ).fetchall()
        return [
            {"manual_id": str(row[0]), "title": str(row[1]), "content": str(row[2])}
            for row in rows
        ]

    def ingestion_history(self) -> list[dict[str, object]]:
        """활성 release를 생성한 성공 ingestion run의 수량·시간 receipt를 반환한다."""

        with psycopg.connect(self._database_url) as connection:
            release_id = self._active_release_id(connection)
            rows = connection.execute(
                """
                SELECT run_id, started_at, finished_at, status, document_count, chunk_count, error_text
                FROM ingestion_runs
                WHERE run_id=%s AND status='SUCCESS'
                """,
                (release_id,),
            ).fetchall()
        if len(rows) != 1:
            raise RuntimeError("Active RAG ingestion receipt is missing")
        return [
            {
                "run_id": str(row[0]),
                "started_at": row[1].isoformat(),
                "finished_at": row[2].isoformat() if row[2] else None,
                "status": row[3], "document_count": row[4],
                "chunk_count": row[5], "error_text": row[6],
            }
            for row in rows
        ]
