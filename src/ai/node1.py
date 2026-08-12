"""Deterministic Node 1 baseline; it proposes meaning and never makes Gate decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .prompt_registry import get_prompt
from .schema import ContractError, validate_payload


def normalize_question(payload: dict[str, Any]) -> dict[str, Any]:
    validate_payload("node1_request", payload)
    question = " ".join(payload["question"].split())
    matched_terms = _matched_terms(question, payload["business_terms"])
    matched_metrics = [
        term_id for term_id, term in matched_terms if term["kind"] == "metric"
    ]
    metrics = list(payload["selected_metric_ids"]) or matched_metrics
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


def _matched_terms(
    question: str, business_terms: dict[str, dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    matches = []
    for term_id, term in business_terms.items():
        spans = [
            (question.find(alias), question.find(alias) + len(alias))
            for alias in term["aliases"]
            if alias in question
        ]
        if spans:
            start, end = min(spans, key=lambda span: (span[0], -(span[1] - span[0])))
            matches.append((start, end, term_id, term))
    selected = []
    occupied: dict[str, list[tuple[int, int]]] = {}
    for start, end, term_id, term in sorted(matches, key=lambda item: (item[0], -item[1])):
        kind_spans = occupied.setdefault(term["kind"], [])
        if any(start < other_end and other_start < end for other_start, other_end in kind_spans):
            continue
        kind_spans.append((start, end))
        selected.append((term_id, term))
    return selected


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

    if "이번 달" in question:
        start = local_as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return [
            {
                "start": start.isoformat(),
                "end_exclusive": local_as_of.isoformat(),
                "source_text": "이번 달",
            }
        ]
    if "오늘" in question:
        start = local_as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        return [
            {
                "start": start.isoformat(),
                "end_exclusive": local_as_of.isoformat(),
                "source_text": "오늘",
            }
        ]
    return []


def _clarification(reasons: list[str]) -> str | None:
    if "metric_missing" in reasons:
        return "확인할 지표를 알려주세요."
    if "metric_ambiguous" in reasons:
        return "확인할 지표를 하나만 선택해 주세요."
    if "period_missing" in reasons:
        return "확인할 기간을 알려주세요."
    return None
