"""artifact evidence의 metric 단위와 유한 수치를 HTML escape, 통화 scale, 균등 sampling 규칙으로 표·KPI 텍스트에 안전하게 표현한다."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Mapping


ARTIFACT_PRESENTATION_MODES = frozenset({"summary", "standard", "detail"})
ARTIFACT_VIEWS = ("summary", "kpi", "chart", "table")
CURRENCY_UNITS = {
    "one": (1, "원"),
    "thousand": (1_000, "천 원"),
    "million": (1_000_000, "백만 원"),
    "hundredMillion": (100_000_000, "억 원"),
    "billion": (1_000_000_000, "십억 원"),
}
CURRENCY_DISPLAY_UNITS = frozenset({"auto", *CURRENCY_UNITS})
NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
CHART_POINT_LIMIT = 12
TABLE_ROW_LIMIT = 12
CHART_COLORS = ("#1c69d4", "#16a36a", "#f28c28", "#7557d6", "#d94f70", "#168a9d")
LAYOUT_PAGE_ROWS = {"portrait": 30, "landscape": 18}
SYNTHETIC_WARNING = "합성 데모 데이터 · 실제 호텔 운영 성과가 아님"


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
        elif isinstance(value, str) and NUMERIC_TEXT.fullmatch(value.strip()):
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
    if requested not in CURRENCY_DISPLAY_UNITS:
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
    divisor, _ = CURRENCY_UNITS[display_unit]
    scaled = number / divisor
    decimals = 0 if display_unit == "one" else 1
    rendered = f"{scaled:,.{decimals}f}"
    return rendered.rstrip("0").rstrip(".") if decimals else rendered


def _unit_label(unit: object, currency_display_unit: str) -> str:
    if _is_krw_unit(unit):
        return CURRENCY_UNITS[currency_display_unit][1]
    return str(unit or "")


def _label_without_unit(label: str, unit: object) -> str:
    if not unit:
        return label
    suffix = r"(?:KRW|원|천 원|백만 원|억 원|십억 원|₩)" if _is_krw_unit(unit) else re.escape(str(unit))
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
    rendered_rows = _evenly_sample(rows, TABLE_ROW_LIMIT)
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
