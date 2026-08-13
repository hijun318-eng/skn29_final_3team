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
    _openai_payload,
    _qwen_payload,
    _validate_sql_semantics,
    openai_transport,
)
from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.contracts import AnalysisRequest, RequestContext
from app.services.context_builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextMetric,
    ContextPackageBuilder,
    ContextRequiredFilter,
)
from app.services.pipeline_support import PipelineSupport
from tests.support.fakes import ContractFakeModelAdapter as FakeModelAdapter
from src.modelops.runtime import ProductionModelClient


class ProductionModelTest(unittest.TestCase):
    def test_three_source_model_output_is_not_replaced_by_a_compiler(self) -> None:
        calls = []

        class Model:
            def generate(self, node, _payload):
                calls.append(node)
                return {
                    "sql": "SELECT 1 LIMIT 1000",
                    "references": [],
                    "parameters": [],
                    "model": {"model_version": "gpt-5.4-mini"},
                }

        question = json.loads(
            (Path(__file__).resolve().parents[2] / "src/data/pms_crm_pos_context.i5.v1.json").read_text(
                encoding="utf-8"
            )
        )["question"]
        context = RequestContext(as_of=date(2026, 8, 12))
        request = AnalysisRequest(
            question=question,
            parameters={
                "period_start": "2026-05-01",
                "period_end_exclusive": "2026-07-01",
            },
        )
        data = I2DataPlatformAdapter(
            "http://trino:8080", "test", require_live_metadata=False
        )
        support = PipelineSupport(data, ContextPackageBuilder())
        assets = data.search_assets(question, context.model_dump(mode="json"))
        package = support.build_context(request, context, assets)

        plan = ContractModelAdapter(Model()).generate(
            "node2",
            {
                "request_id": str(context.request_id),
                "question": question,
                "package": package,
                "context": context,
            },
        )

        self.assertEqual(["node2"], calls)
        self.assertEqual("gpt-5.4-mini", plan["model_version"])
        self.assertEqual("SELECT 1 LIMIT 1000", plan["sql"])
        self.assertIsNotNone(support.g2_violation(plan, package))

    def test_routed_client_uses_a_separate_openai_model_for_node2(self) -> None:
        adapter = ContractModelAdapter.from_endpoints(
            openai_endpoint="https://api.openai.com",
            openai_token="openai-token",
            openai_model="gpt-main",
            node2_endpoint="https://api.openai.com",
            node2_token="openai-token",
            node2_model="gpt-5.6-luna",
            node2_provider="openai",
        )
        main_transport = adapter._model._openai_client._transport
        node2_transport = adapter._model._node2_client._transport

        self.assertEqual(("https://api.openai.com", "openai-token"), main_transport.args)
        self.assertEqual(
            {"model": "gpt-main", "provider": "openai"},
            main_transport.keywords,
        )
        self.assertEqual(("https://api.openai.com", "openai-token"), node2_transport.args)
        self.assertEqual(
            {"model": "gpt-5.6-luna", "provider": "openai"},
            node2_transport.keywords,
        )

    def test_every_node_sends_its_registered_prompt(self) -> None:
        from src.ai.prompt_registry import get_prompt

        prompt_ids = {
            "node1": "node1.normalize",
            "node2": "node2.sql",
            "node2_repair": "node2.repair",
            "node3": "node3.explain",
        }
        openai_prompts = {
            node: _openai_payload("model", node, {})["messages"][0]["content"]
            for node in prompt_ids
        }
        self.assertEqual(4, len(set(openai_prompts.values())))
        for node, prompt_id in prompt_ids.items():
            self.assertEqual(get_prompt(prompt_id).text, openai_prompts[node])

        node2_payload = self._node2_payload()
        self.assertEqual(
            get_prompt("node2.sql").text,
            _qwen_payload("model", "node2", node2_payload)["messages"][0]["content"],
        )

    def test_transport_uses_fixed_serving_contract(self) -> None:
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
            full = FakeModelAdapter().generate("node2", node_payload)
            response = {
                "sql": full["sql"],
                "used_assets": ["pms.public.pms_stays"],
                "used_metrics": ["recognized_room_revenue_krw"],
            }
            return {"choices": [{"message": {"content": json.dumps(response)}}]}

        contract_model.request_json = request
        try:
            result = openai_transport(
                "http://model.local/",
                "secret-token",
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
        self.assertEqual(1_280, captured["payload"]["max_tokens"])
        self.assertEqual(
            {"enable_thinking": False},
            captured["payload"]["chat_template_kwargs"],
        )
        guided = captured["payload"]["guided_json"]
        self.assertEqual(
            {"sql", "used_assets", "used_metrics"}, set(guided["required"])
        )
        self.assertFalse(guided["additionalProperties"])
        model_input = json.loads(captured["payload"]["messages"][1]["content"])
        self.assertEqual(
            {"structured_request", "approved_context"}, set(model_input)
        )
        self.assertNotIn("normalized_question", captured["payload"]["messages"][1]["content"])

    def test_transport_does_not_treat_cte_names_as_used_assets(self) -> None:
        original = contract_model.request_json
        node_payload = self._node2_payload()
        node_payload["context_package"]["assets"].append(
            {
                "urn": "urn:li:dataset:pos",
                "trino_fqn": "pos.pos_db.pos_orders",
                "columns": ["net_amount"],
            }
        )
        node_payload["context_package"]["metrics"] = [
            {
                "id": "total_guest_revenue_krw",
                "field": "derived.total_guest_revenue_krw",
                "aggregation": "derived_sum",
                "time_field": "derived.month",
            }
        ]
        sql = (
            "WITH pms_source AS (SELECT SUM(room_revenue) room_revenue_krw "
            "FROM pms.public.pms_stays), pos_source AS (SELECT SUM(net_amount) "
            "fnb_revenue_krw FROM pos.pos_db.pos_orders) SELECT room_revenue_krw + "
            "fnb_revenue_krw total_guest_revenue_krw FROM pms_source JOIN pos_source ON true LIMIT 1000"
        )

        def request(*_args):
            response = {
                "sql": sql,
                "used_assets": ["pms.public.pms_stays", "pos.pos_db.pos_orders"],
                "used_metrics": ["total_guest_revenue_krw"],
            }
            return {"choices": [{"message": {"content": json.dumps(response)}}]}

        contract_model.request_json = request
        try:
            result = openai_transport("http://model", "token", "node2", node_payload, 7)
        finally:
            contract_model.request_json = original

        self.assertEqual(sql, result["sql"])

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

    def test_model_failure_never_generates_a_fallback_result(self) -> None:
        client = ProductionModelClient(
            lambda _node, _payload, _timeout: (_ for _ in ()).throw(TimeoutError()),
            failure_threshold=1,
        )
        adapter = ContractModelAdapter(client)

        with self.assertRaisesRegex(TimeoutError, "TIMEOUT"):
            adapter._generate("node2", self._node2_payload())
        self.assertFalse(client.last_trace["fallback"])

        with self.assertRaisesRegex(TimeoutError, "CIRCUIT_OPEN"):
            adapter._generate("node2", self._node2_payload())
        self.assertEqual("CIRCUIT_OPEN", client.last_trace["status"])

    def test_plan_ignores_parameters_without_sql_placeholders(self) -> None:
        response = FakeModelAdapter().generate("node2", self._node2_payload())
        response["parameters"].append(
            {"name": "grade_code", "type": "string", "value": "GOLD"}
        )

        plan = ContractModelAdapter._plan(response, "sql")

        self.assertNotIn("grade_code", plan["parameters"])

    def test_plan_rejects_duplicate_parameter_names(self) -> None:
        response = FakeModelAdapter().generate("node2", self._node2_payload())
        response["parameters"].append(dict(response["parameters"][0]))

        with self.assertRaisesRegex(ValueError, "unique"):
            ContractModelAdapter._plan(response, "sql")

    def test_seal_sql_parameters_types_plain_and_typed_date_literals(self) -> None:
        package = self._node2_payload()["context_package"]
        package["metrics"][0]["required_filters"] = [
            {
                "field": "data_period_status",
                "operator": "eq",
                "value_type": "string",
                "value": "ACTUAL",
            }
        ]
        sql = (
            "SELECT 1 FROM pms.public.pms_stays "
            "WHERE actual_checkout_at >= '2026-08-01' "
            "AND actual_checkout_at < DATE '2026-08-04' "
            "AND data_period_status = 'ACTUAL' LIMIT 1000"
        )

        sealed, parameters = contract_model._seal_sql_parameters(sql, package)

        self.assertIn("actual_checkout_at >= :period_start", sealed)
        self.assertIn("actual_checkout_at < DATE ':period_end_exclusive'", sealed)
        self.assertIn("data_period_status = :required_filter_1", sealed)
        self.assertEqual(
            [
                "period_start",
                "period_end_exclusive",
                "required_filter_1",
            ],
            [item["name"] for item in parameters],
        )

    def test_seal_normalizes_date_literal_with_midnight_timezone(self) -> None:
        package = self._node2_payload()["context_package"]
        sql = (
            "SELECT 1 FROM pms.public.pms_stays "
            "WHERE actual_checkout_at >= DATE '2026-08-01T00:00:00+09:00' "
            "AND actual_checkout_at < DATE '2026-08-04T00:00:00+09:00' LIMIT 1000"
        )

        sealed, _parameters = contract_model._seal_sql_parameters(sql, package)

        self.assertIn("DATE ':period_start'", sealed)
        self.assertIn("DATE ':period_end_exclusive'", sealed)

    def test_seal_keeps_same_named_filters_bound_to_their_assets(self) -> None:
        package = self._node2_payload()["context_package"]
        package["metrics"][0]["required_filters"] = [
            {
                "field": "property_id",
                "asset_fqn": "pms.public.pms_stays",
                "operator": "eq",
                "parameter_name": "required_filter_1",
                "value_type": "string",
                "value": "SYNTHETIC_HOTEL_001",
            },
            {
                "field": "property_id",
                "asset_fqn": "pos.pos_db.pos_orders",
                "operator": "eq",
                "parameter_name": "required_filter_2",
                "value_type": "string",
                "value": "SYNTHETIC_HOTEL_001",
            },
        ]
        sql = (
            "SELECT 1 FROM pms.public.pms_stays s "
            "JOIN pos.pos_db.pos_orders o ON s.property_id = o.property_id "
            "WHERE s.property_id = 'SYNTHETIC_HOTEL_001' "
            "AND o.property_id = 'SYNTHETIC_HOTEL_001' LIMIT 1000"
        )

        sealed, parameters = contract_model._seal_sql_parameters(sql, package)

        self.assertIn("s.property_id = :required_filter_1", sealed)
        self.assertIn("o.property_id = :required_filter_2", sealed)
        self.assertEqual(
            ["required_filter_1", "required_filter_2"],
            [item["name"] for item in parameters[2:]],
        )

    def test_seal_normalizes_boolean_spelling_for_numeric_flag(self) -> None:
        package = self._node2_payload()["context_package"]
        package["metrics"][0]["required_filters"] = [
            {
                "field": "is_forecast",
                "asset_fqn": "pos.pos_db.pos_orders",
                "operator": "eq",
                "parameter_name": "required_filter_1",
                "value_type": "number",
                "value": 0,
            }
        ]
        sql = (
            "SELECT 1 FROM pos.pos_db.pos_orders o "
            "WHERE o.is_forecast = false LIMIT 1000"
        )

        sealed, parameters = contract_model._seal_sql_parameters(sql, package)

        self.assertIn("o.is_forecast = :required_filter_1", sealed)
        self.assertEqual(
            {"name": "required_filter_1", "value_type": "number", "value": 0},
            parameters[-1],
        )

    def test_qwen_input_keeps_required_filter_asset_provenance(self) -> None:
        payload = self._node2_payload()
        payload["context_package"]["metrics"][0]["required_filters"] = [
            {
                "field": "data_period_status",
                "asset_fqn": "pms.public.pms_stays",
                "operator": "eq",
                "parameter_name": "required_filter_1",
                "value_type": "string",
                "value": "ACTUAL",
            }
        ]

        model_input = json.loads(
            _qwen_payload("model", "node2", payload)["messages"][1]["content"]
        )

        self.assertIn(
            "pms.public.pms_stays.data_period_status = 'ACTUAL'",
            model_input["structured_request"]["filters"],
        )

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

    def test_node2_requires_the_approved_metric_aggregation(self) -> None:
        payload = self._node2_payload()
        with self.assertRaisesRegex(ValueError, "metric aggregation"):
            _validate_sql_semantics(
                "node2",
                payload,
                "SELECT recognized_room_revenue_krw "
                "FROM pms.public.pms_stays LIMIT 1000",
            )

        _validate_sql_semantics(
            "node2",
            payload,
            "SELECT SUM(room_revenue) AS recognized_room_revenue_krw "
            "FROM pms.public.pms_stays LIMIT 1000",
        )

    def test_node2_requires_requested_dimension_sort(self) -> None:
        payload = self._node2_payload()
        payload["structured_request"] = {
            "dimension_candidates": ["business_date"]
        }
        sql = (
            "SELECT business_date, SUM(room_revenue) AS recognized_room_revenue "
            "FROM pms.public.pms_stays GROUP BY business_date"
        )

        with self.assertRaisesRegex(ValueError, "dimension sort"):
            _validate_sql_semantics("node2", payload, f"{sql} LIMIT 1000")

        _validate_sql_semantics(
            "node2",
            payload,
            f"{sql} ORDER BY business_date LIMIT 1000",
        )

    def test_rejected_model_sql_is_fingerprinted_not_logged(self) -> None:
        original = contract_model.request_json
        rejected_sql = (
            "SELECT recognized_room_revenue_krw "
            "FROM pms.public.pms_stays LIMIT 1000"
        )

        def request(*_args):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "sql": rejected_sql,
                                    "used_assets": ["pms.public.pms_stays"],
                                    "used_metrics": ["recognized_room_revenue_krw"],
                                }
                            )
                        }
                    }
                ]
            }

        contract_model.request_json = request
        try:
            with self.assertLogs("uvicorn.error", level="WARNING") as captured:
                with self.assertRaisesRegex(ValueError, "metric aggregation"):
                    openai_transport(
                        "http://model", "token", "node2", self._node2_payload(), 7
                    )
        finally:
            contract_model.request_json = original

        log_text = "\n".join(captured.output)
        self.assertIn("sql_sha256=", log_text)
        self.assertNotIn(rejected_sql, log_text)

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
                    "asset_fqn": "serving.analytics.hotel_daily_metrics",
                    "operator": "eq",
                    "parameter_name": "required_filter_1",
                    "value_type": "string",
                    "value": "ACTUAL",
                },
                {
                    "field": "is_forecast",
                    "asset_fqn": "serving.analytics.hotel_daily_metrics",
                    "operator": "eq",
                    "parameter_name": "required_filter_2",
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
        self.assertEqual("객실·식음 통합 매출", captured["metric_label"])
        self.assertEqual(
            ["total_guest_revenue_krw"] * 6,
            captured["metric_selection"]["context_metric_ids"],
        )
        self.assertEqual(
            ["total_guest_revenue_krw"],
            captured["metric_selection"]["entitled_metric_ids"],
        )
        self.assertTrue(ContractModelAdapter(FakeModelAdapter()).generate("node3", payload)["summary"])

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
