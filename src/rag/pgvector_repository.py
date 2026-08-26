from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from uuid import UUID

import numpy as np
import psycopg

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

        # Build SQL condition based on retrieval mode
        score_calc = (
            "GREATEST(vector_score, "
            "0.7 * vector_score + 0.3 * LEAST(1.0, lexical_score * 2.0))"
        )
        where_cond = f"(1 - (c.embedding <=> %s::vector) >= %s OR word_similarity(%s, d.title) >= 0.15 OR word_similarity(%s, c.content) >= 0.15)"
        params = [query_vector, query_text, query_text, role, allow_unresolved, list(selected_manual_ids), list(selected_manual_ids), query_vector, minimum_vector_score, query_text, query_text]

        if retrieval_mode == "LEXICAL_ONLY":
            score_calc = "lexical_score"
            where_cond = f"(word_similarity(%s, d.title) >= 0.15 OR word_similarity(%s, c.content) >= 0.15)"
            # Adjust params for LEXICAL_ONLY
            params = [query_vector, query_text, query_text, role, allow_unresolved, list(selected_manual_ids), list(selected_manual_ids), query_text, query_text]
        elif retrieval_mode == "VECTOR_ONLY":
            score_calc = "vector_score"
            where_cond = f"(1 - (c.embedding <=> %s::vector) >= %s)"
            # Adjust params for VECTOR_ONLY
            params = [query_vector, query_text, query_text, role, allow_unresolved, list(selected_manual_ids), list(selected_manual_ids), query_vector, minimum_vector_score]

        sql = f"""
                WITH candidates AS (
                    SELECT d.manual_id, d.title, d.version, c.page_start, c.page_end,
                           c.section_title, c.content, d.document_status, c.chunk_id,
                           c.chunk_index, d.authority_level, d.validity_status,
                           d.approval_status, d.document_type,
                           d.owner_team, d.effective_from, d.expires_at,
                           1 - (c.embedding <=> %s::vector) AS vector_score,
                           GREATEST(
                               word_similarity(%s, d.title),
                               word_similarity(%s, c.content)
                           ) AS lexical_score
                    FROM document_chunks c
                    JOIN documents d ON d.manual_id = c.manual_id
                    WHERE c.deleted_at IS NULL AND d.deleted_at IS NULL
                      AND d.document_status = 'WORKING_KNOWLEDGE'
                      AND %s = ANY(d.role_scope)
                      AND (%s OR d.validity_status != 'UNRESOLVED')
                      AND (
                          cardinality(%s::text[]) = 0
                          OR d.manual_id = ANY(%s::text[])
                      )
                      AND (d.effective_from IS NULL OR d.effective_from <= CURRENT_DATE)
                      AND (d.expires_at IS NULL OR d.expires_at >= CURRENT_DATE)
                      AND {where_cond}
                ), ranked AS (
                    SELECT *,
                           {score_calc} AS score,
                           ROW_NUMBER() OVER (
                               PARTITION BY manual_id
                               ORDER BY {score_calc} DESC
                           ) AS document_rank
                    FROM candidates
                )
                SELECT manual_id, title, version, page_start, page_end, section_title,
                       content, score, vector_score, lexical_score, chunk_id,
                       chunk_index, document_status, authority_level, validity_status,
                       approval_status, document_type,
                       owner_team, effective_from, expires_at
                FROM ranked WHERE document_rank <= %s
                ORDER BY score DESC LIMIT %s
        """
        params.append(maximum_chunks_per_document)
        params.append(top_k)

        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(sql, params).fetchall()

        results = []
        for row in rows:
            # row order follows the final SELECT above.

            # Since to_vector_search_result was used previously, we'll build it here or modify vector_result_mapper.py
            # But it's easier to build VectorSearchResult here to avoid modifying vector_result_mapper.py unnecessarily
            manual_id = row[0]
            title = row[1]
            version = row[2]
            page_start = row[3]
            page_end = row[4]
            section_title = row[5]
            content = row[6]
            score = row[7]
            vector_score = row[8]
            lexical_score = row[9]
            chunk_id = row[10]

            evidence_id = f"{manual_id}:{version}:{page_start}:{chunk_id}"

            # basic snippet logic from old mapper
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
                    ranking_stage="retrieval",
                    reranker_score=None,
                    document_status=row[12],
                    authority_level=row[13],
                    validity_status=row[14],
                    warning=None,
                    document_type=row[16],
                    owner_team=row[17],
                    effective_from=str(row[18]) if row[18] else None,
                    expires_at=str(row[19]) if row[19] else None,
                    chunk_index=int(row[11]),
                    approval_status=row[15],
                )
            )
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

    def catalog(self) -> list[dict[str, object]]:
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """SELECT manual_id, title, version, document_type, owner_team
                   FROM documents WHERE deleted_at IS NULL ORDER BY title, manual_id"""
            ).fetchall()
        return [{"manual_id": row[0], "title": row[1], "version": row[2], "document_type": row[3], "owner_team": row[4]} for row in rows]

    def source_path(self, manual_id: str) -> Path:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute("SELECT source_path FROM documents WHERE manual_id=%s AND deleted_at IS NULL", (manual_id,)).fetchone()
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
