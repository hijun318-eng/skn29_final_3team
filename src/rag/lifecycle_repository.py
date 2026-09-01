"""PostgreSQL RAG 문서의 soft-delete·복원·수명주기 감사 작업을 수행한다."""

from __future__ import annotations

import psycopg


class DocumentLifecycleRepository:
    """문서와 청크의 삭제 상태를 함께 전환하고 행위자·사유를 감사 로그로 남긴다."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def soft_delete(self, manual_id: str, actor_role: str, reason: str) -> int:
        """활성 문서와 청크를 soft-delete하고 실제 전환된 문서 수를 반환한다.

        문서가 전환된 경우에만 행위자 역할과 사유를 기록하며 DB 오류는 트랜잭션
        rollback 후 호출자에게 전파된다.
        """

        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                "UPDATE documents SET deleted_at=CURRENT_TIMESTAMP WHERE manual_id=%s AND deleted_at IS NULL",
                (manual_id,),
            )
            connection.execute(
                "UPDATE document_chunks SET deleted_at=CURRENT_TIMESTAMP WHERE manual_id=%s AND deleted_at IS NULL",
                (manual_id,),
            )
            if row.rowcount:
                self._log(connection, manual_id, "SOFT_DELETE", actor_role, reason)
            return row.rowcount

    def restore(self, manual_id: str, actor_role: str, reason: str) -> int:
        """삭제된 문서·청크를 복원하고 실제 복원된 문서가 있을 때 감사 로그를 남긴다."""

        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                "UPDATE documents SET deleted_at=NULL WHERE manual_id=%s AND deleted_at IS NOT NULL",
                (manual_id,),
            )
            connection.execute(
                "UPDATE document_chunks SET deleted_at=NULL WHERE manual_id=%s",
                (manual_id,),
            )
            if row.rowcount:
                self._log(connection, manual_id, "RESTORE", actor_role, reason)
            return row.rowcount

    def snapshot(self, manual_id: str) -> dict[str, object]:
        """현재 버전·삭제 여부·보관 버전 수·시간순 수명주기 작업을 조회한다."""

        with psycopg.connect(self._database_url) as connection:
            current = connection.execute(
                "SELECT version, deleted_at IS NOT NULL FROM documents WHERE manual_id=%s",
                (manual_id,),
            ).fetchone()
            version_count = connection.execute(
                "SELECT COUNT(*) FROM document_versions WHERE manual_id=%s", (manual_id,)
            ).fetchone()[0]
            actions = connection.execute(
                "SELECT action FROM document_lifecycle_logs WHERE manual_id=%s ORDER BY event_id",
                (manual_id,),
            ).fetchall()
        return {
            "current_version": current[0] if current else None,
            "soft_deleted": bool(current[1]) if current else None,
            "archived_version_count": version_count,
            "actions": [row[0] for row in actions],
        }

    def remove_synthetic_fixture(self, manual_id: str) -> None:
        """``SYNTHETIC-`` 접두어가 있는 검증 fixture만 관련 테이블에서 영구 삭제한다.

        실제 문서 식별자를 받으면 데이터 손상을 막기 위해 ``ValueError``로 거부한다.
        """

        if not manual_id.startswith("SYNTHETIC-"):
            raise ValueError("Only SYNTHETIC fixtures may be removed")
        with psycopg.connect(self._database_url) as connection:
            connection.execute("DELETE FROM document_chunks WHERE manual_id=%s", (manual_id,))
            connection.execute("DELETE FROM documents WHERE manual_id=%s", (manual_id,))
            connection.execute("DELETE FROM document_versions WHERE manual_id=%s", (manual_id,))
            connection.execute("DELETE FROM document_lifecycle_logs WHERE manual_id=%s", (manual_id,))

    @staticmethod
    def _log(connection: psycopg.Connection, manual_id: str, action: str, actor: str, reason: str) -> None:
        connection.execute(
            """
            INSERT INTO document_lifecycle_logs(manual_id, action, actor_role, reason)
            VALUES (%s, %s, %s, %s)
            """,
            (manual_id, action, actor, reason),
        )
