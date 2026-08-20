"""프레임워크 독립 보고서 요청을 도메인 객체와 저장소 포트에 연결하고 HTTP 오류를 정규화한다."""

from dataclasses import asdict
from datetime import datetime
from inspect import isawaitable
from typing import Any, Final

from .domain import (
    BlockFailureCode,
    BlockRunStatus,
    BlockType,
    DefinitionStatus,
    ManualRunCommand,
    REPORT_CONTRACT_VERSION,
    ReportBlock,
    ReportBlockRun,
    ReportDefinitionVersion,
    ReportRun,
    RunStatus,
)
from .repository import ReportRepository

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
)


class ReportRouteError(ValueError):
    """보고서 요청의 검증·미존재·상태 충돌을 HTTP 상태 코드와 공개 상세 문구로 전달한다."""
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def _repository_result(value):
    """프레임워크 독립 포트가 반환한 즉시 값과 비동기 영속 결과를 동일한 router 흐름으로 정규화한다."""
    return await value if isawaitable(value) else value


class ReportRouter:
    """원시 payload를 도메인 값으로 검증하고 주입된 저장소 결과를 버전 있는 응답으로 직렬화한다."""

    routes = REPORT_ROUTES

    def __init__(self, repository: ReportRepository) -> None:
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
            "orientation": version.orientation,
            "currency_display_unit": version.currency_display_unit,
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

    async def create_definition(self, payload: dict[str, Any]) -> dict[str, Any]:
        """새 정의 payload의 허용 필드와 블록 격자를 검증해 버전 1 초안을 저장하고 반환한다."""
        allowed = {
            "definition_id", "title", "blocks", "orientation", "currency_display_unit"
        }
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
                orientation=payload.get("orientation", "portrait"),
                currency_display_unit=payload.get("currency_display_unit", "auto"),
            )
            return self._response(await _repository_result(self.repository.add_draft(draft)))
        except KeyError as error:
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    async def approve_version(self, definition_id: str, version: int, approved_at: str) -> dict[str, Any]:
        """ISO 승인 시각으로 지정 초안을 승인하며 미존재는 404, 상태 충돌은 409로 변환한다."""
        try:
            approved = await _repository_result(
                self.repository.approve(definition_id, version, datetime.fromisoformat(approved_at))
            )
            return self._response(approved)
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error
        except ValueError as error:
            raise ReportRouteError(409, str(error)) from error

    async def create_next_draft(self, definition_id: str, version: int) -> dict[str, Any]:
        """승인된 정의 버전에서 다음 초안을 생성하며 대상 부재와 잘못된 상태를 구분해 반환한다."""
        try:
            return self._response(
                await _repository_result(self.repository.create_next_draft(definition_id, version))
            )
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error
        except ValueError as error:
            raise ReportRouteError(409, str(error)) from error

    async def get_version(self, definition_id: str, version: int) -> dict[str, Any]:
        """정의 ID와 버전으로 단일 정의를 조회하고 저장소 미존재 오류를 404로 정규화한다."""
        try:
            return self._response(
                await _repository_result(self.repository.get_version(definition_id, version))
            )
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error

    async def list_definitions(self) -> dict[str, Any]:
        """저장소가 허용한 정의 버전들을 계약 버전이 포함된 items 응답으로 직렬화한다."""
        versions = await _repository_result(self.repository.list_definitions())
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "items": [self._response(version) for version in versions],
        }

    async def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """초안 블록 전체와 선택적 표시 설정을 검증·교체하고 입력·미존재·충돌 오류를 구분한다."""
        extra = set(payload) - {"blocks", "title", "orientation", "currency_display_unit"}
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            return self._response(
                await _repository_result(self.repository.replace_draft_blocks(
                    definition_id,
                    version,
                    self._blocks(payload["blocks"]),
                    title=payload.get("title"),
                    orientation=payload.get("orientation"),
                    currency_display_unit=payload.get("currency_display_unit"),
                ))
            )
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    async def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """블록별 성공 증거 또는 타입 실패를 검증해 보고서 실행을 저장하고 버전 응답으로 반환한다."""
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
                    request_id=block.get("request_id"),
                    failure_code=(
                        BlockFailureCode(block["failure_code"])
                        if block.get("failure_code")
                        else None
                    ),
                    failure_message=block.get("failure_message"),
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
            saved = await _repository_result(self.repository.add_run(run))
            return self._run_response(saved)
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error

    async def list_runs(self, definition_id: str | None = None) -> dict[str, Any]:
        """선택적 정의 ID로 실행 이력을 조회해 계약 버전과 직렬화된 items를 반환한다."""
        runs = await _repository_result(self.repository.list_runs(definition_id))
        return {
            "contract_version": REPORT_CONTRACT_VERSION,
            "items": [self._run_response(run) for run in runs],
        }

    async def get_run(self, run_id: str) -> dict[str, Any]:
        """실행 ID로 단일 보고서 실행과 블록 증거를 조회하고 미존재를 404로 변환한다."""
        try:
            return self._run_response(await _repository_result(self.repository.get_run(run_id)))
        except KeyError as error:
            raise ReportRouteError(404, str(error)) from error

    async def create_manual_run_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """정의 버전·ISO 기준 시각·멱등 키로 수동 명령을 큐에 넣고 입력·상태 오류를 정규화한다."""
        allowed = {"definition_id", "version", "as_of", "idempotency_key"}
        extra = set(payload) - allowed
        if extra:
            raise ReportRouteError(422, f"허용되지 않은 필드: {', '.join(sorted(extra))}")
        try:
            command = await _repository_result(self.repository.queue_manual_run(
                payload["definition_id"],
                payload["version"],
                datetime.fromisoformat(payload["as_of"]),
                payload["idempotency_key"],
            ))
            return self._command_response(command)
        except KeyError as error:
            if error.args and error.args[0] == "Report definition version을 찾을 수 없습니다.":
                raise ReportRouteError(404, str(error)) from error
            raise ReportRouteError(422, f"필수 필드 누락: {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ReportRouteError(409, str(error)) from error


def create_report_router(repository: ReportRepository) -> ReportRouter:
    """명시적으로 주입된 영속 저장소만 사용해 framework-neutral router를 구성한다."""

    # 저장소 누락을 메모리 구현으로 감추면 재시작 시 데이터가 사라지고 권한·transaction
    # 경계도 우회된다. composition root가 영속 port를 반드시 선택하도록 즉시 실패한다.
    return ReportRouter(repository)
