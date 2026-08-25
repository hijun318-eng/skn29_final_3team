"""Report Agent patch가 fake Artifact를 실제 draft 변경으로 안전하게 적용하는지 검증한다."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.report_contracts import ReportAssistantPatch
from app.report_patch import (
    VerifiedArtifactBinding,
    apply_report_assistant_patch,
)
from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion


class ReportAssistantPatchTest(unittest.TestCase):
    """외부 데이터 없이 허용 patch·Artifact alias·layout 불변식을 단위 검증한다."""

    def setUp(self) -> None:
        self.definition = ReportDefinitionVersion(
            "definition-1",
            2,
            DefinitionStatus.DRAFT,
            "기존 보고서",
            (
                ReportBlock(
                    "summary",
                    "운영 요약",
                    None,
                    12,
                    None,
                    BlockType.TEXT,
                    0,
                    0,
                    12,
                    4,
                    "기존 요약",
                ),
                ReportBlock(
                    "current-chart",
                    "현재 실적",
                    "artifact-old",
                    12,
                    "query-old",
                    BlockType.CHART,
                    0,
                    4,
                    12,
                    7,
                ),
            ),
        )
        self.bindings = {
            "analysis_result": VerifiedArtifactBinding(
                "artifact-new",
                "query-new",
                "a" * 64,
            )
        }

    def test_verified_fake_artifact_creates_real_chart_and_summary_blocks(self) -> None:
        """새 분석 결과 별칭으로 차트·요약을 추가하고 기존 block을 보존한다."""

        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "전월 비교 차트와 해설을 추가합니다.",
                "operations": [
                    {
                        "op": "add_artifact_view",
                        "artifact_ref": "analysis_result",
                        "view": "chart",
                        "title": "전월 비교",
                        "placement": {"after_block_id": "current-chart", "width": "full"},
                    },
                    {
                        "op": "add_text",
                        "title": "전월 비교 요약",
                        "content": "검증된 Artifact를 근거로 작성한 비교 요약입니다.",
                        "placement": {"width": "full"},
                    },
                ],
            }
        )

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual(4, len(result.blocks))
        self.assertEqual(("summary", "current-chart"), tuple(b.block_id for b in result.blocks[:2]))
        chart = next(block for block in result.blocks if block.title == "전월 비교")
        self.assertEqual(BlockType.CHART, chart.type)
        self.assertEqual("artifact-new", chart.artifact_id)
        self.assertEqual("query-new", chart.query_id)
        self.assertEqual(11, chart.y)
        self.assertEqual("기존 요약", result.blocks[0].content)

    def test_text_update_and_title_change_do_not_touch_artifact_lineage(self) -> None:
        """기존 근거만 쓰는 편집은 text와 보고서 제목 외 Artifact 참조를 바꾸지 않는다."""

        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "제목과 요약을 간결하게 수정합니다.",
                "operations": [
                    {"op": "set_report_title", "title": "월간 경영 요약"},
                    {
                        "op": "update_text",
                        "block_id": "summary",
                        "content": "수정된 운영 요약",
                    },
                ],
            }
        )

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual("월간 경영 요약", result.title)
        self.assertEqual("수정된 운영 요약", result.blocks[0].content)
        self.assertEqual("artifact-old", result.blocks[1].artifact_id)
        self.assertEqual("query-old", result.blocks[1].query_id)

    def test_repeated_anchor_preserves_patch_operation_order(self) -> None:
        """같은 기존 block 뒤에 여러 항목을 추가해도 모델의 operation 순서를 보존한다."""

        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "두 설명을 순서대로 추가합니다.",
                "operations": [
                    {
                        "op": "add_text",
                        "title": "첫 번째 설명",
                        "content": "첫 번째",
                        "placement": {"after_block_id": "summary"},
                    },
                    {
                        "op": "add_text",
                        "title": "두 번째 설명",
                        "content": "두 번째",
                        "placement": {"after_block_id": "summary"},
                    },
                ],
            }
        )

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)
        ordered = sorted(result.blocks, key=lambda block: (block.y, block.x))

        self.assertEqual(
            ["운영 요약", "첫 번째 설명", "두 번째 설명", "현재 실적"],
            [block.title for block in ordered],
        )

    def test_existing_block_can_be_repositioned_and_resized_without_lineage_change(self) -> None:
        """기존 Artifact block을 상대 위치로 옮겨도 ID와 lineage를 그대로 보존한다."""

        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "현재 실적 차트를 요약 뒤 절반 폭으로 배치합니다.",
                "operations": [
                    {
                        "op": "reposition_block",
                        "block_id": "current-chart",
                        "after_block_id": "summary",
                        "width": "half",
                    }
                ],
            }
        )

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)
        chart = next(block for block in result.blocks if block.block_id == "current-chart")

        self.assertEqual(4, chart.y)
        self.assertEqual(6, chart.w)
        self.assertEqual("artifact-old", chart.artifact_id)
        self.assertEqual("query-old", chart.query_id)

    def test_reposition_rejects_unknown_block_and_self_anchor(self) -> None:
        """존재하지 않는 이동 대상과 자기 자신을 기준으로 한 배치를 원자적으로 거부한다."""

        unknown = ReportAssistantPatch.model_validate(
            {
                "summary": "없는 block 이동",
                "operations": [
                    {"op": "reposition_block", "block_id": "missing", "width": "full"}
                ],
            }
        )
        with self.assertRaises(ValueError):
            apply_report_assistant_patch(self.definition, unknown, self.bindings)

        with self.assertRaises(ValidationError):
            ReportAssistantPatch.model_validate(
                {
                    "summary": "순환 배치",
                    "operations": [
                        {
                            "op": "reposition_block",
                            "block_id": "summary",
                            "after_block_id": "summary",
                            "width": "full",
                        }
                    ],
                }
            )

    def test_remove_block_preserves_other_blocks_and_rejects_last_block(self) -> None:
        """삭제 대상만 제거하고 보고서를 빈 상태로 만드는 마지막 block 삭제는 거부한다."""

        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "운영 요약을 제거합니다.",
                "operations": [{"op": "remove_block", "block_id": "summary"}],
            }
        )
        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual(("current-chart",), tuple(block.block_id for block in result.blocks))
        self.assertEqual("artifact-old", result.blocks[0].artifact_id)
        self.assertEqual(2, len(self.definition.blocks))

        single = self.definition.replace_blocks((self.definition.blocks[0],))
        with self.assertRaises(ValueError):
            apply_report_assistant_patch(single, patch, self.bindings)

    def test_duplicate_block_gets_server_id_and_preserves_artifact_lineage(self) -> None:
        """복제본은 새 서버 ID를 받지만 원본 Artifact와 query lineage는 그대로 공유한다."""

        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "현재 실적 차트를 복제합니다.",
                "operations": [
                    {"op": "duplicate_block", "block_id": "current-chart"}
                ],
            }
        )
        result = apply_report_assistant_patch(self.definition, patch, self.bindings)
        copies = [block for block in result.blocks if block.title == "현재 실적"]

        self.assertEqual(2, len(copies))
        self.assertEqual(2, len({block.block_id for block in copies}))
        self.assertEqual({"artifact-old"}, {block.artifact_id for block in copies})
        self.assertEqual({"query-old"}, {block.query_id for block in copies})

    def test_restore_previous_revision_creates_current_snapshot_without_mutating_history(self) -> None:
        """직전 version의 전체 문서 설정과 block을 현재 draft 값으로 복원한다."""

        previous = ReportDefinitionVersion(
            "definition-1",
            1,
            DefinitionStatus.DRAFT,
            "직전 보고서",
            (self.definition.blocks[0],),
            orientation="landscape",
            currency_display_unit="million",
        )
        patch = ReportAssistantPatch.model_validate(
            {
                "summary": "직전 revision으로 되돌립니다.",
                "operations": [{"op": "restore_previous_revision"}],
            }
        )
        result = apply_report_assistant_patch(
            self.definition,
            patch,
            self.bindings,
            previous,
        )

        self.assertEqual(2, result.version)
        self.assertEqual("직전 보고서", result.title)
        self.assertEqual("landscape", result.orientation)
        self.assertEqual("million", result.currency_display_unit)
        self.assertEqual(("summary",), tuple(block.block_id for block in result.blocks))
        self.assertEqual("기존 보고서", self.definition.title)

    def test_restore_previous_revision_must_be_the_only_operation(self) -> None:
        """전체 snapshot 복원과 부분 patch를 섞은 모호한 요청은 계약에서 거부한다."""

        with self.assertRaises(ValidationError):
            ReportAssistantPatch.model_validate(
                {
                    "summary": "잘못된 복합 복원",
                    "operations": [
                        {"op": "restore_previous_revision"},
                        {"op": "remove_block", "block_id": "summary"},
                    ],
                }
            )

    def test_unknown_artifact_alias_and_block_are_rejected_atomically(self) -> None:
        """모델이 허용 목록 밖 Artifact나 block을 지목하면 원본을 변경하지 않고 거부한다."""

        cases = (
            {
                "op": "add_artifact_view",
                "artifact_ref": "invented",
                "view": "table",
                "title": "조작된 표",
            },
            {"op": "update_text", "block_id": "missing", "content": "변경"},
        )
        for operation in cases:
            with self.subTest(operation=operation):
                patch = ReportAssistantPatch.model_validate(
                    {"summary": "거부되어야 합니다.", "operations": [operation]}
                )
                with self.assertRaises(ValueError):
                    apply_report_assistant_patch(self.definition, patch, self.bindings)
                self.assertEqual("기존 보고서", self.definition.title)
                self.assertEqual(2, len(self.definition.blocks))

    def test_contract_rejects_raw_ids_coordinates_and_empty_update(self) -> None:
        """모델 patch에 서버 소유 ID·좌표 또는 무의미한 수정이 들어오면 schema에서 차단한다."""

        invalid_operations = (
            {
                "op": "add_artifact_view",
                "artifact_ref": "analysis_result",
                "artifact_id": "model-owned",
                "view": "chart",
                "title": "차트",
            },
            {"op": "add_text", "title": "요약", "content": "내용", "x": 0, "y": 0},
            {"op": "update_text", "block_id": "summary"},
        )
        for operation in invalid_operations:
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                ReportAssistantPatch.model_validate(
                    {"summary": "잘못된 patch", "operations": [operation]}
                )


if __name__ == "__main__":
    unittest.main()
