from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Chunk, DocumentConfig


class SqliteRagRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    manual_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    version TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    role_scope TEXT NOT NULL,
                    document_status TEXT NOT NULL,
                    authority_level TEXT NOT NULL,
                    validity_status TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    manual_id TEXT NOT NULL REFERENCES documents(manual_id),
                    section_number TEXT NOT NULL,
                    section_title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    token_terms TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS retrieval_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    result_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def upsert_document(self, config: DocumentConfig, checksum: str, chunks: list[Chunk]) -> int:
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT checksum FROM documents WHERE manual_id = ?", (config.manual_id,)
            ).fetchone()
            if previous and previous[0] == checksum:
                return 0
            connection.execute(
                """
                INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(manual_id) DO UPDATE SET
                    title=excluded.title, version=excluded.version, checksum=excluded.checksum,
                    role_scope=excluded.role_scope, document_status=excluded.document_status,
                    authority_level=excluded.authority_level, validity_status=excluded.validity_status,
                    deleted_at=NULL
                """,
                (
                    config.manual_id,
                    config.title,
                    config.version,
                    checksum,
                    json.dumps(config.role_scope, ensure_ascii=False),
                    config.document_status,
                    config.authority_level,
                    config.validity_status,
                ),
            )
            connection.execute("DELETE FROM chunks WHERE manual_id = ?", (config.manual_id,))
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk.chunk_id,
                        chunk.manual_id,
                        chunk.section_number,
                        chunk.section_title,
                        chunk.content,
                        json.dumps(chunk.token_terms, ensure_ascii=False),
                    )
                    for chunk in chunks
                ],
            )
            return len(chunks)

    def list_searchable_chunks(self, role: str, allow_unresolved: bool) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT c.*, d.title, d.version, d.role_scope, d.validity_status
                FROM chunks c JOIN documents d ON d.manual_id = c.manual_id
                WHERE d.deleted_at IS NULL AND d.document_status = 'WORKING_KNOWLEDGE'
                  AND d.role_scope LIKE ?
                  AND (? = 1 OR d.validity_status != 'UNRESOLVED')
                """,
                (f'%"{role}"%', int(allow_unresolved)),
            ).fetchall()

    def record_search(self, query_hash: str, role: str, result_count: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO retrieval_audit_logs(query_hash, role, result_count) VALUES (?, ?, ?)",
                (query_hash, role, result_count),
            )

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "chunks": connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "audits": connection.execute("SELECT COUNT(*) FROM retrieval_audit_logs").fetchone()[0],
            }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
