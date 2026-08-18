import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from src.report.domain import (
    BlockRunStatus,
    BlockType,
    DefinitionStatus,
    ReportBlock,
    ReportBlockRun,
    ReportDefinitionVersion,
    ReportRun,
    RunStatus,
)
from tests.support.report_repository import InMemoryReportRepository


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
        block_run = ReportBlockRun(
            "block-1", "artifact-1", "query-1", "sha256-1",
            BlockRunStatus.PARTIAL, "request-1",
        )
        run = ReportRun(
            "run-1", "report-1", 3, datetime(2026, 8, 3, tzinfo=timezone.utc),
            "policy-v1", "context-1", {"pms": "2026-07-28T05:00:00.000Z"},
            RunStatus.PARTIAL, (block_run,),
        )
        with self.assertRaises(TypeError):
            run.watermark["pms"] = "changed"
        self.assertEqual(3, run.definition_version)
        self.assertEqual("artifact-1", run.blocks[0].artifact_id)

    def test_layout_and_artifact_rules_keep_v1_columns_compatible(self):
        chart = ReportBlock(
            "chart-1", "객실 추이", "artifact-1", 5, "query-1",
            BlockType.CHART, 7, 2, 5, 3, "",
        )
        text = ReportBlock(
            "text-1", "해석", None, 12, None,
            BlockType.TEXT, 0, 5, 12, 2, "관측 결과만 설명합니다.",
        )
        self.assertEqual(chart.columns, chart.w)
        self.assertIsNone(text.artifact_id)
        artifact = ReportBlock(
            "artifact-whole", "Analysis Artifact", "artifact-1", 12, "query-1",
            BlockType.ARTIFACT, 0, 7, 12, 12,
            '{"presentationMode":"standard","visibleViews":["summary","kpi","chart","table"]}',
        )
        self.assertEqual(BlockType.ARTIFACT, artifact.type)
        with self.assertRaisesRegex(ValueError, "12-column bounds"):
            ReportBlock("bad", "초과", "artifact-1", 6, None, BlockType.TABLE, 7, 0, 6, 1)
        with self.assertRaisesRegex(ValueError, "positive height"):
            ReportBlock("bad", "높이", "artifact-1", 6, None, BlockType.TABLE, 0, 0, 6, 0)
        with self.assertRaisesRegex(ValueError, "artifact_id"):
            ReportBlock("bad", "차트", None, 6, None, BlockType.CHART)
        with self.assertRaisesRegex(ValueError, "빈 content"):
            ReportBlock("bad", "텍스트", None, 6, None, BlockType.TEXT)

        with self.assertRaisesRegex(ValueError, "artifact_id"):
            ReportBlock("bad-artifact", "Artifact", None, 12, None, BlockType.ARTIFACT)

    def test_only_draft_can_replace_the_complete_block_layout(self):
        text = ReportBlock(
            "text-1", "해석", None, 12, None,
            BlockType.TEXT, 0, 0, 12, 2, "새 해석",
        )
        replaced = self.draft.replace_blocks((text,))
        self.assertEqual((text,), replaced.blocks)
        approved = self.draft.approve(datetime(2026, 8, 3, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ValueError, "draft Report version"):
            approved.replace_blocks((text,))


if __name__ == "__main__":
    unittest.main()
