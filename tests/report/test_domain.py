import unittest
import json
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
    normalize_report_block_content,
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

    def test_definition_and_run_require_complete_release_receipts(self):
        receipt = {
            "product_release_id": "product-v1",
            "permission_snapshot_id": "permission-v1",
            "semantic_release_id": "semantic-v1",
        }
        draft = ReportDefinitionVersion(
            "report-receipt",
            1,
            DefinitionStatus.DRAFT,
            "Receipt report",
            (self.block,),
            **receipt,
        )
        approved = draft.approve(datetime(2026, 8, 3, tzinfo=timezone.utc))
        self.assertEqual("product-v1", approved.next_draft().product_release_id)
        run = ReportRun(
            "run-receipt",
            draft.definition_id,
            1,
            datetime(2026, 8, 3, tzinfo=timezone.utc),
            "policy-v1",
            "context-v1",
            {},
            RunStatus.SUCCESS,
            product_release_id=receipt["product_release_id"],
            permission_snapshot_id=receipt["permission_snapshot_id"],
            semantic_release_id=receipt["semantic_release_id"],
        )
        self.assertEqual("semantic-v1", run.semantic_release_id)
        with self.assertRaisesRegex(ValueError, "receipt must be complete"):
            ReportDefinitionVersion(
                "report-incomplete",
                1,
                DefinitionStatus.DRAFT,
                "Incomplete",
                (self.block,),
                product_release_id="product-v1",
            )

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
        legacy_artifact = ReportBlock(
            "artifact-whole", "Analysis Artifact", "artifact-1", 12, "query-1",
            BlockType.ARTIFACT, 0, 7, 12, 12,
            '{"presentationMode":"standard","visibleViews":["summary","kpi","chart","table"]}',
        )
        self.assertEqual(BlockType.ARTIFACT, legacy_artifact.type)
        with self.assertRaisesRegex(ValueError, "visibleViews"):
            normalize_report_block_content(legacy_artifact.type, legacy_artifact.content)
        self.assertEqual(
            ["chart"],
            json.loads(normalize_report_block_content(BlockType.CHART, ""))["visibleViews"],
        )
        self.assertEqual(
            ["table"],
            json.loads(normalize_report_block_content(BlockType.TABLE, "{}"))["visibleViews"],
        )
        for block_type, mismatched in (
            (BlockType.CHART, '{"visibleViews":["table"]}'),
            (BlockType.TABLE, '{"visibleViews":["chart"]}'),
        ):
            with self.subTest(block_type=block_type), self.assertRaisesRegex(
                ValueError, "type.*visibleViews"
            ):
                normalize_report_block_content(block_type, mismatched)
        self.assertEqual(
            ["summary"],
            json.loads(normalize_report_block_content(
                BlockType.ARTIFACT, '{"visibleViews":["summary"]}',
            ))["visibleViews"],
        )
        for invalid in (
            "{}", '{"visibleViews":[]}', '{"visibleViews":["unknown"]}',
            '{"visibleViews":["summary","kpi"]}',
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "visibleViews"):
                normalize_report_block_content(BlockType.ARTIFACT, invalid)
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

    def test_report_title_is_trimmed_and_rejects_non_single_line_values(self):
        normalized = ReportDefinitionVersion(
            "report-title",
            1,
            DefinitionStatus.DRAFT,
            f"  {'가' * 255}  ",
            (),
        )
        self.assertEqual("가" * 255, normalized.title)
        for invalid in ("", "   ", "첫 줄\n둘째 줄", "제목\t탭", "가" * 256):
            with self.subTest(invalid=repr(invalid)), self.assertRaises(
                (TypeError, ValueError)
            ):
                ReportDefinitionVersion(
                    "report-invalid-title",
                    1,
                    DefinitionStatus.DRAFT,
                    invalid,
                    (),
                )

    def test_report_draft_revision_is_positive_and_survives_domain_transitions(self):
        revised = ReportDefinitionVersion(
            "report-revision",
            1,
            DefinitionStatus.DRAFT,
            "Revision report",
            (),
            draft_revision=7,
        )
        self.assertEqual(7, revised.replace_blocks(()).draft_revision)
        approved = revised.approve(datetime(2026, 8, 3, tzinfo=timezone.utc))
        self.assertEqual(7, approved.draft_revision)
        self.assertEqual(1, approved.next_draft().draft_revision)
        for invalid in (0, -1, True):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "revision"
            ):
                ReportDefinitionVersion(
                    "report-invalid-revision",
                    1,
                    DefinitionStatus.DRAFT,
                    "Invalid revision",
                    (),
                    draft_revision=invalid,
                )


if __name__ == "__main__":
    unittest.main()
