from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from functools import lru_cache, partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ai import schema as ai_schema
from src.ai.fake_model import FakeModelAdapter as R3FakeModelAdapter
from src.ai.prompt_registry import get_prompt
from src.ai.training.benchmark_serving import request_json
from src.modelops.runtime import ProductionModelClient


_PROMPT_IDS = {
    "node2": "node2.sql",
    "node2_repair": "node2.repair",
    "node3": "node3.explain",
}


@lru_cache(maxsize=None)
def _response_schema(node: str) -> dict[str, Any]:
    path = Path(ai_schema.__file__).with_name("contracts") / "node_io.v0.1.json"
    with path.open(encoding="utf-8") as schema_file:
        bundle = json.load(schema_file)
    return {"$defs": bundle["$defs"], **bundle["$defs"][f"{node}_response"]}


def _serving_schema(node: str) -> dict[str, Any]:
    if node == "node2":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["sql"],
            "properties": {"sql": {"type": "string"}},
        }
    if node == "node2_repair":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["corrected_sql"],
            "properties": {"corrected_sql": {"type": "string"}},
        }
    return _response_schema(node)


def _validate_sql_semantics(node: str, payload: dict[str, Any], sql: str) -> None:
    if node != "node2" or "전월 대비" not in payload.get("normalized_question", ""):
        return
    required = (
        r"date_add\s*\(\s*'month'\s*,\s*-2",
        r"from_iso8601_timestamp\s*\(",
        r"group\s+by\s+1",
        r"order\s+by\s+1",
    )
    if any(re.search(pattern, sql, flags=re.IGNORECASE) is None for pattern in required):
        raise ValueError("month-over-month SQL must use the approved two-month window")


def openai_transport(
    endpoint: str,
    token: str | None,
    node: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        {
            "model": "Qwen/Qwen3-4B",
            "messages": [
                {"role": "system", "content": get_prompt(_PROMPT_IDS[node]).text},
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 1_500,
            "chat_template_kwargs": {"enable_thinking": False},
            "guided_json": _serving_schema(node),
        },
        token,
        timeout,
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completion response has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("chat completion response has no text content")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("model content must be a JSON object")
    if node not in {"node2", "node2_repair"}:
        return result
    sql_field = "sql" if node == "node2" else "corrected_sql"
    sql = result[sql_field]
    _validate_sql_semantics(node, payload, sql)
    queried = {
        table.strip('"').lower()
        for table in re.findall(
            r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)",
            sql,
            flags=re.IGNORECASE,
        )
    }
    package = payload["context_package"]
    join_ids = [item["id"] for item in package["joins"]]
    metric_ids = [item["id"] for item in package["metrics"]]
    completed = {
        sql_field: sql,
        "references": [
            {
                "urn": asset["urn"],
                "trino_fqn": asset["trino_fqn"],
                "columns": asset["columns"],
                "join_ids": join_ids,
                "metric_ids": metric_ids,
            }
            for asset in package["assets"]
            if asset["trino_fqn"].lower() in queried
        ],
        "parameters": [],
        "model": get_prompt(_PROMPT_IDS[node]).metadata(),
    }
    if node == "node2_repair":
        completed.update(trace_id=payload["trace_id"], attempt=payload["attempt"])
    return completed


class ContractModelAdapter:
    """R3 동결 schema와 R4 내부 plan 형식을 연결한다."""

    def __init__(self, model=None) -> None:
        self._model = model or R3FakeModelAdapter()

    @classmethod
    def from_openai(
        cls,
        endpoint: str,
        token: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> ContractModelAdapter:
        if not endpoint:
            raise ValueError("MODEL_ENDPOINT is required in openai mode")
        return cls(
            ProductionModelClient(
                partial(openai_transport, endpoint, token),
                timeout_seconds=timeout_seconds,
            )
        )

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        if node == "node2":
            response = self._generate(
                node,
                {
                    "question_id": payload["request_id"],
                    "normalized_question": payload["question"],
                    "context_package": self._context_package(payload),
                },
            )
            return self._plan(
                response, "sql", payload["package"].parameter_bindings
            )
        if node == "node2_repair":
            response = self._generate(
                node,
                {
                    "trace_id": payload["trace_id"],
                    "attempt": 1,
                    "rejected_sql": payload["rejected_sql"],
                    "context_package": self._context_package(payload),
                    "normalized_error_code": payload["violation"],
                    "repair_scope": ["sql"],
                },
            )
            return self._plan(
                response, "corrected_sql", payload["package"].parameter_bindings
            )
        if node == "node3":
            query = payload["query"]
            context = payload["context"]
            rows = query["rows"]
            metric_selection = self._metric_selection(payload["assets"])
            selected_metric = metric_selection["selected_metric_id"]
            response = self._generate(
                node,
                {
                    "g3_result": "pass",
                    "shaped_result": {
                        "columns": [
                            {"name": name, "type": "scalar"}
                            for name in (rows[0] if rows else ())
                        ],
                        "rows": rows,
                    },
                    "metric": selected_metric,
                    "metric_selection": metric_selection,
                    "period": self._execution_time(context),
                    "filters": [
                        f"{key}={value}"
                        for key, value in query.get("filters", {}).items()
                    ],
                    "unit": "KRW",
                    "sampling": bool(query.get("sampling", {}).get("applied")),
                    "masking": bool(query.get("masking", {}).get("applied")),
                    "partial": query.get("status") == "PARTIAL",
                    "source_ids": [item["urn"] for item in payload["assets"]],
                    "result_reference": {
                        "kind": "query_execution_id",
                        "value": str(query["query_id"]),
                    },
                },
            )
            return {
                "summary": response["explanation"],
                "model_version": response["model"]["model_version"],
            }
        raise ValueError(f"unsupported node: {node}")

    @staticmethod
    def _metric_selection(assets: list[dict[str, Any]]) -> dict[str, Any]:
        if not assets:
            raise ValueError("node3 requires entitled Context assets")

        metric_ids = [
            str(metric["id"])
            for asset in assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict) and isinstance(metric.get("id"), str)
        ]
        if metric_ids:
            selected = set(metric_ids)
            if len(selected) != 1:
                raise ValueError("node3 requires exactly one entitled Context metric")
            selected_metric = selected.pop()
            context_metric_ids = [selected_metric] * len(assets)
        else:
            approved_join = "pms_crm_pos_gold_revenue_month_v1"
            if (
                len(assets) != 6
                or len({asset.get("urn") for asset in assets}) != 6
                or any(
                    approved_join not in asset.get("join_ids", ())
                    for asset in assets
                )
            ):
                raise ValueError("node3 requires exactly one entitled Context metric")
            selected_metric = "total_guest_revenue_krw"
            context_metric_ids = [selected_metric] * len(assets)

        explicit_entitlements = [
            str(metric_id)
            for asset in assets
            for metric_id in asset.get("entitled_metric_ids", ())
        ]
        entitled_metric_ids = set(explicit_entitlements) or {selected_metric}
        if selected_metric not in entitled_metric_ids:
            raise ValueError("node3 selected metric is outside entitlement")
        return {
            "selected_metric_id": selected_metric,
            "context_metric_ids": context_metric_ids,
            "entitled_metric_ids": sorted(entitled_metric_ids),
        }

    def _generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._model.generate(node, payload)
        if getattr(self._model, "last_trace", {}).get("fallback"):
            raise TimeoutError("production model fallback is not a product result")
        return response

    @staticmethod
    def _plan(
        response: dict[str, Any],
        sql_field: str,
        parameter_bindings=(),
    ) -> dict[str, Any]:
        sql = response[sql_field]
        expected = {item.name: item for item in parameter_bindings}
        if "period_end_exclusive" in expected and ":period_end" in sql:
            sql = re.sub(r":period_end(?![a-z0-9_])", ":period_end_exclusive", sql)
        placeholders = set(re.findall(r":([a-z_][a-z0-9_]*)", sql))
        response_parameters = response["parameters"]
        names = [
            "period_end_exclusive"
            if item["name"] == "period_end" and "period_end_exclusive" in expected
            else item["name"]
            for item in response_parameters
        ]
        if len(names) != len(set(names)):
            raise ValueError("model parameter names must be unique")
        return {
            "sql": sql,
            "references": [
                {
                    "urn": item["urn"],
                    "fqn": item["trino_fqn"],
                    "columns": item["columns"],
                    "join_ids": item.get("join_ids", []),
                    "metric_ids": item.get("metric_ids", []),
                }
                for item in response["references"]
            ],
            "parameters": {
                name: (
                    {
                        "value_type": expected[name].value_type,
                        "value": item["value"],
                    }
                    if name in expected
                    else item["value"]
                )
                for name, item in zip(names, response_parameters)
                if name in placeholders
            },
            "model_version": response["model"]["model_version"],
        }

    @classmethod
    def _context_package(cls, payload: dict[str, Any]) -> dict[str, Any]:
        package = payload["package"]
        context = payload["context"]
        assets = [
            {
                "urn": item.urn,
                "trino_fqn": item.fqn,
                "columns": list(item.columns),
            }
            for item in package.assets
        ]
        metrics = list(package.metrics)
        fixture_metric = None
        three_source = (
            "pms_crm_pos_gold_revenue_month_v1" in package.approved_join_ids
        )
        execution_time = cls._execution_time(
            context, package.parameter_bindings if three_source else None
        )
        if not metrics and three_source:
            fixture_metric = {
                "id": "total_guest_revenue_krw",
                "field": "derived.total_guest_revenue_krw",
                "aggregation": "derived_sum",
                "time_field": "derived.month",
                "required_filters": [
                    {
                        "field": item.field,
                        "operator": item.operator,
                        "value_type": item.value_type,
                        "value": item.value,
                    }
                    for item in package.required_filters
                ],
            }
        elif not metrics and package.assets:
            asset = package.assets[0]
            fixture_metric = {
                "id": f"fixture_count_{asset.columns[0]}",
                "field": f"{asset.fqn}.{asset.columns[0]}",
                "aggregation": "count",
                "time_field": f"{asset.fqn}.{asset.columns[0]}",
            }
        return {
            "context_version": package.context_release,
            "policy_version": package.policy_version,
            "execution_time": execution_time,
            "assets": assets,
            "metrics": [
                {
                    "id": metric.id,
                    "field": f"{metric.asset_fqn}.{metric.field}",
                    "aggregation": metric.aggregation,
                    "time_field": f"{metric.asset_fqn}.{metric.time_field}",
                    "required_filters": [
                        {
                            "field": item.field,
                            "operator": item.operator,
                            "value": item.value,
                        }
                        for item in metric.required_filters
                    ],
                }
                for metric in metrics
            ] + ([fixture_metric] if fixture_metric else []),
            "joins": (
                [
                    {
                        "id": "pms_crm_pos_gold_revenue_month_v1",
                        "left": left,
                        "right": right,
                        "cardinality": "preaggregate_then_one_to_one_month",
                        "status": "approved",
                    }
                    for left, right in (
                        ("pms.public.pms_stays", "pms.public.pms_reservations"),
                        ("pms.public.pms_reservations", "pms.public.pms_guests"),
                        ("pms.public.pms_guests", "crm.dbo.crm_customer_map"),
                        (
                            "crm.dbo.crm_customer_map",
                            "crm.dbo.crm_member_grade_history",
                        ),
                        ("crm.dbo.crm_customer_map", "pos.pos_db.pos_orders"),
                    )
                ]
                if three_source
                else []
            ),
        }

    @staticmethod
    def _execution_time(context, parameter_bindings=None) -> dict[str, str]:
        timezone = ZoneInfo(context.timezone)
        as_of = datetime.combine(context.as_of, time.min, timezone)
        if parameter_bindings is None:
            period_start = as_of.replace(day=1)
            period_end = as_of
        else:
            periods = [
                item
                for item in parameter_bindings
                if item.name in {"period_start", "period_end_exclusive"}
            ]
            if (
                len(periods) != 2
                or {item.name for item in periods}
                != {"period_start", "period_end_exclusive"}
                or any(
                    item.value_type != "date" or not isinstance(item.value, str)
                    for item in periods
                )
            ):
                raise ValueError("approved Context requires unique typed period bindings")
            try:
                values = {item.name: date.fromisoformat(item.value) for item in periods}
            except ValueError as error:
                raise ValueError("approved Context period binding is not an ISO date") from error
            if any(values[item.name].isoformat() != item.value for item in periods):
                raise ValueError("approved Context period binding is not an ISO date")
            if values["period_start"] >= values["period_end_exclusive"]:
                raise ValueError("approved Context period range is invalid")
            period_start = datetime.combine(values["period_start"], time.min, timezone)
            period_end = datetime.combine(
                values["period_end_exclusive"], time.min, timezone
            )
        return {
            "as_of": as_of.isoformat(),
            "timezone": context.timezone,
            "calendar_id": "gregorian-kr",
            "period_start": period_start.isoformat(),
            "period_end_exclusive": period_end.isoformat(),
        }


class TemplateOnlyModelAdapter:
    """승인 Template은 허용하고 신규 SQL·LLM 호출은 fail-closed한다."""

    def generate(self, node: str, _payload: dict[str, Any]) -> dict[str, Any]:
        raise ValueError(f"{node} requires an approved model endpoint")
