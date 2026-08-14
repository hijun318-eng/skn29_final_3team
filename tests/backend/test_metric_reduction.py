import unittest
from decimal import Decimal
from pathlib import Path
from sys import path


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.analysis_responses import _reduce_metric_values


class MetricReductionTests(unittest.TestCase):
    def test_additive_metric_uses_decimal_sum(self):
        self.assertEqual(Decimal("0.3"), _reduce_metric_values("sum", ["0.1", "0.2"]))

    def test_scalar_metric_requires_exactly_one_value(self):
        self.assertEqual(Decimal("10"), _reduce_metric_values("scalar", [10]))
        self.assertIsNone(_reduce_metric_values("scalar", [10, 20]))

    def test_ratio_or_formula_is_not_summed_without_approved_components(self):
        self.assertIsNone(_reduce_metric_values("weighted_ratio", [0.5, 0.6]))
        self.assertIsNone(_reduce_metric_values("recompute", [100, 200]))

    def test_min_max_and_approved_arithmetic_average_are_explicit(self):
        self.assertEqual(Decimal("1.1"), _reduce_metric_values("min", ["2.2", "1.1"]))
        self.assertEqual(Decimal("2.2"), _reduce_metric_values("max", ["2.2", "1.1"]))
        self.assertEqual(
            Decimal("1.65"),
            _reduce_metric_values("average", ["2.2", "1.1"]),
        )


if __name__ == "__main__":
    unittest.main()
