from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.adapters.analysis_repository import (
    AnalysisRepositoryUnavailable,
    PostgresAnalysisRepository,
)
from app.auth import AuthenticationError, require_active_subject
from app.context import ContextValidationError
from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    ErrorCode,
    RequestContext,
    Role,
)
from app.controllers.analysis_controller import AnalysisController
from src.report.domain import BlockFailureCode, BlockRunStatus, ReportRun


_PUBLIC_FAILURES = {
    code.value: code
    for code in BlockFailureCode
}


class ExecutionGate(Protocol):
    def acquire(self, wait_seconds: float = 0) -> bool: ...

    def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    status: BlockRunStatus
    request_id: str | None = None
    artifact_id: str | None = None
    query_id: str | None = None
    snapshot_checksum: str | None = None
    policy_version: str | None = None
    failure_code: BlockFailureCode | None = None
    failure_message: str | None = None


def _failure_code(value: str | None) -> BlockFailureCode:
    return _PUBLIC_FAILURES.get(value or "", BlockFailureCode.INTERNAL_ERROR)


def _failure(
    code: BlockFailureCode,
    message: str,
    *,
    request_id: UUID | None = None,
    cancelled: bool = False,
) -> ReplayOutcome:
    return ReplayOutcome(
        status=BlockRunStatus.CANCELLED if cancelled else BlockRunStatus.FAILED,
        request_id=str(request_id) if request_id else None,
        failure_code=code,
        failure_message=message[:300],
    )


class AnalysisDefinitionReplay:
    """Run one stored Analysis Definition through the current full pipeline."""

    def __init__(
        self,
        database_url: str,
        controller: AnalysisController,
        execution_gate: ExecutionGate,
        *,
        queue_wait_seconds: float = 0,
    ) -> None:
        self._database_url = database_url
        self._controller = controller
        self._execution_gate = execution_gate
        self._queue_wait_seconds = queue_wait_seconds

    def execute(
        self,
        *,
        owner_id: UUID,
        definition_id: str,
        definition_version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ReplayOutcome:
        repository = PostgresAnalysisRepository(self._database_url, owner_id)
        try:
            require_active_subject(owner_id, Role.HOTEL_ANALYST)
            definition = repository.get_definition_for_report(
                definition_id, definition_version
            )
        except AuthenticationError:
            return _failure(
                BlockFailureCode.ACCESS_DENIED,
                "The Report owner no longer has analysis access.",
            )
        except KeyError:
            return _failure(
                BlockFailureCode.DEFINITION_NOT_FOUND,
                "The saved analysis definition is unavailable.",
            )
        except AnalysisRepositoryUnavailable:
            return _failure(
                BlockFailureCode.REPLAY_UNAVAILABLE,
                "The analysis repository is temporarily unavailable.",
            )

        # report_as_of owns period sealing. Stored non-period parameters remain
        # stable; old absolute period boundaries are never silently reused.
        parameters = {
            key: value
            for key, value in definition["parameters"].items()
            if key not in {"period_start", "period_end_exclusive"}
        }
        report_date = as_of.astimezone(ZoneInfo("Asia/Seoul")).date()
        context = RequestContext(
            request_id=uuid4(),
            trace_id=uuid4().hex,
            user_id=owner_id,
            role=Role.HOTEL_ANALYST,
            as_of=report_date,
            timezone="Asia/Seoul",
        )
        request_id: UUID | None = None
        try:
            request_id, created = repository.begin_run(
                definition,
                context,
                report_date,
                idempotency_key,
                parameters,
            )
            if not created:
                return self._existing_outcome(repository, request_id)
            if not self._execution_gate.acquire(self._queue_wait_seconds):
                repository.fail_run(request_id, ErrorCode.RATE_LIMITED.value)
                return _failure(
                    BlockFailureCode.RATE_LIMITED,
                    "The analysis execution limit was reached.",
                    request_id=request_id,
                )

            execution: dict[str, object] = {}
            try:
                response = self._controller.submit(
                    AnalysisRequest(
                        question=definition["question"],
                        parameters=parameters,
                    ),
                    context,
                    execution.update,
                )
            except ContextValidationError as error:
                repository.fail_run(
                    request_id,
                    "PERMISSION"
                    if error.code is ErrorCode.ACCESS_DENIED
                    else "UNSUPPORTED",
                )
                return _failure(
                    _failure_code(error.code.value),
                    error.message,
                    request_id=request_id,
                )
            except Exception:
                repository.fail_run(request_id)
                return _failure(
                    BlockFailureCode.INTERNAL_ERROR,
                    "The analysis replay failed.",
                    request_id=request_id,
                )
            finally:
                self._execution_gate.release()

            repository.finish_run(request_id, response, execution)
            if response.data.status in {AnalysisStatus.SUCCEEDED, AnalysisStatus.PARTIAL}:
                artifact = repository.get_run_artifact(request_id)
                failure = response.error
                return ReplayOutcome(
                    status=(
                        BlockRunStatus.SUCCESS
                        if response.data.status is AnalysisStatus.SUCCEEDED
                        else BlockRunStatus.PARTIAL
                    ),
                    request_id=str(request_id),
                    artifact_id=str(artifact["artifact_id"]),
                    query_id=str(artifact["query_id"]),
                    snapshot_checksum=str(artifact["artifact_checksum"]),
                    policy_version=(artifact.get("evidence") or {}).get("policy_version"),
                    failure_code=_failure_code(failure.code.value) if failure else None,
                    failure_message=failure.message[:300] if failure else None,
                )
            error = response.error
            code = _failure_code(error.code.value if error else None)
            return _failure(
                code,
                error.message if error else "The analysis replay failed.",
                request_id=request_id,
                cancelled=response.data.status is AnalysisStatus.CANCELLED,
            )
        except AnalysisRepositoryUnavailable:
            if request_id is not None:
                try:
                    repository.fail_run(request_id, ErrorCode.ARTIFACT_PERSIST_FAILED.value)
                except Exception:
                    pass
            return _failure(
                BlockFailureCode.ARTIFACT_PERSIST_FAILED,
                "The replay result could not be persisted.",
                request_id=request_id,
            )
        except (KeyError, ValueError):
            return _failure(
                BlockFailureCode.REPLAY_UNAVAILABLE,
                "The analysis replay could not be completed.",
                request_id=request_id,
            )

    @staticmethod
    def _existing_outcome(
        repository: PostgresAnalysisRepository,
        request_id: UUID,
    ) -> ReplayOutcome:
        run = repository.get_run(request_id)
        if run["status"] in {AnalysisStatus.SUCCEEDED.value, AnalysisStatus.PARTIAL.value}:
            artifact = repository.get_run_artifact(request_id)
            return ReplayOutcome(
                status=(
                    BlockRunStatus.SUCCESS
                    if run["status"] == AnalysisStatus.SUCCEEDED.value
                    else BlockRunStatus.PARTIAL
                ),
                request_id=str(request_id),
                artifact_id=str(artifact["artifact_id"]),
                query_id=str(artifact["query_id"]),
                snapshot_checksum=str(artifact["artifact_checksum"]),
                policy_version=(artifact.get("evidence") or {}).get("policy_version"),
            )
        if run["status"] == AnalysisStatus.CANCELLED.value:
            return _failure(
                BlockFailureCode.REQUEST_CANCELLED,
                "The analysis replay was cancelled.",
                request_id=request_id,
                cancelled=True,
            )
        if run["status"] == AnalysisStatus.RECEIVED.value:
            return _failure(
                BlockFailureCode.RATE_LIMITED,
                "The same analysis replay is already running.",
                request_id=request_id,
            )
        return _failure(
            _failure_code(run.get("error_type")),
            "The previous analysis replay did not produce approved evidence.",
            request_id=request_id,
        )


class ReportExecutionService:
    """Common manual and scheduled Report execution path."""

    def __init__(self, repository, replay: AnalysisDefinitionReplay) -> None:
        self.repository = repository
        self._replay = replay

    def execute_manual_run(self, command_id: str) -> ReportRun:
        claim = self.repository.claim_manual_run(command_id)
        if not claim["claimed"]:
            return self.repository.get_run(str(claim["run_id"]))
        for block in claim["blocks"]:
            if (
                not block["analysis_definition_id"]
                or block["analysis_definition_version"] is None
            ):
                outcome = _failure(
                    BlockFailureCode.DEFINITION_NOT_FOUND,
                    "This legacy Report block has no replayable analysis definition.",
                )
            else:
                try:
                    outcome = self._replay.execute(
                        owner_id=claim["owner_id"],
                        definition_id=block["analysis_definition_id"],
                        definition_version=block["analysis_definition_version"],
                        as_of=claim["as_of"],
                        idempotency_key=(
                            f"report:{claim['run_id']}:{block['block_id']}"
                        ),
                    )
                except Exception:
                    outcome = _failure(
                        BlockFailureCode.INTERNAL_ERROR,
                        "The analysis replay failed.",
                    )
            self.repository.record_block_run(
                str(claim["run_id"]),
                block["block_id"],
                status=outcome.status,
                request_id=outcome.request_id,
                artifact_id=outcome.artifact_id,
                query_id=outcome.query_id,
                snapshot_checksum=outcome.snapshot_checksum,
                policy_version=outcome.policy_version,
                failure_code=outcome.failure_code,
                failure_message=outcome.failure_message,
            )
        return self.repository.finish_manual_run(command_id)

    def run_due_schedule(
        self,
        schedule_id: str,
        now: datetime,
    ) -> tuple[dict[str, object], ReportRun | None]:
        schedule, command = self.repository.queue_due_schedule(schedule_id, now)
        if command is None:
            return schedule, None
        run = self.execute_manual_run(command.command_id)
        schedule = self.repository.complete_due_schedule(
            schedule_id, command.as_of, run.run_id
        )
        return schedule, run
