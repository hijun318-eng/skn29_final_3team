from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api import report_router as report_api  # noqa: E402
from app.contracts import RequestContext, Role  # noqa: E402
from app.report_contracts import ApproveReportVersionRequest  # noqa: E402
from app.services.report.document import (  # noqa: E402
    approve_report_document,
    build_report_html,
    render_report_document,
)
from app.services.report.layout import _paginate_layout  # noqa: E402
from app.services.report.types import (  # noqa: E402
    ReportDocumentRenderError,
    canonical_source_checksum,
)
from app.services.report.values import _finite_number  # noqa: E402
from src.report.domain import (  # noqa: E402
    BlockType,
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionVersion,
)
from tests.support.report_repository import InMemoryReportRepository  # noqa: E402
from src.report.router import create_report_router  # noqa: E402


APPROVED_AT = datetime(2026, 8, 14, 9, 30, tzinfo=timezone.utc)


def source() -> dict[str, object]:
    artifact = {
        "artifact_id": "00000000-0000-0000-0000-000000000099",
        "artifact_checksum": "a" * 64,
        "query_id": "query-1",
        "table": {
            "columns": ["month", "revenue"],
            "rows": [
                {"month": "6월", "revenue": 980000000},
                {"month": "7월", "revenue": 1080000000},
            ],
        },
        "chart_spec": {"chart_type": "line", "x_field": "month", "y_fields": ["revenue"]},
        "evidence": {
            "metric_values": [
                {"label": "총매출", "value": 1080000000, "unit": "KRW"},
            ]
        },
        "narrative": "7월 매출 분석",
    }
    return {
        "definition_id": "00000000-0000-0000-0000-000000000010",
        "version": 3,
        "title": "7월 영업 실적 <script>alert(1)</script>",
        "blocks": [
            {
                "block_id": "summary",
                "title": "핵심 요약",
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 12,
                "h": 3,
                "content": "- 매출이 증가했습니다.\n- 객단가를 확인하세요.",
                "artifact": None,
            },
            {
                "block_id": "chart",
                "title": "월별 매출",
                "type": "chart",
                "x": 0,
                "y": 3,
                "w": 6,
                "h": 6,
                "content": "",
                "artifact": artifact,
            },
            {
                "block_id": "table",
                "title": "월별 상세",
                "type": "table",
                "x": 6,
                "y": 3,
                "w": 6,
                "h": 6,
                "content": "",
                "artifact": artifact,
            },
        ],
        "artifact_versions": [
            {
                "artifact_id": artifact["artifact_id"],
                "artifact_checksum": artifact["artifact_checksum"],
                "query_id": artifact["query_id"],
            }
        ],
    }


class _Repository:
    def __init__(self, report_source: dict[str, object]) -> None:
        self.source = report_source
        self.finalized = None

    def get_document_source(self, definition_id: str, version: int):
        return self.source

    def approve_with_document(self, *args):
        self.finalized = args
        return "approved"


class ReportDocumentTest(unittest.IsolatedAsyncioTestCase):
    def test_html_is_a4_self_contained_and_escapes_content(self):
        report_source = source()
        checksum = canonical_source_checksum(report_source, "landscape")
        html = build_report_html(report_source, "landscape", APPROVED_AT, checksum)

        self.assertIn("size: A4 landscape", html)
        self.assertIn("ANSWERVICE", html)
        self.assertIn("<svg", html)
        self.assertIn("<table>", html)
        self.assertIn("1,080,000,000", html)
        self.assertIn(".report-block--artifact { break-inside:auto; }", html)
        self.assertIn("background:#fbfdff; break-inside:avoid;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_chart_accepts_only_finite_decimal_and_plain_numeric_strings(self):
        accepted = (Decimal("-12.50"), " 1200.75 ", "-2.5e3", 0, 1.25)
        rejected = (True, None, "12%", "₩1200", "$12", "1,200", "NaN", "Infinity", "hotel")
        self.assertTrue(all(_finite_number(value) is not None for value in accepted))
        self.assertTrue(all(_finite_number(value) is None for value in rejected))

        report_source = deepcopy(source())
        artifact = report_source["blocks"][1]["artifact"]
        artifact["table"]["rows"] = [
            {"month": "1월", "revenue": "1080000000.5"},
            {"month": "2월", "revenue": Decimal("-250000000.25")},
            {"month": "3월", "revenue": "12%"},
            {"month": "4월", "revenue": "₩300"},
            {"month": "5월", "revenue": "1,200"},
            {"month": "6월", "revenue": "NaN"},
            {"month": "7월", "revenue": True},
        ]
        artifact["evidence"]["metric_values"] = [{
            "result_field": "revenue", "label": "매출", "value": "1080000000.5", "unit": "KRW",
        }]
        report_source["blocks"] = [report_source["blocks"][1]]

        html = build_report_html(report_source, "landscape", APPROVED_AT, "e" * 64)

        self.assertIn("<polyline", html)
        self.assertIn('data-source-rows="7"', html)
        self.assertIn('data-valid-points="2"', html)
        self.assertIn('data-rendered-points="2"', html)
        self.assertIn("전체 7행 중 모든 계열에 유효한 유한 수치가 있는 2개 행만 표시했습니다.", html)
        self.assertNotIn("차트로 표현할 유한 수치 데이터가 없습니다.", html)

    def test_chart_evenly_samples_all_numeric_rows_and_pdf_keeps_svg_disclosure(self):
        report_source = deepcopy(source())
        report_source["orientation"] = "landscape"
        artifact = report_source["blocks"][1]["artifact"]
        artifact["table"]["rows"] = [
            {"month": str(index), "revenue": str(index * 1000)} for index in range(1, 26)
        ]
        artifact["evidence"]["metric_values"] = [{
            "result_field": "revenue", "label": "매출", "value": "25000", "unit": "KRW",
        }]
        report_source["blocks"] = [report_source["blocks"][1]]

        html = build_report_html(
            report_source,
            "landscape",
            APPROVED_AT,
            canonical_source_checksum(report_source, "landscape"),
        )

        self.assertIn('data-source-rows="25"', html)
        self.assertIn('data-valid-points="25"', html)
        self.assertIn('data-rendered-points="12"', html)
        self.assertIn("25개 행 중 12개 대표 표본을 균등 추출", html)
        self.assertIn("첫·마지막 포함", html)
        self.assertEqual(12, html.count("<circle "))
        self.assertIn(">1</text>", html)
        self.assertIn(">25</text>", html)

        class CaptureHTML:
            rendered_html = ""

            def __init__(self, **kwargs):
                type(self).rendered_html = kwargs["string"]

            def write_pdf(self, **kwargs):
                return b"%PDF-1.7\nnumeric-string-chart"

        with patch.dict(sys.modules, {"weasyprint": SimpleNamespace(HTML=CaptureHTML)}):
            rendered = render_report_document(report_source, "landscape", APPROVED_AT)
        self.assertTrue(rendered.pdf.startswith(b"%PDF-"))
        self.assertIn("<polyline", CaptureHTML.rendered_html)
        self.assertIn('data-rendered-points="12"', CaptureHTML.rendered_html)

    def test_table_uses_disclosed_even_sample_with_frozen_artifact_reference(self):
        report_source = deepcopy(source())
        artifact = report_source["blocks"][2]["artifact"]
        artifact["table"]["rows"] = [
            {"month": str(index), "revenue": str(index * 1000)} for index in range(1, 26)
        ]
        report_source["blocks"] = [report_source["blocks"][2]]

        html = build_report_html(report_source, "landscape", APPROVED_AT, "9" * 64)

        self.assertIn('class="table-wrap" data-source-rows="25" data-rendered-rows="12"', html)
        self.assertIn("전체 25행 중 12개 대표 표본을 균등 추출", html)
        self.assertIn("첫·마지막 포함", html)
        self.assertIn("동결된 Artifact 버전", html)
        self.assertIn("<td>1</td>", html)
        self.assertIn("<td>25</td>", html)
        self.assertNotIn("<td>2</td>", html)

    def test_chart_renders_every_numeric_series_and_blocks_unsafe_series(self):
        report_source = deepcopy(source())
        artifact = report_source["blocks"][1]["artifact"]
        artifact["table"]["rows"] = [
            {"month": "6월", "revenue": "980000000", "target": "1000000000"},
            {"month": "7월", "revenue": "1080000000", "target": "1100000000"},
        ]
        artifact["chart_spec"]["y_fields"] = ["revenue", "target"]
        artifact["evidence"]["metric_values"] = [
            {"result_field": "revenue", "label": "매출", "value": "1080000000", "unit": "KRW"},
            {"result_field": "target", "label": "목표", "value": "1100000000", "unit": "원"},
        ]
        report_source["blocks"] = [report_source["blocks"][1]]

        html = build_report_html(report_source, "landscape", APPROVED_AT, "a" * 64)

        self.assertIn('data-series-count="2"', html)
        self.assertEqual(2, html.count('<polyline class="series-mark'))
        self.assertEqual(4, html.count('<circle class="series-mark'))
        self.assertIn(">매출</span>", html)
        self.assertIn(">목표</span>", html)
        self.assertIn("stroke:#1c69d4", html)
        self.assertIn("stroke:#16a36a", html)

        missing = deepcopy(report_source)
        missing_artifact = missing["blocks"][0]["artifact"]
        for row in missing_artifact["table"]["rows"]:
            row["target"] = "not-a-number"
        with self.assertRaisesRegex(ReportDocumentRenderError, "target"):
            build_report_html(missing, "landscape", APPROVED_AT, "b" * 64)

        mixed_units = deepcopy(report_source)
        mixed_units["blocks"][0]["artifact"]["evidence"]["metric_values"][1]["unit"] = "%"
        with self.assertRaisesRegex(ReportDocumentRenderError, "shared unit"):
            build_report_html(mixed_units, "landscape", APPROVED_AT, "c" * 64)

    def test_editor_chart_types_use_explicit_pdf_fallback_or_block(self):
        fallbacks = {
            "area": "line",
            "horizontal-bar": "bar",
            "stacked-bar": "bar",
            "donut": "bar",
            "pie": "bar",
        }
        for chart_type, rendered_type in fallbacks.items():
            with self.subTest(chart_type=chart_type):
                report_source = deepcopy(source())
                report_source["blocks"] = [report_source["blocks"][1]]
                report_source["blocks"][0]["content"] = json.dumps({"chartType": chart_type})
                html = build_report_html(
                    report_source, "landscape", APPROVED_AT, chart_type[0] * 64
                )
                self.assertIn(f'data-chart-type-original="{chart_type}"', html)
                self.assertIn(f'data-chart-type-rendered="{rendered_type}"', html)
                self.assertIn("PDF 호환 보기", html)

        report_source = deepcopy(source())
        report_source["blocks"] = [report_source["blocks"][1]]
        report_source["blocks"][0]["content"] = json.dumps({"chartType": "radar"})
        with self.assertRaisesRegex(ReportDocumentRenderError, "radar"):
            build_report_html(report_source, "landscape", APPROVED_AT, "d" * 64)

    def test_server_layout_matches_frontend_canonical_grid_fixture(self):
        fixture = json.loads(
            (ROOT / "tests" / "backend" / "fixtures" / "report-layout-canonical.json")
            .read_text(encoding="utf-8")
        )
        pages = _paginate_layout(fixture["blocks"], fixture["orientation"])
        actual = [[{
            "block_id": block["block_id"],
            "x": block["x"],
            "source_y": block["_source_y"],
            "page_y": block["_layout_y"],
            "w": block["w"],
            "h": block["_layout_h"],
        } for block in page] for page in pages]
        self.assertEqual(fixture["expected_pages"], actual)

        report_source = {
            "definition_id": "00000000-0000-0000-0000-000000000010",
            "version": 1,
            "title": "Canonical layout",
            "orientation": fixture["orientation"],
            "currency_display_unit": "auto",
            "blocks": fixture["blocks"],
            "artifact_versions": [],
        }
        html = build_report_html(report_source, "landscape", APPROVED_AT, "f" * 64)
        self.assertEqual(2, html.count('class="report-layout-page"'))
        self.assertIn("보고서 구성 1/2", html)
        self.assertIn("보고서 구성 2/2", html)
        self.assertIn('data-layout-height-policy="minimum-flow"', html)
        self.assertIn('data-block-id="right" data-layout-x="6" data-layout-y="4"', html)
        self.assertIn('data-block-id="next" data-layout-x="0" data-layout-y="0" data-layout-source-y="11"', html)
        self.assertIn('data-layout-y="4" data-layout-h="7" style="min-height:49mm"', html)
        self.assertIn('data-layout-y="0" data-layout-h="8" style="min-height:56mm"', html)
        self.assertIn("grid-column:7 / span 6;grid-row:1;--report-min-rows:7", html)
        self.assertIn("grid-column:1 / span 12;grid-row:1;--report-min-rows:8", html)
        self.assertLess(html.index('data-block-id="left"'), html.index('data-block-id="right"'))

    def test_bar_chart_handles_negative_values_without_negative_svg_height(self):
        report_source = deepcopy(source())
        artifact = report_source["blocks"][1]["artifact"]
        artifact["chart_spec"]["chart_type"] = "bar"
        artifact["table"]["rows"][0]["revenue"] = -500000000
        checksum = canonical_source_checksum(report_source, "landscape")

        html = build_report_html(report_source, "landscape", APPROVED_AT, checksum)

        self.assertIn("<rect", html)
        self.assertNotIn('height="-', html)

    def test_currency_unit_scales_only_krw_across_kpi_table_and_chart(self):
        report_source = deepcopy(source())
        report_source["orientation"] = "landscape"
        report_source["currency_display_unit"] = "hundredMillion"
        artifact = report_source["blocks"][1]["artifact"]
        artifact["table"] = {
            "columns": [
                "month", "revenue (KRW)", "occupancy", "bookings", "usd", "missing"
            ],
            "rows": [
                {
                    "month": "7월",
                    "revenue (KRW)": -1_080_000_000,
                    "occupancy": 82.5,
                    "bookings": 1200,
                    "usd": 1200,
                    "missing": None,
                },
                {
                    "month": "8월",
                    "revenue (KRW)": 0,
                    "occupancy": 0,
                    "bookings": 0,
                    "usd": 0,
                    "missing": None,
                },
            ],
        }
        artifact["chart_spec"] = {
            "chart_type": "bar",
            "x_field": "month",
            "y_fields": ["revenue (KRW)"],
        }
        artifact["evidence"]["metric_values"] = [
            {
                "result_field": "revenue (KRW)", "label": "총매출 (KRW)",
                "value": -1_080_000_000, "unit": "KRW",
            },
            {
                "result_field": "occupancy", "label": "점유율",
                "value": 82.5, "unit": "%",
            },
            {
                "result_field": "bookings", "label": "예약 수",
                "value": 1200, "unit": "count",
            },
            {
                "result_field": "usd", "label": "해외 매출",
                "value": 1200, "unit": "USD",
            },
            {
                "result_field": "missing", "label": "미집계 매출",
                "value": None, "unit": "₩",
            },
        ]
        report_source["blocks"] = [{
            **report_source["blocks"][1],
            "type": "artifact",
            "w": 12,
            "content": json.dumps({"presentationMode": "detail"}),
        }]
        checksum = canonical_source_checksum(report_source, "landscape")

        html = build_report_html(report_source, "landscape", APPROVED_AT, checksum)

        self.assertIn('<meta name="answervice-currency-display-unit" content="hundredMillion">', html)
        self.assertIn("<strong>-10.8 <small>억 원</small>", html)
        self.assertIn("<span>총매출</span>", html)
        self.assertNotIn("총매출 (KRW)", html)
        self.assertIn("<strong>82.5 <small>%</small>", html)
        self.assertIn("<strong>1,200 <small>count</small>", html)
        self.assertIn("<strong>1,200 <small>USD</small>", html)
        self.assertIn("<strong>- <small>억 원</small>", html)
        self.assertIn("<th>revenue (억 원)</th>", html)
        self.assertIn("<th>occupancy (%)</th>", html)
        self.assertIn("<th>bookings (count)</th>", html)
        self.assertIn("<th>usd (USD)</th>", html)
        self.assertIn("<td>-10.8</td>", html)
        self.assertIn("<td>0</td>", html)
        self.assertIn("<td>-</td>", html)
        self.assertIn("단위: 억 원", html)
        self.assertNotIn("억 원) (억 원", html)
        self.assertNotIn('height="-', html)

        report_source["currency_display_unit"] = "auto"
        auto_html = build_report_html(
            report_source,
            "landscape",
            APPROVED_AT,
            canonical_source_checksum(report_source, "landscape"),
        )
        self.assertIn('content="auto"', auto_html)
        self.assertIn(
            '<meta name="answervice-resolved-currency-display-unit" content="hundredMillion">',
            auto_html,
        )
        self.assertIn("<td>-10.8</td>", auto_html)

    def test_source_hash_and_legacy_billion_unit_are_deterministic(self):
        report_source = source()
        report_source["orientation"] = "portrait"
        report_source["currency_display_unit"] = "million"
        million_hash = canonical_source_checksum(report_source, "portrait")

        report_source["currency_display_unit"] = "hundredMillion"
        self.assertNotEqual(
            million_hash,
            canonical_source_checksum(report_source, "portrait"),
        )
        report_source["currency_display_unit"] = "billion"
        html = build_report_html(
            report_source,
            "portrait",
            APPROVED_AT,
            canonical_source_checksum(report_source, "portrait"),
        )
        self.assertIn('content="billion"', html)
        self.assertIn("금액 단위 십억 원", html)

    def test_aggregate_artifact_renders_narrative_kpis_chart_and_table(self):
        report_source = source()
        artifact_block = deepcopy(report_source["blocks"][1])
        artifact_block.update({
            "block_id": "artifact-whole",
            "type": "artifact",
            "w": 12,
            "content": json.dumps({
                "presentationMode": "detail",
                "visibleViews": ["summary", "kpi", "chart", "table"],
            }),
        })
        report_source["blocks"] = [artifact_block]
        checksum = canonical_source_checksum(report_source, "landscape")

        html = build_report_html(report_source, "landscape", APPROVED_AT, checksum)

        self.assertIn("artifact-bundle--detail", html)
        self.assertIn("분석 요약", html)
        self.assertIn("주요 KPI", html)
        self.assertIn("<svg", html)
        self.assertIn("<table>", html)
        self.assertIn("1,080,000,000", html)

    def test_explicit_synthetic_source_is_disclosed_on_cover_and_artifact(self):
        report_source = deepcopy(source())
        report_source["blocks"] = [report_source["blocks"][1]]
        artifact = report_source["blocks"][0]["artifact"]
        artifact["evidence"]["sources"] = [
            {"name": "demo", "synthetic": True},
            {"name": "production", "synthetic": False},
        ]

        html = build_report_html(report_source, "landscape", APPROVED_AT, "1" * 64)

        warning = "합성 데모 데이터 · 실제 호텔 운영 성과가 아님"
        self.assertEqual(2, html.count(warning))
        self.assertIn('class="synthetic-report-warning" role="note"', html)
        self.assertIn('class="synthetic-artifact-warning" role="note"', html)

        for sources in ([{"synthetic": False}], [{}], []):
            with self.subTest(sources=sources):
                non_synthetic = deepcopy(report_source)
                non_synthetic["blocks"][0]["artifact"]["evidence"]["sources"] = sources
                html = build_report_html(
                    non_synthetic, "landscape", APPROVED_AT, "2" * 64
                )
                self.assertNotIn(warning, html)

    def test_aggregate_artifact_settings_are_safe_and_malformed_content_falls_back(self):
        report_source = source()
        artifact_block = deepcopy(report_source["blocks"][1])
        artifact_block.update({"block_id": "artifact-whole", "type": "artifact", "w": 12})
        report_source["blocks"] = [artifact_block]

        artifact_block["content"] = json.dumps({
            "presentationMode": "summary",
            "visibleViews": ["summary", "summary", "unknown"],
        })
        summary_html = build_report_html(
            report_source,
            "portrait",
            APPROVED_AT,
            canonical_source_checksum(report_source, "portrait"),
        )
        self.assertIn('data-visible-views="summary"', summary_html)
        self.assertNotIn("<svg", summary_html)
        self.assertNotIn("<table>", summary_html)

        for malformed in ("{not-json", "[]", '{"presentationMode":{},"visibleViews":"all"}'):
            with self.subTest(content=malformed):
                artifact_block["content"] = malformed
                html = build_report_html(
                    report_source,
                    "portrait",
                    APPROVED_AT,
                    canonical_source_checksum(report_source, "portrait"),
                )
                self.assertIn("artifact-bundle--standard", html)
                self.assertIn('data-visible-views="summary kpi chart table"', html)
                self.assertIn("<svg", html)
                self.assertIn("<table>", html)

    async def test_render_failure_never_calls_atomic_approval(self):
        class BrokenHTML:
            def __init__(self, **kwargs):
                pass

            def write_pdf(self, **kwargs):
                raise RuntimeError("renderer unavailable")

        repository = _Repository(source())
        with patch.dict(sys.modules, {"weasyprint": SimpleNamespace(HTML=BrokenHTML)}):
            with self.assertRaises(ReportDocumentRenderError):
                await approve_report_document(
                    repository,
                    str(source()["definition_id"]),
                    3,
                    APPROVED_AT,
                    "portrait",
                )
        self.assertIsNone(repository.finalized)

    async def test_approval_cannot_override_saved_orientation(self):
        report_source = source()
        report_source["orientation"] = "landscape"
        report_source["currency_display_unit"] = "million"
        repository = _Repository(report_source)

        with self.assertRaisesRegex(ValueError, "match the saved Report draft"):
            await approve_report_document(
                repository,
                str(report_source["definition_id"]),
                3,
                APPROVED_AT,
                "portrait",
            )

        self.assertIsNone(repository.finalized)

    async def test_success_passes_pdf_and_source_hash_to_atomic_repository_method(self):
        class FakeHTML:
            def __init__(self, **kwargs):
                self.html = kwargs["string"]

            def write_pdf(self, **kwargs):
                self.options = kwargs
                return b"%PDF-1.7\nfixture"

        report_source = source()
        repository = _Repository(report_source)
        with patch.dict(sys.modules, {"weasyprint": SimpleNamespace(HTML=FakeHTML)}):
            result = await approve_report_document(
                repository,
                str(report_source["definition_id"]),
                3,
                APPROVED_AT,
                "portrait",
            )

        self.assertEqual("approved", result)
        self.assertEqual(
            canonical_source_checksum(report_source, "portrait"),
            repository.finalized[5],
        )
        self.assertEqual("auto", repository.finalized[4])
        self.assertTrue(repository.finalized[7].startswith(b"%PDF-"))

    async def test_http_approval_creates_read_only_html_and_pdf_for_text_report(self):
        class FakeHTML:
            def __init__(self, **kwargs):
                pass

            def write_pdf(self, **kwargs):
                return b"%PDF-1.7\ncontract"

        definition_id = "00000000-0000-0000-0000-000000000010"
        repository = InMemoryReportRepository()
        repository.add_draft(
            ReportDefinitionVersion(
                definition_id,
                1,
                DefinitionStatus.DRAFT,
                "7월 영업 실적 보고서",
                (
                    ReportBlock(
                        "00000000-0000-0000-0000-000000000011",
                        "핵심 요약",
                        None,
                        12,
                        None,
                        BlockType.TEXT,
                        0,
                        0,
                        12,
                        3,
                        "매출이 증가했습니다.",
                    ),
                ),
                orientation="landscape",
                currency_display_unit="million",
            )
        )
        router = create_report_router(repository)
        request_context = RequestContext(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            role=Role.REPORT_ADMIN,
        )
        payload = ApproveReportVersionRequest(approved_at=APPROVED_AT)
        with patch.object(report_api, "_router", return_value=router), patch.dict(
            sys.modules, {"weasyprint": SimpleNamespace(HTML=FakeHTML)}
        ):
            approved = await report_api.approve_version(
                definition_id, 1, payload, request_context
            )
            metadata = await report_api.get_final_document(
                definition_id, 1, request_context
            )
            html = await report_api.get_final_html(definition_id, 1, request_context)
            pdf = await report_api.get_final_pdf(definition_id, 1, request_context)

        self.assertEqual("approved", approved["status"])
        self.assertEqual("landscape", approved["orientation"])
        self.assertEqual("million", approved["currency_display_unit"])
        self.assertEqual("landscape", metadata["orientation"])
        self.assertEqual("million", metadata["currency_display_unit"])
        self.assertEqual("weasyprint-69", metadata["renderer_version"])
        self.assertIn("7월 영업 실적 보고서", html.body.decode("utf-8"))
        self.assertIn('content="million"', html.body.decode("utf-8"))
        self.assertIn("immutable", html.headers["cache-control"])
        self.assertEqual("default-src 'none'; style-src 'unsafe-inline'", html.headers["content-security-policy"])
        self.assertEqual("application/pdf", pdf.media_type)
        self.assertIn("immutable", pdf.headers["cache-control"])
        self.assertTrue(pdf.body.startswith(b"%PDF-"))

    def test_additive_migration_and_repository_keep_insert_before_approval(self):
        migration = (
            ROOT / "app" / "backend" / "migrations" / "versions"
            / "20260814_21_report_documents.py"
        ).read_text(encoding="utf-8")
        repository = (
            ROOT / "app" / "backend" / "app" / "adapters"
            / "report_document_repository.py"
        ).read_text(encoding="utf-8")

        self.assertIn('revision = "20260814_21"', migration)
        self.assertIn('down_revision = "20260814_20"', migration)
        self.assertIn("CREATE TABLE report_v1.report_documents", migration)
        self.assertIn("report_document_immutable", migration)
        self.assertLess(
            repository.index("INSERT INTO report_v1.report_documents"),
            repository.index("UPDATE report_v1.report_definition_versions"),
        )
        self.assertIn("FOR UPDATE OF v", repository)
        self.assertIn("actual_checksum != expected_source_checksum", repository)


if __name__ == "__main__":
    unittest.main()
