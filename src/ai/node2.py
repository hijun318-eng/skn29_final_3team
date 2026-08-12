"""Context-bound deterministic Node 2 and one-shot Node 2-prime baseline."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from .prompt_registry import get_prompt
from .schema import ContractError, validate_payload


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DERIVED_JOIN_ID = "pms_crm_pos_gold_revenue_month_v1"
_REPAIR_CODES = {
    "METRIC_FILTER_MISSING",
    "MODEL_SCHEMA_INVALID",
    "REFERENCE_MISSING",
    "RESOURCE_POLICY_MISSING",
    "UNKNOWN_COLUMN",
}


def generate_sql(payload: dict[str, Any]) -> dict[str, Any]:
    """Build one read-only aggregate using only identifiers present in Context."""
    validate_payload("node2_request", payload)
    context = payload["context_package"]
    metrics = context["metrics"]
    metric = metrics[0]
    if metric["field"].startswith("derived."):
        return _generate_derived_sql(context, metric)
    resolved = [
        (item, *_resolve_column(context["assets"], item["field"]), *_resolve_column(context["assets"], item["time_field"]))
        for item in metrics
    ]
    _, asset, metric_column, time_asset, time_column = resolved[0]
    if any(
        item_asset["trino_fqn"] != asset["trino_fqn"]
        or item_time_asset["trino_fqn"] != time_asset["trino_fqn"]
        or item_time_column != time_column
        or item.get("required_filters", []) != metric.get("required_filters", [])
        for item, item_asset, _, item_time_asset, item_time_column in resolved
    ):
        raise ContractError("node2_request: multiple metrics require one asset, time field and filter policy")
    if time_asset["trino_fqn"] != asset["trino_fqn"]:
        raise ContractError("node2_request: metric and time field require an approved join predicate")
    aggregates = [(item["aggregation"].upper(), column, item["id"]) for item, _, column, _, _ in resolved]
    if any(aggregation not in {"AVG", "COUNT", "MAX", "MIN", "SUM"} for aggregation, _, _ in aggregates):
        raise ContractError("node2_request: unsupported aggregation")

    fqn = _validated_fqn(asset["trino_fqn"])
    filter_clauses, filter_parameters, filter_columns = _required_filters(asset, metric)
    where = [
        f'"{time_column}" >= DATE \':period_start\'',
        f'"{time_column}" < DATE \':period_end_exclusive\'',
        *filter_clauses,
    ]
    sql = (
        "SELECT " + ", ".join(
            f'{aggregation}("{column}") AS "{metric_id}"'
            for aggregation, column, metric_id in aggregates
        ) + " "
        f'FROM {fqn} WHERE {" AND ".join(where)} LIMIT 1000'
    )
    response = {
        "sql": sql,
        "references": [
            _reference(asset, context, {*(column for _, column, _ in aggregates), time_column, *filter_columns})
        ],
        "parameters": [
            {
                "name": "period_start",
                "value_type": "date",
                "value": context["execution_time"]["period_start"][:10],
            },
            {
                "name": "period_end_exclusive",
                "value_type": "date",
                "value": context["execution_time"]["period_end_exclusive"][:10],
            },
            *filter_parameters,
        ],
        "model": get_prompt("node2.sql").metadata(),
    }
    validate_payload("node2_response", response)
    return response


def _generate_derived_sql(context: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    assets = context["assets"]
    if len(assets) != 6 or metric["aggregation"].lower() != "derived_sum":
        raise ContractError("node2_request: invalid derived metric Context")
    joins = context["joins"]
    if (
        {join["id"] for join in joins} != {_DERIVED_JOIN_ID}
        or any(
            join["status"] != "approved"
            or join["cardinality"] != "preaggregate_then_one_to_one_month"
            for join in joins
        )
        or not {asset["trino_fqn"] for asset in assets}.issubset(
            {fqn for join in joins for fqn in (join["left"], join["right"])}
        )
        or any(not join.get("on_predicates") for join in joins)
    ):
        raise ContractError("node2_request: derived metric requires the approved preaggregate join")

    stays = _asset_with_columns(
        assets,
        {"property_id", "reservation_id", "actual_checkout_at", "room_revenue"},
    )
    reservations = _asset_with_columns(assets, {"property_id", "reservation_id", "guest_id"})
    guests = _asset_with_columns(assets, {"property_id", "guest_id"}, exact=True)
    customer_map = _asset_with_columns(
        assets,
        {"property_id", "pms_guest_id", "pos_customer_ref", "member_no", "valid_from", "valid_to"},
    )
    grades = _asset_with_columns(
        assets,
        {"property_id", "member_no", "grade_code", "valid_from", "valid_to"},
    )
    orders = _asset_with_columns(
        assets,
        {"property_id", "pos_customer_ref", "ordered_at", "net_amount"},
    )
    aliases = {
        stays["trino_fqn"]: "s",
        reservations["trino_fqn"]: "r",
        guests["trino_fqn"]: "g",
        customer_map["trino_fqn"]: "m",
        grades["trino_fqn"]: "h",
        orders["trino_fqn"]: "o",
    }
    filters, parameters, filter_columns = _derived_filters(assets, metric, aliases)
    pms_filters = [clause for fqn, clause in filters if fqn != orders["trino_fqn"]]
    pos_filters = [
        clause
        for fqn, clause in filters
        if fqn in {orders["trino_fqn"], grades["trino_fqn"]}
    ]
    if len(pms_filters) + len(pos_filters) <= len(filters):
        raise ContractError("node2_request: derived filters must cover both source aggregates")

    sql = " ".join(
        (
            "WITH pms_source AS (SELECT s.property_id,",
            "date_trunc('month', s.actual_checkout_at) AS month,",
            "SUM(s.room_revenue) AS room_revenue_krw",
            f"FROM {_validated_fqn(stays['trino_fqn'])} s",
            f"JOIN {_validated_fqn(reservations['trino_fqn'])} r "
            "ON s.property_id = r.property_id AND s.reservation_id = r.reservation_id",
            f"JOIN {_validated_fqn(guests['trino_fqn'])} g "
            "ON r.property_id = g.property_id AND r.guest_id = g.guest_id",
            f"JOIN {_validated_fqn(customer_map['trino_fqn'])} m "
            "ON g.property_id = m.property_id AND g.guest_id = m.pms_guest_id "
            "AND m.valid_from <= s.actual_checkout_at "
            "AND (m.valid_to IS NULL OR s.actual_checkout_at < m.valid_to)",
            f"JOIN {_validated_fqn(grades['trino_fqn'])} h "
            "ON m.property_id = h.property_id AND m.member_no = h.member_no "
            "AND h.valid_from <= s.actual_checkout_at "
            "AND (h.valid_to IS NULL OR s.actual_checkout_at < h.valid_to)",
            "WHERE s.actual_checkout_at >= DATE ':period_start'",
            "AND s.actual_checkout_at < DATE ':period_end_exclusive'",
            *(f"AND {clause}" for clause in pms_filters),
            "GROUP BY s.property_id, date_trunc('month', s.actual_checkout_at)),",
            "pos_source AS (SELECT o.property_id,",
            "date_trunc('month', o.ordered_at) AS month,",
            "SUM(o.net_amount) AS fnb_revenue_krw",
            f"FROM {_validated_fqn(orders['trino_fqn'])} o",
            f"JOIN {_validated_fqn(customer_map['trino_fqn'])} m "
            "ON o.property_id = m.property_id AND o.pos_customer_ref = m.pos_customer_ref "
            "AND m.valid_from <= o.ordered_at "
            "AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)",
            f"JOIN {_validated_fqn(grades['trino_fqn'])} h "
            "ON m.property_id = h.property_id AND m.member_no = h.member_no "
            "AND h.valid_from <= o.ordered_at "
            "AND (h.valid_to IS NULL OR o.ordered_at < h.valid_to)",
            "WHERE o.ordered_at >= DATE ':period_start'",
            "AND o.ordered_at < DATE ':period_end_exclusive'",
            *(f"AND {clause}" for clause in pos_filters),
            "GROUP BY o.property_id, date_trunc('month', o.ordered_at))",
            "SELECT COALESCE(p.property_id, f.property_id) AS property_id,",
            "COALESCE(p.month, f.month) AS month,",
            "COALESCE(p.room_revenue_krw, 0) AS room_revenue_krw,",
            "COALESCE(f.fnb_revenue_krw, 0) AS fnb_revenue_krw,",
            "COALESCE(p.room_revenue_krw, 0) + COALESCE(f.fnb_revenue_krw, 0) AS total_guest_revenue_krw",
            "FROM pms_source p FULL OUTER JOIN pos_source f",
            "ON p.property_id = f.property_id AND p.month = f.month LIMIT 1000",
        )
    )
    referenced_columns = {
        stays["trino_fqn"]: {"property_id", "reservation_id", "actual_checkout_at", "room_revenue"},
        reservations["trino_fqn"]: {"property_id", "reservation_id", "guest_id"},
        guests["trino_fqn"]: {"property_id", "guest_id"},
        customer_map["trino_fqn"]: {
            "property_id", "pms_guest_id", "pos_customer_ref", "member_no", "valid_from", "valid_to"
        },
        grades["trino_fqn"]: {"property_id", "member_no", "valid_from", "valid_to"},
        orders["trino_fqn"]: {"property_id", "pos_customer_ref", "ordered_at", "net_amount"},
    }
    for fqn, columns in filter_columns.items():
        referenced_columns[fqn].update(columns)
    response = {
        "sql": sql,
        "references": [
            {
                "urn": asset["urn"],
                "trino_fqn": asset["trino_fqn"],
                "columns": [
                    column for column in asset["columns"]
                    if column in referenced_columns[asset["trino_fqn"]]
                ],
                "join_ids": [_DERIVED_JOIN_ID],
                "metric_ids": [metric["id"]],
            }
            for asset in assets
        ],
        "parameters": [
            {
                "name": "period_start",
                "value_type": "date",
                "value": context["execution_time"]["period_start"][:10],
            },
            {
                "name": "period_end_exclusive",
                "value_type": "date",
                "value": context["execution_time"]["period_end_exclusive"][:10],
            },
            *parameters,
        ],
        "model": get_prompt("node2.sql").metadata(),
    }
    validate_payload("node2_response", response)
    return response


def _asset_with_columns(
    assets: list[dict[str, Any]],
    required: set[str],
    *,
    exact: bool = False,
) -> dict[str, Any]:
    matches = [
        asset for asset in assets
        if (set(asset["columns"]) == required if exact else required.issubset(asset["columns"]))
    ]
    if len(matches) != 1:
        raise ContractError("node2_request: derived asset roles are ambiguous")
    return matches[0]


def _derived_filters(
    assets: list[dict[str, Any]],
    metric: dict[str, Any],
    aliases: dict[str, str],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]], dict[str, set[str]]]:
    columns_by_fqn = {asset["trino_fqn"]: set(asset["columns"]) for asset in assets}
    filters = sorted(metric.get("required_filters", []), key=lambda item: item["field"])
    seen = set()
    clauses = []
    parameters = []
    referenced = {fqn: set() for fqn in columns_by_fqn}
    for index, item in enumerate(filters, start=1):
        field = item["field"]
        if field in seen or item["operator"] != "eq":
            raise ContractError("node2_request: invalid derived required filter")
        matches = [
            (fqn, field.rsplit(".", 1)[-1])
            for fqn, columns in columns_by_fqn.items()
            if field.startswith(f"{fqn}.") and field.rsplit(".", 1)[-1] in columns
        ]
        if len(matches) != 1 or not _typed_value_is_valid(item["value_type"], item["value"]):
            raise ContractError("node2_request: invalid derived required filter")
        fqn, column = matches[0]
        name = f"required_filter_{index}"
        seen.add(field)
        referenced[fqn].add(column)
        clauses.append((fqn, f'{aliases[fqn]}."{column}" = :{name}'))
        parameters.append(
            {"name": name, "value_type": item["value_type"], "value": item["value"]}
        )
    if not filters:
        raise ContractError("node2_request: derived metric requires typed filters")
    return clauses, parameters, referenced


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
        value_type = item["value_type"]
        value = item["value"]
        if not _typed_value_is_valid(value_type, value):
            raise ContractError("node2_request: invalid required filter value")
        name = f"required_filter_{index}"
        fields.add(field)
        clauses.append(f'"{field}" = :{name}')
        parameters.append({"name": name, "value_type": value_type, "value": value})
    return clauses, parameters, fields


def _typed_value_is_valid(value_type: str, value: object) -> bool:
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if value_type == "string":
        return isinstance(value, str) and bool(value)
    if value_type == "date" and isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    return False


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
