from __future__ import annotations

import copy
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.adapters.contract_model import ContractModelAdapter, _openai_payload, _qwen_payload
from app.adapters.model_schemas import (
    canonical_model_input,
    serving_schema,
    sql_only_serving_schema,
)
from app.adapters.model_transport import openai_transport
from src.ai.schema import ContractError, validate_payload
from src.modelops.runtime import _TRANSPORT_META_KEY
from tests.ai.test_contracts import VALID_PAYLOADS


def _contracts(catalog: str = "orbit") -> dict:
    fqn = f"{catalog}.ops.event_fact"
    return {
        "schema_context": {
            "version": "context-runtime-7",
            "assets": [
                {
                    "urn": f"urn:test:{fqn}",
                    "fqn": fqn,
                    "grain": {"kind": "event", "keys": ["occurred_on"]},
                    "columns": [
                        {
                            "name": "occurred_on",
                            "native_type": "date",
                            "nullable": False,
                            "role": "time",
                        },
                        {
                            "name": "amount",
                            "native_type": "double",
                            "nullable": False,
                            "role": "measure",
                        },
                    ],
                }
            ],
        },
        "metric_rules": [
            {
                "id": "governed_amount",
                "source": {
                    "kind": "column",
                    "field": {"asset_fqn": fqn, "column": "amount"},
                },
                "aggregation": "sum",
                "result_field": "governed_total",
                "unit": "credits",
                "time_field": {"asset_fqn": fqn, "column": "occurred_on"},
                "dimensions": [],
                "required_filters": [],
            }
        ],
        "join_graph": {"edges": []},
        "time_rules": {
            "timezone": "Asia/Seoul",
            "calendar_id": "gregorian-kr",
            "interval": "[start,end)",
            "start_parameter": "window_begin",
            "end_parameter": "window_stop",
            "fields": [
                {
                    "field": {"asset_fqn": fqn, "column": "occurred_on"},
                    "native_type": "date",
                    "bucket": "day",
                    "timezone_mode": "preserve",
                }
            ],
        },
        "parameter_contract": {
            "style": "named",
            "parameters": [
                {"name": "window_begin", "type": "date", "scope": "time"},
                {"name": "window_stop", "type": "date", "scope": "time"},
            ],
        },
        "query_policy": {
            "dialect": "trino",
            "statement_type": "select",
            "read_only": True,
            "require_limit": True,
            "max_limit": 100,
            "allowed_functions": ["SUM", "CAST"],
            "allowed_catalogs": [catalog],
        },
    }


def _runtime_contracts(catalog: str = "orbit") -> dict:
    """봉인 provider 계약에 runtime-only asset filter registry를 결합한다."""

    contracts = _contracts(catalog)
    contracts["filter_rules"] = []
    return contracts


def _node2_payload(catalog: str = "orbit") -> dict:
    return {
        "question_id": "request-arbitrary-1",
        "normalized_question": "Summarize the governed amount for the selected interval.",
        "structured_request": {
            "intent_candidates": ["aggregate"],
            "metric_ids": ["governed_amount"],
            "selected_metric_ids": ["governed_amount"],
            "dimension_fields": [],
        },
        "context_package": _contracts(catalog),
    }


def _node2_response(catalog: str = "orbit") -> dict:
    fqn = f"{catalog}.ops.event_fact"
    return {
        "sql": (
            f"SELECT SUM(e.amount) AS governed_total FROM {fqn} AS e "
            "WHERE e.occurred_on >= CAST(:window_begin AS DATE) "
            "AND e.occurred_on < CAST(:window_stop AS DATE) LIMIT 100"
        ),
        "used_assets": [fqn],
        "used_columns": [
            {"asset_fqn": fqn, "column": "amount"},
            {"asset_fqn": fqn, "column": "occurred_on"},
        ],
        "used_joins": [],
        "used_metrics": ["governed_amount"],
    }


@pytest.mark.parametrize("catalog", ["orbit", "cobalt"])
def test_provider_input_uses_the_six_runtime_contracts(catalog: str) -> None:
    payload = _node2_payload(catalog)
    model_input = canonical_model_input("node2", payload)

    validate_payload("node2_request", model_input)

    assert set(model_input) == {
        "question_id",
        "normalized_question",
        "resolved_request",
        "schema_context",
        "metric_rules",
        "join_graph",
        "time_rules",
        "parameter_contract",
        "query_policy",
    }
    assert all("value" not in item for item in model_input["parameter_contract"]["parameters"])
    assert model_input["resolved_request"]["intent"] == "aggregate"
    assert model_input["resolved_request"]["time_bucket"] == "none"
    assert model_input["resolved_request"]["result_limit"] is None
    assert set(serving_schema("node2")["required"]) == set(_node2_response(catalog))


def test_ratio_request_deduplicates_shared_dimensions_and_filters() -> None:
    contracts = _contracts()
    fqn = "orbit.ops.event_fact"
    shared_dimension = {"asset_fqn": fqn, "column": "occurred_on"}
    shared_filter = {
        "field": shared_dimension,
        "operator": "gte",
        "parameter": "window_begin",
    }
    numerator = copy.deepcopy(contracts["metric_rules"][0])
    numerator.update(
        {
            "id": "occupied_rooms",
            "dimensions": [shared_dimension],
            "required_filters": [shared_filter],
        }
    )
    denominator = copy.deepcopy(numerator)
    denominator["id"] = "available_rooms"
    ratio = {
        "id": "occupancy_rate",
        "source": {
            "kind": "ratio",
            "numerator_metric_id": "occupied_rooms",
            "denominator_metric_id": "available_rooms",
            "zero_policy": "null_on_zero_denominator",
        },
        "aggregation": "ratio",
        "result_field": "occupancy_rate",
        "unit": "percent",
        "time_field": None,
        "dimensions": [],
        "required_filters": [],
    }
    contracts["metric_rules"] = [ratio, numerator, denominator]
    payload = _node2_payload()
    payload["context_package"] = contracts
    payload["structured_request"]["metric_ids"] = [
        "available_rooms",
        "occupancy_rate",
        "occupied_rooms",
    ]
    payload["structured_request"]["selected_metric_ids"] = ["occupancy_rate"]
    payload["structured_request"]["dimension_fields"] = [shared_dimension]

    model_input = canonical_model_input("node2", payload)

    validate_payload("node2_request", model_input)
    assert model_input["resolved_request"]["output_metric_ids"] == ["occupancy_rate"]
    assert model_input["resolved_request"]["dimensions"] == [shared_dimension]
    assert model_input["resolved_request"]["filters"] == [shared_filter]


def test_available_metric_dimensions_are_not_grouped_without_user_selection() -> None:
    contracts = _contracts()
    dimension = {"asset_fqn": "orbit.ops.event_fact", "column": "occurred_on"}
    contracts["metric_rules"][0]["dimensions"] = [dimension]
    payload = _node2_payload()
    payload["context_package"] = contracts

    model_input = canonical_model_input("node2", payload)

    assert model_input["resolved_request"]["dimensions"] == []


def test_node2_rejects_implicit_business_outputs() -> None:
    payload = _node2_payload()
    payload["structured_request"].pop("selected_metric_ids")

    with pytest.raises(ValueError, match="explicit BUSINESS output"):
        canonical_model_input("node2", payload)


def test_sql_only_schema_is_dormant_while_active_provider_schema_remains_legacy() -> None:
    active = serving_schema("node2")
    sql_only = sql_only_serving_schema("node2")

    assert set(active["required"]) == {
        "sql",
        "used_assets",
        "used_columns",
        "used_joins",
        "used_metrics",
    }
    assert sql_only["required"] == ["sql"]
    assert set(sql_only["properties"]) == {"sql"}


def test_openai_and_qwen_use_identical_canonical_messages() -> None:
    payload = canonical_model_input("node2", _node2_payload())

    openai = _openai_payload("gpt-5.4-mini", "node2", payload)
    qwen = _qwen_payload("answervice-sql", "node2", payload)

    assert openai["messages"] == qwen["messages"]
    assert json.loads(openai["messages"][1]["content"]) == payload
    assert openai["max_completion_tokens"] == 1_280
    assert qwen["max_tokens"] == 1_280


def test_openai_and_qwen_schema_dual_adaptation() -> None:
    payload = canonical_model_input("node2", _node2_payload())

    openai = _openai_payload("gpt-5.4-mini", "node2", payload)
    qwen = _qwen_payload("answervice-sql", "node2", payload)

    openai_schema = openai["response_format"]["json_schema"]["schema"]
    qwen_schema = qwen["guided_json"]

    # 1. OpenAI Strict Schema Verification
    assert openai["response_format"]["json_schema"]["strict"] is True
    assert openai_schema["type"] == "object"
    assert openai_schema["additionalProperties"] is False
    assert set(openai_schema["required"]) == set(openai_schema["properties"].keys())
    assert "minItems" not in openai_schema["properties"]["used_assets"]
    assert "uniqueItems" not in openai_schema["properties"]["used_assets"]
    assert "minLength" not in openai_schema["properties"]["sql"]
    assert "$defs" in openai_schema
    assert set(openai_schema["$defs"].keys()) == {"qualified_field"}  # tree-shaked
    assert openai_schema["$defs"]["qualified_field"]["additionalProperties"] is False

    # 2. Qwen Guided Decoding Schema Preservation
    assert qwen_schema["properties"]["used_assets"]["minItems"] == 1
    assert qwen_schema["properties"]["used_assets"]["uniqueItems"] is True
    assert qwen_schema["properties"]["sql"]["minLength"] == 1
    assert len(qwen_schema.get("$defs", {})) > 1  # Full definitions preserved for BNF grammar compiler



class ProductionModelAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_validates_request_and_response_contracts(self) -> None:
        seen = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "model": "runtime-model-snapshot",
                    "choices": [
                        {"message": {"content": json.dumps(_node2_response())}}
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await openai_transport(
                "https://model.invalid",
                "token",
                "node2",
                canonical_model_input("node2", _node2_payload()),
                1,
                model="gpt-5.4-mini",
                provider="openai",
                client=client,
            )

        self.assertEqual(1, len(seen))
        self.assertEqual(["orbit.ops.event_fact"], result["used_assets"])
        self.assertNotIn("model", result)
        self.assertEqual(
            "gpt-5.4-mini",
            result[_TRANSPORT_META_KEY]["model_version"],
        )

    async def test_invalid_runtime_contract_fails_before_network_io(self) -> None:
        payload = _node2_payload()
        del payload["context_package"]["schema_context"]["assets"][0]["grain"]
        called = False

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def transport(node, wire_payload, timeout):
                return await openai_transport(
                    "https://model.invalid",
                    "token",
                    node,
                    wire_payload,
                    timeout,
                    model="gpt-5.4-mini",
                    provider="openai",
                    client=client,
                )

            from app.adapters.async_model_client import AsyncProductionModelClient

            runtime = AsyncProductionModelClient(transport)
            with self.assertRaises((ContractError, ValueError)):
                await runtime.generate(
                    "node2",
                    payload,
                )

        self.assertFalse(called)

    async def test_contract_adapter_preserves_untrusted_model_lineage(self) -> None:
        class ProgrammableModel:
            last_trace = {"model_version": "runtime-model"}

            async def generate(self, node, payload):
                if node != "node2":
                    raise AssertionError(f"unexpected node: {node}")
                validate_payload("node2_request", canonical_model_input(node, payload))
                return _node2_response()

        adapter = ContractModelAdapter(ProgrammableModel())
        plan = await adapter.generate(
            "node2",
            {
                "question": _node2_payload()["normalized_question"],
                "structured_request": _node2_payload()["structured_request"],
                "request_id": "request-arbitrary-1",
                "package": SimpleNamespace(runtime_contracts=_runtime_contracts()),
                "context": SimpleNamespace(),
            },
        )

        self.assertEqual(["orbit.ops.event_fact"], plan["declared_assets"])
        self.assertEqual(["governed_amount"], plan["declared_metrics"])
        self.assertNotIn("references", plan)

    async def test_contract_adapter_accepts_sql_only_without_declared_lineage(self) -> None:
        class ProgrammableModel:
            last_trace = {"model_version": "runtime-model"}

            async def generate(self, node, payload):
                if node != "node2":
                    raise AssertionError(f"unexpected node: {node}")
                validate_payload("node2_request", canonical_model_input(node, payload))
                return {"sql": _node2_response()["sql"]}

        adapter = ContractModelAdapter(ProgrammableModel())
        plan = await adapter.generate(
            "node2",
            {
                "question": _node2_payload()["normalized_question"],
                "structured_request": _node2_payload()["structured_request"],
                "request_id": "request-arbitrary-sql-only",
                "package": SimpleNamespace(runtime_contracts=_runtime_contracts()),
                "context": SimpleNamespace(),
            },
        )

        self.assertEqual(_node2_response()["sql"], plan["sql"])
        self.assertEqual("runtime-model", plan["model_version"])
        self.assertNotIn("declared_assets", plan)
        self.assertNotIn("declared_columns", plan)
        self.assertNotIn("declared_joins", plan)
        self.assertNotIn("declared_metrics", plan)

    async def test_full_stack_validates_all_analysis_nodes_and_separates_trace_metadata(self) -> None:
        seen_wire_requests: dict[str, dict] = {}

        async def openai_handler(request: httpx.Request) -> httpx.Response:
            provider_payload = json.loads(request.content)
            node = provider_payload["response_format"]["json_schema"]["name"].removeprefix(
                "answervice_"
            ).removesuffix("_response")
            wire_request = json.loads(provider_payload["messages"][1]["content"])
            validate_payload(f"{node}_request", wire_request)
            seen_wire_requests[node] = wire_request
            response = {
                "node1": VALID_PAYLOADS["node1_response"],
                "node3": VALID_PAYLOADS["node3_response"],
            }[node]
            return httpx.Response(
                200,
                json={
                    "model": f"{node}-snapshot",
                    "choices": [{"message": {"content": json.dumps(response)}}],
                    "usage": {"prompt_tokens": 17, "completion_tokens": 9},
                },
            )

        async def node2_handler(request: httpx.Request) -> httpx.Response:
            provider_payload = json.loads(request.content)
            wire_request = json.loads(provider_payload["messages"][1]["content"])
            node = "node2_repair" if "trace_id" in wire_request else "node2"
            validate_payload(f"{node}_request", wire_request)
            seen_wire_requests[node] = wire_request
            response = (
                {"corrected_sql": _node2_response()["sql"]}
                if node == "node2_repair"
                else _node2_response()
            )
            return httpx.Response(
                200,
                json={
                    "model": f"runtime-{node}-snapshot",
                    "choices": [
                        {"message": {"content": json.dumps(response)}}
                    ],
                    "usage": {"prompt_tokens": 17, "completion_tokens": 9},
                },
            )

        openai_http = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
        node2_http = httpx.AsyncClient(transport=httpx.MockTransport(node2_handler))
        try:
            with patch(
                "app.adapters.model_transport.httpx.AsyncClient",
                side_effect=[openai_http, node2_http],
            ):
                adapter = ContractModelAdapter.from_endpoints(
                    openai_endpoint="https://openai.invalid",
                    openai_token="openai-token",
                    openai_model="gpt-5.4-mini",
                    node2_endpoint="https://node2.invalid",
                    node2_token="node2-token",
                    node2_model="answervice-sql",
                    node2_provider="qwen",
                    timeout_seconds=2,
                )
            normalized = await adapter.normalize_question(
                dict(VALID_PAYLOADS["node1_request"])
            )
            traces = {"node1": dict(adapter.last_trace)}
            plan = await adapter.generate(
                "node2",
                {
                    "question": _node2_payload()["normalized_question"],
                    "structured_request": _node2_payload()["structured_request"],
                    "request_id": "request-arbitrary-1",
                    "package": SimpleNamespace(runtime_contracts=_runtime_contracts()),
                    "context": SimpleNamespace(),
                },
            )
            traces["node2"] = dict(adapter.last_trace)
            repaired = await adapter.generate(
                "node2_repair",
                {
                    "trace_id": "trace-arbitrary-1",
                    "attempt": 1,
                    "rejected_sql": "SELECT invalid_identifier",
                    "normalized_question": _node2_payload()["normalized_question"],
                    "structured_request": _node2_payload()["structured_request"],
                    "package": SimpleNamespace(runtime_contracts=_runtime_contracts()),
                    "violation": "UNKNOWN_COLUMN",
                    "violation_detail": "A governed column was not resolved.",
                },
            )
            traces["node2_repair"] = dict(adapter.last_trace)
            contracts = _runtime_contracts()
            package = SimpleNamespace(
                runtime_contracts=contracts,
                metrics=(SimpleNamespace(id="governed_amount", unit="credits"),),
                metric_terms=(
                    SimpleNamespace(
                        id="governed_amount",
                        label="Governed amount",
                        unit="credits",
                    ),
                ),
                parameter_bindings=(
                    SimpleNamespace(
                        name="window_begin",
                        value_type="date",
                        value="2026-08-01",
                    ),
                    SimpleNamespace(
                        name="window_stop",
                        value_type="date",
                        value="2026-09-01",
                    ),
                ),
            )
            explanation = await adapter.generate(
                "node3",
                {
                    "query": {
                        "query_id": "query-arbitrary-1",
                        "status": "SUCCESS",
                        "rows": [{"governed_total": 42}],
                        "filters": {},
                        "sampling": {"applied": False},
                        "masking": {"applied": False},
                    },
                    "package": package,
                    "context": SimpleNamespace(
                        timezone="Asia/Seoul",
                        as_of=date(2026, 8, 16),
                    ),
                    "assets": [
                        {
                            "urn": "urn:test:orbit.ops.event_fact",
                            "entitled_metric_ids": ["governed_amount"],
                        }
                    ],
                },
            )
            traces["node3"] = dict(adapter.last_trace)

            self.assertEqual(
                {"node1", "node2", "node2_repair", "node3"},
                set(seen_wire_requests),
            )
            self.assertNotIn("model", normalized)
            self.assertNotIn("context_package", seen_wire_requests["node2"])
            self.assertNotIn("context_package", seen_wire_requests["node2_repair"])
            self.assertNotIn("filter_rules", seen_wire_requests["node2"])
            self.assertNotIn("filter_rules", seen_wire_requests["node2_repair"])
            self.assertEqual("answervice-sql", plan["model_version"])
            self.assertEqual("answervice-sql", repaired["model_version"])
            self.assertEqual("gpt-5.4-mini", explanation["model_version"])
            self.assertEqual("fixture", explanation["summary"])
            self.assertEqual(
                "runtime-node2-snapshot",
                traces["node2"]["model_snapshot"],
            )
            self.assertEqual(
                "runtime-node2_repair-snapshot",
                traces["node2_repair"]["model_snapshot"],
            )
            self.assertEqual("node3-snapshot", traces["node3"]["model_snapshot"])
            self.assertTrue(all(trace["input_tokens"] == 17 for trace in traces.values()))
        finally:
            if "adapter" in locals():
                await adapter.aclose()
            if not openai_http.is_closed:
                await openai_http.aclose()
            if not node2_http.is_closed:
                await node2_http.aclose()
