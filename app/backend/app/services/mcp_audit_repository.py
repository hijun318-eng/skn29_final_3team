"""MCP Tool 실행의 입력 해시와 최소 출력 참조를 App DB 감사 표에 기록한다."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import RequestContext
from app.database import session_scope


class McpAuditUnavailable(RuntimeError):
    """Tool 실행 근거를 저장하지 못해 성공 처리를 중단해야 함을 나타낸다."""

    pass


class McpAuditRepository:
    """민감한 원문 대신 해시·상태·추적 식별자만 영속화하는 감사 저장소다."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def record(
        self,
        tool_id: UUID,
        context: RequestContext,
        arguments: dict[str, Any],
        status: str,
        started: float,
        output_ref: dict[str, Any],
        error_code: str | None = None,
    ) -> None:
        """한 Tool 호출의 권한 결과와 지연 시간, 제한된 출력 참조를 원자적으로 기록한다."""

        try:
            async with session_scope(self._database_url) as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO tooling.tool_runs
                            (tool_run_id, tool_id, caller_user_id, caller_role,
                             trace_id, input_hash, status, latency_ms,
                             output_ref_json, error_code)
                        VALUES (:run_id, :tool_id, :user_id, :role, :trace_id,
                                :input_hash, :status, :latency_ms,
                                CAST(:output_ref AS jsonb), :error_code)
                        """
                    ),
                    {
                        "run_id": uuid4(),
                        "tool_id": tool_id,
                        "user_id": context.user_id,
                        "role": context.role.value,
                        "trace_id": context.trace_id,
                        "input_hash": hashlib.sha256(
                            json.dumps(arguments, sort_keys=True).encode()
                        ).hexdigest(),
                        "status": status,
                        "latency_ms": max(
                            0, round((time.perf_counter() - started) * 1000)
                        ),
                        "output_ref": json.dumps(output_ref, default=str),
                        "error_code": error_code,
                    },
                )
        except SQLAlchemyError as error:
            raise McpAuditUnavailable(
                "MCP execution evidence could not be stored."
            ) from error
