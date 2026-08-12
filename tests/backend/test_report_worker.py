import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.services.report_worker import ReportCommandWorker
from src.report.domain import (
    AnalysisReplayResult,
    BlockType,
    ReportBlock,
    ReportCommand,
    RunStatus,
)


class Repository:
    def __init__(self, command, fallback=None):
        self.command = command
        self.fallback = fallback
        self.completed = None
        self.failed = None
        self.enqueued = 0

    def enqueue_due_schedules(self, _current):
        self.enqueued += 1

    def claim_next(self):
        command, self.command = self.command, None
        return command

    def analysis_binding(self, artifact_id):
        return artifact_id

    def artifact_result(self, _artifact_id):
        if self.fallback is None:
            raise KeyError("fallback 없음")
        return self.fallback

    def complete(self, command, run):
        self.completed = (command, run)

    def fail(self, command_id, message):
        self.failed = (command_id, message)


class Runner:
    def __init__(self, result, failing=()):
        self.result = result
        self.failing = set(failing)

    def replay(self, _command, block_id, _binding):
        if block_id in self.failing:
            raise RuntimeError("source failed")
        return self.result


def command(*blocks):
    return ReportCommand(
        "command-1",
        "report-1",
        1,
        UUID("00000000-0000-0000-0000-000000000001"),
        datetime(2026, 8, 12, tzinfo=timezone.utc),
        "MANUAL",
        tuple(blocks),
    )


RESULT = AnalysisReplayResult(
    "artifact-new", "query-new", "sha256-new", "context-new", "policy-v1", {"pms": "cutoff"}
)


def test_worker_replays_data_blocks_and_preserves_text_blocks_in_definition_only():
    repository = Repository(command(
        ReportBlock("table-1", "매출", "artifact-old", 6),
        ReportBlock("text-1", "해석", None, 6, type=BlockType.TEXT, content="검토"),
    ))
    run = ReportCommandWorker(repository, Runner(RESULT)).run_once()

    assert run.status is RunStatus.SUCCESS
    assert [block.block_id for block in run.blocks] == ["table-1"]
    assert run.blocks[0].artifact_id == "artifact-new"
    assert repository.completed[1] == run
    assert repository.enqueued == 1


def test_worker_records_partial_failure_with_last_verified_artifact():
    repository = Repository(
        command(
            ReportBlock("ok", "정상", "artifact-ok", 6),
            ReportBlock("failed", "실패", "artifact-failed", 6),
        ),
        fallback=RESULT,
    )
    run = ReportCommandWorker(repository, Runner(RESULT, {"failed"})).run_once()

    assert run.status is RunStatus.PARTIAL
    assert [block.status.value for block in run.blocks] == ["success", "failed"]


def test_worker_marks_command_failed_when_no_run_can_be_built():
    repository = Repository(command(ReportBlock("failed", "실패", "missing", 6)))
    worker = ReportCommandWorker(repository, Runner(RESULT, {"failed"}))

    run = worker.run_once()

    assert run.status is RunStatus.FAILED
    assert run.blocks == ()
    assert repository.completed[1] == run


def test_worker_marks_unexpected_persistence_error_on_command():
    repository = Repository(command())

    def fail_complete(_command, _run):
        raise RuntimeError("write failed")

    repository.complete = fail_complete
    with pytest.raises(RuntimeError, match="write failed"):
        ReportCommandWorker(repository, Runner(RESULT)).run_once()
    assert repository.failed == ("command-1", "write failed")


@pytest.mark.skipif(
    not os.getenv("REPORT_WORKER_DATABASE_URL"),
    reason="temporary migrated Report worker database is required",
)
def test_postgres_worker_claims_once_and_persists_completed_run():
    from app.adapters.report_repository import (
        PostgresReportRepository,
        PostgresReportWorkerRepository,
        _engine,
    )
    from sqlalchemy import text
    from src.report.domain import DefinitionStatus, ReportDefinitionVersion

    database_url = os.environ["REPORT_WORKER_DATABASE_URL"]
    owner_id = uuid4()
    definition_id = str(uuid4())
    block_id = str(uuid4())
    artifact_id = str(uuid4())
    repository = PostgresReportRepository(database_url, owner_id)
    repository.add_draft(ReportDefinitionVersion(
        definition_id,
        1,
        DefinitionStatus.DRAFT,
        "worker integration",
        (ReportBlock(block_id, "매출", artifact_id, 12),),
    ))
    now = datetime.now(timezone.utc)
    repository.approve(definition_id, 1, now)
    command = repository.queue_manual_run(definition_id, 1, now, str(uuid4()))

    worker_repository = PostgresReportWorkerRepository(database_url)
    claimed = worker_repository.claim_next()
    assert claimed.command_id == command.command_id
    assert worker_repository.claim_next() is None
    worker_repository.analysis_binding = lambda _artifact_id: "binding"
    result = AnalysisReplayResult(
        str(uuid4()), "query-new", "sha256-new", "context-new", "policy-v1", {}
    )
    run = ReportCommandWorker(worker_repository, Runner(result))._run(claimed)
    worker_repository.complete(claimed, run)

    with _engine(database_url).connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, run_id FROM report_v1.report_manual_run_commands "
                "WHERE command_id = :command_id"
            ),
            {"command_id": command.command_id},
        ).one()
    assert row.status == "success"
    assert str(row.run_id) == run.run_id
