import json
import unittest
from datetime import date
from pathlib import Path
from sys import path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters import contract_model
from app.adapters.contract_model import (
    ContractModelAdapter,
    NodeModelRouter,
    _validate_sql_semantics,
    openai_transport,
    vllm_transport,
)
from app.contracts import RequestContext
from app.services.context_builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextMetric,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from src.ai.fake_model import FakeModelAdapter
from src.modelops.runtime import ProductionModelClient


class ProductionModelTest(unittest.TestCase):
    def test_openai_transport_uses_structured_outputs(self) -> None:
        captured = {}
        original = contract_model.request_json
        node_payload = self._node2_payload()

        def request(method, url, payload, token, timeout):
            captured.update(
                method=method,
                url=url,
                payload=payload,
                token=token,
                timeout=timeout,
            )
            response = FakeModelAdapter().generate("node2", node_payload)
            return {"choices": [{"message": {"content": json.dumps(response)}}]}

        contract_model.request_json = request
        try:
            result = openai_transport(
                "http://model.local/",
                "secret-token",
                "gpt-4.1-mini",
                "node2",
                node_payload,
                7.0,
            )
        finally:
            contract_model.request_json = original

        self.assertIn("sql", result)
        self.assertEqual("http://model.local/v1/chat/completions", captured["url"])
        self.assertEqual("secret-token", captured["token"])
        self.assertEqual(0, captured["payload"]["temperature"])
        self.assertEqual(1_500, captured["payload"]["max_tokens"])
        self.assertEqual("gpt-4.1-mini", captured["payload"]["model"])
        self.assertNotIn("guided_json", captured["payload"])
        self.assertNotIn("chat_template_kwargs", captured["payload"])
        response_format = captured["payload"]["response_format"]
        self.assertEqual("json_schema", response_format["type"])
        self.assertTrue(response_format["json_schema"]["strict"])
        guided = response_format["json_schema"]["schema"]
        self.assertEqual({"sql"}, set(guided["required"]))
        self.assertFalse(guided["additionalProperties"])
        self.assertEqual(node_payload, json.loads(captured["payload"]["messages"][1]["content"]))

    def test_node2_can_route_to_an_openai_compatible_sllm(self) -> None:
        calls = []

        class Client:
            def __init__(self, name):
                self.name = name
                self.last_trace = {}

            def generate(self, node, payload):
                calls.append((self.name, node, payload))
                self.last_trace = {"fallback": False}
                return {"node": node}

        router = NodeModelRouter(
            Client("openai"),
            {"node2": Client("sllm"), "node2_repair": Client("sllm")},
        )

        self.assertEqual({"node": "node2"}, router.generate("node2", {}))
        self.assertEqual({"node": "node3"}, router.generate("node3", {}))
        self.assertEqual([("sllm", "node2"), ("openai", "node3")], [
            (name, node) for name, node, _payload in calls
        ])

    def test_vllm_transport_keeps_guided_json_contract(self) -> None:
        captured = {}
        original = contract_model.request_json
        node_payload = self._node2_payload()

        def request(method, url, payload, token, timeout):
            captured.update(payload=payload, url=url)
            response = FakeModelAdapter().generate("node2", node_payload)
            return {"choices": [{"message": {"content": json.dumps(response)}}]}

        contract_model.request_json = request
        try:
            vllm_transport(
                "http://sllm.local",
                None,
                "Qwen/Qwen3-4B",
                "node2",
                node_payload,
                7.0,
            )
        finally:
            contract_model.request_json = original

        self.assertEqual("Qwen/Qwen3-4B", captured["payload"]["model"])
        self.assertEqual({"enable_thinking": False}, captured["payload"]["chat_template_kwargs"])
        self.assertEqual({"sql"}, set(captured["payload"]["guided_json"]["required"]))

    def test_every_product_node_uses_its_r3_response_schema(self) -> None:
        expected = {
            "node2": "sql",
            "node2_repair": "corrected_sql",
            "node3": "explanation",
        }
        for node, field in expected.items():
            with self.subTest(node=node):
                schema = contract_model._response_schema(node)
                self.assertIn(field, schema["required"])
                self.assertFalse(schema["additionalProperties"])

        with self.assertRaises(KeyError):
            contract_model._response_schema("unknown")

    def test_fallback_is_rejected_as_product_result(self) -> None:
        client = ProductionModelClient(
            lambda _node, _payload, _timeout: (_ for _ in ()).throw(TimeoutError()),
            failure_threshold=1,
        )
        adapter = ContractModelAdapter(client)

        with self.assertRaisesRegex(TimeoutError, "fallback"):
            adapter._generate("node2", self._node2_payload())
        self.assertTrue(client.last_trace["fallback"])

        with self.assertRaisesRegex(TimeoutError, "fallback"):
            adapter._generate("node2", self._node2_payload())
        self.assertEqual("CIRCUIT_OPEN", client.last_trace["status"])

    def test_plan_ignores_parameters_without_sql_placeholders(self) -> None:
        response = FakeModelAdapter().generate("node2", self._node2_payload())
        response["parameters"].append(
            {"name": "grade_code", "type": "string", "value": "GOLD"}
        )

        plan = ContractModelAdapter._plan(response, "sql")

        self.assertNotIn("grade_code", plan["parameters"])

    def test_plan_binds_server_approved_values_for_model_placeholders(self) -> None:
        response = FakeModelAdapter().generate("node2", self._node2_payload())
        response["sql"] = (
            "SELECT room_revenue FROM serving.analytics.hotel_daily_metrics "
            "WHERE data_period_status = :required_filter_1 "
            "AND is_forecast = :required_filter_2 "
            "AND business_date >= DATE '2026-05-01' "
            "AND business_date < DATE '2026-07-01' LIMIT 1000"
        )
        response["parameters"] = []

        plan = ContractModelAdapter._plan(
            response,
            "sql",
            (
                ContextParameterBinding("required_filter_1", "string", "ACTUAL"),
                ContextParameterBinding("required_filter_2", "boolean", False),
                ContextParameterBinding("period_start", "date", "2026-05-01"),
                ContextParameterBinding(
                    "period_end_exclusive", "date", "2026-07-01"
                ),
            ),
        )

        self.assertEqual(
            {
                "required_filter_1": {"value_type": "string", "value": "ACTUAL"},
                "required_filter_2": {"value_type": "boolean", "value": False},
                "period_start": {"value_type": "date", "value": "2026-05-01"},
                "period_end_exclusive": {
                    "value_type": "date",
                    "value": "2026-07-01",
                },
            },
            plan["parameters"],
        )
        self.assertIn("DATE ':period_start'", plan["sql"])
        self.assertIn("DATE ':period_end_exclusive'", plan["sql"])

    def test_plan_rejects_duplicate_parameter_names(self) -> None:
        response = FakeModelAdapter().generate("node2", self._node2_payload())
        response["parameters"].append(dict(response["parameters"][0]))

        with self.assertRaisesRegex(ValueError, "unique"):
            ContractModelAdapter._plan(response, "sql")

    def test_month_comparison_requires_two_month_window(self) -> None:
        payload = {"normalized_question": "전월 대비 매출을 알려줘"}
        with self.assertRaisesRegex(ValueError, "two-month window"):
            _validate_sql_semantics("node2", payload, "SELECT 1 LIMIT 1")

        _validate_sql_semantics(
            "node2",
            payload,
            "SELECT 1 WHERE x >= date_add('month', -2, "
            "from_iso8601_timestamp('2026-08-01T00:00:00+09:00')) "
            "GROUP BY 1 ORDER BY 1 LIMIT 1",
        )

    def test_context_metric_registry_reaches_model_payload(self) -> None:
        metric = ContextMetric(
            "recognized_room_revenue",
            "serving.analytics.hotel_daily_metrics",
            "room_revenue",
            "sum",
            "business_date",
            (
                ContextRequiredFilter("data_period_status", "eq", "ACTUAL"),
                ContextRequiredFilter("is_forecast", "eq", False),
            ),
        )
        asset = ContextAsset(
            "urn:li:dataset:hotel_daily_metrics",
            metric.asset_fqn,
            (
                "room_revenue",
                "business_date",
                "data_period_status",
                "is_forecast",
            ),
            metrics=(metric,),
            metric_registry_required=True,
        )
        package = ContextPackageBuilder().build(
            ContextBuildRequest(
                "I4-CONTEXT-v2.1.0-DRAFT",
                "policy-v1",
                "2026-08-04",
                "entitlement-hash",
                (asset,),
                100,
                24_000,
            ),
            frozenset({asset.urn}),
        )
        context = ContractModelAdapter._context_package(
            {
                "package": package,
                "context": RequestContext(
                    user_id=UUID("00000000-0000-0000-0000-000000000001"),
                    as_of=date(2026, 8, 4),
                ),
            }
        )

        self.assertEqual("recognized_room_revenue", context["metrics"][0]["id"])
        self.assertEqual(
            "serving.analytics.hotel_daily_metrics.room_revenue",
            context["metrics"][0]["field"],
        )
        self.assertEqual(
            [
                {
                    "field": "data_period_status",
                    "operator": "eq",
                    "value_type": "string",
                    "value": "ACTUAL",
                },
                {
                    "field": "is_forecast",
                    "operator": "eq",
                    "value_type": "boolean",
                    "value": False,
                },
            ],
            context["metrics"][0]["required_filters"],
        )

    def test_node3_uses_entitled_metric_instead_of_a_fixed_metric(self) -> None:
        captured = {}

        class Model:
            def generate(self, node, payload):
                captured.update(payload)
                return {
                    "explanation": "검증된 결과",
                    "model": {"model_version": "MODEL-v1"},
                }

        result = ContractModelAdapter(Model()).generate(
            "node3",
            {
                "query": {
                    "rows": [],
                    "query_id": "query-1",
                    "status": "SUCCEEDED",
                },
                "assets": [
                    {
                        "urn": "urn:li:dataset:crm-points",
                        "metrics": ({"id": "expired_points"},),
                    }
                ],
                "context": RequestContext(as_of=date(2026, 8, 4)),
            },
        )

        self.assertEqual("expired_points", captured["metric"])
        self.assertEqual(
            {
                "selected_metric_id": "expired_points",
                "context_metric_ids": ["expired_points"],
                "entitled_metric_ids": ["expired_points"],
            },
            captured["metric_selection"],
        )
        self.assertEqual("검증된 결과", result["summary"])

    def test_node3_passes_approved_six_asset_derived_metric_selection(self) -> None:
        captured = {}

        class Model:
            def generate(self, _node, payload):
                captured.update(payload)
                return {
                    "explanation": "derived",
                    "model": {"model_version": "MODEL-v1"},
                }

        join_id = "pms_crm_pos_gold_revenue_month_v1"
        assets = [
            {"urn": f"urn:li:dataset:source-{index}", "join_ids": (join_id,)}
            for index in range(6)
        ]
        payload = {
            "query": {
                "rows": [],
                "query_id": "query-1",
                "status": "SUCCEEDED",
            },
            "assets": assets,
            "context": RequestContext(as_of=date(2026, 8, 4)),
        }
        ContractModelAdapter(Model()).generate(
            "node3",
            payload,
        )

        self.assertEqual("total_guest_revenue_krw", captured["metric"])
        self.assertEqual(
            ["total_guest_revenue_krw"] * 6,
            captured["metric_selection"]["context_metric_ids"],
        )
        self.assertEqual(
            ["total_guest_revenue_krw"],
            captured["metric_selection"]["entitled_metric_ids"],
        )
        self.assertTrue(ContractModelAdapter().generate("node3", payload)["summary"])

    def test_node3_metric_selection_fails_closed(self) -> None:
        invalid_assets = (
            [],
            [{"urn": "source", "metrics": ()}],
            [
                {
                    "urn": "source",
                    "metrics": ({"id": "metric-a"}, {"id": "metric-b"}),
                }
            ],
            [
                {
                    "urn": "source",
                    "metrics": ({"id": "metric-a"},),
                    "entitled_metric_ids": ("metric-b",),
                }
            ],
        )
        for assets in invalid_assets:
            with self.subTest(assets=assets):
                with self.assertRaises(ValueError):
                    ContractModelAdapter._metric_selection(assets)

    @staticmethod
    def _node2_payload():
        return {
            "question_id": "request-1",
            "context_package": {
                "context_version": "CTX-v1",
                "policy_version": "POLICY-v1",
                "execution_time": {
                    "as_of": "2026-08-04T00:00:00+09:00",
                    "timezone": "Asia/Seoul",
                    "calendar_id": "gregorian-kr",
                    "period_start": "2026-08-01T00:00:00+09:00",
                    "period_end_exclusive": "2026-08-04T00:00:00+09:00",
                },
                "assets": [
                    {
                        "urn": "urn:li:dataset:pms",
                        "trino_fqn": "pms.public.pms_stays",
                        "columns": ["room_revenue", "actual_checkout_at"],
                    }
                ],
                "metrics": [
                    {
                        "id": "recognized_room_revenue_krw",
                        "field": "pms.public.pms_stays.room_revenue",
                        "aggregation": "sum",
                        "time_field": "pms.public.pms_stays.actual_checkout_at",
                    }
                ],
                "joins": [],
            },
        }


if __name__ == "__main__":
    unittest.main()
