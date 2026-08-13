"""Load the approved metric aliases shared by Node 1 and Node 3."""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def metric_glossary() -> dict[str, tuple[str, ...]]:
    path = Path(__file__).with_name("contracts") / "metric_glossary.i5.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(payload.get("version"), str) or not isinstance(metrics, dict):
        raise ValueError("metric glossary contract is invalid")

    glossary: dict[str, tuple[str, ...]] = {}
    for metric_id, aliases in metrics.items():
        if (
            not isinstance(metric_id, str)
            or not metric_id
            or not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(alias, str) or not alias for alias in aliases)
        ):
            raise ValueError("metric glossary aliases are invalid")
        glossary[metric_id] = tuple(aliases)
    return glossary


def metric_display_name(metric_id: str) -> str:
    """Return the first approved alias that identifies one metric unambiguously."""
    glossary = metric_glossary()
    aliases = glossary.get(metric_id, ())
    counts = Counter(alias for values in glossary.values() for alias in values)
    label = next((alias for alias in aliases if counts[alias] == 1), None)
    if label is None:
        raise ValueError(f"metric has no unique display name: {metric_id}")
    return label


@lru_cache(maxsize=1)
def metric_definitions() -> dict[str, str]:
    path = Path(__file__).with_name("contracts") / "metric_glossary.i5.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    definitions = payload.get("definitions")
    if not isinstance(metrics, dict) or not isinstance(definitions, dict):
        raise ValueError("metric definition contract is invalid")
    if set(definitions) != set(metrics) or any(
        not isinstance(metric_id, str)
        or not isinstance(definition, str)
        or not definition.strip()
        for metric_id, definition in definitions.items()
    ):
        raise ValueError("metric definitions must cover every approved metric")
    return dict(definitions)


def metric_definition(metric_id: str) -> str:
    try:
        return metric_definitions()[metric_id]
    except KeyError as error:
        raise ValueError(f"metric has no approved definition: {metric_id}") from error


@lru_cache(maxsize=1)
def metric_units() -> dict[str, str]:
    path = Path(__file__).with_name("contracts") / "metric_glossary.i5.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    units = payload.get("units")
    if not isinstance(metrics, dict) or not isinstance(units, dict):
        raise ValueError("metric unit contract is invalid")
    if set(units) != set(metrics) or any(
        not isinstance(metric_id, str) or not isinstance(unit, str) or not unit.strip()
        for metric_id, unit in units.items()
    ):
        raise ValueError("metric units must cover every approved metric")
    return dict(units)


def metric_unit(metric_id: str) -> str:
    try:
        return metric_units()[metric_id]
    except KeyError as error:
        raise ValueError(f"metric has no approved unit: {metric_id}") from error
