from __future__ import annotations

import json
import copy
import re
from datetime import date, datetime, time
from functools import lru_cache, partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlglot import exp, parse_one

from src.ai import schema as ai_schema
from src.ai.prompt_registry import get_prompt
from src.ai.training.benchmark_serving import request_json
from src.modelops.runtime import ModelResponseValidationError, ProductionModelClient


_PROMPT_IDS = {
    "node1": "node1.normalize",
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
    if node == "node1":
        schema = copy.deepcopy(_response_schema(node))
        schema.pop("$defs", None)
        schema["required"].remove("model")
        schema["properties"].pop("model")
        return schema
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
    if node == "node3":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["explanation", "conditions", "sources", "limitations"],
            "properties": {
                "explanation": {"type": "string"},
                "conditions": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
        }
    return _response_schema(node)


def _validate_sql_semantics(node: str, payload: dict[str, Any], sql: str) -> None:
    if node != "node2":
        return
    if "전월 대비" in payload.get("normalized_question", ""):
        required = (
            r"date_add\s*\(\s*'month'\s*,\s*-2",
            r"from_iso8601_timestamp\s*\(",
            r"group\s+by\s+1",
            r"order\s+by\s+1",
        )
        if any(re.search(pattern, sql, flags=re.IGNORECASE) is None for pattern in required):
            raise ModelResponseValidationError(
                "MONTH_WINDOW_INVALID",
                sql,
                "month-over-month SQL must use the approved two-month window",
            )
    dimensions = {
        str(dimension["field"]).rsplit(".", 1)[-1].lower()
        for dimension in payload.get("context_package", {}).get("dimensions", ())
    }
    if dimensions:
        query = parse_one(sql, read="trino")
        projections = list(query.expressions)
        selected = {
            column.name.lower()
            for projection in projections
            for column in projection.find_all(exp.Column)
        }
        grouped = {
            column.name.lower()
            for column in (query.args.get("group") or exp.Group()).find_all(exp.Column)
        }
        for expression in (query.args.get("group") or exp.Group()).expressions:
            if isinstance(expression, exp.Literal) and expression.is_int:
                position = int(expression.this) - 1
                if 0 <= position < len(projections):
                    grouped.update(
                        column.name.lower()
                        for column in projections[position].find_all(exp.Column)
                    )
        ordered = {
            column.name.lower()
            for column in (query.args.get("order") or exp.Order()).find_all(exp.Column)
        }
        aliases = {
            projection.alias.lower(): {
                column.name.lower() for column in projection.find_all(exp.Column)
            }
            for projection in projections
            if projection.alias
        }
        for order in (query.args.get("order") or exp.Order()).expressions:
            expression = order.this if isinstance(order, exp.Ordered) else order
            if isinstance(expression, exp.Column):
                ordered.update(aliases.get(expression.name.lower(), ()))
            elif isinstance(expression, exp.Literal) and expression.is_int:
                position = int(expression.this) - 1
                if 0 <= position < len(projections):
                    ordered.update(
                        column.name.lower()
                        for column in projections[position].find_all(exp.Column)
                    )
        if not all(dimensions.issubset(columns) for columns in (selected, grouped, ordered)):
            raise ModelResponseValidationError(
                "DIMENSION_GROUPING_INVALID",
                sql,
                "SQL must group by every approved requested dimension",
            )


def _complete_aggregate_group_by(sql: str) -> str:
    """Group non-aggregate projections omitted by the model."""
    query = parse_one(sql, read="trino")
    changed = False
    for select in query.find_all(exp.Select):
        if not any(
            isinstance(node, exp.AggFunc)
            for projection in select.expressions
            for node in projection.walk()
        ):
            continue
        group = select.args.get("group")
        grouped = {
            expression.sql(dialect="trino").lower()
            for expression in (group.expressions if group else ())
        }
        grouped_positions = {
            int(expression.this)
            for expression in (group.expressions if group else ())
            if isinstance(expression, exp.Literal) and expression.is_int
        }
        missing = []
        for position, projection in enumerate(select.expressions, 1):
            expression = projection.this if isinstance(projection, exp.Alias) else projection
            if any(isinstance(node, exp.AggFunc) for node in expression.walk()):
                continue
            if (
                position not in grouped_positions
                and expression.sql(dialect="trino").lower() not in grouped
            ):
                missing.append(expression.copy())
        if not missing:
            continue
        select.set(
            "group",
            exp.Group(expressions=[*(group.expressions if group else ()), *missing]),
        )
        changed = True
    return query.sql(dialect="trino") if changed else sql


def _complete_dimension_order_by(sql: str, dimension_fields: set[str]) -> str:
    if not dimension_fields:
        return sql
    query = parse_one(sql, read="trino")
    changed = False
    for select in query.find_all(exp.Select):
        order = select.args.get("order")
        ordered = {
            column.name.lower()
            for column in (order or exp.Order()).find_all(exp.Column)
        }
        missing = dimension_fields - ordered
        if not missing:
            continue
        grouped = select.args.get("group")
        candidates = list(grouped.expressions if grouped else ()) + list(select.expressions)
        additions = []
        for field in sorted(missing):
            expression = next(
                (
                    candidate.this
                    if isinstance(candidate, exp.Alias)
                    else candidate
                    for candidate in candidates
                    if field
                    in {column.name.lower() for column in candidate.find_all(exp.Column)}
                ),
                None,
            )
            if expression is not None:
                additions.append(exp.Ordered(this=expression.copy()))
        if additions:
            select.set(
                "order",
                exp.Order(expressions=[*(order.expressions if order else ()), *additions]),
            )
            changed = True
    return query.sql(dialect="trino") if changed else sql


def _queried_fqns(sql: str) -> set[str]:
    query = parse_one(sql, read="trino")
    return {
        ".".join(part.name for part in table.parts).lower()
        for table in query.find_all(exp.Table)
    }


def _without_snapshot_time_filters(sql: str, time_fields: set[str]) -> str:
    """Current snapshot metrics must not be narrowed by an event-time window."""
    if not time_fields:
        return sql
    query = parse_one(sql, read="trino")
    changed = False
    for select in query.find_all(exp.Select):
        where = select.args.get("where")
        if where is None:
            continue
        predicates = list(where.this.flatten(unnest=False))
        retained = [
            predicate
            for predicate in predicates
            if not {
                column.name.lower() for column in predicate.find_all(exp.Column)
            }.intersection(time_fields)
            and not re.search(
                r":period_(?:start|end(?:_exclusive)?)\b",
                predicate.sql(),
                re.IGNORECASE,
            )
        ]
        if len(retained) == len(predicates):
            continue
        changed = True
        select.set(
            "where",
            exp.Where(this=exp.and_(*retained)) if retained else None,
        )
    return query.sql(dialect="trino") if changed else sql


def openai_transport(
    endpoint: str,
    token: str | None,
    model: str,
    node: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        {
            "model": model,
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"answervice_{node}",
                    "strict": True,
                    "schema": _serving_schema(node),
                },
            },
        },
        token,
        timeout,
    )
    return _complete_chat_response(response, node, payload, model, "openai")


def vllm_transport(
    endpoint: str,
    token: str | None,
    model: str,
    node: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        {
            "model": model,
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"answervice_{node}",
                    "strict": True,
                    "schema": _serving_schema(node),
                },
            },
        },
        token,
        timeout,
    )
    return _complete_chat_response(response, node, payload, model, "vllm")


def _complete_chat_response(
    response: dict[str, Any],
    node: str,
    payload: dict[str, Any],
    model: str,
    adapter: str,
) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelResponseValidationError("ENVELOPE_CHOICES_INVALID", sorted(response))
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ModelResponseValidationError(
            "MESSAGE_CONTENT_MISSING",
            sorted(message) if isinstance(message, dict) else type(message).__name__,
        )
    try:
        result = json.loads(content)
    except json.JSONDecodeError as error:
        raise ModelResponseValidationError("CONTENT_JSON_INVALID", content) from error
    if not isinstance(result, dict):
        raise ModelResponseValidationError("CONTENT_OBJECT_INVALID", content)
    metadata = get_prompt(_PROMPT_IDS[node]).metadata()
    metadata.update(model_version=model, adapter=adapter)
    if node not in {"node2", "node2_repair"}:
        return {**result, "model": metadata}
    sql_field = "sql" if node == "node2" else "corrected_sql"
    if not isinstance(result.get(sql_field), str):
        raise ModelResponseValidationError("SQL_FIELD_INVALID", sorted(result))
    try:
        sql = _complete_aggregate_group_by(result[sql_field])
        dimension_fields = {
            str(item["field"]).rsplit(".", 1)[-1].lower()
            for item in payload["context_package"].get("dimensions", ())
        }
        sql = _complete_dimension_order_by(sql, dimension_fields)
    except (KeyError, TypeError, ValueError) as error:
        raise ModelResponseValidationError("SQL_PARSE_INVALID", result[sql_field]) from error
    try:
        _validate_sql_semantics(node, payload, sql)
    except ModelResponseValidationError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ModelResponseValidationError("SQL_SEMANTICS_INVALID", result[sql_field]) from error
    queried = _queried_fqns(sql)
    package = payload["context_package"]
    join_ids = sorted({item["id"] for item in package["joins"]})
    metric_ids = [item["id"] for item in package["metrics"]]
    referenced_assets = [
        asset for asset in package["assets"] if asset["trino_fqn"].lower() in queried
    ] or list(package["assets"])
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
            for asset in referenced_assets
        ],
        "parameters": [],
        "model": metadata,
    }
    if node == "node2_repair":
        completed.update(trace_id=payload["trace_id"], attempt=payload["attempt"])
    return completed


class NodeModelRouter:
    """Route selected nodes to replaceable model clients without changing the pipeline."""

    def __init__(
        self,
        default_client: ProductionModelClient,
        node_clients: dict[str, ProductionModelClient] | None = None,
    ) -> None:
        self._default = default_client
        self._clients = dict(node_clients or {})
        if not set(self._clients).issubset(_PROMPT_IDS):
            raise ValueError("unsupported node model route")
        self.last_trace: dict[str, Any] = {}

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._clients.get(node, self._default)
        result = client.generate(node, payload)
        self.last_trace = {
            **client.last_trace,
            "route": "override" if node in self._clients else "default",
        }
        return result


class ContractModelAdapter:
    """R3 동결 schema와 R4 내부 plan 형식을 연결한다."""

    def __init__(self, model) -> None:
        self._model = model

    @classmethod
    def from_openai(
        cls,
        endpoint: str,
        token: str | None = None,
        model: str = "gpt-4.1-mini",
        timeout_seconds: float = 15.0,
        node2_endpoint: str | None = None,
        node2_token: str | None = None,
        node2_model: str = "answervice-sql-lora-qwen3.5-4b",
    ) -> ContractModelAdapter:
        if not endpoint or not token or not model:
            raise ValueError("OpenAI endpoint, API key, and model are required")
        default_client = ProductionModelClient(
            partial(openai_transport, endpoint, token, model),
            timeout_seconds=timeout_seconds,
        )
        node_clients: dict[str, ProductionModelClient] = {}
        if node2_endpoint:
            node2_client = ProductionModelClient(
                partial(
                    vllm_transport,
                    node2_endpoint,
                    node2_token,
                    node2_model,
                ),
                timeout_seconds=timeout_seconds,
            )
            node_clients = {"node2": node2_client, "node2_repair": node2_client}
        return cls(NodeModelRouter(default_client, node_clients))

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        if node == "node1":
            return self._generate(node, payload)
        if node == "node2":
            snapshot_time_fields = self._snapshot_time_fields(payload["package"])
            response = self._generate(
                node,
                {
                    "question_id": payload["request_id"],
                    "normalized_question": payload["question"],
                    "context_package": self._context_package(payload),
                },
            )
            return self._plan(
                response,
                "sql",
                payload["package"].parameter_bindings,
                snapshot_time_fields,
            )
        if node == "node2_repair":
            snapshot_time_fields = self._snapshot_time_fields(payload["package"])
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
                response,
                "corrected_sql",
                payload["package"].parameter_bindings,
                snapshot_time_fields,
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
            current_snapshot = any(
                metric.get("temporal_semantics") == "current_snapshot"
                for asset in payload["assets"]
                for metric in asset.get("metrics", ())
                if isinstance(metric, dict)
            )
            return {
                "summary": response["explanation"] + (
                    " 현재 활성 회원 기준 스냅샷이며, 가입일 기간이나 과거 월말 잔액으로 해석하지 않습니다."
                    if current_snapshot
                    else ""
                ),
                "model_version": response["model"]["model_version"],
            }
        raise ValueError(f"unsupported node: {node}")

    @staticmethod
    def _snapshot_time_fields(package) -> set[str]:
        metrics = tuple(package.metrics)
        if not metrics or any(
            metric.temporal_semantics != "current_snapshot" for metric in metrics
        ):
            return set()
        return {metric.time_field.lower() for metric in metrics}

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
        selected = set(metric_ids)
        if selected:
            selected_metric = metric_ids[0]
            context_metric_ids = metric_ids
        else:
            approved_join = "pms_crm_pos_gold_revenue_month_v1"
            if (
                selected
                or len(assets) != 6
                or len({asset.get("urn") for asset in assets}) != 6
                or any(approved_join not in asset.get("join_ids", ()) for asset in assets)
            ):
                raise ValueError("node3 requires exactly one entitled Context metric")
            selected_metric = "total_guest_revenue_krw"
            context_metric_ids = [selected_metric] * len(assets)

        explicit_entitlements = [
            str(metric_id)
            for asset in assets
            for metric_id in asset.get("entitled_metric_ids", ())
        ]
        entitled_metric_ids = set(explicit_entitlements) or selected or {selected_metric}
        if selected_metric not in entitled_metric_ids:
            raise ValueError("node3 selected metric is outside entitlement")
        return {
            "selected_metric_id": selected_metric,
            "selected_metric_ids": metric_ids or [selected_metric],
            "context_metric_ids": context_metric_ids,
            "entitled_metric_ids": sorted(entitled_metric_ids),
        }

    def _generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._model.generate(node, payload)

    @staticmethod
    def _plan(
        response: dict[str, Any],
        sql_field: str,
        parameter_bindings=(),
        snapshot_time_fields=frozenset(),
    ) -> dict[str, Any]:
        sql = _without_snapshot_time_filters(
            response[sql_field], set(snapshot_time_fields)
        )
        expected = {item.name: item for item in parameter_bindings}
        if "period_end_exclusive" in expected and ":period_end" in sql:
            sql = re.sub(r":period_end(?![a-z0-9_])", ":period_end_exclusive", sql)
        for name, binding in expected.items():
            if binding.value_type == "date":
                sql = re.sub(
                    rf"DATE\s+'{re.escape(str(binding.value))}'",
                    f"DATE ':{name}'",
                    sql,
                    flags=re.IGNORECASE,
                )
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
        supplied = dict(zip(names, response_parameters))
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
                        "value": (
                            supplied[name]["value"]
                            if name in supplied
                            else expected[name].value
                        ),
                    }
                    if name in expected
                    else supplied[name]["value"]
                )
                for name in placeholders
                if name in supplied or name in expected
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
        three_source = (
            "pms_crm_pos_gold_revenue_month_v1" in package.approved_join_ids
        )
        derived_metric = None
        execution_time = cls._execution_time(
            context, package.parameter_bindings if three_source else None
        )
        if not metrics and three_source:
            derived_metric = {
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
                    "temporal_semantics": metric.temporal_semantics,
                    "required_filters": [
                        {
                            "field": item.field,
                            "operator": item.operator,
                            "value_type": item.value_type,
                            "value": item.value,
                        }
                        for item in metric.required_filters
                    ],
                }
                for metric in metrics
            ] + ([derived_metric] if derived_metric else []),
            "dimensions": [
                {
                    "id": dimension.id,
                    "field": f"{dimension.asset_fqn}.{dimension.field}",
                }
                for dimension in package.dimensions
            ],
            "parameter_bindings": [
                {
                    "name": item.name,
                    "value_type": item.value_type,
                    "value": item.value,
                }
                for item in package.parameter_bindings
            ],
            "joins": [
                {
                    "id": item.id,
                    "left": item.left,
                    "right": item.right,
                    "cardinality": item.cardinality,
                    "status": "approved",
                    "on_predicates": list(item.on_predicates),
                }
                for item in package.join_policies
            ],
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
