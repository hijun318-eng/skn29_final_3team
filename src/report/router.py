from dataclasses import asdict
from datetime import datetime
from typing import Any, Final

from .domain import (
    BlockRunStatus,
    DefinitionStatus,
    ReportBlock,
    ReportBlockRun,
    ReportDefinitionVersion,
    ReportRun,
    RunStatus,
)
from .repository import InMemoryReportRepository

REPORT_ROUTES: Final = (
    ("POST", "/reports/definitions", "create_definition"),
    ("POST", "/reports/definitions/{definition_id}/versions/{version}/approve", "approve_version"),
    ("POST", "/reports/definitions/{definition_id}/versions/{version}/drafts", "create_next_draft"),
    ("GET", "/reports/definitions/{definition_id}/versions/{version}", "get_version"),
    ("POST", "/reports/runs", "create_run"),
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
            "contract_version": "REPORT-v1.0.0",
            "definition_id": version.definition_id,
            "version": version.version,
            "status": version.status.value,
            "title": version.title,
            "blocks": [asdict(block) for block in version.blocks],
            "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        }

    def create_definition(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"definition_id", "title", "blocks"}
        extra = set(payload) - allowed
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            blocks = tuple(ReportBlock(**block) for block in payload.get("blocks", []))
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
            return {
                "contract_version": "REPORT-v1.0.0",
                "run_id": saved.run_id,
                "definition_id": saved.definition_id,
                "definition_version": saved.definition_version,
                "as_of": saved.as_of.isoformat(),
                "policy_version": saved.policy_version,
                "context_hash": saved.context_hash,
                "watermark": dict(saved.watermark),
                "status": saved.status.value,
                "blocks": [asdict(block) for block in saved.blocks],
            }
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error


def create_report_router(repository: InMemoryReportRepository | None = None) -> ReportRouter:
    return ReportRouter(repository or InMemoryReportRepository())