from __future__ import annotations

import psycopg


class DocumentLifecycleRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def soft_delete(self, manual_id: str, actor_role: str, reason: str) -> int:
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
