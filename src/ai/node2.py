"""Context-bound deterministic Node 2 and one-shot Node 2-prime baseline."""

from __future__ import annotations

import re
from typing import Any

from .prompt_registry import get_prompt
from .schema import ContractError, validate_payload


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPAIR_CODES = {
    "MODEL_SCHEMA_INVALID",
    "REFERENCE_MISSING",
    "RESOURCE_POLICY_MISSING",
    "UNKNOWN_COLUMN",
}


def generate_sql(payload: dict[str, Any]) -> dict[str, Any]:
    """Build one read-only aggregate using only identifiers present in Context."""
    validate_payload("node2_request", payload)
    context = payload["context_package"]
    metric = context["metrics"][0]
    asset, metric_column = _resolve_column(context["assets"], metric["field"])
    time_asset, time_column = _resolve_column(context["assets"], metric["time_field"])
    if time_asset["trino_fqn"] != asset["trino_fqn"]:
        raise ContractError("node2_request: metric and time field require an approved join predicate")
    aggregation = metric["aggregation"].upper()
    if aggregation not in {"AVG", "COUNT", "MAX", "MIN", "SUM"}:
        raise ContractError("node2_request: unsupported aggregation")

    fqn = _validated_fqn(asset["trino_fqn"])
    filter_clauses, filter_parameters, filter_columns = _required_filters(asset, metric)
    where = [
        f'"{time_column}" >= DATE \':period_start\'',
        f'"{time_column}" < DATE \':period_end\'',
        *filter_clauses,
    ]
    sql = (
        f'SELECT {aggregation}("{metric_column}") AS "{metric_column}" '
        f'FROM {fqn} WHERE {" AND ".join(where)} LIMIT 1000'
    )
    response = {
        "sql": sql,
        "references": [
            _reference(asset, context, {metric_column, time_column, *filter_columns})
        ],
        "parameters": [
            {"name": "period_start", "value": context["execution_time"]["period_start"][:10]},
            {"name": "period_end", "value": context["execution_time"]["period_end_exclusive"][:10]},
            *filter_parameters,
        ],
        "model": get_prompt("node2.sql").metadata(),
    }
    validate_payload("node2_response", response)
    return response


def repair_sql(payload: dict[str, Any]) -> dict[str, Any]:
    """Perform the single Controller-authorized repair; never retries internally."""
    validate_payload("node2_repair_request", payload)
    if payload["normalized_error_code"] not in _REPAIR_CODES:
        raise ContractError("node2_repair_request: unsupported normalized error code")
    generated = generate_sql(
        {"question_id": payload["trace_id"], "context_package": payload["context_package"]}
    )
    response = {
        "trace_id": payload["trace_id"],
        "attempt": 1,
        "corrected_sql": generated["sql"],
        "references": generated["references"],
        "parameters": generated["parameters"],
        "model": get_prompt("node2.repair").metadata(),
    }
    validate_payload("node2_repair_response", response)
    return response


def _resolve_column(assets: list[dict[str, Any]], qualified: str) -> tuple[dict[str, Any], str]:
    column = qualified.rsplit(".", 1)[-1]
    matches = [
        asset for asset in assets
        if qualified == f'{asset["trino_fqn"]}.{column}' and column in asset["columns"]
    ]
    if len(matches) != 1 or not _IDENTIFIER.fullmatch(column):
        raise ContractError(f"node2_request: field outside Context: {qualified!r}")
    return matches[0], column


def _validated_fqn(fqn: str) -> str:
    parts = fqn.split(".")
    if len(parts) != 3 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise ContractError(f"node2_request: invalid Context FQN: {fqn!r}")
    return fqn


def _required_filters(
    asset: dict[str, Any], metric: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]], set[str]]:
    filters = sorted(metric.get("required_filters", []), key=lambda item: item["field"])
    fields: set[str] = set()
    clauses = []
    parameters = []
    for index, item in enumerate(filters, start=1):
        field = item["field"]
        if (
            not _IDENTIFIER.fullmatch(field)
            or field not in asset["columns"]
            or field in fields
        ):
            raise ContractError(f"node2_request: invalid required filter field: {field!r}")
        if item["operator"] != "eq":
            raise ContractError("node2_request: unsupported required filter operator")
        value = item["value"]
        if not isinstance(value, (str, bool)) or isinstance(value, str) and not value:
            raise ContractError("node2_request: invalid required filter value")
        name = f"required_filter_{index}"
        fields.add(field)
        clauses.append(f'"{field}" = :{name}')
        parameters.append({"name": name, "value": value})
    return clauses, parameters, fields


def _reference(
    asset: dict[str, Any], context: dict[str, Any], columns: set[str]
) -> dict[str, Any]:
    fqn = asset["trino_fqn"]
    return {
        "urn": asset["urn"],
        "trino_fqn": fqn,
        "columns": [column for column in asset["columns"] if column in columns],
        "join_ids": [
            join["id"] for join in context["joins"]
            if fqn in {join["left"], join["right"]}
        ],
        "metric_ids": [metric["id"] for metric in context["metrics"]],
    }
