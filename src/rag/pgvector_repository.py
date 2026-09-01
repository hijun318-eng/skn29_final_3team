"""pgvector corpus release의 staging·검색·evidence receipt를 transaction으로 관리한다."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID

import numpy as np
import psycopg

from .bm25 import bm25_scores
from .vector_models import PdfChunk, PdfDocument, VectorSearchResult
from .vector_result_mapper import to_vector_search_result
from .pgvector_observability import PgVectorObservabilityMixin


_ARTICLE_SECTION_PATTERN = re.compile(r"^제([0-9]+)조 (.+)$")
_NEXT_ARTICLE_PATTERN = re.compile(r"^\s*제\s*[0-9]+\s*조")


def _matches_active_evidence_projection(
    stored: dict[str, str],
    active_row: tuple[object, ...],
    ordinal: int,
) -> bool:
    """검색 receipt가 원시 chunk 또는 서버의 조항 투영과 정확히 일치하는지 확인한다."""

    if len(active_row) != 10 or int(active_row[0]) != ordinal:
        return False
    (
        _,
        evidence_id,
        manual_id,
        title,
        version,
        document_type,
        owner_team,
        source_section,
        source_text,
        page_start,
    ) = active_row
    exact_fields = {
        "evidence_id": str(evidence_id),
        "manual_id": str(manual_id),
        "title": str(title),
        "version": str(version),
        "document_type": str(document_type),
        "owner_team": str(owner_team),
    }
    if any(stored.get(field) != value for field, value in exact_fields.items()):
        return False

    source_section = str(source_section)
    source_text = str(source_text)
    locator = "explicit-segment" if document_type == "INTERNAL_REPORT" else "p"
    source_citation = (
        f"[{title} v{version} {locator}.{page_start} {source_section}]"
    )
    if (
        stored.get("section_title") == source_section
        and stored.get("text") == source_text
        and stored.get("citation") == source_citation
    ):
        return True

    if document_type != "MANUAL":
        return False
    article_section = str(stored.get("section_title") or "")
    article_match = _ARTICLE_SECTION_PATTERN.fullmatch(article_section)
    if article_match is None or article_match.group(2) != source_section:
        return False
    projected_text = str(stored.get("text") or "")
    if projected_text != source_text:
        if not projected_text or not source_text.startswith(projected_text):
            return False
        if _NEXT_ARTICLE_PATTERN.match(source_text[len(projected_text) :]) is None:
            return False
    article_citation = f"[{title} v{version} p.{page_start} {article_section}]"
    return stored.get("citation") == article_citation


class PgVectorRepository(PgVectorObservabilityMixin):
    """PostgreSQL에서 immutable release와 역할 필터 검색을 원자적으로 수행한다."""

    def __init__(
        self,
        database_url: str,
        expected_embedding: dict[str, object] | None = None,
        corpus_manifest_sha256: str | None = None,
        expected_documents: dict[str, str] | None = None,
        processing_profile_sha256: str | None = None,
    ) -> None:
        self._database_url = database_url
        self._expected_embedding = (
            self._validated_embedding_metadata(expected_embedding)
            if expected_embedding is not None
            else None
        )
        if corpus_manifest_sha256 is not None and re.fullmatch(
            r"[0-9a-f]{64}", corpus_manifest_sha256
        ) is None:
            raise ValueError("RAG corpus manifest hash is invalid")
        self._corpus_manifest_sha256 = corpus_manifest_sha256
        if expected_documents is not None and (
            not expected_documents
            or any(
                re.fullmatch(r"[A-Z][A-Z0-9-]{2,99}", manual_id) is None
                or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
                for manual_id, checksum in expected_documents.items()
            )
        ):
            raise ValueError("RAG expected corpus documents are invalid")
        self._expected_documents = (
            dict(expected_documents) if expected_documents is not None else None
        )
        if processing_profile_sha256 is not None and re.fullmatch(
            r"[0-9a-f]{64}", processing_profile_sha256
        ) is None:
            raise ValueError("RAG processing profile hash is invalid")
        self._processing_profile_sha256 = processing_profile_sha256

    @staticmethod
    def _validated_embedding_metadata(
        metadata: dict[str, object],
    ) -> dict[str, object]:
        if (
            set(metadata) != {"provider", "model", "dimensions", "version"}
            or not isinstance(metadata["provider"], str)
            or not metadata["provider"]
            or not isinstance(metadata["model"], str)
            or not metadata["model"]
            or type(metadata["dimensions"]) is not int
            or int(metadata["dimensions"]) <= 0
            or not isinstance(metadata["version"], str)
            or not metadata["version"]
        ):
            raise ValueError("RAG embedding metadata is invalid")
        return dict(metadata)

    def _active_embedding(self) -> dict[str, object]:
        if (
            self._expected_embedding is None
            or self._corpus_manifest_sha256 is None
        ):
            raise RuntimeError("RAG active release metadata is not configured")
        return self._expected_embedding

    def _active_release_parameters(self) -> list[object]:
        metadata = self._active_embedding()
        return [
            metadata["provider"],
            metadata["model"],
            metadata["dimensions"],
            metadata["version"],
            self._corpus_manifest_sha256,
            self._required_processing_profile(),
        ]

    def _required_documents(self) -> dict[str, str]:
        if self._expected_documents is None:
            raise RuntimeError("RAG expected corpus documents are not configured")
        return self._expected_documents

    def _required_processing_profile(self) -> str:
        if self._processing_profile_sha256 is None:
            raise RuntimeError("RAG processing profile is not configured")
        return self._processing_profile_sha256

    def _assert_runtime_contract(
        self,
        metadata: dict[str, object],
        corpus_manifest_sha256: str,
        processing_profile_sha256: str,
    ) -> dict[str, object]:
        validated = self._validated_embedding_metadata(metadata)
        if (
            self._expected_embedding is not None
            and validated != self._expected_embedding
        ):
            raise ValueError("RAG embedding metadata differs from runtime startup")
        if (
            re.fullmatch(r"[0-9a-f]{64}", corpus_manifest_sha256) is None
            or (
                self._corpus_manifest_sha256 is not None
                and corpus_manifest_sha256 != self._corpus_manifest_sha256
            )
        ):
            raise ValueError("RAG corpus manifest hash differs from runtime startup")
        if (
            re.fullmatch(r"[0-9a-f]{64}", processing_profile_sha256) is None
            or (
                self._processing_profile_sha256 is not None
                and processing_profile_sha256 != self._processing_profile_sha256
            )
        ):
            raise ValueError("RAG processing profile differs from runtime startup")
        return validated

    def migrate(self, migration_path: Path) -> None:
        """UTF-8 SQL migration 하나를 읽어 PostgreSQL autocommit 경계로 적용한다."""

        sql = migration_path.read_text(encoding="utf-8")
        with psycopg.connect(self._database_url, autocommit=True) as connection:
            connection.execute(sql)

    def start_run(
        self,
        run_id: UUID,
        metadata: dict[str, object],
        corpus_manifest_sha256: str,
        processing_profile_sha256: str,
    ) -> None:
        """embedding·manifest·processing profile이 봉인된 staging run을 시작한다."""

        metadata = self._assert_runtime_contract(
            metadata,
            corpus_manifest_sha256,
            processing_profile_sha256,
        )
        with psycopg.connect(self._database_url) as connection:
            started = connection.execute(
                """INSERT INTO ingestion_runs(
                       run_id, started_at, status, embedding_provider, embedding_model,
                       embedding_dimensions, embedding_version
                   ) VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s)""",
                (run_id, datetime.now(timezone.utc), metadata["provider"], metadata["model"], metadata["dimensions"], metadata["version"]),
            )
            staged = connection.execute(
                """
                INSERT INTO corpus_releases(
                    release_id, status, embedding_provider, embedding_model,
                    embedding_dimensions, embedding_version,
                    corpus_manifest_sha256, processing_profile_sha256
                ) VALUES (%s, 'STAGING', %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    corpus_manifest_sha256,
                    processing_profile_sha256,
                ),
            )
            if started.rowcount != 1 or staged.rowcount != 1:
                raise RuntimeError("RAG staging release could not be started")

    def finish_run(
        self, run_id: UUID, status: str, document_count: int, chunk_count: int, error: str | None = None
    ) -> None:
        """실패 ingestion run과 staging release의 수량·오류 상태를 함께 종결한다."""

        if status != "FAILED":
            raise ValueError("Only failed corpus releases may finish without publish")
        with psycopg.connect(self._database_url) as connection:
            finished = connection.execute(
                """
                UPDATE ingestion_runs
                SET finished_at=%s, status=%s, document_count=%s, chunk_count=%s, error_text=%s
                WHERE run_id=%s AND status='RUNNING'
                """,
                (datetime.now(timezone.utc), status, document_count, chunk_count, error, run_id),
            )
            failed = connection.execute(
                """
                UPDATE corpus_releases
                SET status='FAILED', document_count=%s, chunk_count=%s
                WHERE release_id=%s AND status='STAGING'
                """,
                (document_count, chunk_count, run_id),
            )
            if finished.rowcount != 1 or failed.rowcount != 1:
                raise RuntimeError("RAG failed release could not be finalized")

    def unchanged(
        self,
        document: PdfDocument,
        metadata: dict[str, object],
        processing_profile_sha256: str,
    ) -> bool:
        """활성 문서 bytes·metadata·embedding·처리 profile이 모두 같은지 판정한다."""

        metadata = self._validated_embedding_metadata(metadata)
        if self._expected_embedding is not None and metadata != self._expected_embedding:
            raise ValueError("RAG embedding metadata differs from runtime startup")
        if processing_profile_sha256 != self._required_processing_profile():
            raise ValueError("RAG processing profile differs from runtime startup")
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT d.content_checksum, d.title, d.version, d.source_path,
                       d.role_scope, d.document_type, d.owner_team,
                       d.effective_from, d.expires_at, COUNT(c.chunk_id)
                FROM corpus_active_release active
                JOIN corpus_releases release ON release.release_id=active.release_id
                JOIN corpus_release_documents d ON d.release_id=release.release_id
                JOIN corpus_release_chunks c
                  ON c.release_id=d.release_id AND c.manual_id=d.manual_id
                WHERE active.singleton=TRUE
                  AND release.status='ACTIVE'
                  AND release.embedding_provider=%s
                  AND release.embedding_model=%s
                  AND release.embedding_dimensions=%s
                  AND release.embedding_version=%s
                  AND release.processing_profile_sha256=%s
                  AND d.manual_id=%s
                  AND d.deleted_at IS NULL
                  AND c.deleted_at IS NULL
                  AND c.embedding_provider=release.embedding_provider
                  AND c.embedding_model=release.embedding_model
                  AND c.embedding_dimensions=release.embedding_dimensions
                  AND c.embedding_version=release.embedding_version
                  AND c.source_document_hash=d.content_checksum
                GROUP BY d.content_checksum, d.title, d.version, d.source_path,
                         d.role_scope, d.document_type, d.owner_team,
                         d.effective_from, d.expires_at
                """,
                (
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    processing_profile_sha256,
                    document.manual_id,
                ),
            ).fetchone()
        return bool(
            row
            and row[0] == document.checksum
            and row[1] == document.title
            and row[2] == document.version
            and row[3] == document.source_path
            and tuple(row[4]) == document.role_scope
            and row[5] == document.document_type
            and row[6] == document.owner_team
            and row[7] == document.effective_from
            and row[8] == document.expires_at
            and int(row[9]) > 0
        )

    def copy_active_document(
        self,
        release_id: UUID,
        document: PdfDocument,
        chunks: list[PdfChunk],
        metadata: dict[str, object],
        processing_profile_sha256: str,
    ) -> int:
        """동일성이 잠금 안에서 재확인된 활성 문서·vector를 새 staging run에 복사한다."""

        metadata = self._validated_embedding_metadata(metadata)
        if self._expected_embedding is not None and metadata != self._expected_embedding:
            raise ValueError("RAG embedding metadata differs from runtime startup")
        if processing_profile_sha256 != self._required_processing_profile():
            raise ValueError("RAG processing profile differs from runtime startup")
        if (
            not chunks
            or any(chunk.manual_id != document.manual_id for chunk in chunks)
            or any(
                chunk.checksum
                != hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
                for chunk in chunks
            )
        ):
            raise ValueError("RAG reparsed chunks are incomplete or drifted")
        with psycopg.connect(self._database_url) as connection:
            source = connection.execute(
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
                  AND release.processing_profile_sha256=%s
                FOR SHARE OF active, release
                """,
                (
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    processing_profile_sha256,
                ),
            ).fetchone()
            if source is None:
                raise RuntimeError("Active RAG release changed during corpus staging")
            source_release_id = source[0]
            target = connection.execute(
                """
                SELECT 1 FROM corpus_releases
                WHERE release_id=%s AND status='STAGING'
                  AND embedding_provider=%s AND embedding_model=%s
                  AND embedding_dimensions=%s AND embedding_version=%s
                  AND corpus_manifest_sha256=%s
                  AND processing_profile_sha256=%s
                FOR UPDATE
                """,
                (
                    release_id,
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    self._corpus_manifest_sha256,
                    processing_profile_sha256,
                ),
            ).fetchone()
            if target is None:
                raise RuntimeError("RAG target staging release is unavailable or drifted")
            source_document = connection.execute(
                """
                SELECT d.title, d.version, d.source_path, d.content_checksum,
                       d.role_scope, d.document_type, d.owner_team,
                       d.effective_from, d.expires_at, d.deleted_at
                FROM corpus_release_documents d
                WHERE d.release_id=%s AND d.manual_id=%s
                FOR UPDATE
                """,
                (source_release_id, document.manual_id),
            ).fetchone()
            if source_document != (
                document.title,
                document.version,
                document.source_path,
                document.checksum,
                list(document.role_scope),
                document.document_type,
                document.owner_team,
                document.effective_from,
                document.expires_at,
                None,
            ):
                raise RuntimeError("Active RAG document changed during corpus staging")
            source_chunks = connection.execute(
                """
                SELECT c.chunk_id, c.chunk_index, c.page_start, c.page_end,
                       c.section_title, c.content, c.content_checksum,
                       c.token_count, c.deleted_at, c.embedding_provider,
                       c.embedding_model, c.embedding_dimensions,
                       c.embedding_version, c.source_document_hash
                FROM corpus_release_chunks c
                WHERE c.release_id=%s AND c.manual_id=%s
                ORDER BY c.chunk_index, c.chunk_id
                FOR SHARE
                """,
                (source_release_id, document.manual_id),
            ).fetchall()
            expected_chunks = [
                (
                    chunk.chunk_id,
                    chunk.chunk_index,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.section_title,
                    chunk.content,
                    chunk.checksum,
                    chunk.token_count,
                )
                for chunk in chunks
            ]
            stored_chunks = [tuple(chunk[:8]) for chunk in source_chunks]
            if (
                stored_chunks != expected_chunks
                or any(
                    stored[6]
                    != hashlib.sha256(str(stored[5]).encode("utf-8")).hexdigest()
                    or stored[8] is not None
                    or stored[9] != metadata["provider"]
                    or stored[10] != metadata["model"]
                    or stored[11] != metadata["dimensions"]
                    or stored[12] != metadata["version"]
                    or stored[13] != document.checksum
                    for stored in source_chunks
                )
            ):
                raise RuntimeError(
                    "Active RAG document chunks are incomplete or drifted"
                )
            copied_document = connection.execute(
                """
                INSERT INTO corpus_release_documents(
                    release_id, manual_id, title, version, source_path,
                    content_checksum, document_status, authority_level,
                    validity_status, role_scope, document_type, owner_team,
                    effective_from, expires_at, approval_status, deleted_at
                )
                SELECT %s, d.manual_id, d.title, d.version, d.source_path,
                       d.content_checksum, d.document_status, d.authority_level,
                       d.validity_status, d.role_scope, d.document_type, d.owner_team,
                       d.effective_from, d.expires_at, d.approval_status, d.deleted_at
                FROM corpus_release_documents d
                WHERE d.release_id=%s
                  AND d.manual_id=%s
                  AND d.content_checksum=%s
                  AND d.deleted_at IS NULL
                RETURNING manual_id
                """,
                (
                    release_id,
                    source_release_id,
                    document.manual_id,
                    document.checksum,
                ),
            ).fetchone()
            if copied_document is None:
                raise RuntimeError("Active RAG document changed during corpus staging")
            copied_chunks = connection.execute(
                """
                INSERT INTO corpus_release_chunks(
                    release_id, chunk_id, manual_id, chunk_index,
                    page_start, page_end, section_title, content,
                    content_checksum, embedding, embedding_provider,
                    embedding_model, embedding_dimensions, embedding_version,
                    source_document_hash, token_count, embedded_at, deleted_at
                )
                SELECT %s, c.chunk_id, c.manual_id, c.chunk_index,
                       c.page_start, c.page_end, c.section_title, c.content,
                       c.content_checksum, c.embedding, c.embedding_provider,
                       c.embedding_model, c.embedding_dimensions,
                       c.embedding_version, c.source_document_hash,
                       c.token_count, c.embedded_at, c.deleted_at
                FROM corpus_release_chunks c
                WHERE c.release_id=%s
                  AND c.manual_id=%s
                RETURNING chunk_id
                """,
                (
                    release_id,
                    source_release_id,
                    document.manual_id,
                ),
            ).fetchall()
            if len(copied_chunks) != len(source_chunks):
                raise RuntimeError("Active RAG document chunks were not copied exactly")
        return len(copied_chunks)

    def stage_document(
        self,
        release_id: UUID,
        document: PdfDocument,
        chunks: list[PdfChunk],
        embeddings: np.ndarray,
        metadata: dict[str, object],
    ) -> int:
        """문서·chunk·vector shape과 provenance를 검증해 staging release에 기록한다."""

        metadata = self._validated_embedding_metadata(metadata)
        if (
            self._expected_embedding is not None
            and metadata != self._expected_embedding
        ):
            raise ValueError("RAG embedding metadata differs from runtime startup")
        if (
            len(chunks) != len(embeddings)
            or not chunks
            or any(chunk.manual_id != document.manual_id for chunk in chunks)
            or any(len(vector) != metadata["dimensions"] for vector in embeddings)
        ):
            raise ValueError("Chunk and embedding counts differ or are empty")
        if self._required_documents().get(document.manual_id) != document.checksum:
            raise ValueError("RAG staged document differs from corpus manifest")
        if (
            document.approval_status != "APPROVED"
            or document.validity_status != "VALID"
        ):
            raise ValueError("RAG staged document lacks a curated manifest approval receipt")
        with psycopg.connect(self._database_url) as connection:
            release = connection.execute(
                """
                SELECT 1 FROM corpus_releases
                WHERE release_id=%s AND status='STAGING'
                  AND embedding_provider=%s AND embedding_model=%s
                  AND embedding_dimensions=%s AND embedding_version=%s
                  AND corpus_manifest_sha256=%s
                  AND processing_profile_sha256=%s
                FOR UPDATE
                """,
                (
                    release_id,
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    self._corpus_manifest_sha256,
                    self._required_processing_profile(),
                ),
            ).fetchone()
            if release is None:
                raise RuntimeError("RAG staging release is unavailable or drifted")
            connection.execute(
                """
                INSERT INTO corpus_release_documents(
                    release_id, manual_id, title, version, source_path,
                    content_checksum, role_scope, document_type, owner_team,
                    effective_from, expires_at, approval_status, validity_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    release_id,
                    document.manual_id,
                    document.title,
                    document.version,
                    document.source_path,
                    document.checksum,
                    list(document.role_scope),
                    document.document_type,
                    document.owner_team,
                    document.effective_from,
                    document.expires_at,
                    document.approval_status,
                    document.validity_status,
                ),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO corpus_release_chunks(
                        release_id, chunk_id, manual_id, chunk_index,
                        page_start, page_end, section_title, content,
                        content_checksum, embedding, embedding_provider,
                        embedding_model, embedding_dimensions, embedding_version,
                        source_document_hash, token_count
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        (
                            release_id,
                            chunk.chunk_id,
                            chunk.manual_id,
                            chunk.chunk_index,
                            chunk.page_start,
                            chunk.page_end,
                            chunk.section_title,
                            chunk.content,
                            chunk.checksum,
                            self._vector_literal(vector),
                            metadata["provider"],
                            metadata["model"],
                            metadata["dimensions"],
                            metadata["version"],
                            document.checksum,
                            chunk.token_count,
                        )
                        for chunk, vector in zip(chunks, embeddings, strict=True)
                    ],
                )
        return len(chunks)

    def publish_release(
        self,
        release_id: UUID,
        *,
        expected_document_count: int,
        expected_chunk_count: int,
        metadata: dict[str, object],
        corpus_manifest_sha256: str,
        processing_profile_sha256: str,
    ) -> dict[str, object]:
        """문서·chunk·embedding receipt가 완전한 staging run만 active로 원자 전환한다."""

        metadata = self._assert_runtime_contract(
            metadata,
            corpus_manifest_sha256,
            processing_profile_sha256,
        )
        expected_documents = self._required_documents()
        if expected_document_count != len(expected_documents):
            raise ValueError("RAG expected document count differs from corpus manifest")
        if expected_document_count <= 0 or expected_chunk_count <= 0:
            raise ValueError("RAG corpus release must contain documents and chunks")
        with psycopg.connect(self._database_url) as connection:
            pointer = connection.execute(
                """
                SELECT release_id FROM corpus_active_release
                WHERE singleton=TRUE FOR UPDATE
                """
            ).fetchone()
            if pointer is None:
                raise RuntimeError("RAG active release pointer is unavailable")
            receipt = connection.execute(
                """
                SELECT release.status,
                       (SELECT COUNT(*) FROM corpus_release_documents d
                        WHERE d.release_id=release.release_id),
                       (SELECT COUNT(*) FROM corpus_release_documents d
                        WHERE d.release_id=release.release_id
                          AND d.deleted_at IS NOT NULL),
                       (SELECT COUNT(*) FROM corpus_release_chunks c
                        WHERE c.release_id=release.release_id),
                       (SELECT COUNT(*) FROM corpus_release_chunks c
                        WHERE c.release_id=release.release_id
                          AND c.deleted_at IS NOT NULL),
                       (SELECT COUNT(*) FROM corpus_release_chunks c
                        WHERE c.release_id=release.release_id
                          AND (c.embedding_provider<>release.embedding_provider
                            OR c.embedding_model<>release.embedding_model
                            OR c.embedding_dimensions<>release.embedding_dimensions
                            OR c.embedding_version<>release.embedding_version
                            OR c.source_document_hash<>(
                                SELECT d.content_checksum
                                FROM corpus_release_documents d
                                WHERE d.release_id=c.release_id
                                  AND d.manual_id=c.manual_id
                            ))),
                       (SELECT COUNT(*) FROM corpus_release_documents d
                        WHERE d.release_id=release.release_id
                          AND NOT EXISTS (
                              SELECT 1 FROM corpus_release_chunks c
                              WHERE c.release_id=d.release_id
                                AND c.manual_id=d.manual_id
                                AND c.deleted_at IS NULL
                          )),
                       (SELECT COUNT(*) FROM corpus_release_documents d
                        WHERE d.release_id=release.release_id
                          AND d.deleted_at IS NULL
                          AND d.document_status='WORKING_KNOWLEDGE'
                          AND d.approval_status='APPROVED'
                          AND d.validity_status!='UNRESOLVED'
                          AND cardinality(d.role_scope)>0
                          AND 'STAFF'=ANY(d.role_scope)
                          AND (d.effective_from IS NULL
                            OR d.effective_from<=CURRENT_DATE)
                          AND (d.expires_at IS NULL
                            OR d.expires_at>=CURRENT_DATE)),
                       (SELECT COALESCE(
                            jsonb_object_agg(d.manual_id, d.content_checksum),
                            '{}'::jsonb
                        ) FROM corpus_release_documents d
                        WHERE d.release_id=release.release_id)
                FROM corpus_releases release
                WHERE release.release_id=%s
                  AND release.embedding_provider=%s
                  AND release.embedding_model=%s
                  AND release.embedding_dimensions=%s
                  AND release.embedding_version=%s
                  AND release.corpus_manifest_sha256=%s
                  AND release.processing_profile_sha256=%s
                FOR UPDATE
                """,
                (
                    release_id,
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    corpus_manifest_sha256,
                    processing_profile_sha256,
                ),
            ).fetchone()
            if receipt != (
                "STAGING",
                expected_document_count,
                0,
                expected_chunk_count,
                0,
                0,
                0,
                expected_document_count,
                expected_documents,
            ):
                raise RuntimeError("RAG staging release is incomplete or drifted")
            previous_release_id = pointer[0]
            if previous_release_id is not None:
                previous_receipt = connection.execute(
                    """
                    SELECT release.status, release.document_count,
                           (SELECT COUNT(*) FROM corpus_release_documents d
                            WHERE d.release_id=release.release_id),
                           (SELECT COUNT(*) FROM corpus_release_documents d
                            WHERE d.release_id=release.release_id
                              AND d.deleted_at IS NOT NULL),
                           release.chunk_count,
                           (SELECT COUNT(*) FROM corpus_release_chunks c
                            WHERE c.release_id=release.release_id),
                           (SELECT COUNT(*) FROM corpus_release_chunks c
                            WHERE c.release_id=release.release_id
                              AND c.deleted_at IS NOT NULL),
                           (SELECT COUNT(*) FROM corpus_release_chunks c
                            WHERE c.release_id=release.release_id
                              AND (c.embedding_provider<>release.embedding_provider
                                OR c.embedding_model<>release.embedding_model
                                OR c.embedding_dimensions<>release.embedding_dimensions
                                OR c.embedding_version<>release.embedding_version
                                OR c.source_document_hash<>(
                                    SELECT d.content_checksum
                                    FROM corpus_release_documents d
                                    WHERE d.release_id=c.release_id
                                      AND d.manual_id=c.manual_id
                                ))),
                           (SELECT COUNT(*) FROM corpus_release_documents d
                            WHERE d.release_id=release.release_id
                              AND NOT EXISTS (
                                  SELECT 1 FROM corpus_release_chunks c
                                  WHERE c.release_id=d.release_id
                                    AND c.manual_id=d.manual_id
                                    AND c.deleted_at IS NULL
                              )),
                           (SELECT COUNT(*) FROM ingestion_runs run
                            WHERE run.run_id=release.release_id
                              AND run.status='SUCCESS'
                              AND run.document_count=release.document_count
                              AND run.chunk_count=release.chunk_count)
                    FROM corpus_releases release
                    WHERE release.release_id=%s
                    FOR UPDATE
                    """,
                    (previous_release_id,),
                ).fetchone()
                if (
                    previous_receipt is None
                    or previous_receipt[0] != "ACTIVE"
                    or previous_receipt[1] <= 0
                    or previous_receipt[1] != previous_receipt[2]
                    or previous_receipt[3] != 0
                    or previous_receipt[4] <= 0
                    or previous_receipt[4] != previous_receipt[5]
                    or previous_receipt[6:] != (0, 0, 0, 1)
                ):
                    raise RuntimeError("Previous RAG active release receipt is invalid")
                retired = connection.execute(
                    """
                    UPDATE corpus_releases SET status='RETIRED'
                    WHERE release_id=%s AND status='ACTIVE'
                    """,
                    (previous_release_id,),
                )
                if retired.rowcount != 1:
                    raise RuntimeError("Previous RAG active release was not retired")
            published_at = datetime.now(timezone.utc)
            activated = connection.execute(
                """
                UPDATE corpus_releases
                SET status='ACTIVE', document_count=%s, chunk_count=%s,
                    published_at=%s
                WHERE release_id=%s AND status='STAGING'
                """,
                (
                    expected_document_count,
                    expected_chunk_count,
                    published_at,
                    release_id,
                ),
            )
            if activated.rowcount != 1:
                raise RuntimeError("RAG staging release was not activated")
            pointer_update = connection.execute(
                """
                UPDATE corpus_active_release
                SET release_id=%s, updated_at=%s
                WHERE singleton=TRUE
                """,
                (release_id, published_at),
            )
            if pointer_update.rowcount != 1:
                raise RuntimeError("RAG active release pointer was not updated")
            finished = connection.execute(
                """
                UPDATE ingestion_runs
                SET finished_at=%s, status='SUCCESS', document_count=%s,
                    chunk_count=%s, error_text=NULL
                WHERE run_id=%s AND status='RUNNING'
                """,
                (
                    published_at,
                    expected_document_count,
                    expected_chunk_count,
                    release_id,
                ),
            )
            if finished.rowcount != 1:
                raise RuntimeError("RAG ingestion run was not finalized")
        return {
            "release_id": str(release_id),
            "previous_release_id": (
                str(previous_release_id) if previous_release_id is not None else None
            ),
            "document_count": expected_document_count,
            "chunk_count": expected_chunk_count,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "processing_profile_sha256": processing_profile_sha256,
            **metadata,
        }

    def active_release_receipt(
        self,
        metadata: dict[str, object],
        corpus_manifest_sha256: str,
        processing_profile_sha256: str,
    ) -> dict[str, object] | None:
        """pointer·수량·embedding·manifest·profile이 일치하는 active release만 반환한다."""

        metadata = self._assert_runtime_contract(
            metadata,
            corpus_manifest_sha256,
            processing_profile_sha256,
        )
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT release.release_id, release.document_count,
                       release.chunk_count, release.published_at,
                       (SELECT COUNT(*) FROM corpus_release_documents eligible
                        WHERE eligible.release_id=release.release_id
                          AND eligible.deleted_at IS NULL
                          AND eligible.document_status='WORKING_KNOWLEDGE'
                          AND eligible.approval_status='APPROVED'
                          AND eligible.validity_status!='UNRESOLVED'
                          AND cardinality(eligible.role_scope)>0
                          AND 'STAFF'=ANY(eligible.role_scope)
                          AND (eligible.effective_from IS NULL
                            OR eligible.effective_from<=CURRENT_DATE)
                          AND (eligible.expires_at IS NULL
                            OR eligible.expires_at>=CURRENT_DATE))
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
                        AND cardinality(eligible.role_scope)>0
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
                  AND release.document_count=(
                      SELECT COUNT(*) FROM corpus_release_documents eligible
                      WHERE eligible.release_id=release.release_id
                        AND eligible.deleted_at IS NULL
                        AND eligible.document_status='WORKING_KNOWLEDGE'
                        AND eligible.approval_status='APPROVED'
                        AND eligible.validity_status!='UNRESOLVED'
                        AND cardinality(eligible.role_scope)>0
                        AND 'STAFF'=ANY(eligible.role_scope)
                        AND (eligible.effective_from IS NULL
                          OR eligible.effective_from<=CURRENT_DATE)
                        AND (eligible.expires_at IS NULL
                          OR eligible.expires_at>=CURRENT_DATE)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM corpus_release_documents d
                      WHERE d.release_id=release.release_id
                        AND d.deleted_at IS NOT NULL
                  )
                  AND release.chunk_count=(
                      SELECT COUNT(*) FROM corpus_release_chunks c
                      WHERE c.release_id=release.release_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM corpus_release_chunks c
                      WHERE c.release_id=release.release_id
                        AND c.deleted_at IS NOT NULL
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM corpus_release_chunks c
                      WHERE c.release_id=release.release_id
                        AND (c.embedding_provider<>release.embedding_provider
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
                """,
                (
                    metadata["provider"],
                    metadata["model"],
                    metadata["dimensions"],
                    metadata["version"],
                    corpus_manifest_sha256,
                    processing_profile_sha256,
                    json.dumps(self._required_documents(), sort_keys=True),
                ),
            ).fetchone()
        if row is None:
            return None
        return {
            "release_id": str(row[0]),
            "document_count": int(row[1]),
            "chunk_count": int(row[2]),
            "published_at": row[3].isoformat() if row[3] is not None else None,
            "approved_document_count": int(row[4]),
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "processing_profile_sha256": processing_profile_sha256,
            **metadata,
        }

    def search(
        self,
        vector: np.ndarray,
        query_text: str,
        role: str,
        top_k: int,
        minimum_vector_score: float,
        allow_unresolved: bool,
        selected_manual_ids: tuple[str, ...] = (),
        retrieval_mode: str = "HYBRID",
        maximum_chunks_per_document: int = 1,
    ) -> list[VectorSearchResult]:
        """역할·유효성·선택 문서 Gate 아래 vector·lexical 후보를 융합해 반환한다."""

        query_vector = self._vector_literal(vector)

        # 현재 승인된 corpus는 363개 chunk로 작다. 역할·승인·유효기간 필터를
        # DB에서 먼저 적용한 뒤, 동일 후보군에 Jaehong 검증값인 Dense 0.65와
        # BM25 0.35를 적용한다. corpus가 커지면 별도 lexical index로 교체한다.
        sql = """
            SELECT d.manual_id, d.title, d.version, c.page_start, c.page_end,
                   c.section_title, c.content,
                   1 - (c.embedding <=> %s::vector) AS vector_score,
                   c.chunk_id, c.chunk_index, d.document_status,
                   d.authority_level, d.validity_status, d.approval_status,
                   d.document_type, d.owner_team, d.effective_from, d.expires_at
            FROM corpus_active_release active
            JOIN corpus_releases release ON release.release_id=active.release_id
            JOIN corpus_release_documents d ON d.release_id=release.release_id
            JOIN corpus_release_chunks c
              ON c.release_id=d.release_id AND c.manual_id=d.manual_id
            WHERE active.singleton=TRUE
              AND release.status='ACTIVE'
              AND release.embedding_provider=%s
              AND release.embedding_model=%s
              AND release.embedding_dimensions=%s
              AND release.embedding_version=%s
              AND release.corpus_manifest_sha256=%s
              AND release.processing_profile_sha256=%s
              AND c.embedding_provider=release.embedding_provider
              AND c.embedding_model=release.embedding_model
              AND c.embedding_dimensions=release.embedding_dimensions
              AND c.embedding_version=release.embedding_version
              AND c.deleted_at IS NULL AND d.deleted_at IS NULL
              AND d.document_status = 'WORKING_KNOWLEDGE'
              AND d.approval_status = 'APPROVED'
              AND %s = ANY(d.role_scope)
              AND (%s OR d.validity_status != 'UNRESOLVED')
              AND (
                  cardinality(%s::text[]) = 0
                  OR d.manual_id = ANY(%s::text[])
              )
              AND (d.effective_from IS NULL OR d.effective_from <= CURRENT_DATE)
              AND (d.expires_at IS NULL OR d.expires_at >= CURRENT_DATE)
        """
        params = [
            query_vector,
            *self._active_release_parameters(),
            role,
            allow_unresolved,
            list(selected_manual_ids),
            list(selected_manual_ids),
        ]

        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(sql, params).fetchall()

        lexical_scores = bm25_scores(
            query_text,
            [f"{row[1]}\n{row[5]}\n{row[6]}" for row in rows],
        )
        ranked: list[tuple[float, float, float, tuple[object, ...]]] = []
        for row, lexical_score in zip(rows, lexical_scores, strict=True):
            vector_score = max(0.0, min(1.0, float(row[7])))
            if retrieval_mode == "VECTOR_ONLY":
                if vector_score < minimum_vector_score:
                    continue
                score = vector_score
            elif retrieval_mode == "LEXICAL_ONLY":
                if lexical_score <= 0:
                    continue
                score = lexical_score
            else:
                if vector_score < minimum_vector_score and lexical_score <= 0:
                    continue
                score = max(
                    vector_score,
                    0.65 * vector_score + 0.35 * lexical_score,
                )
            ranked.append((score, vector_score, lexical_score, row))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

        results: list[VectorSearchResult] = []
        document_counts: dict[str, int] = {}
        for score, vector_score, lexical_score, row in ranked:
            manual_id, title, version = str(row[0]), str(row[1]), str(row[2])
            if document_counts.get(manual_id, 0) >= maximum_chunks_per_document:
                continue
            stored_location_start, stored_location_end, section_title, content = row[3:7]
            chunk_id = row[8]
            evidence_id = f"{manual_id}:{version}:{stored_location_start}:{chunk_id}"
            snippet_limit_raw = os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip()
            try:
                snippet_limit = max(200, int(snippet_limit_raw))
            except ValueError:
                snippet_limit = 1800
            snippet = content[:snippet_limit] + "..." if len(content) > snippet_limit else content
            document_type = str(row[14])
            if document_type == "INTERNAL_REPORT":
                page_start = None
                page_end = None
                locator_kind = "EXPLICIT_BREAK_SEGMENT"
                citation = (
                    f"[{title} v{version} explicit-segment."
                    f"{stored_location_start} {section_title}]"
                )
            else:
                page_start = int(stored_location_start)
                page_end = int(stored_location_end)
                locator_kind = "PAGE"
                citation = f"[{title} v{version} p.{page_start} {section_title}]"

            results.append(
                VectorSearchResult(
                    manual_id=manual_id,
                    title=title,
                    version=version,
                    page_start=page_start,
                    page_end=page_end,
                    section_title=section_title,
                    score=float(score),
                    vector_score=float(vector_score),
                    lexical_score=float(lexical_score),
                    snippet=snippet,
                    content=content,
                    citation=citation,
                    evidence_id=evidence_id,
                    ranking_stage="dense_bm25",
                    reranker_score=None,
                    document_status=str(row[10]),
                    authority_level=str(row[11]),
                    validity_status=str(row[12]),
                    warning=None,
                    document_type=document_type,
                    owner_team=str(row[15]),
                    effective_from=str(row[16]) if row[16] else None,
                    expires_at=str(row[17]) if row[17] else None,
                    chunk_index=int(row[9]),
                    approval_status=str(row[13]),
                    locator_kind=locator_kind,
                    locator_start=int(stored_location_start),
                    locator_end=int(stored_location_end),
                )
            )
            document_counts[manual_id] = document_counts.get(manual_id, 0) + 1
            if len(results) >= top_k:
                break
        return results

    def article_context(
        self,
        manual_ids: tuple[str, ...],
        article_numbers: tuple[int, ...],
        role: str,
        allow_unresolved: bool,
        maximum_chunks_per_document: int = 8,
    ) -> list[VectorSearchResult]:
        """검색된 PDF 매뉴얼의 조항 주변 chunk를 같은 접근 계약으로 hydration한다."""

        if not manual_ids or not article_numbers:
            return []
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT d.manual_id, d.title, d.version, c.page_start, c.page_end,
                       c.section_title, c.content, c.chunk_id, c.chunk_index,
                       d.document_status, d.authority_level, d.validity_status,
                       d.approval_status, d.document_type, d.owner_team,
                       d.effective_from, d.expires_at
                FROM corpus_active_release active
                JOIN corpus_releases release ON release.release_id=active.release_id
                JOIN corpus_release_documents d ON d.release_id=release.release_id
                JOIN corpus_release_chunks c
                  ON c.release_id=d.release_id AND c.manual_id=d.manual_id
                WHERE active.singleton=TRUE
                  AND release.status='ACTIVE'
                  AND release.embedding_provider=%s
                  AND release.embedding_model=%s
                  AND release.embedding_dimensions=%s
                  AND release.embedding_version=%s
                  AND release.corpus_manifest_sha256=%s
                  AND release.processing_profile_sha256=%s
                  AND c.embedding_provider=release.embedding_provider
                  AND c.embedding_model=release.embedding_model
                  AND c.embedding_dimensions=release.embedding_dimensions
                  AND c.embedding_version=release.embedding_version
                  AND c.deleted_at IS NULL AND d.deleted_at IS NULL
                  AND d.manual_id=ANY(%s::text[])
                  AND d.document_type='MANUAL'
                  AND %s=ANY(d.role_scope)
                  AND d.document_status='WORKING_KNOWLEDGE'
                  AND d.approval_status='APPROVED'
                  AND (%s OR d.validity_status!='UNRESOLVED')
                  AND (d.effective_from IS NULL OR d.effective_from <= CURRENT_DATE)
                  AND (d.expires_at IS NULL OR d.expires_at >= CURRENT_DATE)
                ORDER BY d.manual_id, c.page_start, c.chunk_index
                """,
                (
                    *self._active_release_parameters(),
                    list(manual_ids),
                    role,
                    allow_unresolved,
                ),
            ).fetchall()

        by_manual: dict[str, list[tuple[object, ...]]] = {}
        for row in rows:
            by_manual.setdefault(str(row[0]), []).append(row)
        targets = set(article_numbers)
        article_pattern = re.compile(r"제\s*(\d+)\s*조")
        selected_rows: list[tuple[tuple[object, ...], int, str]] = []
        for manual_id in manual_ids:
            manual_rows = by_manual.get(manual_id, [])
            if targets == {4}:
                process_pages = {
                    int(row[3])
                    for row in manual_rows
                    if 4 in [int(value) for value in article_pattern.findall(str(row[6]))]
                }
                selected_count = 0
                for row in manual_rows:
                    if int(row[3]) not in process_pages:
                        continue
                    content = str(row[6])
                    numbers = [int(value) for value in article_pattern.findall(content)]
                    section_title = str(row[5])
                    if 4 not in numbers:
                        if not re.match(r"\s*\d+[.)]", section_title):
                            continue
                        if numbers:
                            marker = article_pattern.search(content)
                            content = content[:marker.start()].strip() if marker else content
                    if content and selected_count < maximum_chunks_per_document:
                        selected_rows.append((row, 4, content))
                        selected_count += 1
                continue
            current_article: int | None = None
            selected_count = 0
            for row in manual_rows:
                content = str(row[6])
                numbers = [int(value) for value in article_pattern.findall(content)]
                matched_numbers = [number for number in numbers if number in targets]
                article_number = (
                    matched_numbers[-1]
                    if matched_numbers
                    else current_article if current_article in targets else None
                )
                bounded_content = content
                if article_number is not None and not matched_numbers and numbers:
                    marker = article_pattern.search(content)
                    bounded_content = content[:marker.start()].strip() if marker else content
                if numbers:
                    current_article = numbers[-1]
                if article_number is not None and bounded_content and selected_count < maximum_chunks_per_document:
                    selected_rows.append((row, article_number, bounded_content))
                    selected_count += 1

        snippet_limit_raw = os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip()
        try:
            snippet_limit = max(200, int(snippet_limit_raw))
        except ValueError:
            snippet_limit = 1800
        results = []
        for row, article_number, content in selected_rows:
            evidence_id = f"{row[0]}:{row[2]}:{row[3]}:{row[7]}"
            section_title = f"제{article_number}조 {row[5]}"
            results.append(VectorSearchResult(
                manual_id=str(row[0]),
                title=str(row[1]),
                version=str(row[2]),
                page_start=int(row[3]),
                page_end=int(row[4]),
                section_title=section_title,
                score=0.0,
                vector_score=0.0,
                lexical_score=0.0,
                snippet=content[:snippet_limit] + ("..." if len(content) > snippet_limit else ""),
                content=content,
                citation=f"[{row[1]} v{row[2]} p.{row[3]} {section_title}]",
                evidence_id=evidence_id,
                ranking_stage="article_context",
                reranker_score=None,
                document_status=str(row[9]),
                authority_level=str(row[10]),
                validity_status=str(row[11]),
                warning=None,
                document_type=str(row[13]),
                owner_team=str(row[14]),
                effective_from=str(row[15]) if row[15] else None,
                expires_at=str(row[16]) if row[16] else None,
                chunk_index=int(row[8]),
                approval_status=str(row[12]) if row[12] else None,
            ))
        return results

    def catalog(self, role: str, allow_unresolved: bool) -> list[dict[str, object]]:
        """활성 release에서 역할과 유효성 조건을 통과한 문서 metadata를 나열한다."""

        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT manual_id, title, version, document_type, owner_team
                FROM corpus_active_release active
                JOIN corpus_releases release ON release.release_id=active.release_id
                JOIN corpus_release_documents document
                  ON document.release_id=release.release_id
                WHERE active.singleton=TRUE
                  AND release.status='ACTIVE'
                  AND release.embedding_provider=%s
                  AND release.embedding_model=%s
                  AND release.embedding_dimensions=%s
                  AND release.embedding_version=%s
                  AND release.corpus_manifest_sha256=%s
                  AND release.processing_profile_sha256=%s
                  AND document.deleted_at IS NULL
                  AND document.document_status = 'WORKING_KNOWLEDGE'
                  AND document.approval_status = 'APPROVED'
                  AND %s = ANY(document.role_scope)
                  AND (%s OR document.validity_status != 'UNRESOLVED')
                  AND (document.effective_from IS NULL OR document.effective_from <= CURRENT_DATE)
                  AND (document.expires_at IS NULL OR document.expires_at >= CURRENT_DATE)
                ORDER BY document.title, document.manual_id
                """,
                (*self._active_release_parameters(), role, allow_unresolved),
            ).fetchall()
        return [{"manual_id": row[0], "title": row[1], "version": row[2], "document_type": row[3], "owner_team": row[4]} for row in rows]

    def source_receipt(
        self,
        manual_id: str,
        role: str,
        allow_unresolved: bool,
    ) -> tuple[Path, str]:
        """원본 조회 권한을 검증하고 저장 경로와 발행 시점 checksum을 반환한다."""

        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT source_path, content_checksum
                FROM corpus_active_release active
                JOIN corpus_releases release ON release.release_id=active.release_id
                JOIN corpus_release_documents document
                  ON document.release_id=release.release_id
                WHERE active.singleton=TRUE
                  AND release.status='ACTIVE'
                  AND release.embedding_provider=%s
                  AND release.embedding_model=%s
                  AND release.embedding_dimensions=%s
                  AND release.embedding_version=%s
                  AND release.corpus_manifest_sha256=%s
                  AND release.processing_profile_sha256=%s
                  AND document.manual_id = %s
                  AND document.deleted_at IS NULL
                  AND document.document_status = 'WORKING_KNOWLEDGE'
                  AND document.approval_status = 'APPROVED'
                  AND %s = ANY(document.role_scope)
                  AND (%s OR document.validity_status != 'UNRESOLVED')
                  AND (document.effective_from IS NULL OR document.effective_from <= CURRENT_DATE)
                  AND (document.expires_at IS NULL OR document.expires_at >= CURRENT_DATE)
                """,
                (
                    *self._active_release_parameters(),
                    manual_id,
                    role,
                    allow_unresolved,
                ),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(manual_id)
        return Path(row[0]), str(row[1])

    def load_answer_evidence(
        self,
        *,
        retrieval_request_id: str,
        role: str,
        query: str,
        answer_intent: str,
        trace_id: str,
        actor_hash: str,
        caller_evidence: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """현재 권한·질문·trace에 봉인된 retrieval evidence를 검증해 원자 소비한다."""

        try:
            receipt_id = UUID(retrieval_request_id)
        except (TypeError, ValueError) as error:
            raise ValueError("RAG retrieval receipt identity is invalid") from error
        if (
            not role.strip()
            or not answer_intent.strip()
            or not trace_id.strip()
            or len(trace_id) > 128
            or len(actor_hash) != 64
            or any(character not in "0123456789abcdef" for character in actor_hash)
        ):
            raise ValueError("RAG retrieval receipt principal is invalid")
        query_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT receipt.evidence_ids, receipt.evidence_payload,
                       receipt.evidence_payload_sha256
                FROM retrieval_evidence_receipts receipt
                JOIN corpus_active_release active
                  ON active.release_id=receipt.release_id
                JOIN corpus_releases release
                  ON release.release_id=receipt.release_id
                WHERE receipt.receipt_id=%s
                  AND receipt.user_role=%s
                  AND receipt.answer_intent=%s
                  AND receipt.trace_id=%s
                  AND receipt.actor_hash=%s
                  AND receipt.answer_query_sha256=%s
                  AND receipt.consumed_at IS NULL
                  AND receipt.expires_at>CURRENT_TIMESTAMP
                  AND active.singleton=TRUE
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
                FOR UPDATE OF receipt
                FOR SHARE OF active, release
                """,
                (
                    receipt_id,
                    role,
                    answer_intent,
                    trace_id,
                    actor_hash,
                    query_sha256,
                    *self._active_release_parameters(),
                    json.dumps(self._required_documents(), sort_keys=True),
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError(
                    "RAG retrieval receipt is unavailable, expired, consumed, or unauthorized"
                )
            return self._consume_answer_evidence_receipt(
                connection=connection,
                receipt_id=receipt_id,
                role=role,
                row=row,
                caller_evidence=caller_evidence,
            )

    def _consume_answer_evidence_receipt(
        self,
        *,
        connection: psycopg.Connection,
        receipt_id: UUID,
        role: str,
        row: tuple[object, ...],
        caller_evidence: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        evidence_ids = [str(value) for value in row[0]]
        stored = row[1]
        if isinstance(stored, str):
            stored = json.loads(stored)
        fields = {
            "evidence_id",
            "text",
            "title",
            "manual_id",
            "version",
            "document_type",
            "owner_team",
            "section_title",
            "citation",
        }
        if (
            not isinstance(stored, list)
            or not stored
            or len(stored) != len(evidence_ids)
            or len(stored) > 50
            or any(
                not isinstance(item, dict)
                or set(item) != fields
                or any(not isinstance(value, str) for value in item.values())
                or not item["evidence_id"]
                or not item["text"]
                for item in stored
            )
            or [item["evidence_id"] for item in stored] != evidence_ids
        ):
            raise RuntimeError("RAG retrieval evidence receipt is invalid")
        canonical = json.dumps(
            stored,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if (
            hashlib.sha256(canonical.encode("utf-8")).hexdigest() != str(row[2])
            or caller_evidence != stored
        ):
            raise RuntimeError("RAG answer evidence differs from its search receipt")
        matched = connection.execute(
            """
            SELECT evidence.ordinality, evidence.item->>'evidence_id',
                   document.manual_id, document.title, document.version,
                   document.document_type, document.owner_team,
                   chunk.section_title, chunk.content, chunk.page_start
            FROM jsonb_array_elements(%s::jsonb)
                 WITH ORDINALITY AS evidence(item, ordinality)
            JOIN corpus_active_release active ON active.singleton=TRUE
            JOIN corpus_releases release ON release.release_id=active.release_id
            JOIN corpus_release_documents document
              ON document.release_id=release.release_id
             AND document.manual_id=evidence.item->>'manual_id'
            JOIN corpus_release_chunks chunk
              ON chunk.release_id=document.release_id
             AND chunk.manual_id=document.manual_id
             AND evidence.item->>'evidence_id'=(
                 document.manual_id || ':' || document.version || ':' ||
                 chunk.page_start::text || ':' || chunk.chunk_id
             )
            WHERE release.status='ACTIVE'
              AND release.embedding_provider=%s
              AND release.embedding_model=%s
              AND release.embedding_dimensions=%s
              AND release.embedding_version=%s
              AND release.corpus_manifest_sha256=%s
              AND release.processing_profile_sha256=%s
              AND document.deleted_at IS NULL
              AND document.document_status='WORKING_KNOWLEDGE'
              AND document.approval_status='APPROVED'
              AND document.validity_status!='UNRESOLVED'
              AND cardinality(document.role_scope)>0
              AND %s=ANY(document.role_scope)
              AND (document.effective_from IS NULL
                OR document.effective_from<=CURRENT_DATE)
              AND (document.expires_at IS NULL
                OR document.expires_at>=CURRENT_DATE)
              AND chunk.deleted_at IS NULL
              AND chunk.embedding_provider=release.embedding_provider
              AND chunk.embedding_model=release.embedding_model
              AND chunk.embedding_dimensions=release.embedding_dimensions
              AND chunk.embedding_version=release.embedding_version
              AND chunk.source_document_hash=document.content_checksum
            ORDER BY evidence.ordinality
            FOR SHARE OF active, release, document, chunk
            """,
            (
                canonical,
                *self._active_release_parameters(),
                role,
            ),
        ).fetchall()
        if len(matched) != len(stored) or any(
            not _matches_active_evidence_projection(item, row, index)
            for index, (item, row) in enumerate(
                zip(stored, matched, strict=True),
                start=1,
            )
        ):
            raise RuntimeError(
                "RAG retrieval evidence no longer matches authorized corpus rows"
            )
        consumed = connection.execute(
            """
            UPDATE retrieval_evidence_receipts
            SET consumed_at=CURRENT_TIMESTAMP
            WHERE receipt_id=%s
              AND consumed_at IS NULL
              AND expires_at>CURRENT_TIMESTAMP
            """,
            (receipt_id,),
        )
        if consumed.rowcount != 1:
            raise RuntimeError("RAG retrieval receipt could not be consumed")
        return [dict(item) for item in stored]

    def record_answer_trace(
        self,
        *,
        request_id: str,
        trace_id: str,
        retrieval_request_id: str | None,
        query_hash: str,
        status: str,
        latency_ms: float,
        model_id: str,
        answer_hash: str,
        answer_type: str | None,
        citation_evidence_ids: list[str],
    ) -> None:
        """답변 상태·인용·제한 사항을 retrieval request와 연결해 감사 trace로 남긴다."""

        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO answer_traces(
                    request_id, trace_id, retrieval_request_id, query_hash,
                    status, latency_ms, model_id, answer_hash, answer_type,
                    citation_evidence_ids, citation_count
                ) VALUES (
                    %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s
                )
                ON CONFLICT(request_id) DO UPDATE SET
                    status=EXCLUDED.status,
                    latency_ms=EXCLUDED.latency_ms,
                    answer_hash=EXCLUDED.answer_hash,
                    answer_type=EXCLUDED.answer_type,
                    citation_evidence_ids=EXCLUDED.citation_evidence_ids,
                    citation_count=EXCLUDED.citation_count
                """,
                (
                    request_id,
                    trace_id,
                    retrieval_request_id,
                    query_hash,
                    status,
                    latency_ms,
                    model_id,
                    answer_hash,
                    answer_type,
                    json.dumps(citation_evidence_ids, ensure_ascii=False),
                    len(citation_evidence_ids),
                ),
            )

    def _vector_literal(self, vector: np.ndarray) -> str:
        return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
