from __future__ import annotations

from datetime import datetime, timezone
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


class PgVectorRepository(PgVectorObservabilityMixin):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def migrate(self, migration_path: Path) -> None:
        sql = migration_path.read_text(encoding="utf-8")
        with psycopg.connect(self._database_url, autocommit=True) as connection:
            connection.execute(sql)

    def start_run(self, run_id: UUID, metadata: dict[str, object]) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """INSERT INTO ingestion_runs(
                       run_id, started_at, status, embedding_provider, embedding_model,
                       embedding_dimensions, embedding_version
                   ) VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s)""",
                (run_id, datetime.now(timezone.utc), metadata["provider"], metadata["model"], metadata["dimensions"], metadata["version"]),
            )

    def finish_run(
        self, run_id: UUID, status: str, document_count: int, chunk_count: int, error: str | None = None
    ) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE ingestion_runs
                SET finished_at=%s, status=%s, document_count=%s, chunk_count=%s, error_text=%s
                WHERE run_id=%s
                """,
                (datetime.now(timezone.utc), status, document_count, chunk_count, error, run_id),
            )

    def unchanged(self, document: PdfDocument, metadata: dict[str, object]) -> bool:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT d.content_checksum, d.title, d.version, d.source_path,
                       MIN(c.embedding_provider), MIN(c.embedding_model), MIN(c.embedding_dimensions),
                       MIN(c.embedding_version), COUNT(DISTINCT c.embedding_provider), COUNT(DISTINCT c.embedding_version)
                FROM documents d JOIN document_chunks c ON c.manual_id=d.manual_id
                WHERE d.manual_id=%s AND d.deleted_at IS NULL AND c.deleted_at IS NULL
                GROUP BY d.content_checksum, d.title, d.version, d.source_path
                """,
                (document.manual_id,),
            ).fetchone()
        return bool(
            row
            and row[0] == document.checksum
            and row[1] == document.title
            and row[2] == document.version
            and row[3] == document.source_path
            and row[4] == metadata["provider"]
            and row[5] == metadata["model"]
            and row[6] == metadata["dimensions"]
            and row[7] == metadata["version"]
            and row[8] == 1
            and row[9] == 1
        )

    def replace_document(
        self, document: PdfDocument, chunks: list[PdfChunk], embeddings: np.ndarray, metadata: dict[str, object]
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts differ")
        with psycopg.connect(self._database_url) as connection:
            archived = connection.execute(
                """
                INSERT INTO document_versions(
                    manual_id, title, version, source_path, content_checksum,
                    document_status, authority_level, validity_status, role_scope,
                    document_type, owner_team, effective_from, expires_at,
                    approval_status, archive_reason
                )
                SELECT manual_id, title, version, source_path, content_checksum,
                       document_status, authority_level, validity_status, role_scope,
                       document_type, owner_team, effective_from, expires_at,
                       approval_status, 'CONTENT_REPLACED'
                FROM documents
                WHERE manual_id=%s AND deleted_at IS NULL
                ON CONFLICT(manual_id, content_checksum) DO NOTHING
                RETURNING version_id
                """,
                (document.manual_id,),
            ).fetchone()
            if archived:
                connection.execute(
                    """
                    INSERT INTO document_chunk_versions(
                        version_id, chunk_id, chunk_index, page_start, page_end, section_title,
                        content, content_checksum, embedding
                    )
                    SELECT %s, chunk_id, chunk_index, page_start, page_end, section_title,
                           content, content_checksum, embedding
                    FROM document_chunks WHERE manual_id=%s AND deleted_at IS NULL
                    """,
                    (archived[0], document.manual_id),
                )
                connection.execute(
                    """
                    INSERT INTO document_lifecycle_logs(manual_id, action, actor_role, reason)
                    VALUES (%s, 'VERSION_ARCHIVED', 'SYSTEM_ADMIN', 'CONTENT_REPLACED')
                    """,
                    (document.manual_id,),
                )
            connection.execute(
                """
                INSERT INTO documents(
                    manual_id, title, version, source_path, content_checksum, role_scope,
                    document_type, owner_team, effective_from, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(manual_id) DO UPDATE SET
                    title=EXCLUDED.title, version=EXCLUDED.version,
                    source_path=EXCLUDED.source_path, content_checksum=EXCLUDED.content_checksum,
                    role_scope=EXCLUDED.role_scope, document_type=EXCLUDED.document_type,
                    owner_team=EXCLUDED.owner_team, effective_from=EXCLUDED.effective_from,
                    expires_at=EXCLUDED.expires_at, deleted_at=NULL,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
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
                ),
            )
            connection.execute("DELETE FROM document_chunks WHERE manual_id=%s", (document.manual_id,))
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO document_chunks(
                        chunk_id, manual_id, chunk_index, page_start, page_end, section_title,
                        content, content_checksum, embedding, embedding_provider,
                        embedding_model, embedding_dimensions, embedding_version,
                        source_document_hash, embedded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """,
                    [
                        (
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
                        )
                        for chunk, vector in zip(chunks, embeddings, strict=True)
                    ],
                )
            connection.execute(
                """
                INSERT INTO document_lifecycle_logs(manual_id, action, actor_role, reason)
                VALUES (%s, 'UPSERT', 'SYSTEM_ADMIN', 'INGESTION')
                """,
                (document.manual_id,),
            )
        return len(chunks)

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
            FROM document_chunks c
            JOIN documents d ON d.manual_id = c.manual_id
            WHERE c.deleted_at IS NULL AND d.deleted_at IS NULL
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
            page_start, page_end, section_title, content = row[3:7]
            chunk_id = row[8]
            evidence_id = f"{manual_id}:{version}:{page_start}:{chunk_id}"
            snippet_limit_raw = os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip()
            try:
                snippet_limit = max(200, int(snippet_limit_raw))
            except ValueError:
                snippet_limit = 1800
            snippet = content[:snippet_limit] + "..." if len(content) > snippet_limit else content
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
                    document_type=str(row[14]),
                    owner_team=str(row[15]),
                    effective_from=str(row[16]) if row[16] else None,
                    expires_at=str(row[17]) if row[17] else None,
                    chunk_index=int(row[9]),
                    approval_status=str(row[13]),
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
                FROM document_chunks c
                JOIN documents d ON d.manual_id=c.manual_id
                WHERE c.deleted_at IS NULL AND d.deleted_at IS NULL
                  AND d.manual_id=ANY(%s::text[])
                  AND %s=ANY(d.role_scope)
                  AND d.document_status='WORKING_KNOWLEDGE'
                  AND d.approval_status='APPROVED'
                  AND (%s OR d.validity_status!='UNRESOLVED')
                  AND (d.effective_from IS NULL OR d.effective_from <= CURRENT_DATE)
                  AND (d.expires_at IS NULL OR d.expires_at >= CURRENT_DATE)
                ORDER BY d.manual_id, c.page_start, c.chunk_index
                """,
                (list(manual_ids), role, allow_unresolved),
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
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT manual_id, title, version, document_type, owner_team
                FROM documents
                WHERE deleted_at IS NULL
                  AND document_status = 'WORKING_KNOWLEDGE'
                  AND approval_status = 'APPROVED'
                  AND %s = ANY(role_scope)
                  AND (%s OR validity_status != 'UNRESOLVED')
                  AND (effective_from IS NULL OR effective_from <= CURRENT_DATE)
                  AND (expires_at IS NULL OR expires_at >= CURRENT_DATE)
                ORDER BY title, manual_id
                """,
                (role, allow_unresolved),
            ).fetchall()
        return [{"manual_id": row[0], "title": row[1], "version": row[2], "document_type": row[3], "owner_team": row[4]} for row in rows]

    def source_path(self, manual_id: str, role: str, allow_unresolved: bool) -> Path:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT source_path
                FROM documents
                WHERE manual_id = %s
                  AND deleted_at IS NULL
                  AND document_status = 'WORKING_KNOWLEDGE'
                  AND approval_status = 'APPROVED'
                  AND %s = ANY(role_scope)
                  AND (%s OR validity_status != 'UNRESOLVED')
                  AND (effective_from IS NULL OR effective_from <= CURRENT_DATE)
                  AND (expires_at IS NULL OR expires_at >= CURRENT_DATE)
                """,
                (manual_id, role, allow_unresolved),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(manual_id)
        return Path(row[0])

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
