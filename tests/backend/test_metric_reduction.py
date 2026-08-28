import unittest
from decimal import Decimal
from pathlib import Path
from sys import path
from types import SimpleNamespace


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.analysis.evidence import _reduce_context_metric, _reduce_metric_values
from app.services.analysis.responses import _presentation_rows
from app.services.analysis.result_narrative import _format_value, explanation_is_grounded
from app.services.analysis.result_validator import PipelineResultValidator
from app.contracts import PeriodEvidence
from app.services.context.builder import ContextMetric


class MetricReductionTests(unittest.TestCase):
    def test_additive_metric_uses_decimal_sum(self):
        self.assertEqual(Decimal("0.3"), _reduce_metric_values("sum", ["0.1", "0.2"]))

    def test_scalar_metric_requires_exactly_one_value(self):
        self.assertEqual(Decimal("10"), _reduce_metric_values("scalar", [10]))
        self.assertIsNone(_reduce_metric_values("scalar", [10, 20]))

    def test_min_max_and_approved_arithmetic_average_are_explicit(self):
        self.assertEqual(Decimal("1.1"), _reduce_metric_values("min", ["2.2", "1.1"]))
        self.assertEqual(Decimal("2.2"), _reduce_metric_values("max", ["2.2", "1.1"]))
        self.assertEqual(
            Decimal("1.65"),
            _reduce_metric_values("average", ["2.2", "1.1"]),
        )

    def test_ratio_uses_operand_totals_instead_of_averaging_row_ratios(self):
        numerator = ContextMetric(
            "occupied", "serving.rooms", "occupied", "sum", "business_date", (),
            "occupied", "room_nights", visibility="SUPPORT",
        )
        denominator = ContextMetric(
            "available", "serving.rooms", "available", "sum", "business_date", (),
            "available", "room_nights", visibility="SUPPORT",
        )
        ratio = ContextMetric(
            "occupancy", "", "", "ratio", "", (), "occupancy", "ratio",
            numerator_metric_id="occupied",
            denominator_metric_id="available",
            zero_policy="null_on_zero_denominator",
        )
        package = SimpleNamespace(metrics=(numerator, denominator, ratio))
        rows = [
            {"occupied": 1, "available": 2, "occupancy": 0.5},
            {"occupied": 9, "available": 10, "occupancy": 0.9},
        ]

        self.assertEqual(Decimal("10") / Decimal("12"), _reduce_context_metric(ratio, package, rows))
        self.assertFalse(PipelineResultValidator._ratio_value_violation(rows, package))
        rows[0]["occupancy"] = 0
        self.assertTrue(PipelineResultValidator._ratio_value_violation(rows, package))
        ratio_query = {
            "rows": [{"occupied": 1, "available": 2, "occupancy": 0.5}],
            "period": {"start": "2026-08-01", "end_exclusive": "2026-08-02"},
        }
        self.assertFalse(
            explanation_is_grounded(
                "2026-08-01부터 2026-08-02 전까지 Occupancy Rate는 0.5 ratio입니다.",
                ratio_query,
                package,
            )
        )
        self.assertTrue(
            explanation_is_grounded(
                "2026-08-01부터 2026-08-02 전까지 Occupancy Rate는 50%입니다.",
                ratio_query,
                package,
            )
        )

    def test_ratio_display_is_percent_rounded_and_zero_is_not_erased(self):
        self.assertEqual("65.23%", _format_value(Decimal("0.652306318"), "ratio"))
        self.assertEqual("0 KRW", _format_value(Decimal("0"), "KRW"))

    def test_support_metric_columns_are_hidden_only_from_user_presentation(self):
        package = SimpleNamespace(
            metrics=(
                SimpleNamespace(id="numerator", result_field="internal_numerator"),
                SimpleNamespace(id="denominator", result_field="internal_denominator"),
                SimpleNamespace(id="ratio", result_field="business_ratio"),
            ),
            metric_terms=(SimpleNamespace(id="ratio"),),
        )
        source_rows = (
            {
                "business_date": "2026-08-01",
                "internal_numerator": 8,
                "internal_denominator": 10,
                "business_ratio": 0.8,
            },
        )

        self.assertEqual(
            (
                {
                    "business_date": "2026-08-01",
                    "business_ratio": 0.8,
                },
            ),
            _presentation_rows(package, source_rows),
        )
        self.assertIn("internal_numerator", source_rows[0])

    def test_period_comparison_is_presented_as_period_rows_without_internal_suffixes(self):
        package = SimpleNamespace(
            metrics=(
                SimpleNamespace(id="alpha", result_field="alpha_value"),
                SimpleNamespace(id="beta", result_field="beta_value"),
            ),
            metric_terms=(SimpleNamespace(id="alpha"), SimpleNamespace(id="beta")),
        )
        source_rows = (
            {
                "alpha_value": 17,
                "alpha_value__comparison": 11,
                "beta_value": 29,
                "beta_value__comparison": 23,
            },
        )

        rows = _presentation_rows(
            package,
            source_rows,
            PeriodEvidence(start="2042-06-01", end_exclusive="2042-07-01"),
            PeriodEvidence(start="2042-05-01", end_exclusive="2042-06-01"),
        )

        self.assertEqual(
            (
                {"period": "2042-06-01", "alpha_value": 17, "beta_value": 29},
                {"period": "2042-05-01", "alpha_value": 11, "beta_value": 23},
            ),
            rows,
        )
        self.assertNotIn("alpha_value__comparison", rows[1])

    def test_ratio_period_comparison_preserves_business_values_and_hides_operands(self):
        numerator = ContextMetric(
            "numerator", "serving.metrics", "numerator", "sum", "business_date", (),
            "internal_numerator", "units", visibility="SUPPORT",
        )
        denominator = ContextMetric(
            "denominator", "serving.metrics", "denominator", "sum", "business_date", (),
            "internal_denominator", "units", visibility="SUPPORT",
        )
        ratio = ContextMetric(
            "ratio", "", "", "ratio", "", (), "business_ratio", "ratio",
            numerator_metric_id="numerator",
            denominator_metric_id="denominator",
            zero_policy="null_on_zero_denominator",
        )
        package = SimpleNamespace(
            metrics=(numerator, denominator, ratio),
            metric_terms=(SimpleNamespace(id="ratio"),),
        )
        source_rows = (
            {
                "business_ratio": 2.0,
                "business_ratio__comparison": 3.0,
                "internal_numerator": 10,
                "internal_numerator__comparison": 9,
                "internal_denominator": 5,
                "internal_denominator__comparison": 3,
            },
        )

        self.assertFalse(
            PipelineResultValidator._ratio_value_violation(list(source_rows), package)
        )
        self.assertEqual(
            Decimal("3"),
            _reduce_context_metric(ratio, package, source_rows, "__comparison"),
        )
        self.assertEqual(
            (
                {"period": "2042-06-01", "business_ratio": 2.0},
                {"period": "2042-05-01", "business_ratio": 3.0},
            ),
            _presentation_rows(
                package,
                source_rows,
                PeriodEvidence(start="2042-06-01", end_exclusive="2042-07-01"),
                PeriodEvidence(start="2042-05-01", end_exclusive="2042-06-01"),
            ),
        )

    def test_narrative_rejects_inclusive_wording_for_exclusive_period_end(self):
        query = {
            "rows": [{"hotel_code": "VISTA", "revenue": 10}],
            "period": {"start": "2026-08-01", "end_exclusive": "2026-08-20"},
        }

        self.assertFalse(
            explanation_is_grounded(
                "2026-08-01부터 2026-08-20까지 매출은 10 KRW입니다.",
                query,
            )
        )
        self.assertTrue(
            explanation_is_grounded(
                "2026-08-01부터 2026-08-20 전까지 매출은 10 KRW입니다.",
                query,
            )
        )
        self.assertFalse(
            explanation_is_grounded(
                "2026-08-01 전부터 2026-08-20 전까지 매출은 10 KRW입니다.",
                query,
            )
        )
        self.assertFalse(
            explanation_is_grounded(
                "2026-08-01부터 2026-08-20 전까지 관측값이 10 KRW입니다.",
                query,
            )
        )


if __name__ == "__main__":
    unittest.main()
