from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from app.adapters.analysis_repository import PostgresAnalysisRepository
from app.contracts import AnalysisRequest, AnalysisStatus, RequestContext, Role
from src.report.domain import (
    AnalysisReplayResult,
    BlockRunStatus,
    BlockType,
    ReportBlockRun,
    ReportCommand,
    ReportRun,
    RunStatus,
)


class ReportAnalysisRunner:
    def __init__(self, database_url: str, controller, worker_repository) -> None:
        self.database_url = database_url
        self.controller = controller
        self.worker_repository = worker_repository

    def replay(
        self,
        command: ReportCommand,
        block_id: str,
        binding,
    ) -> AnalysisReplayResult:
        context = RequestContext(
            user_id=binding.owner_id,
            role=Role.HOTEL_ANALYST,
            as_of=command.as_of.date(),
        )
        repository = PostgresAnalysisRepository(self.database_url, binding.owner_id)
        definition = {
            "definition_id": binding.definition_id,
            "version": binding.version,
            "question": binding.question,
            "parameters": dict(binding.parameters),
        }
        request_id, created = repository.begin_run(
            definition,
            context,
            context.as_of,
            f"report:{command.command_id}:{block_id}",
        )
        if created:
            execution = {}
            try:
                response = self.controller.submit(
                    AnalysisRequest(
                        question=binding.question,
                        parameters=dict(binding.parameters),
                    ),
                    context,
                    execution.update,
                )
                repository.finish_run(request_id, response, execution)
            except Exception:
                repository.fail_run(request_id)
                raise
            if response.data.status not in {AnalysisStatus.SUCCEEDED, AnalysisStatus.PARTIAL}:
                raise ValueError("Report block Analysis 재실행이 성공하지 못했습니다.")
        result = self.worker_repository.analysis_result(request_id)
        if created and response.data.artifact:
            return AnalysisReplayResult(
                result.artifact_id,
                result.query_id,
                result.snapshot_checksum,
                response.data.artifact.context_hash,
                result.policy_version,
                result.watermark,
            )
        return result


class ReportCommandWorker:
    def __init__(self, repository, runner) -> None:
        self.repository = repository
        self.runner = runner

    def run_once(self, current: datetime | None = None) -> ReportRun | None:
        current = current or datetime.now(timezone.utc)
        self.repository.enqueue_due_schedules(current)
        command = self.repository.claim_next()
        if command is None:
            return None
        try:
            run = self._run(command)
            self.repository.complete(command, run)
            return run
        except Exception as error:
            self.repository.fail(command.command_id, str(error))
            raise

    def _run(self, command: ReportCommand) -> ReportRun:
        block_runs = []
        failures = 0
        context_hashes = []
        policies = []
        watermark = {}
        for block in command.blocks:
            if block.type is BlockType.TEXT:
                continue
            try:
                binding = self.repository.analysis_binding(block.artifact_id)
                result = self.runner.replay(command, block.block_id, binding)
                status = BlockRunStatus.SUCCESS
            except Exception:
                failures += 1
                try:
                    result = self.repository.artifact_result(block.artifact_id)
                except Exception:
                    continue
                status = BlockRunStatus.FAILED
            block_runs.append(ReportBlockRun(
                block.block_id,
                result.artifact_id,
                result.query_id,
                result.snapshot_checksum,
                status,
            ))
            context_hashes.append(result.context_hash)
            policies.append(result.policy_version)
            watermark.update(result.watermark)
        executable_count = sum(block.type is not BlockType.TEXT for block in command.blocks)
        if failures == 0:
            status = RunStatus.SUCCESS
        elif failures < executable_count:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.FAILED
        context_hash = hashlib.sha256("|".join(context_hashes).encode()).hexdigest()
        return ReportRun(
            str(uuid5(NAMESPACE_URL, f"report-run:{command.command_id}")),
            command.definition_id,
            command.version,
            command.as_of,
            policies[0] if policies else "policy-v1",
            context_hash,
            watermark,
            status,
            tuple(block_runs),
        )
