from __future__ import annotations

import unittest

from app.services.analysis_result_stage import _chart_spec


class AnalysisResultStageChartTest(unittest.TestCase):
    def test_governed_metrics_drive_chart_without_domain_names(self) -> None:
        chart = _chart_spec(
            [
                {"period_bucket": "alpha", "metric_beta": 11, "noise": 3},
                {"period_bucket": "bravo", "metric_beta": 13, "noise": 5},
            ],
            ("metric_beta",),
        )

        self.assertIsNotNone(chart)
        assert chart is not None
        self.assertEqual("period_bucket", chart.x_field)
        self.assertEqual(("metric_beta",), chart.y_fields)

    def test_generic_numeric_fallback_excludes_dimension(self) -> None:
        chart = _chart_spec(
            [
                {"category": "north", "value_a": 2, "value_b": 7},
                {"category": "south", "value_a": 3, "value_b": 8},
            ],
            (),
        )

        self.assertIsNotNone(chart)
        assert chart is not None
        self.assertEqual("category", chart.x_field)
        self.assertEqual(("value_a", "value_b"), chart.y_fields)

    def test_metric_only_result_does_not_invent_an_axis(self) -> None:
        chart = _chart_spec(
            [{"governed_value": 42}],
            ("governed_value",),
        )

        self.assertIsNone(chart)


if __name__ == "__main__":
    unittest.main()
