from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time
from functools import lru_cache, partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ai import schema as ai_schema
from src.ai.metric_glossary import metric_display_name, metric_glossary
from src.ai.prompt_registry import get_prompt
from src.ai.training.benchmark_serving import request_json
from src.modelops.runtime import ProductionModelClient


logger = logging.getLogger("uvicorn.error")


def _sql_fingerprint(sql: Any) -> str:
    return hashlib.sha256(str(sql or "").encode("utf-8")).hexdigest()[:16]


_PROMPT_IDS = {
    "node1": "node1.normalize",
    "node2": "node2.sql",
    "node2_repair": "node2.repair",
    "node3": "node3.explain",
    "report_assistant": "report.assistant",
}

@lru_cache(maxsize=None)
def _response_schema(node: str) -> dict[str, Any]:
    path = Path(ai_schema.__file__).with_name("contracts") / "node_io.v0.1.json"
    with path.open(encoding="utf-8") as schema_file:
        bundle = json.load(schema_file)
    return {"$defs": bundle["$defs"], **bundle["$defs"][f"{node}_response"]}


def _serving_schema(node: str) -> dict[str, Any]:
    if node == "node1":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "normalized_question",
                "intent_candidates",
                "metric_candidates",
                "selected_metric_id",
                "dimension_candidates",
                "period_candidates",
                "ambiguity",
            ],
            "properties": {
                "normalized_question": {"type": "string"},
                "intent_candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "metric_candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "selected_metric_id": {"type": ["string", "null"]},
                "dimension_candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "period_candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["start", "end_exclusive", "source_text"],
                        "properties": {
                            "start": {"type": "string", "format": "date-time"},
                            "end_exclusive": {
                                "type": "string",
                                "format": "date-time",
                            },
                            "source_text": {"type": "string"},
                        },
                    },
                },
                "ambiguity": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "is_ambiguous",
                        "reasons",
                        "clarification_question",
                    ],
                    "properties": {
                        "is_ambiguous": {"type": "boolean"},
                        "reasons": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "clarification_question": {"type": ["string", "null"]},
                    },
                },
            },
        }
    if node == "node2":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["sql", "used_assets", "used_metrics"],
            "properties": {
                "sql": {"type": "string"},
                "used_assets": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "used_metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
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
                name: {"type": "string"}
                if name == "explanation"
                else {"type": "array", "items": {"type": "string"}}
                for name in ("explanation", "conditions", "sources", "limitations")
            },
        }
    if node == "report_assistant":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "executive_summary", "table_title", "chart_title"],
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 255},
                "executive_summary": {"type": "string", "minLength": 1, "maxLength": 4000},
                "table_title": {"type": "string", "minLength": 1, "maxLength": 255},
                "chart_title": {"type": "string", "minLength": 1, "maxLength": 255},
            },
        }
    raise ValueError(f"unsupported serving schema node: {node}")


def _model_metadata(node: str, model: str) -> dict[str, Any]:
    metadata = get_prompt(_PROMPT_IDS[node]).metadata()
    metadata["adapter"] = model if node in {"node2", "node2_repair"} else None
    metadata["model_version"] = model
    return metadata


def _openai_payload(model: str, node: str, payload: dict[str, Any]) -> dict[str, Any]:
    schema = _serving_schema(node)
    return {
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
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"answervice_{node}_response",
                "strict": True,
                "schema": schema,
            },
        },
    }


def _filter_sql(item: dict[str, Any]) -> str:
    value = item["value"]
    if isinstance(value, bool):
        literal = "true" if value else "false"
    elif isinstance(value, str):
        literal = "'" + value.replace("'", "''") + "'"
    else:
        literal = str(value)
    field = str(item["field"])
    if item.get("asset_fqn"):
        field = f"{item['asset_fqn']}.{field.rsplit('.', 1)[-1]}"
    return f"{field} = {literal}"


@lru_cache(maxsize=1)
def _approved_column_types() -> dict[str, dict[str, str]]:
    root = Path(__file__).resolve().parents[4]
    contract = json.loads(
        (root / "src" / "data" / "serving_analytics_contract.i4.v1.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        str(view["fqn"]): {
            str(name): str(trino_type)
            for name, trino_type in view["columns"].items()
        }
        for view in contract["views"]
    }


@lru_cache(maxsize=1)
def _three_source_source_predicates() -> dict[str, list[str]]:
    root = Path(__file__).resolve().parents[4]
    contract = json.loads(
        (root / "src" / "data" / "pms_crm_pos_context.i5.v1.json").read_text(
            encoding="utf-8"
        )
    )
    predicates = contract.get("approved_source_predicates")
    if not isinstance(predicates, dict) or not predicates:
        raise ValueError("three-source approved source predicates are missing")
    return {
        str(source): [str(predicate) for predicate in values]
        for source, values in predicates.items()
        if isinstance(values, list) and values
    }


def _seal_sql_parameters(
    sql: str,
    package: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    sealed = sql
    execution = package["execution_time"]
    parameters: list[dict[str, Any]] = []
    for name in ("period_start", "period_end_exclusive"):
        value = str(execution[name])[:10]
        sealed = re.sub(
            rf"(\bDATE\s*)'{re.escape(value)}(?:T00:00:00(?:Z|[+-]\d{{2}}:\d{{2}})?)?'",
            lambda match, parameter=name: f"{match.group(1)}':{parameter}'",
            sealed,
            flags=re.IGNORECASE,
        )
        sealed = re.sub(
            rf"(\bTIMESTAMP(?:\s+WITH\s+TIME\s+ZONE)?\s*)'{re.escape(value)}([^']*)'",
            lambda match, parameter=name: (
                f"{match.group(1)}':{parameter}{match.group(2)}'"
            ),
            sealed,
            flags=re.IGNORECASE,
        )
        sealed = re.sub(
            rf"(\bfrom_iso8601_timestamp\s*\(\s*)'{re.escape(value)}([^']*)'",
            lambda match, parameter=name: (
                f"{match.group(1)}':{parameter}{match.group(2)}'"
            ),
            sealed,
            flags=re.IGNORECASE,
        )
        sealed = re.sub(
            rf"'{re.escape(value)}'",
            lambda _match, parameter=name: f":{parameter}",
            sealed,
        )
        parameters.append({"name": name, "value_type": "date", "value": value})

    required_filters = [
        item
        for metric in package["metrics"]
        for item in metric.get("required_filters", ())
    ]
    for index, item in enumerate(required_filters, start=1):
        name = str(item.get("parameter_name") or f"required_filter_{index}")
        value = item["value"]
        if isinstance(value, bool):
            literal = "true" if value else "false"
        elif isinstance(value, str):
            literal = "'" + value.replace("'", "''") + "'"
        else:
            literal = str(value)
        literal_candidates = [literal]
        if item["value_type"] == "number" and value in {0, 1}:
            literal_candidates.append("false" if value == 0 else "true")
        field = re.escape(str(item["field"]).rsplit(".", 1)[-1])
        asset_fqn = str(item.get("asset_fqn") or "")
        aliases: set[str] = set()
        if asset_fqn:
            fqn_pattern = r"\.".join(
                rf'"?{re.escape(part)}"?' for part in asset_fqn.split(".")
            )
            aliases = {
                alias
                for alias in re.findall(
                    rf"\b(?:from|join)\s+{fqn_pattern}\s+(?:as\s+)?([a-z_][a-z0-9_]*)",
                    sealed,
                    flags=re.IGNORECASE,
                )
                if alias.lower()
                not in {
                    "on",
                    "where",
                    "join",
                    "full",
                    "left",
                    "right",
                    "inner",
                    "cross",
                }
            }
        patterns = [
            rf"(?<![a-z0-9_]){re.escape(alias)}\s*\.\s*\"?{field}\"?"
            for alias in sorted(aliases)
        ]
        if not asset_fqn or (not aliases and len(package["assets"]) == 1):
            patterns = [rf"(?<![a-z0-9_])(?:[a-z_][a-z0-9_]*\.)?\"?{field}\"?"]
        for pattern in patterns:
            for candidate in literal_candidates:
                sealed = re.sub(
                    rf"({pattern}\s*=\s*){re.escape(candidate)}(?![a-z0-9_])",
                    lambda match, parameter=name: f"{match.group(1)}:{parameter}",
                    sealed,
                    flags=re.IGNORECASE,
                )
        parameters.append(
            {
                "name": name,
                "value_type": item["value_type"],
                "value": value,
            }
        )
    return sealed, parameters


def _node2_training_input(payload: dict[str, Any]) -> dict[str, Any]:
    package = payload["context_package"]
    execution = package["execution_time"]
    metrics = package["metrics"]
    filters = [
        _filter_sql(item)
        for metric in metrics
        for item in metric.get("required_filters", ())
    ]
    datasets = []
    approved_types = _approved_column_types()
    for asset in package["assets"]:
        column_types = asset.get("column_types") or approved_types.get(
            asset["trino_fqn"], {}
        )
        datasets.append(
            {
                "fqn": asset["trino_fqn"],
                "description_ko": "Backend가 승인한 Context dataset",
                "grain_ko": "승인된 dataset grain",
                "columns": [
                    {
                        "name": column,
                        "role": "field",
                        "semantic_type": column,
                        "trino_type": column_types.get(column, "unknown"),
                    }
                    for column in asset["columns"]
                ],
            }
        )
    approved_metrics = []
    for metric in metrics:
        field = metric["field"].rsplit(".", 1)[-1]
        asset = metric["field"].rsplit(".", 1)[0]
        approved_metrics.append(
            {
                "id": metric["id"],
                "alias": metric["id"],
                "asset": asset,
                "calculation_sql": f"{metric['aggregation'].upper()}({field})",
                "description_ko": "Backend가 승인한 metric",
                "label_ko": metric["id"],
                "required_columns": [field],
                "required_filters": [
                    _filter_sql(item) for item in metric.get("required_filters", ())
                ],
                "time_field": metric["time_field"].rsplit(".", 1)[-1],
                "allowed_dimensions": [],
            }
        )
    dimensions = list(
        (payload.get("structured_request") or {}).get("dimension_candidates", ())
    )
    return {
        "structured_request": {
            "metric_ids": [metric["id"] for metric in metrics],
            "dimensions": dimensions,
            "filters": filters,
            "period": {
                "start": execution["period_start"][:10],
                "end": execution["period_end_exclusive"][:10],
                "boundary": "half_open",
                "timezone": execution["timezone"],
            },
            "sort": [],
            "limit": 1000,
        },
        "approved_context": {
            "context_version": package["context_version"],
            "datasets": datasets,
            "metrics": approved_metrics,
            "approved_joins": package["joins"],
            "required_source_predicates": package.get("required_source_predicates", {}),
            "identity_rules": [],
            "permission_scope": {
                "role": "approved_backend_user",
                "allowed_assets": [asset["trino_fqn"] for asset in package["assets"]],
                "synthetic_only": True,
            },
            "query_policy": {
                "dialect": "trino",
                "single_read_only_statement": True,
                "require_limit": True,
                "maximum_limit": 1000,
                "timezone": execution["timezone"],
            },
            "time_rules": [
                {
                    "id": "kst_half_open_period_v1",
                    "description_ko": "Backend가 확정한 시작 이상·종료 미만 기간",
                }
            ],
        },
    }


def _qwen_payload(model: str, node: str, payload: dict[str, Any]) -> dict[str, Any]:
    if node == "node2":
        user_payload = _node2_training_input(payload)
    else:
        user_payload = payload
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": get_prompt(_PROMPT_IDS[node]).text,
            },
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 1_280,
        "chat_template_kwargs": {"enable_thinking": False},
        "guided_json": _serving_schema(node),
    }


def _validate_sql_semantics(node: str, payload: dict[str, Any], sql: str) -> None:
    if node == "node2":
        for metric in (payload.get("context_package") or {}).get("metrics", ()):
            field = re.escape(metric["field"].rsplit(".", 1)[-1])
            aggregation = str(metric["aggregation"]).lower()
            if aggregation == "sum" and re.search(
                rf"\bsum\s*\(\s*(?:[a-z_][a-z0-9_]*\.)?\"?{field}\"?\s*\)",
                sql,
                flags=re.IGNORECASE,
            ) is None:
                raise ValueError(
                    "model SQL does not apply the approved metric aggregation"
                )
        dimensions = (payload.get("structured_request") or {}).get(
            "dimension_candidates", ()
        )
        join_ids = {
            str(item.get("id"))
            for item in (payload.get("context_package") or {}).get("joins", ())
            if isinstance(item, dict)
        }
        if (
            not dimensions
            and "pms_crm_pos_gold_revenue_month_v1" not in join_ids
            and "전월 대비" not in str(payload.get("normalized_question", ""))
            and re.search(r"\bgroup\s+by\b", sql, re.IGNORECASE)
        ):
            raise ValueError(
                "model SQL groups by dimensions absent from the structured request"
            )
        if dimensions and re.search(r"\border\s+by\b", sql, re.IGNORECASE) is None:
            raise ValueError("model SQL does not apply the requested dimension sort")
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
    *,
    model: str = "Qwen/Qwen3-4B",
    provider: str = "qwen",
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        _qwen_payload(model, node, payload)
        if provider == "qwen"
        else _openai_payload(model, node, payload),
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
    expected_fields = set(_serving_schema(node)["required"])
    if set(result) != expected_fields:
        raise ValueError("model content fields do not match the serving schema")
    if node not in {"node2", "node2_repair"}:
        result["model"] = _model_metadata(node, model)
        return result
    sql_field = "sql" if node == "node2" else "corrected_sql"
    sql, parameters = _seal_sql_parameters(result[sql_field], payload["context_package"])
    try:
        _validate_sql_semantics(node, payload, sql)
    except ValueError as error:
        logger.warning(
            "generated SQL rejected: node=%s reason=%s sql_sha256=%s",
            node,
            error,
            _sql_fingerprint(sql),
        )
        raise
    cte_names = {
        name.lower()
        for name in re.findall(
            r"(?:\bwith\b|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(",
            sql,
            flags=re.IGNORECASE,
        )
    }
    queried = {
        table.strip('"').lower()
        for table in re.findall(
            r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)",
            sql,
            flags=re.IGNORECASE,
        )
        if table.strip('"').lower() not in cte_names
    }
    package = payload["context_package"]
    if node == "node2":
        approved_assets = {item["trino_fqn"].lower() for item in package["assets"]}
        approved_metrics = {item["id"] for item in package["metrics"]}
        used_assets = {str(item).lower() for item in result["used_assets"]}
        used_metrics = {str(item) for item in result["used_metrics"]}
        if used_assets != queried or not used_assets.issubset(approved_assets):
            raise ValueError("model used_assets do not match approved SQL assets")
        if not used_metrics or not used_metrics.issubset(approved_metrics):
            raise ValueError("model used_metrics are outside approved Context")
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
        "parameters": parameters,
        "model": _model_metadata(node, model),
    }
    if node == "node2_repair":
        completed.update(trace_id=payload["trace_id"], attempt=payload["attempt"])
    return completed


class RoutedProductionModelClient:
    def __init__(
        self,
        openai_client: ProductionModelClient,
        node2_client: ProductionModelClient,
    ) -> None:
        self._openai_client = openai_client
        self._node2_client = node2_client
        self.last_trace: dict[str, Any] = {}

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = (
            self._node2_client
            if node in {"node2", "node2_repair"}
            else self._openai_client
        )
        result = client.generate(node, payload)
        self.last_trace = dict(client.last_trace)
        return result


class ContractModelAdapter:
    """R3 동결 schema와 R4 내부 plan 형식을 연결한다."""

    def __init__(self, model) -> None:
        if model is None:
            raise ValueError("a production model client is required")
        self._model = model
        self.last_trace: dict[str, Any] = {}

    @classmethod
    def from_openai(
        cls,
        endpoint: str,
        token: str | None = None,
        model: str = "",
        timeout_seconds: float = 15.0,
    ) -> ContractModelAdapter:
        if not endpoint or not token or not model:
            raise ValueError("OPENAI_ENDPOINT, OPENAI_API_KEY, and OPENAI_MODEL are required")
        return cls(
            ProductionModelClient(
                partial(
                    openai_transport,
                    endpoint,
                    token,
                    model=model,
                    provider="openai",
                ),
                timeout_seconds=timeout_seconds,
            )
        )

    @classmethod
    def from_endpoints(
        cls,
        *,
        openai_endpoint: str,
        openai_token: str,
        openai_model: str,
        node2_endpoint: str,
        node2_token: str,
        node2_model: str,
        node2_provider: str = "openai",
        timeout_seconds: float = 60.0,
    ) -> ContractModelAdapter:
        if node2_provider not in {"openai", "qwen"}:
            raise ValueError(f"unsupported NODE2_MODEL_PROVIDER: {node2_provider}")
        required = {
            "OPENAI_ENDPOINT": openai_endpoint,
            "OPENAI_API_KEY": openai_token,
            "OPENAI_MODEL": openai_model,
            "NODE2_MODEL_ENDPOINT": node2_endpoint,
            "NODE2_MODEL_API_TOKEN": node2_token,
            "NODE2_MODEL": node2_model,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing model configuration: {', '.join(missing)}")
        openai_client = ProductionModelClient(
            partial(
                openai_transport,
                openai_endpoint,
                openai_token,
                model=openai_model,
                provider="openai",
            ),
            timeout_seconds=timeout_seconds,
        )
        node2_client = ProductionModelClient(
            partial(
                openai_transport,
                node2_endpoint,
                node2_token,
                model=node2_model,
                provider=node2_provider,
            ),
            timeout_seconds=timeout_seconds,
            max_attempts=3,
        )
        return cls(RoutedProductionModelClient(openai_client, node2_client))

    def normalize_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._generate("node1", payload)

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        if node == "node1":
            return self.normalize_question(payload)
        if node == "node2":
            context_package = self._context_package(payload)
            response = self._generate(
                node,
                {
                    "question_id": payload["request_id"],
                    "normalized_question": payload["question"],
                    "structured_request": payload.get("structured_request")
                    or {
                        "intent_candidates": [],
                        "dimension_candidates": [],
                        "period_candidates": [],
                    },
                    "context_package": context_package,
                },
            )
            try:
                return self._plan(
                    response, "sql", payload["package"].parameter_bindings
                )
            except (TypeError, ValueError) as error:
                logger.warning(
                    "generated plan rejected: node=%s reason=%s sql_sha256=%s",
                    node,
                    error,
                    _sql_fingerprint(response.get("sql")),
                )
                raise
        if node == "node2_repair":
            context_package = self._context_package(payload)
            response = self._generate(
                node,
                {
                    "trace_id": payload["trace_id"],
                    "attempt": 1,
                    "rejected_sql": payload["rejected_sql"],
                    "context_package": context_package,
                    "normalized_error_code": payload["violation"],
                    "violation_detail": payload["violation_detail"],
                    "repair_scope": ["sql"],
                },
            )
            try:
                return self._plan(
                    response,
                    "corrected_sql",
                    payload["package"].parameter_bindings,
                )
            except (TypeError, ValueError) as error:
                logger.warning(
                    "generated plan rejected: node=%s reason=%s sql_sha256=%s",
                    node,
                    error,
                    _sql_fingerprint(response.get("corrected_sql")),
                )
                raise
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
                    "metric_label": self._metric_label(selected_metric),
                    "metric_selection": metric_selection,
                    "period": self._execution_time(
                        context,
                        getattr(payload.get("package"), "parameter_bindings", None),
                    ),
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
    def _metric_label(metric_id: str) -> str:
        return metric_display_name(metric_id)

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
        transport_trace = dict(getattr(self._model, "last_trace", {}))
        model_metadata = response.get("model", {}) if isinstance(response, dict) else {}
        prompt_metadata = get_prompt(_PROMPT_IDS[node]).metadata()
        self.last_trace = {
            **transport_trace,
            "node": node,
            "model_version": model_metadata.get("model_version"),
            "prompt_id": prompt_metadata["prompt_id"],
            "prompt_version": prompt_metadata["version"],
            "prompt_hash": prompt_metadata["hash"],
        }
        if transport_trace.get("fallback"):
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
        ordered_filters = (
            *package.required_filters,
            *(item for metric in package.metrics for item in metric.required_filters),
        )
        parameter_names = {
            id(item): f"required_filter_{index}"
            for index, item in enumerate(ordered_filters, start=1)
        }

        def required_filter_payload(item) -> dict[str, Any]:
            matching_assets = [
                asset.fqn
                for asset in package.assets
                if item.field == asset.fqn or item.field.startswith(f"{asset.fqn}.")
            ]
            if not matching_assets:
                raise ValueError(
                    f"required filter field is outside approved assets: {item.field}"
                )
            return {
                "field": item.field,
                "asset_fqn": max(matching_assets, key=len),
                "operator": item.operator,
                "parameter_name": parameter_names[id(item)],
                "value_type": item.value_type,
                "value": item.value,
            }

        assets = [
            {
                "urn": item.urn,
                "trino_fqn": item.fqn,
                "columns": list(item.columns),
                "column_types": dict(item.column_types),
            }
            for item in package.assets
        ]
        metrics = list(package.metrics)
        derived_metric = None
        three_source = (
            "pms_crm_pos_gold_revenue_month_v1" in package.approved_join_ids
        )
        stay_crm_join = (
            "pms_stay_to_crm_membership_grade_event_time_v1"
            in package.approved_join_ids
        )
        execution_time = cls._execution_time(
            context, package.parameter_bindings or None
        )
        if not metrics and three_source:
            derived_metric = {
                "id": "total_guest_revenue_krw",
                "field": "derived.total_guest_revenue_krw",
                "aggregation": "derived_sum",
                "time_field": "derived.month",
                "required_filters": [
                    required_filter_payload(item)
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
                    "required_filters": [
                        {
                            "field": item.field,
                            "asset_fqn": metric.asset_fqn,
                            "operator": item.operator,
                            "parameter_name": parameter_names[id(item)],
                            "value_type": item.value_type,
                            "value": item.value,
                        }
                        for item in metric.required_filters
                    ],
                }
                for metric in metrics
            ] + ([derived_metric] if derived_metric else []),
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
                else [
                    {
                        "id": "pms_stay_to_crm_membership_grade_event_time_v1",
                        "left": left,
                        "right": right,
                        "cardinality": "many_to_one_event_time",
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
                    )
                ]
                if stay_crm_join
                else []
            ),
            "required_source_predicates": (
                _three_source_source_predicates() if three_source else {}
            ),
        }

    @staticmethod
    def _execution_time(context, parameter_bindings=None) -> dict[str, str]:
        timezone = ZoneInfo(context.timezone)
        as_of = datetime.combine(context.as_of, time.min, timezone)
        periods = [
            item
            for item in (parameter_bindings or ())
            if item.name in {"period_start", "period_end_exclusive"}
        ]
        if not periods:
            period_start = as_of.replace(day=1)
            period_end = as_of
        else:
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
