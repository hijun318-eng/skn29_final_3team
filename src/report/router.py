from dataclasses import asdict
from datetime import datetime
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from .domain import (
    BlockRunStatus,
    BlockType,
    DefinitionStatus,
    ManualRunCommand,
    REPORT_CONTRACT_VERSION,
    ReportBlock,
    ReportBlockRun,
    ReportDefinitionVersion,
    ReportRun,
    ReportSchedule,
    RunStatus,
    ScheduleFrequency,
)
from .repository import InMemoryReportRepository

REPORT_ROUTES: Final = (
    ("POST", "/reports/definitions", "create_definition"),
    ("GET", "/reports/definitions", "list_definitions"),
    ("POST", "/reports/definitions/{definition_id}/versions/{version}/approve", "approve_version"),
    ("POST", "/reports/definitions/{definition_id}/versions/{version}/drafts", "create_next_draft"),
    ("GET", "/reports/definitions/{definition_id}/versions/{version}", "get_version"),
    ("PUT", "/reports/definitions/{definition_id}/versions/{version}/blocks", "replace_draft_blocks"),
    ("POST", "/reports/runs", "create_run"),
    ("GET", "/reports/runs", "list_runs"),
    ("GET", "/reports/runs/{run_id}", "get_run"),
    ("POST", "/reports/runs/manual", "create_manual_run_command"),
    ("PUT", "/reports/definitions/{definition_id}/versions/{version}/schedule", "upsert_schedule"),
    ("GET", "/reports/schedules", "list_schedules"),
)


class ReportRouteError(ValueError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ReportRouter:
    """Framework-neutral router contract that R4 can wrap with FastAPI APIRouter."""

    routes = REPORT_ROUTES

    def __init__(self, repository: InMemoryReportRepository) -> None:
        self.repository = repository

    @staticmethod
    def _response(version: ReportDefinitionVersion) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "definition_id": version.definition_id,
            "version": version.version,
            "status": version.status.value,
            "title": version.title,
            "blocks": [asdict(block) for block in version.blocks],
            "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        }

    @staticmethod
    def _blocks(payload: list[dict[str, Any]]) -> tuple[ReportBlock, ...]:
        blocks = []
        for block in payload:
            width = block.get("w", block.get("columns"))
            if width is None:
                raise KeyError("columns")
            blocks.append(ReportBlock(
                block_id=block["block_id"],
                title=block["title"],
                artifact_id=block.get("artifact_id"),
                columns=block.get("columns", width),
                query_id=block.get("query_id"),
                type=BlockType(block.get("type", "table")),
                x=block.get("x", 0),
                y=block.get("y", 0),
                w=width,
                h=block.get("h", 1),
                content=block.get("content", ""),
            ))
        return tuple(blocks)

    @staticmethod
    def _run_response(run: ReportRun) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "run_id": run.run_id,
            "definition_id": run.definition_id,
            "definition_version": run.definition_version,
            "as_of": run.as_of.isoformat(),
            "policy_version": run.policy_version,
            "context_hash": run.context_hash,
            "watermark": dict(run.watermark),
            "status": run.status.value,
            "blocks": [asdict(block) for block in run.blocks],
        }

    @staticmethod
    def _command_response(command: ManualRunCommand) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "command_id": command.command_id,
            "definition_id": command.definition_id,
            "version": command.version,
            "as_of": command.as_of.isoformat(),
            "idempotency_key": command.idempotency_key,
            "status": command.status.value,
        }

    @staticmethod
    def _schedule_response(schedule: ReportSchedule) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "schedule_id": schedule.schedule_id,
            "definition_id": schedule.definition_id,
            "version": schedule.version,
            "frequency": schedule.frequency.value,
            "hour": schedule.hour,
            "minute": schedule.minute,
            "timezone": schedule.timezone,
            "weekday": schedule.weekday,
            "day_of_month": schedule.day_of_month,
            "enabled": schedule.enabled,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        }

    def create_definition(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"definition_id", "title", "blocks"}
        extra = set(payload) - allowed
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            blocks = self._blocks(payload.get("blocks", []))
            draft = ReportDefinitionVersion(
                definition_id=payload["definition_id"],
                version=1,
                status=DefinitionStatus.DRAFT,
                title=payload["title"],
                blocks=blocks,
            )
            return self._response(self.repository.add_draft(draft))
        except KeyError as error:
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    def approve_version(self, definition_id: str, version: int, approved_at: str) -> dict[str, Any]:
        try:
            approved = self.repository.approve(definition_id, version, datetime.fromisoformat(approved_at))
            return self._response(approved)
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error
        except ValueError as error:
            raise ReportRouteError(409, str(error)) from error

    def create_next_draft(self, definition_id: str, version: int) -> dict[str, Any]:
        try:
            return self._response(self.repository.create_next_draft(definition_id, version))
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error
        except ValueError as error:
            raise ReportRouteError(409, str(error)) from error

    def get_version(self, definition_id: str, version: int) -> dict[str, Any]:
        try:
            return self._response(self.repository.get_version(definition_id, version))
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error

    def list_definitions(self) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "items": [self._response(version) for version in self.repository.list_definitions()],
        }

    def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        extra = set(payload) - {"blocks"}
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            return self._response(
                self.repository.replace_draft_blocks(
                    definition_id,
                    version,
                    self._blocks(payload["blocks"]),
                )
            )
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "run_id", "definition_id", "definition_version", "as_of", "policy_version",
            "context_hash", "watermark", "status", "blocks",
        }
        extra = set(payload) - allowed
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            blocks = tuple(
                ReportBlockRun(
                    block_id=block["block_id"],
                    artifact_id=block["artifact_id"],
                    query_id=block["query_id"],
                    snapshot_checksum=block["snapshot_checksum"],
                    status=BlockRunStatus(block["status"]),
                )
                for block in payload.get("blocks", [])
            )
            run = ReportRun(
                run_id=payload["run_id"],
                definition_id=payload["definition_id"],
                definition_version=payload["definition_version"],
                as_of=datetime.fromisoformat(payload["as_of"]),
                policy_version=payload["policy_version"],
                context_hash=payload["context_hash"],
                watermark=payload["watermark"],
                status=RunStatus(payload["status"]),
                blocks=blocks,
            )
            saved = self.repository.add_run(run)
            return self._run_response(saved)
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    def list_runs(self, definition_id: str | None = None) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "items": [self._run_response(run) for run in self.repository.list_runs(definition_id)],
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            return self._run_response(self.repository.get_run(run_id))
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error

    def create_manual_run_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"definition_id", "version", "as_of", "idempotency_key"}
        extra = set(payload) - allowed
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            command = self.repository.queue_manual_run(
                payload["definition_id"],
                payload["version"],
                datetime.fromisoformat(payload["as_of"]),
                payload["idempotency_key"],
            )
            return self._command_response(command)
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    def upsert_schedule(
        self,
        definition_id: str,
        version: int,
        payload: dict[str, Any],
        current: datetime | None = None,
    ) -> dict[str, Any]:
        allowed = {"frequency", "hour", "minute", "weekday", "day_of_month", "enabled"}
        extra = set(payload) - allowed
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            schedule = ReportSchedule(
                schedule_id=str(uuid5(NAMESPACE_URL, f"report-schedule:{definition_id}:{version}")),
                definition_id=definition_id,
                version=version,
                frequency=ScheduleFrequency(payload["frequency"]),
                hour=payload["hour"],
                minute=payload["minute"],
                weekday=payload.get("weekday"),
                day_of_month=payload.get("day_of_month"),
                enabled=payload.get("enabled", False),
            )
            if schedule.enabled:
                now = current or datetime.now(ZoneInfo(schedule.timezone))
                schedule = ReportSchedule(
                    schedule.schedule_id, schedule.definition_id, schedule.version,
                    schedule.frequency, schedule.hour, schedule.minute, schedule.timezone,
                    schedule.weekday, schedule.day_of_month, True, schedule.next_after(now),
                )
            return self._schedule_response(self.repository.save_schedule(schedule))
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    def list_schedules(self) -> dict[str, Any]:
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "items": [self._schedule_response(item) for item in self.repository.list_schedules()],
        }


def create_report_router(repository: InMemoryReportRepository | None = None) -> ReportRouter:
    return ReportRouter(repository or InMemoryReportRepository())
