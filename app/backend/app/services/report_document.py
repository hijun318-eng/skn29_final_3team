from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Mapping


_ARTIFACT_PRESENTATION_MODES = frozenset({"summary", "standard", "detail"})
_ARTIFACT_VIEWS = ("summary", "kpi", "chart", "table")
_CURRENCY_UNITS = {
    "one": (1, "원"),
    "thousand": (1_000, "천 원"),
    "million": (1_000_000, "백만 원"),
    "hundredMillion": (100_000_000, "억 원"),
    "billion": (1_000_000_000, "십억 원"),
}
_CURRENCY_DISPLAY_UNITS = frozenset({"auto", *_CURRENCY_UNITS})
_NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_CHART_POINT_LIMIT = 12
_TABLE_ROW_LIMIT = 12
_CHART_COLORS = ("#1c69d4", "#16a36a", "#f28c28", "#7557d6", "#d94f70", "#168a9d")
_LAYOUT_PAGE_ROWS = {"portrait": 30, "landscape": 18}
_SYNTHETIC_WARNING = "합성 데모 데이터 · 실제 호텔 운영 성과가 아님"


class ReportDocumentRenderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RenderedReportDocument:
    source_checksum: str
    html: str
    pdf: bytes

    @property
    def html_checksum(self) -> str:
        return hashlib.sha256(self.html.encode("utf-8")).hexdigest()

    @property
    def pdf_checksum(self) -> str:
        return hashlib.sha256(self.pdf).hexdigest()


def canonical_source_checksum(source: Mapping[str, Any], orientation: str) -> str:
    serialized = json.dumps(
        {"orientation": orientation, "source": source},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _format_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float, Decimal)):
            number = float(value)
        elif isinstance(value, str) and _NUMERIC_TEXT.fullmatch(value.strip()):
            number = float(Decimal(value.strip()))
        else:
            return None
    except (InvalidOperation, OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_numeric(value: object) -> bool:
    return _finite_number(value) is not None


def _evenly_sample(values: list[Any], limit: int) -> list[Any]:
    if len(values) <= limit:
        return values
    return [
        values[index * (len(values) - 1) // (limit - 1)]
        for index in range(limit)
    ]


def _is_krw_unit(unit: object) -> bool:
    normalized = re.sub(r"\s+", "", str(unit or "")).upper()
    return normalized in {"KRW", "원", "₩"}


def _metric_units(artifact: Mapping[str, Any]) -> dict[str, str]:
    units: dict[str, str] = {}
    metrics = (artifact.get("evidence") or {}).get("metric_values", ())
    for metric in metrics:
        field = metric.get("result_field")
        unit = metric.get("unit")
        if field and unit:
            units[str(field)] = str(unit)
    return units


def _metric_labels(artifact: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    metrics = (artifact.get("evidence") or {}).get("metric_values", ())
    for metric in metrics:
        field = metric.get("result_field")
        label = metric.get("label")
        if field and label:
            labels[str(field)] = _label_without_unit(str(label), metric.get("unit"))
    return labels


def _currency_values(source: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for block in source.get("blocks", ()):
        artifact = block.get("artifact") or {}
        metrics = (artifact.get("evidence") or {}).get("metric_values", ())
        for metric in metrics:
            value = _finite_number(metric.get("value"))
            if _is_krw_unit(metric.get("unit")) and value is not None:
                values.append(value)
        units = _metric_units(artifact)
        for row in (artifact.get("table") or {}).get("rows", ()):
            for field, unit in units.items():
                value = _finite_number(row.get(field))
                if _is_krw_unit(unit) and value is not None:
                    values.append(value)
    return values


def _resolve_currency_display_unit(source: Mapping[str, Any]) -> str:
    requested = str(source.get("currency_display_unit") or "auto")
    if requested not in _CURRENCY_DISPLAY_UNITS:
        raise ValueError("currency_display_unit is invalid")
    if requested != "auto":
        return requested
    maximum = max((abs(value) for value in _currency_values(source)), default=0)
    if maximum >= 100_000_000:
        return "hundredMillion"
    if maximum >= 1_000_000:
        return "million"
    if maximum >= 1_000:
        return "thousand"
    return "one"


def _format_currency(value: object, display_unit: str) -> str:
    if value is None:
        return "-"
    number = _finite_number(value)
    if number is None:
        return str(value)
    divisor, _ = _CURRENCY_UNITS[display_unit]
    scaled = number / divisor
    decimals = 0 if display_unit == "one" else 1
    rendered = f"{scaled:,.{decimals}f}"
    return rendered.rstrip("0").rstrip(".") if decimals else rendered


def _unit_label(unit: object, currency_display_unit: str) -> str:
    if _is_krw_unit(unit):
        return _CURRENCY_UNITS[currency_display_unit][1]
    return str(unit or "")


def _label_without_unit(label: str, unit: object) -> str:
    if not unit:
        return label
    suffix = r"(?:KRW|₩|원|천 원|백만 원|억 원|십억 원)" if _is_krw_unit(unit) else re.escape(str(unit))
    return re.sub(rf"\s*\({suffix}\)\s*$", "", label, flags=re.I)


def _column_label(column: str, unit: str, currency_display_unit: str) -> str:
    label = column
    display = _unit_label(unit, currency_display_unit)
    if not display:
        return label
    if _is_krw_unit(unit):
        label = _label_without_unit(label, unit)
    elif re.search(rf"\({re.escape(display)}\)\s*$", label, flags=re.I):
        return label
    return f"{label} ({display})"


def _markdown_text(value: str) -> str:
    parts: list[str] = []
    items: list[str] = []

    def finish_list() -> None:
        if items:
            parts.append("<ul>" + "".join(items) + "</ul>")
            items.clear()

    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            finish_list()
            continue
        if line.startswith("- ") or line.startswith("* "):
            items.append(f"<li>{escape(line[2:].strip())}</li>")
            continue
        finish_list()
        if line.startswith("### "):
            parts.append(f"<h4>{escape(line[4:])}</h4>")
        elif line.startswith("## "):
            parts.append(f"<h3>{escape(line[3:])}</h3>")
        elif line.startswith("# "):
            parts.append(f"<h2>{escape(line[2:])}</h2>")
        else:
            parts.append(f"<p>{escape(line)}</p>")
    finish_list()
    return "".join(parts) or '<p class="empty">내용이 없습니다.</p>'


def _artifact_settings(content: object) -> tuple[str, tuple[str, ...]]:
    """Read presentation hints without making saved content a hard contract."""
    try:
        settings = json.loads(content) if isinstance(content, str) else {}
    except (TypeError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    mode = settings.get("presentationMode")
    if not isinstance(mode, str) or mode not in _ARTIFACT_PRESENTATION_MODES:
        mode = "standard"
    requested = settings.get("visibleViews")
    if not isinstance(requested, list):
        return mode, _ARTIFACT_VIEWS
    visible = tuple(dict.fromkeys(view for view in requested if view in _ARTIFACT_VIEWS))
    return mode, visible or _ARTIFACT_VIEWS


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


def _table_html(
    artifact: Mapping[str, Any],
    currency_display_unit: str,
) -> str:
    table = artifact.get("table")
    if not table:
        return '<p class="empty">표 데이터가 없습니다.</p>'
    columns = [str(column) for column in table.get("columns", ())]
    rows = list(table.get("rows", ()))
    if not columns:
        return '<p class="empty">표 데이터가 없습니다.</p>'
    units = _metric_units(artifact)
    head = "".join(
        f"<th>{escape(_column_label(column, units.get(column, ''), currency_display_unit))}</th>"
        for column in columns
    )
    rendered_rows = _evenly_sample(rows, _TABLE_ROW_LIMIT)
    body = "".join(
        "<tr>" + "".join(
            "<td>" + escape(
                _format_currency(row.get(column), currency_display_unit)
                if _is_krw_unit(units.get(column))
                else _format_value(row.get(column))
            ) + "</td>"
            for column in columns
        ) + "</tr>"
        for row in rendered_rows
    )
    sample_note = (
        f'<p class="table-sample-note" role="note">전체 {len(rows)}행 중 '
        f'{len(rendered_rows)}개 대표 표본을 균등 추출해 표시했습니다(첫·마지막 포함). '
        "전체 원본은 이 보고서에 동결된 Artifact 버전에서 확인할 수 있습니다.</p>"
        if len(rendered_rows) != len(rows) else ""
    )
    return (
        sample_note + f'<div class="table-wrap" data-source-rows="{len(rows)}" '
        f'data-rendered-rows="{len(rendered_rows)}"><table><thead><tr>' + head
        + "</tr></thead><tbody>" + body + "</tbody></table></div>"
    )


def _chart_svg(
    artifact: Mapping[str, Any],
    currency_display_unit: str,
    chart_type_override: str | None = None,
) -> str:
    spec = artifact.get("chart_spec") or {}
    table = artifact.get("table") or {}
    rows = list(table.get("rows", ()))
    x_field = str(spec.get("x_field") or "")
    y_fields = list(dict.fromkeys(str(field) for field in spec.get("y_fields", ()) if str(field)))
    if not y_fields:
        return '<p class="empty">차트 계열 정보가 없습니다.</p>'

    units = _metric_units(artifact)
    series_labels = _metric_labels(artifact)
    unit_keys = {
        "KRW" if _is_krw_unit(units.get(field))
        else re.sub(r"\s+", "", units.get(field, "")).upper()
        for field in y_fields
    }
    if len(unit_keys) > 1:
        raise ReportDocumentRenderError(
            "PDF chart series must use one shared unit; mixed or missing units: "
            + ", ".join(y_fields)
        )
    raw_unit = units.get(y_fields[0], "")
    display_unit = _unit_label(raw_unit, currency_display_unit)

    missing_fields = [
        field for field in y_fields
        if not any(_finite_number(row.get(field)) is not None for row in rows)
    ]
    if missing_fields:
        raise ReportDocumentRenderError(
            "PDF chart series has no finite numeric values: " + ", ".join(missing_fields)
        )

    points: list[tuple[str, dict[str, float]]] = []
    for row in rows:
        values = {field: _finite_number(row.get(field)) for field in y_fields}
        if all(value is not None for value in values.values()):
            points.append((str(row.get(x_field, "")), values))
    if not points:
        raise ReportDocumentRenderError(
            "PDF chart has no row with finite values for every series: " + ", ".join(y_fields)
        )

    valid_row_count = len(points)
    if valid_row_count > _CHART_POINT_LIMIT:
        points = _evenly_sample(points, _CHART_POINT_LIMIT)
        sample_note = (
            f'<p class="chart-sample-note" role="note">전체 {len(rows)}행의 모든 계열이 유효한 '
            f'{valid_row_count}개 행 중 {len(points)}개 대표 표본을 균등 추출해 표시했습니다'
            "(첫·마지막 포함).</p>"
        )
    elif valid_row_count != len(rows):
        sample_note = (
            f'<p class="chart-sample-note" role="note">전체 {len(rows)}행 중 모든 계열에 유효한 '
            f'유한 수치가 있는 {valid_row_count}개 행만 표시했습니다.</p>'
        )
    else:
        sample_note = ""

    original_chart_type = str(chart_type_override or spec.get("chart_type") or "bar").strip().lower()
    if original_chart_type in {"line", "bar"}:
        rendered_chart_type = original_chart_type
        fallback_note = ""
    elif original_chart_type == "area":
        rendered_chart_type = "line"
        fallback_note = (
            '<p class="chart-fallback-note" role="note">PDF 호환 보기: 영역 차트를 '
            "모든 계열을 보존하는 선형 차트로 표시했습니다.</p>"
        )
    elif original_chart_type in {"horizontal-bar", "stacked-bar", "donut", "pie"}:
        rendered_chart_type = "bar"
        fallback_note = (
            f'<p class="chart-fallback-note" role="note">PDF 호환 보기: '
            f'{escape(original_chart_type)} 차트를 모든 계열과 값을 보존하는 묶은 막대 차트로 '
            "표시했습니다.</p>"
        )
    else:
        raise ReportDocumentRenderError(
            f"PDF renderer does not support chart_type: {original_chart_type or '(empty)'}"
        )

    width, height = 720, 285
    left, top, bottom = 68, 28, 62
    chart_width, chart_height = width - left - 18, height - top - bottom
    values = [value for _, row_values in points for value in row_values.values()]
    lower = min(0.0, min(values))
    upper = max(0.0, max(values))
    if lower == upper:
        upper = lower + 1.0
    value_range = upper - lower

    def value_y(value: float) -> float:
        return top + chart_height * (upper - value) / value_range

    baseline_y = value_y(0.0)
    value_label = (
        lambda value: _format_currency(value, currency_display_unit)
        if _is_krw_unit(raw_unit)
        else _format_value(value)
    )
    y_labels = (
        f'<text x="{left - 8}" y="{top + 4}" text-anchor="end">'
        f'{escape(value_label(upper))}</text>'
        f'<text x="{left - 8}" y="{top + chart_height + 4}" text-anchor="end">'
        f'{escape(value_label(lower))}</text>'
    )
    unit_label = (
        f'<text class="unit-label" x="{left}" y="15">단위: {escape(display_unit)}</text>'
        if display_unit else ""
    )
    labels = "".join(
        (
            f'<text x="{left + (index + .5) * chart_width / len(points):.1f}" '
            f'y="{height - bottom + 18}" text-anchor="middle">{escape(label)}</text>'
            if len(points) <= 6 else
            f'<text x="{left + (index + .5) * chart_width / len(points):.1f}" '
            f'y="{height - bottom + 16}" text-anchor="end" '
            f'transform="rotate(-28 {left + (index + .5) * chart_width / len(points):.1f} '
            f'{height - bottom + 16})">{escape(label)}</text>'
        )
        for index, (label, _) in enumerate(points)
    )
    if rendered_chart_type == "line":
        shapes = "".join(
            (
                f'<polyline class="series-mark series-{series_index}" '
                f'points="{" ".join(f"{left + (index + .5) * chart_width / len(points):.1f},{value_y(row_values[field]):.1f}" for index, (_, row_values) in enumerate(points))}" '
                f'style="fill:none;stroke:{_CHART_COLORS[series_index % len(_CHART_COLORS)]};'
                'stroke-width:4;stroke-linecap:round;stroke-linejoin:round"/>'
                + "".join(
                    f'<circle class="series-mark series-{series_index}" '
                    f'cx="{left + (index + .5) * chart_width / len(points):.1f}" '
                    f'cy="{value_y(row_values[field]):.1f}" r="4" '
                    f'style="fill:{_CHART_COLORS[series_index % len(_CHART_COLORS)]}"/>'
                    for index, (_, row_values) in enumerate(points)
                )
            )
            for series_index, field in enumerate(y_fields)
        )
    else:
        slot = chart_width / len(points)
        group_width = slot * .74
        bar_width = max(1.0, group_width / len(y_fields) - 1.5)
        shapes = "".join(
            f'<rect class="series-mark series-{series_index}" '
            f'x="{left + index * slot + (slot - group_width) / 2 + series_index * (group_width / len(y_fields)):.1f}" '
            f'y="{min(value_y(row_values[field]), baseline_y):.1f}" '
            f'width="{bar_width:.1f}" '
            f'height="{abs(value_y(row_values[field]) - baseline_y):.1f}" rx="3" '
            f'style="fill:{_CHART_COLORS[series_index % len(_CHART_COLORS)]}"/>'
            for index, (_, row_values) in enumerate(points)
            for series_index, field in enumerate(y_fields)
        )
    legend = (
        '<div class="chart-legend" aria-label="차트 범례">'
        + "".join(
            f'<span><i style="background:{_CHART_COLORS[index % len(_CHART_COLORS)]}"></i>'
            f'{escape(series_labels.get(field, _label_without_unit(field, units.get(field))))}</span>'
            for index, field in enumerate(y_fields)
        )
        + "</div>"
    )
    aria_series = ", ".join(
        series_labels.get(field, _label_without_unit(field, units.get(field)))
        for field in y_fields
    )
    return (
        f'{fallback_note}{sample_note}{legend}'
        f'<svg class="report-chart" viewBox="0 0 {width} {height}" role="img" '
        f'data-chart-type-original="{escape(original_chart_type)}" '
        f'data-chart-type-rendered="{rendered_chart_type}" data-series-count="{len(y_fields)}" '
        f'data-source-rows="{len(rows)}" data-valid-points="{valid_row_count}" '
        f'data-rendered-points="{len(points)}" '
        f'data-valid-rows="{valid_row_count}" data-rendered-rows="{len(points)}" '
        f'aria-label="{escape(aria_series)} 차트{f", 단위 {escape(display_unit)}" if display_unit else ""}">'
        f'{unit_label}{y_labels}'
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" '
        f'y2="{top + chart_height}" stroke="#aebbc9" stroke-width="1"/>'
        f'<line class="axis" x1="{left}" y1="{baseline_y:.1f}" x2="{width - 18}" '
        f'y2="{baseline_y:.1f}" stroke="#aebbc9" stroke-width="1"/>'
        f'{shapes}<g class="labels">{labels}</g></svg>'
    )


def _metrics_html(
    artifact: Mapping[str, Any],
    currency_display_unit: str,
    *,
    limit: int = 4,
) -> str:
    metrics = list((artifact.get("evidence") or {}).get("metric_values", ()))[:limit]
    if not metrics:
        return ""
    return '<div class="metrics">' + "".join(
        '<div><span>' + escape(_label_without_unit(
            str(metric.get("label") or metric.get("result_field") or "지표"),
            metric.get("unit"),
        ))
        + "</span><strong>" + escape(
            _format_currency(metric.get("value"), currency_display_unit)
            if _is_krw_unit(metric.get("unit"))
            else _format_value(metric.get("value"))
        )
        + (
            f" <small>{escape(_unit_label(metric.get('unit'), currency_display_unit))}</small>"
            if metric.get("unit") else ""
        )
        + "</strong></div>"
        for metric in metrics
    ) + "</div>"


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
    row_limit = _LAYOUT_PAGE_ROWS[orientation]
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
    if page or not pages:
        pages.append(page)
    return pages


def _block_html(block: Mapping[str, Any], currency_display_unit: str) -> str:
    block_type = str(block["type"])
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
            f'<p class="synthetic-artifact-warning" role="note">{_SYNTHETIC_WARNING}</p>'
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


def build_report_html(
    source: Mapping[str, Any],
    orientation: str,
    approved_at: datetime,
    source_checksum: str,
) -> str:
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
    raise ReportDocumentRenderError(f"external resource is not allowed in Report PDF: {url}")


def render_report_document(
    source: Mapping[str, Any],
    orientation: str,
    approved_at: datetime,
) -> RenderedReportDocument:
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
        raise ReportDocumentRenderError("Report PDF rendering failed") from error
    if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF-"):
        raise ReportDocumentRenderError("Report renderer returned an invalid PDF")
    return RenderedReportDocument(checksum, html, pdf)


def approve_report_document(
    repository: object,
    definition_id: str,
    version: int,
    approved_at: datetime,
    orientation: str | None,
):
    source = repository.get_document_source(definition_id, version)
    saved_orientation = str(source.get("orientation") or orientation or "portrait")
    if orientation is not None and orientation != saved_orientation:
        raise ValueError("Approval orientation must match the saved Report draft")
    currency_display_unit = str(source.get("currency_display_unit") or "auto")
    rendered = render_report_document(source, saved_orientation, approved_at)
    return repository.approve_with_document(
        definition_id,
        version,
        approved_at,
        saved_orientation,
        currency_display_unit,
        rendered.source_checksum,
        rendered.html,
        rendered.pdf,
    )
