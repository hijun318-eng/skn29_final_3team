"""보고서 그리드 배치, A4 페이지 분할(Pagination) 및 블록 HTML 조립 레이아웃 모듈.

[핵심 목적]
12열 반응형 CSS Grid 시스템을 기반으로:
1. 페이지 방향(Portrait/Landscape)에 따른 페이지 높이 상한(각각 30행/18행) 기반의 결정론적 페이지 분할(`_paginate_layout`)
2. 개별 블록(Text, Artifact Bundle, Chart, Table)의 HTML 및 메타데이터 렌더링
3. 합성 데모 데이터(Synthetic Provenance) 경고 배너 주입
을 수행합니다.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any, Mapping

from app.services.report.chart import _chart_svg
from app.services.report.values import (
    ARTIFACT_PRESENTATION_MODES,
    ARTIFACT_VIEWS,
    LAYOUT_PAGE_ROWS,
    SYNTHETIC_WARNING,
    _markdown_text,
    _metrics_html,
    _table_html,
)


def _artifact_settings(content: object) -> tuple[str, tuple[str, ...]]:
    """블록 content로부터 프레젠테이션 모드 및 노출할 뷰 목록을 파싱합니다."""
    try:
        settings = json.loads(content) if isinstance(content, str) else {}
    except (TypeError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    mode = settings.get("presentationMode")
    if not isinstance(mode, str) or mode not in ARTIFACT_PRESENTATION_MODES:
        mode = "standard"
    requested = settings.get("visibleViews")
    if not isinstance(requested, list):
        return mode, ARTIFACT_VIEWS
    visible = tuple(dict.fromkeys(view for view in requested if view in ARTIFACT_VIEWS))
    return mode, visible or ARTIFACT_VIEWS


def _block_chart_type(block: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    default = str((artifact.get("chart_spec") or {}).get("chart_type") or "bar")
    try:
        settings = json.loads(block.get("content")) if isinstance(block.get("content"), str) else {}
    except (TypeError, ValueError):
        settings = {}
    selected = settings.get("chartType") if isinstance(settings, dict) else None
    return selected if isinstance(selected, str) and selected.strip() else default


def _artifact_is_synthetic(artifact: Mapping[str, Any]) -> bool:
    evidence = artifact.get("evidence")
    sources = evidence.get("sources") if isinstance(evidence, Mapping) else None
    return isinstance(sources, (list, tuple)) and any(
        isinstance(source, Mapping) and source.get("synthetic") is True
        for source in sources
    )


def _report_is_synthetic(source: Mapping[str, Any]) -> bool:
    return any(
        isinstance(block, Mapping)
        and isinstance(block.get("artifact"), Mapping)
        and _artifact_is_synthetic(block["artifact"])
        for block in source.get("blocks", ())
    )


def _artifact_html(
    block: Mapping[str, Any],
    artifact: Mapping[str, Any],
    currency_display_unit: str,
) -> str:
    mode, views = _artifact_settings(block.get("content"))
    metric_limit = {"summary": 2, "standard": 4, "detail": 6}[mode]
    sections: list[str] = []
    if "summary" in views:
        sections.append(
            '<section class="artifact-section artifact-summary"><h3>분석 요약</h3>'
            + _markdown_text(str(artifact.get("narrative") or ""))
            + "</section>"
        )
    if "kpi" in views:
        metrics = _metrics_html(artifact, currency_display_unit, limit=metric_limit)
        sections.append(
            '<section class="artifact-section artifact-kpis"><h3>주요 KPI</h3>'
            + (metrics or '<p class="empty">대표 KPI가 제공되지 않았습니다.</p>')
            + "</section>"
        )
    if "chart" in views:
        sections.append(
            '<section class="artifact-section artifact-chart"><h3>변화와 구성</h3>'
            + _chart_svg(artifact, currency_display_unit, _block_chart_type(block, artifact))
            + "</section>"
        )
    if "table" in views:
        sections.append(
            '<section class="artifact-section artifact-table"><h3>상세 데이터</h3>'
            + _table_html(artifact, currency_display_unit)
            + "</section>"
        )
    visible = " ".join(views)
    return (
        f'<div class="artifact-bundle artifact-bundle--{mode}" '
        f'data-visible-views="{visible}">' + "".join(sections) + "</div>"
    )


def _paginate_layout(
    blocks: object,
    orientation: str,
) -> list[list[dict[str, Any]]]:
    """블록 좌표와 명시적 page_break를 A4 페이지 목록으로 결정론적으로 분할합니다."""
    row_limit = LAYOUT_PAGE_ROWS[orientation]
    ordered = sorted(
        enumerate(blocks if isinstance(blocks, (list, tuple)) else ()),
        key=lambda item: (
            int(item[1].get("y") or 0),
            int(item[1].get("x") or 0),
            item[0],
        ),
    )
    rows: list[tuple[int, list[Mapping[str, Any]]]] = []
    for _, block in ordered:
        source_y = max(0, int(block.get("y") or 0))
        if rows and rows[-1][0] == source_y:
            rows[-1][1].append(block)
        else:
            rows.append((source_y, [block]))

    pages: list[list[dict[str, Any]]] = []
    page: list[dict[str, Any]] = []
    cursor_y = 0
    for source_y, row_blocks in rows:
        if any(str(block.get("type")) == "page_break" for block in row_blocks):
            pages.append(page)
            page = []
            cursor_y = 0
            continue
        row_height = min(
            row_limit,
            max(max(1, int(block.get("h") or 1)) for block in row_blocks),
        )
        if page and cursor_y + row_height > row_limit:
            pages.append(page)
            page = []
            cursor_y = 0
        for block in row_blocks:
            placed = dict(block)
            placed["_layout_y"] = cursor_y
            placed["_layout_h"] = row_height
            placed["_source_y"] = source_y
            page.append(placed)
        cursor_y += row_height
    if page or not pages or (rows and any(str(block.get("type")) == "page_break" for block in rows[-1][1])):
        pages.append(page)
    return pages


def _block_html(block: Mapping[str, Any], currency_display_unit: str) -> str:
    """단일 보고서 블록의 HTML 엘리먼트를 조립합니다."""
    block_type = str(block["type"])
    if block_type == "page_break":
        return ""
    artifact = block.get("artifact") or {}
    if block_type == "text":
        content = _markdown_text(str(block.get("content") or ""))
    elif block_type == "artifact":
        content = _artifact_html(block, artifact, currency_display_unit)
    elif block_type == "chart":
        content = (
            _metrics_html(artifact, currency_display_unit)
            + _chart_svg(artifact, currency_display_unit, _block_chart_type(block, artifact))
        )
    else:
        content = (
            _metrics_html(artifact, currency_display_unit)
            + _table_html(artifact, currency_display_unit)
        )
    if artifact and _artifact_is_synthetic(artifact):
        content = (
            f'<p class="synthetic-artifact-warning" role="note">{SYNTHETIC_WARNING}</p>'
            + content
        )
    width = min(12, max(1, int(block.get("w") or 12)))
    column = min(12 - width, max(0, int(block.get("x") or 0)))
    row = max(0, int(block.get("_layout_y", block.get("y")) or 0))
    height = max(1, int(block.get("_layout_h", block.get("h")) or 1))
    source_y = max(0, int(block.get("_source_y", block.get("y")) or 0))
    return (
        f'<article class="report-block report-block--{escape(block_type)}" '
        f'data-block-id="{escape(str(block["block_id"]))}" '
        f'data-layout-x="{column}" data-layout-y="{row}" data-layout-source-y="{source_y}" '
        f'data-layout-w="{width}" data-layout-h="{height}" '
        f'style="grid-column:{column + 1} / span {width};grid-row:1;'
        f'--report-min-rows:{height}">'
        f'<header><span>{escape(block_type.upper())}</span><h2>{escape(str(block["title"]))}</h2></header>'
        f'<div class="block-content">{content}</div></article>'
    )


def _layout_page_html(
    page_blocks: list[dict[str, Any]],
    currency_display_unit: str,
    orientation: str,
) -> str:
    """한 페이지에 배치된 블록 행들의 HTML을 조립합니다."""
    row_mm = 6 if orientation == "portrait" else 7
    rows: list[list[dict[str, Any]]] = []
    for block in page_blocks:
        if rows and rows[-1][0]["_layout_y"] == block["_layout_y"]:
            rows[-1].append(block)
        else:
            rows.append([block])
    return "".join(
        f'<section class="report-layout-row" data-layout-y="{row[0]["_layout_y"]}" '
        f'data-layout-h="{row[0]["_layout_h"]}" '
        f'style="min-height:{row[0]["_layout_h"] * row_mm}mm">'
        + "".join(_block_html(block, currency_display_unit) for block in row)
        + "</section>"
        for row in rows
    )
