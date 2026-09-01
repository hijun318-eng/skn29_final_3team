"""로컬 RAG 검증용 문서·청크·검색 감사를 SQLite 트랜잭션으로 보관한다."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import Chunk, DocumentConfig


class SqliteRagRepository:
    """운영 pgvector와 분리된 로컬 검증 저장소의 스키마와 원자적 갱신을 담당한다."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """문서, 청크, 검색 감사 테이블이 없을 때 동일 스키마로 생성한다."""

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
        """checksum이 바뀐 문서와 전체 청크를 한 트랜잭션으로 교체하고 삽입 수를 반환한다.

        기존 checksum과 같으면 저장 내용을 건드리지 않고 0을 반환하며 SQLite 오류는
        연결 경계에서 rollback한 뒤 전파한다.
        """

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
        """삭제되지 않은 작업지식 중 역할과 유효성 조건을 만족하는 청크 행을 조회한다."""

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
        """원문 질의 대신 해시·역할·결과 수만 검색 감사 로그에 기록한다."""

        with self._connect() as connection:
            connection.execute(
                "INSERT INTO retrieval_audit_logs(query_hash, role, result_count) VALUES (?, ?, ?)",
                (query_hash, role, result_count),
            )

    def counts(self) -> dict[str, int]:
        """현재 로컬 저장소의 문서·청크·검색 감사 행 수를 반환한다."""

        with self._connect() as connection:
            return {
                "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "chunks": connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "audits": connection.execute("SELECT COUNT(*) FROM retrieval_audit_logs").fetchone()[0],
            }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """작업 종료 시 Windows 파일 잠금까지 해제하는 연결 범위를 제공한다."""

        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
