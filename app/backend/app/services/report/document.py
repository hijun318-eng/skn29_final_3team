"""A4 인쇄용 HTML 문서 조립, WeasyPrint 기반 PDF/A-3u 렌더링 및 승인(Approval) 트랜잭션 서비스 모듈.

[핵심 목적]
1. `build_report_html`: 보고서 드래프트 소스로부터 표준 CSS가 포함된 고품질 인쇄용 A4 HTML 문서 조립
2. `render_report_document`: WeasyPrint 엔진을 통한 안전한 PDF/A-3u 문서 렌더링 (외부 URL fetch 차단으로 보안 보장)
3. `approve_report_document`: 보고서 승인 시 HTML/PDF를 원자적으로 생성하고 리포지토리에 영속화
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from html import escape
from inspect import isawaitable
from typing import Any, Mapping

from app.services.report.chart import _chart_svg
from app.services.report.layout import (
    _artifact_html,
    _artifact_is_synthetic,
    _artifact_settings,
    _block_chart_type,
    _block_html,
    _layout_page_html,
    _paginate_layout,
    _report_is_synthetic,
)
from app.services.report.types import (
    RenderedReportDocument,
    ReportDocumentRenderError,
    canonical_source_checksum,
)
from app.services.report.values import (
    ARTIFACT_PRESENTATION_MODES as _ARTIFACT_PRESENTATION_MODES,
    ARTIFACT_VIEWS as _ARTIFACT_VIEWS,
    CHART_COLORS as _CHART_COLORS,
    CHART_POINT_LIMIT as _CHART_POINT_LIMIT,
    CURRENCY_DISPLAY_UNITS as _CURRENCY_DISPLAY_UNITS,
    CURRENCY_UNITS as _CURRENCY_UNITS,
    LAYOUT_PAGE_ROWS as _LAYOUT_PAGE_ROWS,
    NUMERIC_TEXT as _NUMERIC_TEXT,
    SYNTHETIC_WARNING as _SYNTHETIC_WARNING,
    TABLE_ROW_LIMIT as _TABLE_ROW_LIMIT,
    _column_label,
    _currency_values,
    _evenly_sample,
    _finite_number,
    _format_currency,
    _format_value,
    _is_krw_unit,
    _is_numeric,
    _label_without_unit,
    _markdown_text,
    _metric_labels,
    _metric_units,
    _metrics_html,
    _resolve_currency_display_unit,
    _table_html,
    _unit_label,
)


def build_report_html(
    source: Mapping[str, Any],
    orientation: str,
    approved_at: datetime,
    source_checksum: str,
) -> str:
    """저장된 드래프트 소스로부터 A4 인쇄용 표준 HTML 문서를 생성합니다."""
    if orientation not in {"portrait", "landscape"}:
        raise ValueError("orientation must be portrait or landscape")
    saved_orientation = str(source.get("orientation") or orientation)
    if saved_orientation != orientation:
        raise ValueError("orientation must match the saved Report draft")
    requested_currency_display_unit = str(source.get("currency_display_unit") or "auto")
    currency_display_unit = _resolve_currency_display_unit(source)
    title = escape(str(source["title"]))
    timestamp = escape(approved_at.isoformat())
    page_size = "A4 portrait" if orientation == "portrait" else "A4 landscape"
    currency_label = escape(_CURRENCY_UNITS[currency_display_unit][1])
    synthetic_warning = (
        f'<p class="synthetic-report-warning" role="note">{_SYNTHETIC_WARNING}</p>'
        if _report_is_synthetic(source) else ""
    )
    layout_pages = _paginate_layout(source.get("blocks", ()), orientation)
    page_count = len(layout_pages)
    pages = "".join(
        f'<section class="report-layout-page" data-layout-page="{page_index}" '
        f'data-layout-page-count="{page_count}" data-layout-row-limit="{_LAYOUT_PAGE_ROWS[orientation]}">'
        f'<header class="report-cover"><small>ANSWERVICE · 확정 보고서</small><h1>{title}</h1>'
        f'<p>Report revision {int(source["version"])} · {timestamp} · '
        f'보고서 구성 {page_index}/{page_count} · 금액 단위 {currency_label}</p>'
        f'{synthetic_warning}</header>'
        '<main class="report-grid" data-layout-height-policy="minimum-flow">'
        + _layout_page_html(page_blocks, currency_display_unit, orientation)
        + "</main></section>"
        for page_index, page_blocks in enumerate(layout_pages, start=1)
    )
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<meta name="author" content="ANSWERVICE"><meta name="generator" content="ANSWERVICE Report PDF v1">
<meta name="dcterms.created" content="{timestamp}"><meta name="dcterms.modified" content="{timestamp}">
<meta name="answervice-source-checksum" content="{source_checksum}">
<meta name="answervice-orientation" content="{orientation}">
<meta name="answervice-currency-display-unit" content="{escape(requested_currency_display_unit)}">
<meta name="answervice-resolved-currency-display-unit" content="{currency_display_unit}">
<meta name="answervice-layout-height-policy" content="minimum-flow">
<style>
@page {{ size: {page_size}; margin: 13mm 14mm 12mm; @top-left {{ content: "ANSWERVICE"; color:#1c69d4; font-weight:800; font-size:8pt; }} @bottom-left {{ content: "확정 {timestamp}"; color:#66758b; font-size:7pt; }} @bottom-right {{ content: counter(page) " / " counter(pages); color:#1c69d4; font-size:7pt; font-weight:700; }} }}
* {{ box-sizing:border-box; }} html,body {{ margin:0; color:#162238; background:#fff; font-family:"Noto Sans CJK KR","Noto Sans KR",sans-serif; font-size:9pt; line-height:1.55; }}
.report-layout-page {{ --report-grid-row:{'6mm' if orientation == 'portrait' else '7mm'}; border-top:1.5mm solid #1c69d4; }} .report-layout-page + .report-layout-page {{ break-before:page; }} .report-cover {{ padding:7mm 0 6mm; border-bottom:.3mm solid #d9e2ee; }}
.report-cover small {{ color:#1c69d4; font-size:7.5pt; font-weight:800; letter-spacing:.12em; }} .report-cover h1 {{ margin:2mm 0 1mm; color:#0b1f44; font-size:24pt; line-height:1.2; letter-spacing:-.03em; }}
.report-cover p {{ margin:0; color:#66758b; font-size:8pt; }} .synthetic-report-warning,.synthetic-artifact-warning {{ padding:2mm 2.5mm; color:#7a4e00; border:.2mm solid #edcf8f; border-radius:1.5mm; background:#fff8e7; font-size:7.5pt; font-weight:750; }} .report-cover .synthetic-report-warning {{ margin:3mm 0 0; }} .synthetic-artifact-warning {{ margin:0 0 3mm; }} .report-grid {{ margin-top:5mm; display:grid; gap:1.5mm; }} .report-layout-row {{ min-width:0; display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:1.5mm; align-items:stretch; break-inside:auto; }}
.report-block {{ min-width:0; min-height:0; overflow:visible; padding:4.5mm; border:.25mm solid #d9e2ee; border-radius:2.5mm; background:#fff; break-inside:avoid; }} .report-block--table,.report-block--artifact {{ break-inside:auto; }}
.report-block>header {{ margin-bottom:3mm; padding-bottom:2.5mm; border-bottom:.25mm solid #e5ebf3; }} .report-block>header span {{ color:#1c69d4; font-size:6.5pt; font-weight:800; letter-spacing:.1em; }} .report-block h2 {{ margin:.8mm 0 0; color:#0b1f44; font-size:12pt; line-height:1.3; }}
.block-content p {{ margin:0 0 2mm; }} .block-content h2,.block-content h3,.block-content h4 {{ color:#0b1f44; margin:3mm 0 1mm; }} .block-content ul {{ margin:1mm 0; padding-left:5mm; }} .empty {{ color:#7d899a; }}
.metrics {{ margin-bottom:3mm; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:2mm; }} .metrics>div {{ padding:2.5mm; border-radius:2mm; background:#eef5ff; }} .metrics span,.metrics strong {{ display:block; }} .metrics span {{ color:#66758b; font-size:6.5pt; }} .metrics strong {{ margin-top:1mm; color:#0b3c91; font-size:13pt; }} .metrics small {{ font-size:7pt; font-weight:600; }}
.artifact-bundle {{ display:grid; gap:3mm; }} .artifact-section {{ min-width:0; padding:3mm; border:.2mm solid #e2e9f2; border-radius:2mm; background:#fbfdff; break-inside:avoid; }} .artifact-section>h3 {{ margin:0 0 2mm; color:#233a5b; font-size:9pt; }} .artifact-summary {{ border-left:.8mm solid #1c69d4; }} .artifact-kpis .metrics {{ margin-bottom:0; }} .artifact-bundle--summary .artifact-section {{ padding:2.5mm; }} .artifact-bundle--detail {{ gap:4mm; }}
.table-wrap {{ width:100%; overflow:hidden; }} table {{ width:100%; border-collapse:collapse; font-size:7.5pt; }} thead {{ display:table-header-group; }} th,td {{ padding:2mm 2.4mm; border-bottom:.2mm solid #dde5ef; text-align:left; overflow-wrap:anywhere; }} th {{ color:#405169; background:#eff4fa; font-weight:750; }} tbody tr:nth-child(even) td {{ background:#f8fafc; }}
.chart-sample-note,.table-sample-note,.chart-fallback-note {{ margin:0 0 2mm; padding:1.5mm 2mm; border-radius:1.5mm; background:#f2f6fb; color:#526781; font-size:7pt; }} .chart-fallback-note {{ border-left:.7mm solid #f28c28; background:#fff7ed; color:#70451a; }} .chart-legend {{ margin:0 0 1.5mm; display:flex; flex-wrap:wrap; gap:1.5mm 4mm; color:#405169; font-size:7pt; }} .chart-legend span {{ display:inline-flex; align-items:center; gap:1.2mm; }} .chart-legend i {{ width:2.2mm; height:2.2mm; flex:0 0 auto; border-radius:.7mm; }} .report-chart {{ width:100%; height:auto; color:#5d6b7d; }} .report-chart .axis {{ stroke:#aebbc9; stroke-width:1; }} .report-chart text {{ fill:#66758b; font:11px "Noto Sans CJK KR",sans-serif; }}
@media screen {{ html {{ background:#edf2f8; }} body {{ background:transparent; }} .report-layout-page {{ width:{'210mm' if orientation == 'portrait' else '297mm'}; min-height:{'297mm' if orientation == 'portrait' else '210mm'}; margin:20px auto; padding:13mm 14mm 12mm; background:#fff; box-shadow:0 20px 60px rgba(11,31,68,.18); }} }}
</style></head><body>{pages}</body></html>'''


def _deny_external_url(url: str, *args: object, **kwargs: object) -> object:
    """PDF 렌더링 중 외부 네트워크 URL 리소스 요청을 차단하여 SSRF를 방지합니다."""
    raise ReportDocumentRenderError(f"Report PDF 렌더링 중 외부 리소스 접근이 차단되었습니다: {url}")


def render_report_document(
    source: Mapping[str, Any],
    orientation: str,
    approved_at: datetime,
) -> RenderedReportDocument:
    """보고서 소스를 HTML 및 PDF/A-3u 바이너리로 렌더링합니다."""
    checksum = canonical_source_checksum(source, orientation)
    html = build_report_html(source, orientation, approved_at, checksum)
    try:
        from weasyprint import HTML

        pdf = HTML(string=html, url_fetcher=_deny_external_url).write_pdf(
            pdf_identifier=bytes.fromhex(checksum),
            pdf_variant="pdf/a-3u",
            pdf_tags=True,
        )
    except ReportDocumentRenderError:
        raise
    except Exception as error:
        raise ReportDocumentRenderError("Report PDF 렌더링에 실패했습니다.") from error
    if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF-"):
        raise ReportDocumentRenderError("Report 렌더러가 올바른 PDF 바이너리를 반환하지 않았습니다.")
    return RenderedReportDocument(checksum, html, pdf)


async def approve_report_document(
    repository: object,
    definition_id: str,
    version: int,
    approved_at: datetime,
    orientation: str | None,
):
    """보고서 드래프트를 렌더링하고 승인 상태로 전이하여 원자적으로 저장합니다."""
    source_result = repository.get_document_source(definition_id, version)
    source = await source_result if isawaitable(source_result) else source_result
    saved_orientation = str(source.get("orientation") or orientation or "portrait")
    if orientation is not None and orientation != saved_orientation:
        raise ValueError("Approval orientation must match the saved Report draft")
    currency_display_unit = str(source.get("currency_display_unit") or "auto")
    rendered = await asyncio.to_thread(
        render_report_document, source, saved_orientation, approved_at
    )
    approved = repository.approve_with_document(
        definition_id,
        version,
        approved_at,
        saved_orientation,
        currency_display_unit,
        rendered.source_checksum,
        rendered.html,
        rendered.pdf,
    )
    return await approved if isawaitable(approved) else approved
