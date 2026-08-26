"""보고서 분석 정의 재생(AnalysisDefinitionReplay) 및 수동/예약 실행 오케스트레이션 서비스 모듈.

[핵심 목적]
저장된 보고서 블록별 분석 정의(`analysis_definition_id`, `version`)를 현재 소유자 권한,
보고서 기준일(`as_of`), 그리고 동시 실행 제어 게이트(`ExecutionGate`) 하에서 멱등 재생(`replay`)하고,
블록별 실행 결과(Artifact/오류)를 수집하여 최종 `ReportRun` 완료 상태로 전이합니다.
"""

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
from app.authorization import permission_snapshot_id as build_permission_snapshot_id
from app.auth import AuthenticationError, require_active_subject_with_capability
from app.context import ContextValidationError
from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    Capability,
    ErrorCode,
    RequestContext,
)
from app.controllers.analysis_controller import AnalysisController
from src.report.domain import BlockFailureCode, BlockRunStatus, ReportRun, RunStatus

_PUBLIC_FAILURES = {
    code.value: code
    for code in BlockFailureCode
}


class ExecutionGate(Protocol):
    """동시 실행 제한을 제어하는 실행 게이트 프로토콜 인터페이스."""

    async def acquire(self, wait_seconds: float = 0) -> bool:
        """실행 토큰을 획득합니다 (성공 시 True)."""
        ...

    def release(self) -> None:
        """획득한 실행 토큰을 반환합니다."""
        ...


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """개별 블록 재생 실행 결과를 담는 데이터 클래스.

    Attributes:
        status: 블록 실행 상태 (SUCCESS, PARTIAL, FAILED, CANCELLED)
        request_id: 생성된 분석 요청 ID
        artifact_id: 생성된 아티팩트 ID
        query_id: 실행된 Trino 쿼리 ID
        snapshot_checksum: 아티팩트 스냅샷 체크섬
        policy_version: 적용된 거버넌스 정책 버전
        failure_code: 실패 시 에러 코드
        failure_message: 상세 실패 메시지
    """

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
    """저장된 분석 정의를 현재 보고서 기준일 및 권한으로 재실행하는 재생기 클래스."""

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
        product_release_id: str | None = None,
        permission_snapshot_id: str | None = None,
        semantic_release_id: str | None = None,
    ) -> ReplayOutcome:
        """저장된 분석 정의 1건을 재생 실행합니다."""
        repository = PostgresAnalysisRepository(self._database_url, owner_id)
        try:
            owner = await require_active_subject_with_capability(
                owner_id,
                Capability.RUN_ANALYSIS,
            )
            receipt = (
                product_release_id,
                permission_snapshot_id,
                semantic_release_id,
            )
            if any(receipt) and not all(receipt):
                raise ValueError("Report replay release receipt is incomplete")
            if permission_snapshot_id and permission_snapshot_id != build_permission_snapshot_id(
                owner_id, owner.role
            ):
                return _failure(
                    BlockFailureCode.ACCESS_DENIED,
                    "The Report permission snapshot is no longer current.",
                )
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
            role=owner.role,
            as_of=report_date,
            timezone="Asia/Seoul",
            product_release_id=product_release_id,
            permission_snapshot_id=permission_snapshot_id,
            semantic_release_id=semantic_release_id,
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

            async def _persist_context_receipt(
                receipt_context: RequestContext,
                package: object,
            ) -> None:
                await repository.persist_context_receipt(receipt_context, package)

            try:
                response = await self._controller.submit(
                    AnalysisRequest(
                        question=definition["question"],
                        parameters=parameters,
                    ),
                    context,
                    execution.update,
                    context_receipt_sink=_persist_context_receipt,
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
    """수동 및 예약 보고서 실행을 총괄하는 서비스 클래스."""

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
        """수동 실행 명령을 원자적으로 획득하여 모든 블록을 실행하고 최종 ReportRun을 반환합니다."""
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
                        product_release_id=claim.get("product_release_id"),
                        permission_snapshot_id=claim.get("permission_snapshot_id"),
                        semantic_release_id=claim.get("semantic_release_id"),
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
        """예약 실행 대상 스케줄을 조회하여 실행하고 결과를 갱신합니다."""
        schedule, command = await self.repository.queue_due_schedule(schedule_id, now)
        if command is None:
            return schedule, None
        run = await self.execute_manual_run(command.command_id)
        if run.status not in self._TERMINAL_RUN_STATUSES:
            return schedule, None
        schedule = await self.repository.complete_due_schedule(
            schedule_id, command.as_of, run.run_id
        )
        return schedule, run
