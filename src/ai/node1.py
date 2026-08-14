"""Deterministic Node 1 baseline; it proposes meaning and never makes Gate decisions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .prompt_registry import get_prompt
from .schema import ContractError, validate_payload


def normalize_question(payload: dict[str, Any]) -> dict[str, Any]:
    validate_payload("node1_request", payload)
    question = " ".join(payload["question"].split())
    alias_matches = [
        (term_id, term, alias)
        for term_id, term in payload["business_terms"].items()
        for alias in term["aliases"]
        if alias in question
    ]
    specific_matches = [
        match
        for match in alias_matches
        if not any(
            match[2] != other[2] and match[2] in other[2]
            for other in alias_matches
        )
    ]
    matched_terms = list(
        {
            term_id: (term_id, term)
            for term_id, term, _alias in specific_matches
        }.values()
    )
    metrics = [term_id for term_id, term in matched_terms if term["kind"] == "metric"]
    dimensions = [term_id for term_id, term in matched_terms if term["kind"] == "dimension"]
    periods = _period_candidates(question, payload["as_of"], payload["timezone"])
    reasons = []
    if not metrics:
        reasons.append("metric_missing")
    elif len(metrics) > 1:
        reasons.append("metric_ambiguous")
    if not periods:
        reasons.append("period_missing")

    response = {
        "normalized_question": question,
        "intent_candidates": [_intent(question)],
        "metric_candidates": metrics,
        "selected_metric_id": metrics[0] if len(metrics) == 1 else None,
        "dimension_candidates": dimensions,
        "period_candidates": periods,
        "ambiguity": {
            "is_ambiguous": bool(reasons),
            "reasons": reasons,
            "clarification_question": _clarification(reasons),
        },
        "model": get_prompt("node1.normalize").metadata(),
    }
    validate_payload("node1_response", response)
    return response


def _intent(question: str) -> str:
    if any(token in question for token in ("비교", "대비")):
        return "compare"
    if any(token in question for token in ("추이", "변화")):
        return "trend"
    return "aggregate"


def _period_candidates(question: str, as_of_text: str, timezone_name: str) -> list[dict[str, str]]:
    as_of = datetime.fromisoformat(as_of_text)
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ContractError(f"node1_request.timezone: unknown timezone {timezone_name!r}") from error
    local_as_of = as_of.astimezone(timezone)
    if as_of.utcoffset() != local_as_of.utcoffset():
        raise ContractError("node1_request.as_of: UTC offset does not match timezone")

    selected_period = re.search(r"선택한 기간:\s*([^)]*)", question)
    period_text = selected_period.group(1).strip() if selected_period else question

    relative = _relative_period(period_text, local_as_of)
    if relative:
        return [relative]

    if "이번 달" in period_text:
        start = local_as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return [
            {
                "start": start.isoformat(),
                "end_exclusive": local_as_of.isoformat(),
                "source_text": "이번 달",
            }
        ]
    if "오늘" in period_text:
        start = local_as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        return [
            {
                "start": start.isoformat(),
                "end_exclusive": local_as_of.isoformat(),
                "source_text": "오늘",
            }
        ]
    month_range = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(?:과|와|부터|~)\s*(?:(\d{4})년\s*)?(\d{1,2})월",
        period_text,
    )
    if month_range:
        start_year = int(month_range.group(1) or local_as_of.year)
        start_month = int(month_range.group(2))
        end_year = int(month_range.group(3) or start_year)
        end_month = int(month_range.group(4))
        if month_range.group(3) is None and end_month < start_month:
            end_year += 1
        try:
            start = _month_start(start_year, start_month, local_as_of)
            end = _month_start_after(end_year, end_month, local_as_of)
        except ContractError:
            return []
        if start >= end:
            return []
        return [{
            "start": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "source_text": month_range.group(0),
        }]
    month_mentions = list(
        re.finditer(r"(?:(\d{4})년\s*)?(\d{1,2})월", period_text)
    )
    candidates = []
    inherited_year = local_as_of.year
    for mention in month_mentions:
        if mention.group(1):
            inherited_year = int(mention.group(1))
        month = int(mention.group(2))
        try:
            start = _month_start(inherited_year, month, local_as_of)
        except ContractError:
            return []
        candidate = {
            "start": start.isoformat(),
            "end_exclusive": _month_start_after(
                inherited_year, month, local_as_of
            ).isoformat(),
            "source_text": mention.group(0),
        }
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _relative_period(text: str, as_of: datetime) -> dict[str, str] | None:
    """Resolve common Korean relative calendar phrases against the supplied clock."""
    day = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    week = day - timedelta(days=day.weekday())

    rules = (
        (r"지지난\s*달", _shift_month(month, -2), _shift_month(month, -1)),
        (r"(?:지난|저번)\s*달|전월", _shift_month(month, -1), month),
        (r"이번\s*달", month, day),
        (r"지지난\s*주", week - timedelta(days=14), week - timedelta(days=7)),
        (r"(?:지난|저번)\s*주|전주", week - timedelta(days=7), week),
        (r"이번\s*주", week, day),
        (r"그저께|그제", day - timedelta(days=2), day - timedelta(days=1)),
        (r"어제", day - timedelta(days=1), day),
        (r"작년", day.replace(year=day.year - 1, month=1, day=1), day.replace(month=1, day=1)),
        (r"올해|금년", day.replace(month=1, day=1), day),
    )
    for pattern, start, end in rules:
        match = re.search(pattern, text)
        if match and start < end:
            return _period(start, end, match.group(0))

    recent_days = re.search(r"최근\s*(\d{1,3})\s*일", text)
    if recent_days:
        days = int(recent_days.group(1))
        if 1 <= days <= 366:
            return _period(day - timedelta(days=days), day, recent_days.group(0))
        return None
    recent_weeks = re.search(r"최근\s*(\d{1,2})\s*주", text)
    if recent_weeks:
        weeks = int(recent_weeks.group(1))
        if 1 <= weeks <= 52:
            return _period(day - timedelta(days=weeks * 7), day, recent_weeks.group(0))
        return None
    recent_week = re.search(r"최근\s*(?:한|일)\s*주일", text)
    if recent_week:
        return _period(day - timedelta(days=7), day, recent_week.group(0))

    quarter = ((day.month - 1) // 3) * 3 + 1
    quarter_start = day.replace(month=quarter, day=1)
    previous_quarter = _shift_month(quarter_start, -3)
    match = re.search(r"지난\s*분기", text)
    if match:
        return _period(previous_quarter, quarter_start, match.group(0))
    match = re.search(r"이번\s*분기", text)
    if match and quarter_start < day:
        return _period(quarter_start, day, match.group(0))
    return None


def _shift_month(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 + months
    return value.replace(year=index // 12, month=index % 12 + 1, day=1)


def _period(start: datetime, end: datetime, source_text: str) -> dict[str, str]:
    return {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "source_text": source_text,
    }


def _month_start(year: int, month: int, reference: datetime) -> datetime:
    if month < 1 or month > 12:
        raise ContractError(f"node1_request.question: invalid month {month}")
    return reference.replace(
        year=year,
        month=month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _month_start_after(year: int, month: int, reference: datetime) -> datetime:
    if month == 12:
        return _month_start(year + 1, 1, reference)
    return _month_start(year, month + 1, reference)


def _clarification(reasons: list[str]) -> str | None:
    if "metric_missing" in reasons:
        return "확인할 지표를 알려주세요."
    if "metric_ambiguous" in reasons:
        return "확인할 지표를 하나만 선택해 주세요."
    if "period_missing" in reasons:
        return "확인할 기간을 알려주세요."
    return None
