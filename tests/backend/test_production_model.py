import unittest
from unittest.mock import patch
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
    _complete_aggregate_group_by,
    _complete_dimension_order_by,
    _complete_chat_response,
    _queried_fqns,
    _validate_sql_semantics,
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


class ProductionModelTest(unittest.TestCase):
    def test_unmatched_model_table_reaches_g2_with_entitled_references(self) -> None:
        result = _complete_chat_response(
            {"choices": [{"message": {"content": '{"sql":"SELECT x FROM other.schema.table LIMIT 1000"}'}}]},
            "node2",
            {
                "context_package": {
                    "assets": [{
                        "urn": "urn:approved",
                        "trino_fqn": "serving.analytics.hotel_daily_metrics",
                        "columns": ["business_date", "room_revenue"],
                    }],
                    "joins": [],
                    "metrics": [],
                    "dimensions": [],
                }
            },
            "model",
            "vllm",
        )

        self.assertEqual("serving.analytics.hotel_daily_metrics", result["references"][0]["trino_fqn"])

    def test_dimension_order_is_completed_from_group_expression(self) -> None:
        sql = _complete_dimension_order_by(
            "SELECT membership_grade, SUM(points_balance) AS total "
            "FROM crm.dbo.crm_members GROUP BY membership_grade LIMIT 1000",
            {"membership_grade"},
        )

        self.assertIn("ORDER BY membership_grade", sql)

    def test_quoted_model_tables_are_matched_to_context_fqns(self) -> None:
        self.assertEqual(
            {"crm.dbo.crm_point_transactions", "crm.dbo.crm_members"},
            _queried_fqns(
                'SELECT m."membership_grade" FROM "crm"."dbo"."crm_point_transactions" t '
                'JOIN "crm"."dbo"."crm_members" m ON t."member_no" = m."member_no"'
            ),
        )

    def test_dimension_semantics_accepts_order_by_projection_alias(self) -> None:
        _validate_sql_semantics(
            "node2",
            {
                "context_package": {
                    "dimensions": [{"field": "serving.analytics.hotel_daily_metrics.business_date"}]
                }
            },
            "SELECT date_trunc('month', business_date) AS month, SUM(room_revenue) "
            "FROM serving.analytics.hotel_daily_metrics GROUP BY 1 ORDER BY month LIMIT 1000",
        )

    def test_model_sql_groups_every_non_aggregate_projection(self) -> None:
        sql = _complete_aggregate_group_by(
            "SELECT business_date, SUM(room_revenue) AS revenue "
            "FROM serving.analytics.hotel_daily_metrics ORDER BY business_date LIMIT 1000"
        )

        self.assertIn("GROUP BY business_date", sql)

    def test_model_sql_preserves_existing_group_by_position(self) -> None:
        sql = (
            "SELECT business_date, SUM(room_revenue) AS revenue "
            "FROM serving.analytics.hotel_daily_metrics GROUP BY 1 LIMIT 1000"
        )

        self.assertEqual(sql, _complete_aggregate_group_by(sql))

    @patch("app.adapters.contract_model.request_json")
    def test_vllm_uses_supported_openai_json_schema(self, request_json) -> None:
        request_json.return_value = {
            "choices": [{"message": {"content": '{"sql":"SELECT 1"}'}}]
        }

        result = vllm_transport(
            "https://model.test/openai",
            "token",
            "model",
            "node2",
            {"context_package": {"assets": [], "joins": [], "metrics": []}},
            30,
        )

        body = request_json.call_args.args[2]
        self.assertNotIn("guided_json", body)
        self.assertEqual("json_schema", body["response_format"]["type"])
        self.assertEqual(
            "object", body["response_format"]["json_schema"]["schema"]["type"]
        )
        self.assertEqual("SELECT 1", result["sql"])

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

        self.assertEqual({"node": "node1"}, router.generate("node1", {}))
        self.assertEqual({"node": "node2"}, router.generate("node2", {}))
        self.assertEqual({"node": "node3"}, router.generate("node3", {}))
        self.assertEqual([("openai", "node1"), ("sllm", "node2"), ("openai", "node3")], [
            (name, node) for name, node, _payload in calls
        ])

    def test_every_product_node_uses_its_r3_response_schema(self) -> None:
        expected = {
            "node1": "selected_metric_id",
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

        self.assertNotIn("$defs", contract_model._serving_schema("node1"))

    def test_plan_ignores_parameters_without_sql_placeholders(self) -> None:
        response = self._node2_response()
        response["parameters"].append(
            {"name": "grade_code", "type": "string", "value": "GOLD"}
        )

        plan = ContractModelAdapter._plan(response, "sql")

        self.assertNotIn("grade_code", plan["parameters"])

    def test_plan_binds_server_approved_values_for_model_placeholders(self) -> None:
        response = self._node2_response()
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
        response = self._node2_response()
        response["parameters"] = [
            {"name": "period_start", "value": "2026-08-01"},
            {"name": "period_start", "value": "2026-08-01"},
        ]

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

    def test_dimension_semantics_accepts_fqn_context_and_sql_alias(self) -> None:
        payload = {
            "context_package": {
                "dimensions": [{
                    "id": "membership_grade",
                    "field": "crm.dbo.crm_members.membership_grade",
                }]
            }
        }

        _validate_sql_semantics(
            "node2",
            payload,
            "SELECT m.membership_grade, SUM(t.points_delta) "
            "FROM crm.dbo.crm_point_transactions t "
            "JOIN crm.dbo.crm_members m ON t.member_no = m.member_no "
            "GROUP BY m.membership_grade ORDER BY m.membership_grade LIMIT 1000",
        )

        with self.assertRaisesRegex(ValueError, "group by"):
            _validate_sql_semantics(
                "node2",
                payload,
                "SELECT m.membership_grade, SUM(t.points_delta) "
                "FROM crm.dbo.crm_point_transactions t "
                "JOIN crm.dbo.crm_members m ON t.member_no = m.member_no "
                "GROUP BY m.membership_grade LIMIT 1000",
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
                "selected_metric_ids": ["expired_points"],
                "context_metric_ids": ["expired_points"],
                "entitled_metric_ids": ["expired_points"],
            },
            captured["metric_selection"],
        )
        self.assertEqual("검증된 결과", result["summary"])

    def test_node3_metric_selection_fails_closed(self) -> None:
        invalid_assets = (
            [],
            [{"urn": "source", "metrics": ()}],
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

        selection = ContractModelAdapter._metric_selection([
            {
                "urn": "source",
                "metrics": ({"id": "metric-a"}, {"id": "metric-b"}),
            }
        ])
        self.assertEqual(["metric-a", "metric-b"], selection["selected_metric_ids"])
        self.assertEqual(["metric-a", "metric-b"], selection["context_metric_ids"])

    @staticmethod
    def _node2_response():
        return {
            "sql": "SELECT 1 LIMIT 1000",
            "parameters": [],
            "references": [],
            "model": {"model_version": "MODEL-v1"},
        }

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
