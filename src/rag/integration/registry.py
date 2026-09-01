"""PostgreSQL Tool Registry에서 지정 도구와 역할별 호출 가능 도구를 읽기 전용으로 조회한다."""

from __future__ import annotations

import psycopg

from .contracts import ToolRegistration


class PgToolRegistryRepository:
    """도구의 승인·상태·역할·스키마 레코드를 PostgreSQL에서 typed 등록 정보로 복원한다."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def load(self, tool_codes: tuple[str, ...]) -> dict[str, ToolRegistration]:
        """요청한 도구 코드만 매개변수화 조회하고 코드별 등록 정보 사전으로 반환한다."""

        if not tool_codes:
            return {}
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT tool_code, semantic_version, evidence_type, enabled,
                       approval_status, required_roles, timeout_seconds,
                       maximum_retries, name, description, input_schema_json,
                       output_schema_json, health_status
                FROM tool_registry
                WHERE tool_code = ANY(%s)
                """,
                (list(tool_codes),),
            ).fetchall()
        return {
            str(row[0]): ToolRegistration(
                tool_code=str(row[0]),
                semantic_version=str(row[1]),
                evidence_type=str(row[2]),
                enabled=bool(row[3]),
                approval_status=str(row[4]),
                required_roles=frozenset(str(role) for role in row[5]),
                timeout_seconds=int(row[6]),
                maximum_retries=int(row[7]),
                title=str(row[8]),
                description=str(row[9]),
                input_schema_json=dict(row[10]),
                output_schema_json=dict(row[11]),
                health_status=str(row[12]),
            )
            for row in rows
        }

    def list_callable(self, role: str) -> tuple[ToolRegistration, ...]:
        """활성·승인·정상이며 지정 역할을 허용한 도구만 코드 순으로 반환한다."""

        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT tool_code, semantic_version, evidence_type, enabled,
                       approval_status, required_roles, timeout_seconds,
                       maximum_retries, name, description, input_schema_json,
                       output_schema_json, health_status
                FROM tool_registry
                WHERE enabled = TRUE AND approval_status = 'APPROVED'
                  AND health_status = 'HEALTHY'
                  AND %s = ANY(required_roles)
                ORDER BY tool_code
                """,
                (role,),
            ).fetchall()
        return tuple(
            ToolRegistration(
                tool_code=str(row[0]),
                semantic_version=str(row[1]),
                evidence_type=str(row[2]),
                enabled=bool(row[3]),
                approval_status=str(row[4]),
                required_roles=frozenset(str(item) for item in row[5]),
                timeout_seconds=int(row[6]),
                maximum_retries=int(row[7]),
                title=str(row[8]),
                description=str(row[9]),
                input_schema_json=dict(row[10]),
                output_schema_json=dict(row[11]),
                health_status=str(row[12]),
            )
            for row in rows
        )
