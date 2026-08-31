"""Gateway 인증 결과와 재전송 방지 nonce를 PostgreSQL에 기록한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg


class SecurityAuditRepository:
    """민감 payload 대신 request·role·hash·결과만 제한 길이로 감사 저장한다."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def record(
        self,
        request_id: str | None,
        role: str | None,
        query_hash: str,
        outcome: str,
        reason: str,
    ) -> None:
        """인증 outcome과 reason을 원문 질문 없이 security audit log에 기록한다."""

        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO api_security_audit_logs(
                    request_id, presented_role, query_hash, outcome, reason
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    (request_id or "MISSING")[:100],
                    (role or "MISSING")[:50],
                    query_hash,
                    outcome,
                    reason[:100],
                ),
            )

    def reserve_request_id(self, request_id: str, ttl_seconds: int = 120) -> bool:
        """만료 nonce를 정리하고 request ID를 한 번만 예약했는지 반환한다."""

        now = datetime.now(timezone.utc)
        with psycopg.connect(self._database_url) as connection:
            connection.execute("DELETE FROM api_request_nonces WHERE expires_at < %s", (now,))
            row = connection.execute(
                """
                INSERT INTO api_request_nonces(request_id, expires_at)
                VALUES (%s, %s) ON CONFLICT(request_id) DO NOTHING
                RETURNING request_id
                """,
                (request_id, now + timedelta(seconds=ttl_seconds)),
            ).fetchone()
        return row is not None
