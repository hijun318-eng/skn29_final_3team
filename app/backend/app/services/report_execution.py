"""저장된 Analysis Definition을 현재 owner 권한·기준일·pipeline으로 멱등 replay하고, block 결과가 terminal일 때만 report run과 schedule CAS를 완료한다."""

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
from src.report.domain import BlockFailureCode, BlockRunStatus, ReportRun, RunStatus


_PUBLIC_FAILURES = {
    code.value: code
    for code in BlockFailureCode
}


class ExecutionGate(Protocol):
    """ExecutionGate는 실행 gate 구현이 제공해야 할 acquire, release 메서드와 반환 타입을 선언한다."""
    async def acquire(self, wait_seconds: float = 0) -> bool:
        """실행 gate 동시 실행 권한을 제한 시간 안에 획득한다."""
        ...

    def release(self) -> None:
        """실행 gate 동시 실행 권한을 반환해 대기 작업이 진행되게 한다."""
        ...


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """ReplayOutcome 계약에서 허용하는 상태 값을 정의한다."""
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
    """저장된 Analysis Definition을 현재 권한·policy·data 기준으로 다시 실행한다.

    DB의 versioned 정의를 입력 권위로 삼되 과거 기간과 실행 결과는 재사용하지 않는다.
    현재 owner 인증, report ``as_of``, execution gate와 전체 controller pipeline을 거쳐
    검증된 artifact 증거 또는 ``ReplayOutcome``의 typed failure만 반환한다.
    """

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

    async def execute(
        self,
        *,
        owner_id: UUID,
        definition_id: str,
        definition_version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ReplayOutcome:
        """한 정의 version을 report 기준일로 봉인해 멱등한 분석 run으로 실행한다.

        owner 활성 권한과 저장 정의를 DB에서 다시 확인하고 기존 기간 binding은 제거한다.
        idempotency key로 중복 run을 조회하며 gate를 얻은 경우에만 controller를 호출한다.
        인증·repository·pipeline·persist 실패는 공개 ``BlockFailureCode``로 축약해 반환한다.
        """
        repository = PostgresAnalysisRepository(self._database_url, owner_id)
        try:
            await require_active_subject(owner_id, Role.HOTEL_ANALYST)
            definition = await repository.get_definition_for_report(
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
            request_id, created = await repository.begin_run(
                definition,
                context,
                report_date,
                idempotency_key,
                parameters,
            )
            if not created:
                return await self._existing_outcome(repository, request_id)
            if not await self._execution_gate.acquire(self._queue_wait_seconds):
                await repository.fail_run(request_id, ErrorCode.RATE_LIMITED.value)
                return _failure(
                    BlockFailureCode.RATE_LIMITED,
                    "The analysis execution limit was reached.",
                    request_id=request_id,
                )

            execution: dict[str, object] = {}
            try:
                response = await self._controller.submit(
                    AnalysisRequest(
                        question=definition["question"],
                        parameters=parameters,
                    ),
                    context,
                    execution.update,
                )
            except ContextValidationError as error:
                await repository.fail_run(
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
                await repository.fail_run(request_id)
                return _failure(
                    BlockFailureCode.INTERNAL_ERROR,
                    "The analysis replay failed.",
                    request_id=request_id,
                )
            finally:
                self._execution_gate.release()

            await repository.finish_run(request_id, response, execution)
            if response.data.status in {AnalysisStatus.SUCCEEDED, AnalysisStatus.PARTIAL}:
                artifact = await repository.get_run_artifact(request_id)
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
                    await repository.fail_run(
                        request_id, ErrorCode.ARTIFACT_PERSIST_FAILED.value
                    )
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
    async def _existing_outcome(
        repository: PostgresAnalysisRepository,
        request_id: UUID,
    ) -> ReplayOutcome:
        run = await repository.get_run(request_id)
        if run["status"] in {AnalysisStatus.SUCCEEDED.value, AnalysisStatus.PARTIAL.value}:
            artifact = await repository.get_run_artifact(request_id)
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
    """ReportExecutionService는 보고서 실행 서비스에서 execute_manual_run, run_due_schedule 흐름과 선행 도메인 검증 순서를 조정한다.

    Common manual and scheduled Report execution path.
    """

    _TERMINAL_RUN_STATUSES = frozenset(
        {
            RunStatus.SUCCESS,
            RunStatus.PARTIAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    )

    def __init__(self, repository, replay: AnalysisDefinitionReplay) -> None:
        self.repository = repository
        self._replay = replay

    async def execute_manual_run(self, command_id: str) -> ReportRun:
        """repository가 원자적으로 claim한 수동 report command의 모든 block을 실행한다.

        이미 claim된 command는 기존 run을 반환한다. 각 block은 저장 definition version으로
        replay하고 성공·부분·실패 증거를 개별 저장하며, 예상 밖 예외도 typed block 실패로
        격리한다. 모든 block 기록 후 repository가 계산한 최종 ``ReportRun``을 반환한다.
        """
        claim = await self.repository.claim_manual_run(command_id)
        if not claim["claimed"]:
            return await self.repository.get_run(str(claim["run_id"]))
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
                    outcome = await self._replay.execute(
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
            await self.repository.record_block_run(
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
        return await self.repository.finish_manual_run(command_id)

    async def run_due_schedule(
        self,
        schedule_id: str,
        now: datetime,
    ) -> tuple[dict[str, object], ReportRun | None]:
        """기준 시각에 due인 schedule을 멱등 command로 queue하고 terminal run까지 처리한다.

        다른 poller가 먼저 queue했거나 아직 실행 중이면 run 없이 현재 schedule을 반환한다.
        SUCCESS·PARTIAL·FAILED·CANCELLED가 확인된 경우에만 ``complete_due_schedule``로 다음
        시각을 전진시켜 조기 전진 race가 재시도 window를 건너뛰지 않게 한다.
        """
        schedule, command = await self.repository.queue_due_schedule(schedule_id, now)
        if command is None:
            return schedule, None
        run = await self.execute_manual_run(command.command_id)
        # A concurrent poller can observe the idempotent command while the first
        # poller is still executing it. Advancing here would skip the next retry
        # window before any terminal evidence exists.
        if run.status not in self._TERMINAL_RUN_STATUSES:
            return schedule, None
        schedule = await self.repository.complete_due_schedule(
            schedule_id, command.as_of, run.run_id
        )
        return schedule, run
