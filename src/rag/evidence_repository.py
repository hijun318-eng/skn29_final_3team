from __future__ import annotations

import psycopg


class RagEvidenceRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def source_inventory(self) -> list[dict[str, object]]:
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT d.manual_id, d.title, d.version, d.source_path, d.content_checksum,
                       COUNT(c.chunk_id), MAX(c.page_end)
                FROM documents d
                LEFT JOIN document_chunks c ON c.manual_id=d.manual_id AND c.deleted_at IS NULL
                WHERE d.deleted_at IS NULL
                GROUP BY d.manual_id, d.title, d.version, d.source_path, d.content_checksum
                ORDER BY d.manual_id
                """
            ).fetchall()
        return [
            {
                "manual_id": row[0], "title": row[1], "version": row[2],
                "source_path": row[3], "sha256": row[4],
                "chunk_count": row[5], "page_count": row[6],
            }
            for row in rows
        ]

    def evaluation_sources(self) -> list[dict[str, str]]:
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT d.manual_id, d.title, STRING_AGG(c.content, E'\n' ORDER BY c.page_start, c.chunk_id)
                FROM documents d
                JOIN document_chunks c ON c.manual_id=d.manual_id AND c.deleted_at IS NULL
                WHERE d.deleted_at IS NULL
                GROUP BY d.manual_id, d.title ORDER BY d.manual_id
                """
            ).fetchall()
        return [
            {"manual_id": str(row[0]), "title": str(row[1]), "content": str(row[2])}
            for row in rows
        ]

    def ingestion_history(self) -> list[dict[str, object]]:
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT run_id, started_at, finished_at, status, document_count, chunk_count, error_text
                FROM ingestion_runs ORDER BY started_at
                """
            ).fetchall()
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
