"""보고서 schedule의 활성 상태·next run·DUE claim을 DB clock과 row lock으로 관리한다."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters.report_repository_common import _advance_schedule, _uuid
from src.report.domain import ManualRunCommand, RunStatus


class ReportScheduleRepositoryMixin:
    """승인 보고서 schedule의 등록·조회·DUE claim·완료 전진을 소유자 범위에서 제공한다.

    DB row lock과 scheduled timestamp 기반 idempotency key로 중복 command를 막는다. 완료
    시각은 연결된 동일 definition version의 terminal run이 확인될 때만 다음 cadence로
    전진한다.
    """
    async def create_schedule(
        self,
        schedule_id: str,
        definition_id: str,
        version: int,
        cadence: str,
        timezone_name: str,
        next_run_at: datetime,
    ) -> dict[str, object]:
        """접근 가능한 승인 definition version에 Asia/Seoul schedule을 등록한다.

        UUID·cadence·timezone을 검증하고 한 transaction에서 schedule을 삽입한다. 비승인 또는
        비소유 definition과 중복 schedule ID는 ``ValueError``이며, 성공하면 저장된 schedule
        dict를 다시 조회해 반환한다.
        """
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        definition_uuid = _uuid(definition_id, "definition_id")
        if cadence not in {"daily", "weekly", "monthly"}:
            raise ValueError("지원하지 않는 Report cadence입니다.")
        if timezone_name != "Asia/Seoul":
            raise ValueError("Report schedule timezone은 Asia/Seoul이어야 합니다.")
        try:
            async with self._sessionmaker.begin() as session:
                approved = (await session.execute(
                    text(
                        """
                        SELECT 1 FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id AND v.version = :version
                          AND v.status = 'approved'
                          AND (:manage_all OR d.owner_id = :owner_id)
                        """
                    ),
                    {
                        **self._scope_params(),
                        "definition_id": definition_uuid,
                        "version": version,
                    },
                )).first()
                if approved is None:
                    raise ValueError("관리 범위의 승인된 Report definition version만 예약할 수 있습니다.")
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_schedules
                            (schedule_id, definition_id, definition_version, cadence,
                             timezone_name, next_run_at)
                        VALUES (:schedule_id, :definition_id, :version, :cadence,
                                :timezone_name, :next_run_at)
                        """
                    ),
                    {
                        "schedule_id": schedule_uuid,
                        "definition_id": definition_uuid,
                        "version": version,
                        "cadence": cadence,
                        "timezone_name": timezone_name,
                        "next_run_at": next_run_at,
                    },
                )
        except IntegrityError as error:
            raise ValueError("같은 Report schedule_id가 이미 존재합니다.") from error
        return await self.get_schedule(str(schedule_uuid))

    async def get_schedule(self, schedule_id: str) -> dict[str, object]:
        """소유자 또는 ``manage_all`` 범위의 schedule 설정과 실행 포인터를 반환한다.

        UUID 형식 오류는 ``ValueError``이고 누락·비소유 schedule은 같은 ``KeyError``로
        처리해 존재 여부를 노출하지 않는다.
        """
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT s.schedule_id, s.definition_id, s.definition_version,
                           s.cadence, s.timezone_name, s.next_run_at,
                           s.enabled, s.last_run_id
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.schedule_id = :schedule_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {**self._scope_params(), "schedule_id": schedule_uuid},
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("Report schedule을 찾을 수 없습니다.")
        return self._schedule_response(row)

    async def list_schedules(self) -> tuple[dict[str, object], ...]:
        """owner scope의 schedule 설정·next run·last run을 생성 순서대로 반환한다."""
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                text(
                    """
                    SELECT s.schedule_id, s.definition_id, s.definition_version,
                           s.cadence, s.timezone_name, s.next_run_at,
                           s.enabled, s.last_run_id
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE (:manage_all OR d.owner_id = :owner_id)
                    ORDER BY s.created_at, s.schedule_id
                    """
                ),
                self._scope_params(),
            )).mappings().all()
        return tuple(self._schedule_response(row) for row in rows)

    async def list_due_schedule_ids(
        self,
        now: datetime,
        *,
        limit: int = 50,
    ) -> tuple[str, ...]:
        """timezone-aware 기준 시각까지 DUE인 활성 schedule ID를 next-run 순으로 제한 조회한다."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now에는 timezone offset이 필요합니다.")
        if limit < 1 or limit > 100:
            raise ValueError("Report schedule 조회 limit은 1~100이어야 합니다.")
        async with self._sessionmaker() as session:
            schedule_ids = (await session.execute(
                text(
                    """
                    SELECT s.schedule_id
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.enabled AND s.next_run_at <= :now
                      AND (:manage_all OR d.owner_id = :owner_id)
                    ORDER BY s.next_run_at, s.schedule_id
                    LIMIT :limit
                    """
                ),
                {**self._scope_params(), "now": now, "limit": limit},
            )).scalars().all()
        return tuple(str(schedule_id) for schedule_id in schedule_ids)

    async def set_schedule_enabled(
        self,
        schedule_id: str,
        enabled: bool,
    ) -> dict[str, object]:
        """스케줄 enabled 변경을 현재 상태와 충돌 여부를 확인한 뒤 원자적으로 반영한다."""
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        async with self._sessionmaker.begin() as session:
            updated = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_schedules AS s
                    SET enabled = :enabled, updated_at = now()
                    FROM report_v1.report_definitions AS d
                    WHERE s.schedule_id = :schedule_id
                      AND d.definition_id = s.definition_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    RETURNING s.schedule_id
                    """
                ),
                {
                    **self._scope_params(),
                    "schedule_id": schedule_uuid,
                    "enabled": enabled,
                },
            )).scalar_one_or_none()
        if updated is None:
            raise KeyError("Report schedule을 찾을 수 없습니다.")
        return await self.get_schedule(str(updated))

    async def queue_due_schedule(
        self,
        schedule_id: str,
        now: datetime,
    ) -> tuple[dict[str, object], ManualRunCommand | None]:
        """DUE 스케줄 작업을 멱등성·소유권 조건을 확인한 뒤 실행 대기 상태로 전환한다."""
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        command = None
        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT s.definition_id, s.definition_version, s.cadence,
                           s.next_run_at, s.enabled
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.schedule_id = :schedule_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF s
                    """
                ),
                {**self._scope_params(), "schedule_id": schedule_uuid},
            )).mappings().one_or_none()
            if row is None:
                raise KeyError("Report schedule not found")
            if row["enabled"] and row["next_run_at"] <= now:
                scheduled_for = row["next_run_at"]
                command_row = (await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_manual_run_commands
                            (command_id, definition_id, definition_version, as_of,
                             idempotency_key)
                        VALUES (:command_id, :definition_id, :version, :as_of,
                                :idempotency_key)
                        ON CONFLICT (definition_id, definition_version, idempotency_key)
                        DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                        RETURNING command_id, definition_id, definition_version, as_of,
                                  idempotency_key, status
                        """
                    ),
                    {
                        "command_id": uuid4(),
                        "definition_id": row["definition_id"],
                        "version": row["definition_version"],
                        "as_of": scheduled_for,
                        "idempotency_key": f"schedule:{schedule_uuid}:{scheduled_for.isoformat()}",
                    },
                )).mappings().one()
                command = ManualRunCommand(
                    str(command_row["command_id"]),
                    str(command_row["definition_id"]),
                    command_row["definition_version"],
                    command_row["as_of"],
                    command_row["idempotency_key"],
                    RunStatus(command_row["status"]),
                )
        return await self.get_schedule(str(schedule_uuid)), command

    async def complete_due_schedule(
        self,
        schedule_id: str,
        scheduled_for: datetime,
        run_id: str,
    ) -> dict[str, object]:
        """완료된 동일 보고서 run을 확인한 뒤 schedule의 다음 실행 시각을 비교 갱신한다.

        row lock 후 현재 ``next_run_at``이 ``scheduled_for``와 같고 run이 같은 definition
        version의 terminal 상태일 때만 cadence를 전진하고 ``last_run_id``를 기록한다. 이미
        전진했거나 run 조건이 다르면 no-op이다. 누락·비소유 schedule은 ``KeyError``이며
        성공하면 현재 schedule dict를 반환한다.
        """
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        run_uuid = _uuid(run_id, "run_id")
        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT s.cadence, s.next_run_at
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.schedule_id = :schedule_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF s
                    """
                ),
                {**self._scope_params(), "schedule_id": schedule_uuid},
            )).mappings().one_or_none()
            if row is None:
                raise KeyError("Report schedule not found")
            if row["next_run_at"] == scheduled_for:
                await session.execute(
                    text(
                        """
                        UPDATE report_v1.report_schedules AS s
                        SET next_run_at = :next_run_at, last_run_id = :run_id,
                            updated_at = now()
                        WHERE s.schedule_id = :schedule_id
                          AND s.next_run_at = :scheduled_for
                          AND EXISTS (
                              SELECT 1
                              FROM report_v1.report_runs AS r
                              WHERE r.run_id = :run_id
                                AND r.definition_id = s.definition_id
                                AND r.definition_version = s.definition_version
                                AND r.status IN ('success', 'partial', 'failed', 'cancelled')
                          )
                        """
                    ),
                    {
                        "next_run_at": _advance_schedule(scheduled_for, row["cadence"]),
                        "run_id": run_uuid,
                        "schedule_id": schedule_uuid,
                        "scheduled_for": scheduled_for,
                    },
                )
        return await self.get_schedule(str(schedule_uuid))

    @staticmethod
    def _schedule_response(row) -> dict[str, object]:
        return {
            "schedule_id": row["schedule_id"],
            "definition_id": row["definition_id"],
            "version": row["definition_version"],
            "cadence": row["cadence"],
            "timezone": row["timezone_name"],
            "next_run_at": row["next_run_at"],
            "enabled": row["enabled"],
            "last_run_id": row["last_run_id"],
        }
