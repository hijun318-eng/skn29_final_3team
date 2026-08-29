"""Node 3 설명의 수치 근거를 채점하고 불일치 시 결정론적 요약을 만든다."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.context.builder import ContextMetric, ContextPackage
from app.services.context.display_metadata import (
    metric_display_label,
    metric_display_unit,
)
from app.services.analysis.evidence import _reduce_context_metric


_NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_UNSUPPORTED_INFERENCE = re.compile(
    r"(?:때문|원인|기인|영향으로|덕분|로\s*인해|추정|예상|전망|예측|권장|제안|"
    r"\bbecause\b|\bdue\s+to\b|\bdriven\s+by\b|\bcaused\s+by\b|"
    r"\blikely\b|\bsuggests?\b|\bforecast\w*\b|\brecommend\w*\b)",
    re.IGNORECASE,
)


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _numbers(text: str) -> tuple[Decimal, ...]:
    return tuple(
        value
        for token in _NUMBER.findall(text)
        if (value := _decimal(token)) is not None
    )


def _numeric_columns(rows: list[dict[str, Any]]) -> dict[str, tuple[Decimal, ...]]:
    if not rows:
        return {}
    result: dict[str, tuple[Decimal, ...]] = {}
    for name in rows[0]:
        values = tuple(
            value
            for row in rows
            if (value := _decimal(row.get(name))) is not None
        )
        if values and len(values) == len(rows):
            result[name] = values
    return result


def _derived_numbers(rows: list[dict[str, Any]]) -> set[Decimal]:
    derived: set[Decimal] = set()
    for values in _numeric_columns(rows).values():
        derived.update(values)
        derived.update({sum(values), min(values), max(values)})
        derived.add(sum(values) / Decimal(len(values)))
        derived.update(value * 100 for value in values if abs(value) <= 1)
    if rows:
        derived.add(Decimal(len(rows)))
    return derived


def _period_numbers(period: object) -> set[Decimal]:
    if not isinstance(period, dict):
        return set()
    result: set[Decimal] = set()
    for name in ("start", "end_exclusive"):
        raw = period.get(name)
        if not isinstance(raw, str):
            continue
        try:
            value = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        result.update({Decimal(value.year), Decimal(value.month), Decimal(value.day)})
    return result


def _snapshot_numbers(snapshot: object) -> set[Decimal]:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("cutoff"), str):
        return set()
    try:
        value = date.fromisoformat(str(snapshot["cutoff"])[:10])
    except ValueError:
        return set()
    return {Decimal(value.year), Decimal(value.month), Decimal(value.day)}


def explanation_is_grounded(
    summary: str,
    query: dict[str, Any],
    package: ContextPackage | None = None,
) -> bool:
    """설명의 모든 수치가 shaped rows의 값·결정론적 집계·기간에서 유도되는지 확인한다."""

    rows = query.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return False
    mentioned = _numbers(summary)
    result_numbers = _derived_numbers(rows)
    allowed = (
        result_numbers
        | _period_numbers(query.get("period"))
        | _period_numbers(query.get("comparison_period"))
        | _snapshot_numbers(query.get("snapshot"))
    )
    for period in (query.get("period"), query.get("comparison_period")):
        if not isinstance(period, dict):
            continue
        compact = summary.replace(" ", "")
        start = str(period.get("start") or "")[:10]
        end = str(period.get("end_exclusive") or "")[:10]
        if start and f"{start}전부터" in compact:
            return False
        if end and f"{end}까지" in compact and f"{end}전까지" not in compact:
            return False
    if rows and any(
        phrase in summary
        for phrase in ("관측값이", "관측값은", "관측값이 존재", "관측값이 비어 있지")
    ):
        return False
    if package is not None:
        metrics = _business_metrics(package)
        terms = tuple(getattr(package, "metric_terms", ()))
        if terms:
            terms_by_id = {term.id: term for term in terms}
            summary_key = summary.casefold()
            if any(
                metric_display_label(terms_by_id[metric.id]).casefold()
                not in summary_key
                for metric in metrics
            ):
                return False
        if any((metric.unit or "").casefold() == "ratio" for metric in metrics) and (
            "%" not in summary or "ratio" in summary.casefold()
        ):
            return False
    if _UNSUPPORTED_INFERENCE.search(summary):
        return False
    if not mentioned or any(value not in allowed for value in mentioned):
        return False
    return not result_numbers or any(value in result_numbers for value in mentioned)


def _business_metrics(package: ContextPackage) -> tuple[ContextMetric, ...]:
    """Glossary Term이 결합된 사용자 출력 Metric만 안정 순서로 반환한다."""

    terms = tuple(getattr(package, "metric_terms", ()))
    term_ids = (
        {term.id for term in terms}
        if terms
        else {
            metric.id
            for metric in getattr(package, "metrics", ())
            if metric.visibility == "BUSINESS"
        }
    )
    metrics = tuple(
        metric for metric in package.metrics if metric.visibility == "BUSINESS"
        and metric.id in term_ids
    )
    if not metrics:
        raise ValueError("grounded narrative requires BUSINESS metrics")
    return metrics


def _metric_value(
    metric: ContextMetric,
    package: ContextPackage,
    rows: list[dict[str, Any]],
    result_suffix: str = "",
) -> Decimal | None:
    return _reduce_context_metric(metric, package, rows, result_suffix)


def _period_label(period: object) -> str:
    if not isinstance(period, dict):
        return "요청 기간"
    try:
        start = date.fromisoformat(str(period["start"])[:10])
        end = date.fromisoformat(str(period["end_exclusive"])[:10])
    except (KeyError, ValueError):
        return "요청 기간"
    next_month = date(
        start.year + (1 if start.month == 12 else 0),
        1 if start.month == 12 else start.month + 1,
        1,
    )
    if start.day == 1 and end == next_month:
        return f"{start.year}년 {start.month}월"
    return f"{start.isoformat()}부터 {end.isoformat()} 전까지"


def _time_label(query: dict[str, Any]) -> str:
    snapshot = query.get("snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("cutoff"), str):
        try:
            cutoff = date.fromisoformat(str(snapshot["cutoff"])[:10])
        except ValueError:
            pass
        else:
            return f"{cutoff.isoformat()} 이전 최신 스냅샷"
    return _period_label(query.get("period"))


def _format_value(value: Decimal, unit: str) -> str:
    display_unit = metric_display_unit(unit)
    displayed = value * 100 if unit.lower() == "ratio" else value
    if unit.lower() == "ratio":
        displayed = displayed.quantize(Decimal("0.01"))
    raw = format(displayed, ",f")
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    suffix = "%" if unit.lower() == "ratio" else f" {display_unit}" if display_unit else ""
    return f"{raw}{suffix}"


def grounded_summary(query: dict[str, Any], package: ContextPackage) -> str:
    """승인된 지표·기간·행만 사용해 수치가 틀릴 수 없는 짧은 사용자 요약을 만든다."""

    rows = query.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("grounded narrative rows are invalid")
    period = _time_label(query)
    metrics = _business_metrics(package)
    terms = {term.id: term for term in package.metric_terms}
    comparison_period = query.get("comparison_period")
    if isinstance(comparison_period, dict):
        def period_clause(period_value: object, result_suffix: str) -> str:
            label = _period_label(period_value)
            values = [
                (
                    metric_display_label(terms[metric.id]),
                    _metric_value(metric, package, rows, result_suffix),
                    metric.unit or terms[metric.id].unit,
                )
                for metric in metrics
            ]
            available = [
                f"{metric_label} {_format_value(value, unit)}"
                for metric_label, value, unit in values
                if value is not None
            ]
            missing = [
                metric_label
                for metric_label, value, _unit in values
                if value is None
            ]
            if not available:
                return f"{label}에는 요청 지표의 표시 가능한 관측값이 없습니다"
            clause = f"{label} 기준 계산 결과는 {', '.join(available)}"
            if missing:
                clause += f"이며 {', '.join(missing)}에는 표시 가능한 관측값이 없습니다"
            return clause

        return (
            f"{period_clause(query.get('period'), '')}. "
            f"{period_clause(comparison_period, '__comparison')}."
        )
    if len(metrics) > 1:
        values = [
            (
                metric_display_label(terms[metric.id]),
                _metric_value(metric, package, rows),
                metric.unit or terms[metric.id].unit,
            )
            for metric in metrics
        ]
        available = [
            f"{label} {_format_value(value, unit)}"
            for label, value, unit in values
            if value is not None
        ]
        missing = [label for label, value, _unit in values if value is None]
        if not available:
            return f"{period}의 요청 지표들에 표시할 수 있는 관측값이 없습니다."
        summary = f"{period} 기준 계산 결과는 {', '.join(available)}입니다."
        if missing:
            summary += f" {', '.join(missing)}에는 표시할 수 있는 관측값이 없습니다."
        return summary

    metric = metrics[0]
    term = terms[metric.id]
    display_label = metric_display_label(term)
    value = _metric_value(metric, package, rows)
    if value is None:
        return f"{period}의 {display_label}에 표시할 수 있는 관측값이 없습니다."
    label = {"sum": "합계", "average": "평균"}.get(metric.reduction, "")
    calculation = f"{label} 계산 결과" if label else "계산 결과"
    summary = f"{period}의 {display_label} {calculation}는 {_format_value(value, metric.unit or term.unit)}입니다."

    numeric = _numeric_columns(rows)
    values = numeric.get(metric.result_field)
    dimension = next(
        (
            name
            for name in rows[0]
            if name != metric.result_field and name not in numeric
        ),
        None,
    ) if rows else None
    if dimension and values and len(rows) > 1:
        pairs = tuple(zip(rows, values, strict=True))
        high_row, high = max(pairs, key=lambda item: item[1])
        low_row, low = min(pairs, key=lambda item: item[1])
        summary += (
            f" 항목별 최댓값은 {high_row[dimension]} {_format_value(high, metric.unit or term.unit)}이고,"
            f" 최솟값은 {low_row[dimension]} {_format_value(low, metric.unit or term.unit)}입니다."
        )
    return summary
