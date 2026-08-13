"""Load the approved metric aliases shared by Node 1 and Node 3."""

from __future__ import annotations

import json
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
