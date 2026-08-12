from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from .domain import (
    DefinitionStatus,
    ManualRunCommand,
    ReportBlock,
    ReportDefinitionVersion,
    ReportRun,
    ReportSchedule,
    RunStatus,
)


class InMemoryReportRepository:
    """R4 등록 전 contract test용 repository; production persistence가 아니다."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, int], ReportDefinitionVersion] = {}
        self._runs: dict[str, ReportRun] = {}
        self._commands: dict[str, ManualRunCommand] = {}
        self._idempotency: dict[tuple[str, int, str], str] = {}
        self._schedules: dict[str, ReportSchedule] = {}

    def add_draft(self, draft: ReportDefinitionVersion) -> ReportDefinitionVersion:
        if draft.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft만 저장할 수 있습니다.")
        key = (draft.definition_id, draft.version)
        existing = self._versions.get(key)
        if existing and existing.status is DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report version은 덮어쓸 수 없습니다.")
        self._versions[key] = draft
        return draft

    def get_version(self, definition_id: str, version: int) -> ReportDefinitionVersion:
        try:
            return self._versions[(definition_id, version)]
        except KeyError as error:
            raise KeyError("Report definition version을 찾을 수 없습니다.") from error

    def list_definitions(self) -> tuple[ReportDefinitionVersion, ...]:
        return tuple(self._versions[key] for key in sorted(self._versions))

    def approve(self, definition_id: str, version: int, approved_at: datetime) -> ReportDefinitionVersion:
        approved = self.get_version(definition_id, version).approve(approved_at)
        self._versions[(definition_id, version)] = approved
        return approved

    def create_next_draft(self, definition_id: str, approved_version: int) -> ReportDefinitionVersion:
        draft = self.get_version(definition_id, approved_version).next_draft()
        return self.add_draft(draft)

    def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
    ) -> ReportDefinitionVersion:
        replaced = self.get_version(definition_id, version).replace_blocks(blocks)
        self._versions[(definition_id, version)] = replaced
        return replaced

    def add_run(self, run: ReportRun) -> ReportRun:
        version = self.get_version(run.definition_id, run.definition_version)
        if version.status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
        if run.run_id in self._runs:
            raise ValueError("같은 Report run_id를 다시 저장할 수 없습니다.")
        self._runs[run.run_id] = run
        return run

    def list_runs(self, definition_id: str | None = None) -> tuple[ReportRun, ...]:
        runs = self._runs.values()
        return tuple(run for run in runs if definition_id is None or run.definition_id == definition_id)

    def get_run(self, run_id: str) -> ReportRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise KeyError("Report run을 찾을 수 없습니다.") from error

    def queue_manual_run(
        self,
        definition_id: str,
        version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ManualRunCommand:
        if self.get_version(definition_id, version).status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
        key = (definition_id, version, idempotency_key)
        if command_id := self._idempotency.get(key):
            return self._commands[command_id]
        command = ManualRunCommand(str(uuid4()), definition_id, version, as_of, idempotency_key)
        self._commands[command.command_id] = command
        self._idempotency[key] = command.command_id
        return command

    def save_schedule(self, schedule: ReportSchedule) -> ReportSchedule:
        if self.get_version(schedule.definition_id, schedule.version).status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report definition version만 예약할 수 있습니다.")
        if schedule.enabled:
            self.assert_schedule_activatable(schedule.definition_id, schedule.version)
        self._schedules[schedule.schedule_id] = schedule
        return schedule

    def assert_schedule_activatable(self, definition_id: str, version: int) -> None:
        report_version = self.get_version(definition_id, version)
        if not any(
            run.definition_id == definition_id
            and run.definition_version == version
            and run.status is RunStatus.SUCCESS
            for run in self._runs.values()
        ):
            raise ValueError("스케줄 활성화 전에 성공한 수동 실행이 필요합니다.")
        if any(
            block.type.value != "text" and not block.artifact_id
            for block in report_version.blocks
        ):
            raise ValueError("스케줄 활성화 전에 모든 block의 재실행 binding이 필요합니다.")

    def list_schedules(self) -> tuple[ReportSchedule, ...]:
        return tuple(self._schedules[key] for key in sorted(self._schedules))

    def get_schedule(self, schedule_id: str) -> ReportSchedule:
        try:
            return self._schedules[schedule_id]
        except KeyError as error:
            raise KeyError("Report schedule을 찾을 수 없습니다.") from error

    def queue_due_schedules(self, current: datetime) -> tuple[ManualRunCommand, ...]:
        commands = []
        for schedule_id, schedule in tuple(self._schedules.items()):
            if not schedule.enabled or schedule.next_run_at is None or schedule.next_run_at > current:
                continue
            command = self.queue_manual_run(
                schedule.definition_id,
                schedule.version,
                schedule.next_run_at,
                f"schedule:{schedule.schedule_id}:{schedule.next_run_at.isoformat()}",
            )
            commands.append(command)
            self._schedules[schedule_id] = replace(
                schedule, next_run_at=schedule.next_after(schedule.next_run_at)
            )
        return tuple(commands)
