import unittest

from src.ai.training.verify_case_specs import (
    PipelineSupport,
    _result_hash,
    _rows_hash,
    _runtime_package,
)


def _context(fqn, columns, metric):
    return {
        "context_version": "I4-CONTEXT-v2.0.0",
        "policy_version": "G2-v1.0.0",
        "execution_time": {"as_of": "2026-08-01T00:00:00+09:00"},
        "assets": [{"urn": f"urn:{fqn}", "trino_fqn": fqn, "columns": columns}],
        "metrics": [metric],
        "joins": [],
    }


def _plan(fqn, sql):
    return {
        "sql": sql,
        "references": [{"urn": f"urn:{fqn}", "fqn": fqn, "columns": [], "join_ids": []}],
        "parameters": {},
    }


class TrainingVerificationTests(unittest.TestCase):
    def test_result_hash_ignores_row_order(self):
        first = _result_hash('{"name":"B","value":2}\n{"name":"A","value":1}\n')
        second = _result_hash('{"value":1,"name":"A"}\n{"value":2,"name":"B"}\n')

        self.assertEqual(first, second)
        self.assertEqual(first, _rows_hash([{"value": 2, "name": "B"}, {"value": 1, "name": "A"}]))

    def test_runtime_package_preserves_typed_metric_filters(self):
        fqn = "crm.dbo.crm_point_transactions"
        package = _runtime_package(
            _context(
                fqn,
                ["event_at", "txn_type", "is_forecast", "points_delta"],
                {
                    "id": "expired_points",
                    "field": f"{fqn}.points_delta",
                    "aggregation": "negative_sum",
                    "time_field": f"{fqn}.event_at",
                    "required_filters": [
                        {"field": "txn_type", "operator": "eq", "value": "EXPIRE"},
                        {"field": "is_forecast", "operator": "eq", "value": False},
                    ],
                },
            )
        )

        metric = package.metrics[0]
        self.assertEqual("expired_points", metric.id)
        self.assertEqual(fqn, metric.asset_fqn)
        self.assertEqual(f"{fqn}.points_delta", metric.field)
        self.assertEqual("negative_sum", metric.aggregation)
        self.assertEqual(f"{fqn}.event_at", metric.time_field)
        self.assertEqual(("EXPIRE", False), tuple(item.value for item in metric.required_filters))

    def test_runtime_g2_enforces_crm_and_view_metric_filters(self):
        cases = (
            (
                "crm.dbo.crm_point_transactions",
                ["event_at", "txn_type", "is_forecast", "points_delta"],
                {
                    "id": "expired_points",
                    "field": "crm.dbo.crm_point_transactions.points_delta",
                    "aggregation": "negative_sum",
                    "time_field": "crm.dbo.crm_point_transactions.event_at",
                    "required_filters": [
                        {"field": "txn_type", "operator": "eq", "value": "EXPIRE"},
                        {"field": "is_forecast", "operator": "eq", "value": False},
                    ],
                },
                "txn_type = 'EXPIRE' AND is_forecast = false",
            ),
            (
                "serving.analytics.hotel_daily_metrics",
                ["business_date", "data_period_status", "is_forecast", "room_revenue"],
                {
                    "id": "recognized_room_revenue",
                    "field": "serving.analytics.hotel_daily_metrics.room_revenue",
                    "aggregation": "sum",
                    "time_field": "serving.analytics.hotel_daily_metrics.business_date",
                    "required_filters": [
                        {"field": "data_period_status", "operator": "eq", "value": "ACTUAL"},
                        {"field": "is_forecast", "operator": "eq", "value": False},
                    ],
                },
                "data_period_status = 'ACTUAL' AND is_forecast = false",
            ),
        )
        for fqn, columns, metric, filters in cases:
            with self.subTest(metric=metric["id"]):
                package = _runtime_package(_context(fqn, columns, metric))
                prefix = f"SELECT SUM({columns[-1]}) FROM {fqn} WHERE "
                self.assertIsNone(
                    PipelineSupport.g2_violation(
                        _plan(fqn, f"{prefix}{filters} LIMIT 1000"),
                        package,
                    )
                )
                for invalid in (
                    "is_forecast = false",
                    filters.replace("EXPIRE", "EARN").replace("ACTUAL", "FORECAST"),
                    filters.replace(" AND ", " OR "),
                ):
                    self.assertEqual(
                        "METRIC_FILTER_MISSING",
                        PipelineSupport.g2_violation(
                            _plan(fqn, f"{prefix}{invalid} LIMIT 1000"),
                            package,
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
