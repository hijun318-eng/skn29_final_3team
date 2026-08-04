import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from src.report.domain import (
    BlockRunStatus,
    DefinitionStatus,
    ReportBlock,
    ReportBlockRun,
    ReportDefinitionVersion,
    ReportRun,
    RunStatus,
)
from src.report.repository import InMemoryReportRepository


class ReportDomainTest(unittest.TestCase):
    def setUp(self):
        self.block = ReportBlock("block-1", "객실 매출", "artifact-1", 6, "query-1")
        self.draft = ReportDefinitionVersion(
            "report-1", 1, DefinitionStatus.DRAFT, "주간 보고서", (self.block,)
        )

    def test_approved_version_is_frozen_and_next_edit_creates_new_version(self):
        approved = self.draft.approve(datetime(2026, 8, 3, tzinfo=timezone.utc))
        with self.assertRaises(FrozenInstanceError):
            approved.title = "덮어쓰기"
        next_draft = approved.next_draft()
        self.assertEqual(2, next_draft.version)
        self.assertEqual(DefinitionStatus.DRAFT, next_draft.status)
        self.assertEqual("artifact-1", next_draft.blocks[0].artifact_id)

    def test_repository_rejects_approved_version_overwrite(self):
        repo = InMemoryReportRepository()
        repo.add_draft(self.draft)
        repo.approve("report-1", 1, datetime(2026, 8, 3, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ValueError, "덮어쓸 수 없습니다"):
            repo.add_draft(self.draft)

    def test_run_keeps_definition_context_watermark_and_block_snapshot(self):
        block_run = ReportBlockRun("block-1", "artifact-1", "query-1", "sha256-1", BlockRunStatus.PARTIAL)
        run = ReportRun(
            "run-1", "report-1", 3, datetime(2026, 8, 3, tzinfo=timezone.utc),
            "policy-v1", "context-1", {"pms": "2026-07-28T05:00:00.000Z"},
            RunStatus.PARTIAL, (block_run,),
        )
        with self.assertRaises(TypeError):
            run.watermark["pms"] = "changed"
        self.assertEqual(3, run.definition_version)
        self.assertEqual("artifact-1", run.blocks[0].artifact_id)


if __name__ == "__main__":
    unittest.main()