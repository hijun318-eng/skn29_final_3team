"""Deterministic Node 3 explanation for G3-approved shaped results."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .prompt_registry import get_prompt
from .schema import ContractError, validate_payload


def explain_result(
    payload: dict[str, Any],
    *,
    model_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe approved values without recalculating results or gates."""
    validate_payload("node3_request", payload)
    _validate_metric_selection(payload)

    period = payload["period"]
    rows = json.dumps(
        payload["shaped_result"]["rows"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    conditions = [
        "metrics=" + ",".join(
            payload.get("metric_selection", {}).get(
                "selected_metric_ids", [payload["metric"]]
            )
        ),
        f"period={period['period_start']}..{period['period_end_exclusive']}",
        f"unit={payload['unit']}",
        f"sampling={str(payload['sampling']).lower()}",
        f"masking={str(payload['masking']).lower()}",
        f"partial={str(payload['partial']).lower()}",
        "result_reference="
        f"{payload['result_reference']['kind']}:{payload['result_reference']['value']}",
        *(f"filter={item}" for item in payload["filters"]),
    ]
    limitations = [
        label
        for enabled, label in (
            (payload["sampling"], "sampling"),
            (payload["masking"], "masking"),
            (payload["partial"], "partial"),
        )
        if enabled
    ]
    response = {
        "explanation": f"검증된 shaped result: {rows}",
        "conditions": conditions,
        "sources": deepcopy(payload["source_ids"]),
        "limitations": limitations,
        "model": deepcopy(model_metadata or get_prompt("node3.explain").metadata()),
    }
    validate_payload("node3_response", response)
    return response


def _validate_metric_selection(payload: dict[str, Any]) -> None:
    source_ids = payload["source_ids"]
    if len(source_ids) != len(set(source_ids)):
        raise ContractError("node3_request: source_ids must be unique")

    selection = payload.get("metric_selection")
    if selection is None:
        if len(source_ids) > 1:
            raise ContractError("node3_request: multi-source result requires metric selection")
        return

    selected = selection["selected_metric_id"]
    selected_ids = selection["selected_metric_ids"]
    context_ids = selection["context_metric_ids"]
    if (
        not selected_ids
        or len(selected_ids) != len(set(selected_ids))
        or selected != selected_ids[0]
        or context_ids != selected_ids
        or payload["metric"] != selected
        or not set(selected_ids).issubset(selection["entitled_metric_ids"])
    ):
        raise ContractError("node3_request: metric selection is outside approved Context or entitlement")
