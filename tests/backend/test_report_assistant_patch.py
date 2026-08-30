"""Report Agent patch가 fake Artifact를 실제 draft 변경으로 안전하게 적용하는지 검증한다."""

from __future__ import annotations

import unittest
import json
from pathlib import Path
from sys import path

from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.report_contracts import ReportAssistantPatch
from app.report_patch import (
    ReportPatchNoChangesError,
    VerifiedArtifactBinding,
    apply_report_assistant_patch,
    report_patch_operation_dependencies,
    validate_report_patch_dependency_selection,
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
                "신규 분석",
                frozenset({"summary", "kpi", "chart", "table"}),
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
                        "title": "신규 분석 · 차트",
                        "placement": {"after_block_id": "current-chart", "width": "full"},
                    },
                    {
                        "op": "add_text",
                        "title": "전월 비교 요약",
                        "content": "검증된 Artifact를 근거로 작성한 비교 요약입니다.",
                        "evidence_refs": ["artifact_narrative"],
                        "placement": {"width": "full"},
                    },
                ],
            }
        )

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual(4, len(result.blocks))
        self.assertEqual(("summary", "current-chart"), tuple(b.block_id for b in result.blocks[:2]))
        chart = next(block for block in result.blocks if block.title == "신규 분석 · 차트")
        self.assertEqual(BlockType.CHART, chart.type)
        self.assertEqual("artifact-new", chart.artifact_id)
        self.assertEqual("query-new", chart.query_id)
        self.assertEqual(11, chart.y)
        self.assertEqual("기존 요약", result.blocks[0].content)
        summary = next(block for block in result.blocks if block.title == "전월 비교 요약")
        self.assertEqual(("artifact_narrative",), summary.evidence_refs)

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
                        "evidence_refs": ["artifact_narrative"],
                    },
                ],
            }
        )

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual("월간 경영 요약", result.title)
        self.assertEqual("수정된 운영 요약", result.blocks[0].content)
        self.assertEqual(("artifact_narrative",), result.blocks[0].evidence_refs)
        self.assertEqual("artifact-old", result.blocks[1].artifact_id)
        self.assertEqual("query-old", result.blocks[1].query_id)

    def test_noop_title_and_text_patch_are_rejected_before_revision(self) -> None:
        """제목·본문이 실제로 같으면 의미 없는 새 Revision을 만들 수 없다."""

        for operation in (
            {"op": "set_report_title", "title": self.definition.title},
            {
                "op": "update_text",
                "block_id": "summary",
                "content": "기존 요약",
                "evidence_refs": [],
            },
        ):
            patch = ReportAssistantPatch.model_validate({
                "summary": "변경 없는 요청",
                "operations": [operation],
            })
            with self.assertRaisesRegex(ValueError, "실제 변경"):
                apply_report_assistant_patch(self.definition, patch, self.bindings)

    def test_report_orientation_changes_without_mutating_source(self) -> None:
        """문서 방향 patch는 승인 대상 사본만 가로형으로 바꾸고 원본은 유지한다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "보고서를 A4 가로형으로 전환합니다.",
            "operations": [{
                "op": "set_report_orientation", "orientation": "landscape",
            }],
        })

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual("landscape", result.orientation)
        self.assertEqual("portrait", self.definition.orientation)
        self.assertEqual(self.definition.blocks, result.blocks)

        with self.assertRaises(ReportPatchNoChangesError):
            apply_report_assistant_patch(result, patch, self.bindings)

    def test_add_report_page_appends_server_owned_page_break(self) -> None:
        """빈 페이지 요청은 원본을 보존하고 보고서 끝에 12열 page break 한 건만 추가한다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "보고서 끝에 빈 페이지를 한 장 추가합니다.",
            "operations": [{"op": "add_report_page"}],
        })

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)
        page_break = result.blocks[-1]

        self.assertEqual(BlockType.PAGE_BREAK, page_break.type)
        self.assertEqual((None, None, 0, 12, 1, ""), (
            page_break.artifact_id, page_break.query_id, page_break.x,
            page_break.w, page_break.h, page_break.content,
        ))
        self.assertGreaterEqual(page_break.y, max(block.y + block.h for block in self.definition.blocks))
        self.assertEqual(2, len(self.definition.blocks))

        multi_page = ReportAssistantPatch.model_validate({
            "summary": "빈 페이지 세 장과 각 페이지 내용을 추가합니다.",
            "operations": [
                {"op": "add_report_page"},
                {
                    "op": "add_text", "title": "두 번째 페이지 요약",
                    "content": "검증 근거를 요약합니다.",
                    "evidence_refs": ["artifact_narrative"],
                },
                {"op": "add_report_page"},
                {
                    "op": "add_artifact_view", "artifact_ref": "analysis_result",
                    "view": "chart", "title": "신규 분석 · 차트",
                },
                {"op": "add_report_page"},
                {
                    "op": "reposition_block", "block_id": "current-chart",
                    "width": "full",
                },
            ],
        })

        multi_page_result = apply_report_assistant_patch(
            self.definition, multi_page, self.bindings
        )

        self.assertEqual(
            3,
            sum(block.type is BlockType.PAGE_BREAK for block in multi_page_result.blocks),
        )
        self.assertEqual(
            ((), (0,), (0,), (2,), (2,), (4,)),
            report_patch_operation_dependencies(multi_page),
        )
        validate_report_patch_dependency_selection(multi_page, (0, 1, 2, 3, 4, 5))
        with self.assertRaisesRegex(ValueError, "선행 변경"):
            validate_report_patch_dependency_selection(multi_page, (0, 1, 2, 3, 5))

        remove_marker = ReportAssistantPatch.model_validate({
            "summary": "추가한 페이지를 삭제합니다.",
            "operations": [{"op": "remove_block", "block_id": page_break.block_id}],
        })
        with self.assertRaisesRegex(ValueError, "페이지 경계 수정"):
            apply_report_assistant_patch(result, remove_marker, self.bindings)

        for operation in (
            {"op": "duplicate_block", "block_id": page_break.block_id},
            {
                "op": "reposition_block", "block_id": page_break.block_id,
                "width": "full",
            },
        ):
            with self.subTest(operation=operation["op"]):
                protected_marker = ReportAssistantPatch.model_validate({
                    "summary": "페이지 경계를 직접 변경합니다.",
                    "operations": [operation],
                })
                with self.assertRaisesRegex(ValueError, "페이지 경계 수정"):
                    apply_report_assistant_patch(
                        result, protected_marker, self.bindings
                    )

        redundant_title = ReportAssistantPatch.model_validate({
            "summary": "빈 페이지를 추가하고 제목을 유지합니다.",
            "operations": [
                {"op": "add_report_page"},
                {"op": "set_report_title", "title": self.definition.title},
            ],
        })
        with self.assertRaisesRegex(ReportPatchNoChangesError, "제목 operation"):
            apply_report_assistant_patch(self.definition, redundant_title, self.bindings)

    def test_assistant_patch_cannot_store_more_than_100_blocks(self) -> None:
        """모델 입력은 100개여도 신규 operation으로 저장 상한을 넘기면 전체 patch를 닫는다."""

        full_definition = self.definition.replace_blocks(tuple(
            ReportBlock(
                f"text-{index}", f"본문 {index}", None, 12, None,
                BlockType.TEXT, 0, index, 12, 1, "본문",
            )
            for index in range(100)
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "페이지를 추가합니다.",
            "operations": [{"op": "add_report_page"}],
        })

        with self.assertRaisesRegex(ValueError, "최대 100개"):
            apply_report_assistant_patch(full_definition, patch, self.bindings)

    def test_document_currency_and_compact_layout_are_server_applied(self) -> None:
        """통화 단위와 빈 공간 정리는 원본을 건드리지 않고 typed patch로만 적용한다."""

        gapped = self.definition.replace_blocks((
            self.definition.blocks[0],
            ReportBlock(
                "current-chart", "현재 실적", "artifact-old", 6, "query-old",
                BlockType.CHART, 0, 20, 6, 7,
            ),
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "통화 단위를 백만원으로 바꾸고 빈 공간을 정리합니다.",
            "operations": [
                {"op": "set_currency_display_unit", "currency_display_unit": "million"},
                {"op": "compact_report_layout"},
            ],
        })

        result = apply_report_assistant_patch(gapped, patch, self.bindings)

        self.assertEqual("million", result.currency_display_unit)
        self.assertEqual(4, result.blocks[1].y)
        self.assertEqual("auto", gapped.currency_display_unit)
        self.assertEqual(20, gapped.blocks[1].y)

    def test_text_title_and_chart_settings_preserve_lineage(self) -> None:
        """text 제목과 chart 설정은 허용 필드만 바꾸고 lineage를 보존한다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "차트 제목과 크기 및 표현을 변경합니다.",
            "operations": [
                {"op": "update_block_title", "block_id": "summary", "title": "월간 운영 요약"},
                {"op": "resize_block", "block_id": "current-chart", "block_width": 6, "block_height": 9},
                {
                    "op": "update_chart_settings", "block_id": "current-chart",
                    "chart_type": "horizontal-bar", "show_legend": False,
                },
            ],
        })

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)
        chart = next(block for block in result.blocks if block.block_id == "current-chart")
        settings = json.loads(chart.content)

        self.assertEqual("월간 운영 요약", result.blocks[0].title)
        self.assertEqual("현재 실적", chart.title)
        self.assertEqual((6, 9), (chart.w, chart.h))
        self.assertEqual("artifact-old", chart.artifact_id)
        self.assertEqual("query-old", chart.query_id)
        self.assertEqual(
            {"chartType": "horizontal-bar", "showLegend": False, "sizeMode": "manual", "visibleViews": ["chart"]},
            settings,
        )
        self.assertEqual("현재 실적", self.definition.blocks[1].title)

    def test_artifact_view_title_change_is_rejected(self) -> None:
        """chart·table·Artifact 제목은 승인 근거 식별값이므로 patch로 바꿀 수 없다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "차트 제목을 변경합니다.",
            "operations": [{
                "op": "update_block_title",
                "block_id": "current-chart",
                "title": "월간 매출 추이",
            }],
        })

        with self.assertRaisesRegex(ValueError, "Artifact view block 제목"):
            apply_report_assistant_patch(self.definition, patch, self.bindings)

    def test_table_settings_and_artifact_view_presentation_are_typed(self) -> None:
        """표와 신규 Artifact view는 해당 view에 허용된 renderer 설정만 저장한다."""

        definition = self.definition.replace_blocks((
            self.definition.blocks[0],
            ReportBlock(
                "current-table", "현재 표", "artifact-old", 12, "query-old",
                BlockType.TABLE, 0, 4, 12, 5,
            ),
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "표를 간결하게 하고 새 차트를 추가합니다.",
            "operations": [
                {
                    "op": "update_table_settings", "block_id": "current-table",
                    "density": "compact", "show_row_numbers": True, "size_mode": "auto",
                },
                {
                    "op": "add_artifact_view", "artifact_ref": "analysis_result",
                    "view": "chart", "title": "신규 분석 · 차트", "chart_type": "line",
                    "show_legend": False, "size_mode": "auto",
                },
            ],
        })

        result = apply_report_assistant_patch(definition, patch, self.bindings)
        table = next(block for block in result.blocks if block.block_id == "current-table")
        chart = next(block for block in result.blocks if block.title == "신규 분석 · 차트")

        self.assertEqual(
            {"density": "compact", "showRowNumbers": True, "sizeMode": "auto", "visibleViews": ["table"]},
            json.loads(table.content),
        )
        self.assertEqual(
            {"chartType": "line", "showLegend": False, "sizeMode": "auto", "visibleViews": ["chart"]},
            json.loads(chart.content),
        )

    def test_atomic_artifact_views_create_independent_server_owned_blocks(self) -> None:
        """요약·KPI·차트·표는 합본이 아닌 유형별 최소 크기의 독립 block으로 저장한다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "승인 분석의 네 가지 보기를 독립 요소로 추가합니다.",
            "operations": [
                {
                    "op": "add_artifact_view", "artifact_ref": "analysis_result",
                    "view": view, "title": f"신규 분석 · {label}",
                    "placement": {"width": width},
                }
                for view, label, width in (
                    ("summary", "요약", "half"),
                    ("kpi", "핵심 지표", "half"),
                    ("chart", "차트", "full"),
                    ("table", "표", "full"),
                )
            ],
        })

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)
        created = {block.title: block for block in result.blocks[2:]}

        expected = {
            "신규 분석 · 요약": (BlockType.ARTIFACT, 6, 5, ["summary"]),
            "신규 분석 · 핵심 지표": (BlockType.ARTIFACT, 6, 6, ["kpi"]),
            "신규 분석 · 차트": (BlockType.CHART, 12, 7, None),
            "신규 분석 · 표": (BlockType.TABLE, 12, 5, None),
        }
        self.assertEqual(set(expected), set(created))
        for title, (block_type, width, height, visible_views) in expected.items():
            with self.subTest(title=title):
                block = created[title]
                settings = json.loads(block.content)
                self.assertEqual((block_type, width, height), (block.type, block.w, block.h))
                self.assertEqual("artifact-new", block.artifact_id)
                self.assertEqual("query-new", block.query_id)
                self.assertIsNone(block.view_spec_id)
                if visible_views is not None:
                    self.assertEqual(visible_views, settings["visibleViews"])
                    self.assertEqual("ANSWER-ARTIFACT-BLOCK-v1", settings["schemaVersion"])

    def test_atomic_artifact_view_revalidates_availability_and_server_title(self) -> None:
        """저장 직전에는 binding의 실제 view와 서버 파생 제목이 모두 일치해야 한다."""

        summary_only = {
            "analysis_result": VerifiedArtifactBinding(
                "artifact-new", "query-new", "a" * 64, "신규 분석",
                frozenset({"summary"}),
            )
        }
        unavailable = ReportAssistantPatch.model_validate({
            "summary": "없는 차트를 추가합니다.",
            "operations": [{
                "op": "add_artifact_view", "artifact_ref": "analysis_result",
                "view": "chart", "title": "신규 분석 · 차트",
            }],
        })
        forged_title = ReportAssistantPatch.model_validate({
            "summary": "모델 제목을 신뢰하지 않습니다.",
            "operations": [{
                "op": "add_artifact_view", "artifact_ref": "analysis_result",
                "view": "summary", "title": "모델이 만든 제목",
            }],
        })

        with self.assertRaisesRegex(ValueError, "사용할 수 없습니다"):
            apply_report_assistant_patch(self.definition, unavailable, summary_only)
        with self.assertRaisesRegex(ValueError, "서버 검증 제목"):
            apply_report_assistant_patch(self.definition, forged_title, summary_only)

    def test_legacy_whole_artifact_patch_fails_closed(self) -> None:
        """합본 artifact operation은 새 Revision으로 재생하지 않고 원본 기록을 보존한다."""

        with self.assertRaises(ValueError):
            ReportAssistantPatch.model_validate({
                "summary": "기존 합본 분석 결과를 복원합니다.",
                "operations": [{
                    "op": "add_artifact_view", "artifact_ref": "analysis_result",
                    "view": "artifact", "title": "기존 합본 분석 결과",
                    "placement": {"width": "full"},
                }],
            })

    def test_all_existing_block_transforms_preserve_view_spec_lineage(self) -> None:
        """resize·setting·reposition·duplicate 경로 모두 기존 view_spec_id를 잃지 않는다."""

        view_spec_id = "00000000-0000-0000-0000-000000000777"
        definition = self.definition.replace_blocks((
            self.definition.blocks[0],
            ReportBlock(
                "current-chart", "현재 실적", "artifact-old", 12, "query-old",
                BlockType.CHART, 0, 4, 12, 7, "", (), view_spec_id,
            ),
        ))
        operations = (
            {"op": "resize_block", "block_id": "current-chart", "block_width": 6, "block_height": 8},
            {"op": "update_chart_settings", "block_id": "current-chart", "show_legend": False},
            {"op": "reposition_block", "block_id": "current-chart", "width": "half"},
            {"op": "duplicate_block", "block_id": "current-chart"},
        )
        for operation in operations:
            with self.subTest(operation=operation["op"]):
                patch = ReportAssistantPatch.model_validate({
                    "summary": "기존 표현 계보를 보존합니다.", "operations": [operation],
                })
                result = apply_report_assistant_patch(definition, patch, self.bindings)
                affected = [
                    block for block in result.blocks
                    if block.block_id == "current-chart" or operation["op"] == "duplicate_block"
                    and block.title == "현재 실적"
                ]
                self.assertTrue(affected)
                self.assertTrue(all(block.view_spec_id == view_spec_id for block in affected))

    def test_view_settings_fail_closed_for_wrong_block_type_and_conflicts(self) -> None:
        """잘못된 view 대상과 같은 대상을 지우며 변경하는 모순은 전체 patch를 거부한다."""

        wrong_type = ReportAssistantPatch.model_validate({
            "summary": "텍스트에 차트 설정을 적용합니다.",
            "operations": [{
                "op": "update_chart_settings", "block_id": "summary", "show_legend": False,
            }],
        })
        conflicting = ReportAssistantPatch.model_validate({
            "summary": "차트를 삭제하면서 키웁니다.",
            "operations": [
                {"op": "remove_block", "block_id": "current-chart"},
                {"op": "resize_block", "block_id": "current-chart", "block_width": 12, "block_height": 9},
            ],
        })

        for invalid in (wrong_type, conflicting):
            with self.subTest(summary=invalid.summary), self.assertRaises(ValueError):
                apply_report_assistant_patch(self.definition, invalid, self.bindings)
        self.assertEqual(("summary", "current-chart"), tuple(block.block_id for block in self.definition.blocks))

    def test_reordered_evidence_refs_do_not_create_a_revision(self) -> None:
        """근거 alias 순서는 의미가 없으므로 순서만 바꾼 본문 patch를 no-op으로 차단한다."""

        definition = self.definition.replace_blocks((
            ReportBlock(
                "summary", "운영 요약", None, 12, None, BlockType.TEXT,
                0, 0, 12, 4, "기존 요약", ("metric_1", "artifact_narrative"),
            ),
            self.definition.blocks[1],
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "근거 순서만 변경",
            "operations": [{
                "op": "update_text", "block_id": "summary", "content": "기존 요약",
                "evidence_refs": ["metric_1", "artifact_narrative"],
            }],
        })

        with self.assertRaisesRegex(ValueError, "실제 변경"):
            apply_report_assistant_patch(definition, patch, self.bindings)

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
                        "evidence_refs": ["artifact_narrative"],
                        "placement": {"after_block_id": "summary"},
                    },
                    {
                        "op": "add_text",
                        "title": "두 번째 설명",
                        "content": "두 번째",
                        "evidence_refs": ["artifact_narrative"],
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

    def test_insert_after_short_block_uses_uneven_row_bottom(self) -> None:
        """높이 5 요약 옆 높이 6 KPI가 있어도 다음 full block은 y=6부터 시작한다."""

        uneven = self.definition.replace_blocks((
            ReportBlock(
                "atomic-summary", "분석 · 요약", "artifact-old", 6, "query-old",
                BlockType.ARTIFACT, 0, 0, 6, 5,
                json.dumps({"visibleViews": ["summary"]}),
            ),
            ReportBlock(
                "atomic-kpi", "분석 · 핵심 지표", "artifact-old", 6, "query-old",
                BlockType.ARTIFACT, 6, 0, 6, 6,
                json.dumps({"visibleViews": ["kpi"]}),
            ),
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "요약 행 다음에 차트를 추가합니다.",
            "operations": [{
                "op": "add_artifact_view", "artifact_ref": "analysis_result",
                "view": "chart", "title": "신규 분석 · 차트",
                "placement": {"after_block_id": "atomic-summary", "width": "full"},
            }],
        })

        result = apply_report_assistant_patch(uneven, patch, self.bindings)
        chart = next(block for block in result.blocks if block.title == "신규 분석 · 차트")

        self.assertEqual(6, chart.y)
        self.assertTrue(all(
            chart.y >= block.y + block.h or chart.y + chart.h <= block.y
            for block in result.blocks if block.block_id != chart.block_id
        ))

    def test_full_insert_avoids_staggered_crossing_block(self) -> None:
        """다른 x에서 먼저 시작한 block이 anchor bottom을 지나면 full 삽입은 그 아래로 간다."""

        staggered = self.definition.replace_blocks((
            ReportBlock(
                "left-summary", "왼쪽 요약", "artifact-old", 6, "query-old",
                BlockType.ARTIFACT, 0, 0, 6, 5,
                json.dumps({"visibleViews": ["summary"]}),
            ),
            ReportBlock(
                "right-kpi", "오른쪽 KPI", "artifact-old", 6, "query-old",
                BlockType.ARTIFACT, 6, 2, 6, 7,
                json.dumps({"visibleViews": ["kpi"]}),
            ),
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "staggered 행 다음에 full 차트를 추가합니다.",
            "operations": [{
                "op": "add_artifact_view", "artifact_ref": "analysis_result",
                "view": "chart", "title": "신규 분석 · 차트",
                "placement": {"after_block_id": "left-summary", "width": "full"},
            }],
        })

        result = apply_report_assistant_patch(staggered, patch, self.bindings)
        chart = next(block for block in result.blocks if block.title == "신규 분석 · 차트")

        self.assertEqual(9, chart.y)
        self.assertTrue(all(
            chart.y >= block.y + block.h or chart.y + chart.h <= block.y
            for block in result.blocks if block.block_id != chart.block_id
        ))

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

    def test_reposition_to_current_end_with_same_width_is_rejected_as_noop(self) -> None:
        """화면상 이미 마지막인 block은 원시 y에 간격이 있어도 같은 너비 이동을 거부한다."""

        definition = self.definition.replace_blocks((
            self.definition.blocks[0],
            ReportBlock(
                "current-chart", "현재 실적", "artifact-old", 6, "query-old",
                BlockType.CHART, 0, 29, 6, 7,
            ),
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "현재 실적을 현재 너비로 보고서 끝에 둡니다.",
            "operations": [{
                "op": "reposition_block", "block_id": "current-chart", "width": "half",
            }],
        })

        with self.assertRaisesRegex(ValueError, "실제 변경"):
            apply_report_assistant_patch(definition, patch, self.bindings)

    def test_reposition_after_current_anchor_with_same_width_is_rejected_as_noop(self) -> None:
        """현재 바로 앞 block을 anchor로 다시 지정해도 새 Revision을 만들지 않는다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "현재 순서를 유지합니다.",
            "operations": [{
                "op": "reposition_block", "block_id": "current-chart",
                "after_block_id": "summary", "width": "full",
            }],
        })

        with self.assertRaisesRegex(ValueError, "실제 변경"):
            apply_report_assistant_patch(self.definition, patch, self.bindings)

    def test_reposition_at_same_place_can_still_change_width(self) -> None:
        """순서가 같더라도 실제 너비 변경은 유효한 patch로 적용한다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "현재 위치에서 너비를 줄입니다.",
            "operations": [{
                "op": "reposition_block", "block_id": "current-chart",
                "after_block_id": "summary", "width": "half",
            }],
        })

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        chart = next(block for block in result.blocks if block.block_id == "current-chart")
        self.assertEqual(6, chart.w)
        self.assertEqual(4, chart.y)

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

    def test_remove_conflicts_with_same_target_change_or_anchor_use(self) -> None:
        """삭제 block을 동시에 수정하거나 새 block의 anchor로 사용하는 모순 patch를 거부한다."""

        same_target = ReportAssistantPatch.model_validate({
            "summary": "요약을 수정한 뒤 삭제합니다.",
            "operations": [
                {"op": "update_text", "block_id": "summary", "content": "새 요약"},
                {"op": "remove_block", "block_id": "summary"},
            ],
        })
        removed_anchor = ReportAssistantPatch.model_validate({
            "summary": "차트를 기준으로 설명을 추가하고 차트를 삭제합니다.",
            "operations": [
                {
                    "op": "add_text", "title": "설명", "content": "설명입니다.",
                    "placement": {"after_block_id": "current-chart"},
                },
                {"op": "remove_block", "block_id": "current-chart"},
            ],
        })

        for conflicting in (same_target, removed_anchor):
            with self.subTest(summary=conflicting.summary), self.assertRaises(ValueError):
                apply_report_assistant_patch(self.definition, conflicting, self.bindings)

    def test_independent_title_and_block_removal_can_be_selected_together(self) -> None:
        """서로 다른 대상을 바꾸는 operation 조합은 기존 부분 승인 범위를 유지한다."""

        patch = ReportAssistantPatch.model_validate({
            "summary": "제목을 바꾸고 요약을 삭제합니다.",
            "operations": [
                {"op": "set_report_title", "title": "새 보고서"},
                {"op": "remove_block", "block_id": "summary"},
            ],
        })

        result = apply_report_assistant_patch(self.definition, patch, self.bindings)

        self.assertEqual("새 보고서", result.title)
        self.assertEqual(("current-chart",), tuple(block.block_id for block in result.blocks))

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

    def test_structure_operations_preserve_existing_text_evidence(self) -> None:
        """텍스트 이동·복제는 검증 근거를 보존하고 본문 변경만 새 근거로 교체한다."""

        grounded = self.definition.replace_blocks((
            ReportBlock(
                "summary", "운영 요약", None, 12, None, BlockType.TEXT,
                0, 0, 12, 4, "기존 요약", ("artifact_narrative",),
            ),
            self.definition.blocks[1],
        ))
        patch = ReportAssistantPatch.model_validate({
            "summary": "근거 있는 요약을 복제합니다.",
            "operations": [{"op": "duplicate_block", "block_id": "summary"}],
        })

        result = apply_report_assistant_patch(grounded, patch, self.bindings)

        copies = [block for block in result.blocks if block.title == "운영 요약"]
        self.assertEqual(2, len(copies))
        self.assertTrue(all(block.evidence_refs == ("artifact_narrative",) for block in copies))

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
            {"op": "update_text", "block_id": "missing", "content": "변경", "evidence_refs": ["artifact_narrative"]},
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
            {"op": "add_text", "title": "요약", "content": "내용", "evidence_refs": ["artifact_narrative"], "x": 0, "y": 0},
            {"op": "update_text", "block_id": "summary"},
        )
        for operation in invalid_operations:
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                ReportAssistantPatch.model_validate(
                    {"summary": "잘못된 patch", "operations": [operation]}
                )


if __name__ == "__main__":
    unittest.main()
