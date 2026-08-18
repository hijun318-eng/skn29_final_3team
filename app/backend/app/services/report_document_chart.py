"""동결 artifact의 chart spec·metric 단위·유한 수치만으로 인쇄용 SVG를 만들고 혼합 단위·빈 series·미지원 chart는 ReportDocumentRenderError로 거부한다."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Mapping

from .report_document_types import ReportDocumentRenderError
from .report_document_values import (
    CHART_COLORS,
    CHART_POINT_LIMIT,
    _evenly_sample,
    _finite_number,
    _format_currency,
    _format_value,
    _is_krw_unit,
    _label_without_unit,
    _metric_labels,
    _metric_units,
    _unit_label,
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
    if valid_row_count > CHART_POINT_LIMIT:
        points = _evenly_sample(points, CHART_POINT_LIMIT)
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
                f'style="fill:none;stroke:{CHART_COLORS[series_index % len(CHART_COLORS)]};'
                'stroke-width:4;stroke-linecap:round;stroke-linejoin:round"/>'
                + "".join(
                    f'<circle class="series-mark series-{series_index}" '
                    f'cx="{left + (index + .5) * chart_width / len(points):.1f}" '
                    f'cy="{value_y(row_values[field]):.1f}" r="4" '
                    f'style="fill:{CHART_COLORS[series_index % len(CHART_COLORS)]}"/>'
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
            f'style="fill:{CHART_COLORS[series_index % len(CHART_COLORS)]}"/>'
            for index, (_, row_values) in enumerate(points)
            for series_index, field in enumerate(y_fields)
        )
    legend = (
        '<div class="chart-legend" aria-label="차트 범례">'
        + "".join(
            f'<span><i style="background:{CHART_COLORS[index % len(CHART_COLORS)]}"></i>'
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
