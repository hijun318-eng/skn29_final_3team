import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

from src.ai.node2 import generate_sql, repair_sql
from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.adapters.contract_model import ContractModelAdapter
from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.adapters.context_registry_repository import PublishedContextRelease
from app.contracts import AnalysisRequest, RequestContext
from app.services.context_builder import ContextPackageBuilder
from app.services.pipeline_support import PipelineSupport


def _published_release(_as_of):
    return PublishedContextRelease(
        "00000000-0000-0000-0000-000000000201",
        "test-release",
        1,
        "f" * 64,
        "time-policy:v1:" + "a" * 64,
        "Asia/Seoul",
        "gregorian-kr",
    )


def derived_payload():
    source = json.loads(
        (ROOT / "src/data/pms_crm_pos_context.i5.v1.json").read_text(encoding="utf-8")
    )
    assets = [
        {"urn": item["urn"], "trino_fqn": item["fqn"], "columns": item["columns"]}
        for item in source["assets"]
    ]
    fqns = {item["trino_fqn"] for item in assets}
    chain = source["approved_join"]["join_edges"]
    assert fqns.issubset({fqn for edge in chain for fqn in (edge["left"], edge["right"])})
    joins = [
        {
            "id": source["approved_join"]["id"],
            "left": edge["left"],
            "right": edge["right"],
            "cardinality": source["approved_join"]["cardinality"],
            "status": "approved",
            "on_predicates": edge["on_predicates"],
        }
        for edge in chain
    ]
    return {
        "question_id": "derived-question",
        "context_package": {
            "context_version": source["contract_version"],
            "policy_version": "G2-v1.0.0",
            "execution_time": {
                "as_of": "2026-07-01T00:00:00+09:00",
                "timezone": source["execution_time"]["timezone"],
                "calendar_id": "gregorian-kr",
                "period_start": source["execution_time"]["period_start"] + "T00:00:00+09:00",
                "period_end_exclusive": source["execution_time"]["period_end_exclusive"] + "T00:00:00+09:00",
            },
            "assets": assets,
            "metrics": [{
                "id": "total_guest_revenue_krw",
                "field": "derived.total_guest_revenue_krw",
                "aggregation": "derived_sum",
                "time_field": "derived.month",
                "required_filters": source["required_filters"],
            }],
            "joins": joins,
        },
    }


class Node2Tests(unittest.TestCase):
    def test_current_snapshot_metrics_group_by_approved_dimension_without_period_filter(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        context = payload["context_package"]
        context["assets"] = [{
            "urn": "urn:crm",
            "trino_fqn": "crm.dbo.crm_members",
            "columns": ["membership_grade", "points_balance", "joined_at", "member_status"],
        }]
        context["metrics"] = [
            {
                "id": "current_points_balance_sum",
                "field": "crm.dbo.crm_members.points_balance",
                "aggregation": "sum",
                "time_field": "crm.dbo.crm_members.joined_at",
                "temporal_semantics": "current_snapshot",
                "required_filters": [
                    {"field": "member_status", "operator": "eq", "value_type": "string", "value": "ACTIVE"}
                ],
            },
            {
                "id": "current_points_balance_average",
                "field": "crm.dbo.crm_members.points_balance",
                "aggregation": "avg",
                "time_field": "crm.dbo.crm_members.joined_at",
                "temporal_semantics": "current_snapshot",
                "required_filters": [
                    {"field": "member_status", "operator": "eq", "value_type": "string", "value": "ACTIVE"}
                ],
            },
        ]
        context["dimensions"] = [{
            "id": "membership_grade",
            "field": "crm.dbo.crm_members.membership_grade",
        }]

        response = generate_sql(payload)

        self.assertIn('"membership_grade" AS "membership_grade"', response["sql"])
        self.assertIn('GROUP BY "membership_grade" ORDER BY "membership_grade"', response["sql"])
        self.assertNotIn('"joined_at" >=', response["sql"])
        self.assertEqual(["required_filter_1"], [item["name"] for item in response["parameters"]])
        self.assertIn("membership_grade", response["references"][0]["columns"])

    def test_explicit_multiple_metrics_share_one_context_bound_query(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        first = payload["context_package"]["metrics"][0]
        payload["context_package"]["metrics"] = [
            {**first, "id": "points_total", "aggregation": "sum"},
            {**first, "id": "points_average", "aggregation": "avg"},
        ]

        response = generate_sql(payload)

        self.assertIn('SUM("room_revenue") AS "points_total"', response["sql"])
        self.assertIn('AVG("room_revenue") AS "points_average"', response["sql"])
        self.assertEqual(
            ["points_total", "points_average"],
            response["references"][0]["metric_ids"],
        )

    def test_sql_and_references_use_only_context(self):
        response = generate_sql(VALID_PAYLOADS["node2_request"])

        self.assertIn("FROM pms.public.reservations", response["sql"])
        self.assertNotIn("current_date", response["sql"].lower())
        self.assertEqual(["stay_date", "room_revenue"], response["references"][0]["columns"])
        self.assertEqual(
            ["period_start", "period_end_exclusive"],
            [item["name"] for item in response["parameters"]],
        )
        self.assertEqual(["date", "date"], [item["value_type"] for item in response["parameters"]])

    def test_context_outside_field_is_rejected(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        payload["context_package"]["metrics"][0]["field"] = "secret.private.revenue"

        with self.assertRaisesRegex(ContractError, "outside Context"):
            generate_sql(payload)

    def test_required_filters_are_parameterized_and_referenced(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        context = payload["context_package"]
        context["assets"][0]["columns"] += ["is_forecast", "data_period_status"]
        context["metrics"][0]["required_filters"] = [
            {"field": "is_forecast", "operator": "eq", "value_type": "boolean", "value": False},
            {"field": "data_period_status", "operator": "eq", "value_type": "string", "value": "ACTUAL"},
        ]

        response = generate_sql(payload)

        self.assertIn('"data_period_status" = :required_filter_1', response["sql"])
        self.assertIn('"is_forecast" = :required_filter_2', response["sql"])
        self.assertNotIn("ACTUAL", response["sql"])
        self.assertEqual(
            ["period_start", "period_end_exclusive", "required_filter_1", "required_filter_2"],
            [item["name"] for item in response["parameters"]],
        )
        self.assertEqual(
            ["2026-07-01", "2026-07-30", "ACTUAL", False],
            [item["value"] for item in response["parameters"]],
        )
        self.assertEqual(
            ["date", "date", "string", "boolean"],
            [item["value_type"] for item in response["parameters"]],
        )
        self.assertEqual(
            ["stay_date", "room_revenue", "is_forecast", "data_period_status"],
            response["references"][0]["columns"],
        )

        context["metrics"][0]["required_filters"].reverse()
        self.assertEqual(response, generate_sql(payload))

    def test_invalid_and_duplicate_required_filters_are_rejected(self):
        for filters in (
            [
                {"field": "stay_date", "operator": "eq", "value_type": "date", "value": "2026-07-01"},
                {"field": "stay_date", "operator": "eq", "value_type": "date", "value": "2026-07-02"},
            ],
            [{"field": "secret", "operator": "eq", "value_type": "string", "value": "ACTUAL"}],
            [{"field": "stay_date OR 1=1", "operator": "eq", "value_type": "string", "value": "ACTUAL"}],
            [{"field": "stay_date", "operator": "eq", "value_type": "string", "value": ""}],
            [{"field": "stay_date", "operator": "eq", "value_type": "date", "value": "2026-07-01T00:00:00"}],
            [{"field": "stay_date", "operator": "eq", "value_type": "number", "value": True}],
        ):
            payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
            payload["context_package"]["metrics"][0]["required_filters"] = filters
            with self.subTest(filters=filters):
                with self.assertRaisesRegex(ContractError, "required filter"):
                    generate_sql(payload)

    def test_all_required_filter_value_types_are_preserved(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        context = payload["context_package"]
        context["assets"][0]["columns"] += ["active", "cutoff_date", "minimum_amount", "segment"]
        context["metrics"][0]["required_filters"] = [
            {"field": "segment", "operator": "eq", "value_type": "string", "value": "GOLD"},
            {"field": "minimum_amount", "operator": "eq", "value_type": "number", "value": 12.5},
            {"field": "cutoff_date", "operator": "eq", "value_type": "date", "value": "2026-07-01"},
            {"field": "active", "operator": "eq", "value_type": "boolean", "value": True},
        ]

        response = generate_sql(payload)

        self.assertEqual(
            ["boolean", "date", "number", "string"],
            [item["value_type"] for item in response["parameters"][2:]],
        )
        self.assertEqual(
            [True, "2026-07-01", 12.5, "GOLD"],
            [item["value"] for item in response["parameters"][2:]],
        )

    def test_repair_preserves_required_filter_contract(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        payload["context_package"]["metrics"][0]["required_filters"] = [
            {"field": "stay_date", "operator": "eq", "value_type": "date", "value": "2026-07-01"}
        ]

        response = repair_sql(payload)

        self.assertIn('"stay_date" = :required_filter_1', response["corrected_sql"])
        self.assertEqual("required_filter_1", response["parameters"][-1]["name"])

    def test_repair_is_exactly_once_and_uses_normalized_codes(self):
        response = repair_sql(VALID_PAYLOADS["node2_repair_request"])
        self.assertEqual(1, response["attempt"])
        self.assertEqual("trace-1", response["trace_id"])

        unsupported = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        unsupported["normalized_error_code"] = "raw database stack trace"
        with self.assertRaisesRegex(ContractError, "normalized error code"):
            repair_sql(unsupported)

    def test_derived_metric_uses_two_source_preaggregates_and_all_typed_bindings(self):
        payload = derived_payload()

        response = generate_sql(payload)
        sql = response["sql"]

        self.assertTrue(sql.startswith("WITH pms_source AS ("))
        self.assertEqual(2, sql.count("GROUP BY"))
        self.assertIn("FROM pms_source p FULL OUTER JOIN pos_source f", sql)
        self.assertIn("p.property_id = f.property_id AND p.month = f.month", sql)
        self.assertIn("valid_from <= s.actual_checkout_at", sql)
        self.assertIn("valid_from <= o.ordered_at", sql)
        self.assertNotIn("GOLD", sql)
        self.assertNotIn("SYNTHETIC_HOTEL_001", sql)
        expected = json.loads(
            (ROOT / "src/data/pms_crm_pos_context.i5.v1.json").read_text(encoding="utf-8")
        )["parameter_bindings"]
        self.assertEqual(expected, response["parameters"])
        self.assertEqual(6, len(response["references"]))
        self.assertTrue(
            all(
                item["join_ids"] == ["pms_crm_pos_gold_revenue_month_v1"]
                for item in response["references"]
            )
        )
        self.assertTrue(all(item["columns"] for item in response["references"]))

    def test_derived_metric_rejects_unapproved_or_amplifying_context(self):
        for mutate in (
            lambda context: context["joins"][0].update(id="outside_join"),
            lambda context: context["joins"][0].update(cardinality="many_to_many"),
            lambda context: context["assets"].append(copy.deepcopy(context["assets"][0])),
            lambda context: context["metrics"][0]["required_filters"].append(
                copy.deepcopy(context["metrics"][0]["required_filters"][0])
            ),
        ):
            payload = derived_payload()
            mutate(payload["context_package"])
            with self.subTest(context=payload["context_package"]):
                with self.assertRaisesRegex(ContractError, "derived|filter"):
                    generate_sql(payload)

    def test_metric_filter_missing_repair_is_exactly_once(self):
        request = derived_payload()
        expected = generate_sql(request)
        repair = {
            "trace_id": "derived-trace",
            "attempt": 1,
            "rejected_sql": expected["sql"].replace(
                'h."grade_code" = :required_filter_1', "1 = 1"
            ),
            "context_package": request["context_package"],
            "normalized_error_code": "METRIC_FILTER_MISSING",
            "repair_scope": ["sql", "references", "parameters"],
        }

        corrected = repair_sql(repair)

        self.assertEqual(1, corrected["attempt"])
        self.assertEqual(expected["sql"], corrected["corrected_sql"])
        self.assertEqual(expected["parameters"], corrected["parameters"])

    def test_actual_context_passes_g2_binder_and_one_repair(self):
        adapter = I2DataPlatformAdapter(
            "http://trino:8080", "node2-composition", require_live_metadata=False
        )
        support = PipelineSupport(adapter, ContextPackageBuilder(), _published_release)
        request = AnalysisRequest(
            question="5월과 6월 GOLD 고객의 객실·식음 통합 매출을 보여줘."
        )
        context = RequestContext(as_of=date(2026, 7, 1))
        assets = adapter.search_assets(
            request.question, context.model_dump(mode="json")
        )
        package = support.build_context(request, context, assets)
        model_context = ContractModelAdapter._context_package(
            {"package": package, "context": context}
        )
        response = generate_sql(
            {"question_id": "g120-046-composition", "context_package": model_context}
        )
        plan = ContractModelAdapter._plan(
            response, "sql", package.parameter_bindings
        )

        self.assertIsNone(support.g2_violation(plan, package))
        bound = adapter._bind_parameters(plan["sql"], plan["parameters"])
        self.assertNotRegex(bound, r":(?:period|required_filter_)\w*")

        rejected_sql = plan["sql"].replace(
            'AND o."void_flag" = :required_filter_9', ""
        )
        self.assertEqual(
            "METRIC_FILTER_MISSING",
            support.g2_violation({**plan, "sql": rejected_sql}, package),
        )
        for bypass in (
            plan["sql"].replace(
                'o."void_flag" = :required_filter_9', 'o."void_flag" = 0'
            ),
            plan["sql"].replace(
                'AND o."void_flag" = :required_filter_9',
                'OR o."void_flag" = :required_filter_9',
            ),
        ):
            self.assertEqual(
                "METRIC_FILTER_MISSING",
                support.g2_violation({**plan, "sql": bypass}, package),
            )
        mutated = {
            **plan["parameters"],
            "required_filter_7": {"value_type": "number", "value": 1},
        }
        self.assertEqual(
            "PARAMETERS_INVALID",
            support.g2_violation({**plan, "parameters": mutated}, package),
        )
        self.assertEqual(
            "PARAMETERS_INVALID",
            support.g2_violation(
                {**plan, "parameters": {**plan["parameters"], "unknown": "value"}},
                package,
            ),
        )
        outside_join = [
            {**item, "join_ids": ["outside_join"]} for item in plan["references"]
        ]
        self.assertEqual(
            "UNAPPROVED_JOIN",
            support.g2_violation({**plan, "references": outside_join}, package),
        )
        duplicate = {
            **response,
            "parameters": [*response["parameters"], response["parameters"][-1]],
        }
        with self.assertRaisesRegex(ValueError, "unique"):
            ContractModelAdapter._plan(
                duplicate, "sql", package.parameter_bindings
            )

        repaired = repair_sql(
            {
                "trace_id": "g120-046-composition",
                "attempt": 1,
                "rejected_sql": rejected_sql,
                "context_package": model_context,
                "normalized_error_code": "METRIC_FILTER_MISSING",
                "repair_scope": ["sql", "references", "parameters"],
            }
        )
        repaired_plan = ContractModelAdapter._plan(
            repaired, "corrected_sql", package.parameter_bindings
        )
        self.assertIsNone(support.g2_violation(repaired_plan, package))
        with self.assertRaises(ContractError):
            repair_sql(
                {
                    "trace_id": "g120-046-composition",
                    "attempt": 2,
                    "rejected_sql": rejected_sql,
                    "context_package": model_context,
                    "normalized_error_code": "METRIC_FILTER_MISSING",
                    "repair_scope": ["sql"],
                }
            )


if __name__ == "__main__":
    unittest.main()
