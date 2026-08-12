import unittest

from src.ai.node1 import normalize_question
from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS


class Node1Tests(unittest.TestCase):
    def test_metric_dimension_and_absolute_period_candidates(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "이번 달 골드 회원의 객실 매출을 보여줘",
            "business_terms": {
                "room_revenue": {"kind": "metric", "aliases": ["객실 매출"]},
                "membership_grade": {"kind": "dimension", "aliases": ["골드 회원"]},
            },
        }
        result = normalize_question(payload)
        self.assertEqual(result["metric_candidates"], ["room_revenue"])
        self.assertEqual(result["selected_metric_id"], "room_revenue")
        self.assertEqual(result["dimension_candidates"], ["membership_grade"])
        self.assertEqual(result["period_candidates"][0]["start"], "2026-07-01T00:00:00+09:00")
        self.assertFalse(result["ambiguity"]["is_ambiguous"])
        self.assertNotIn("asset", result)
        self.assertNotIn("authorized", result)
        self.assertNotIn("gate", result)
        self.assertNotIn("sql", result)

    def test_missing_metric_has_no_selection(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "이번 달 현황을 보여줘",
        }

        result = normalize_question(payload)

        self.assertEqual(result["metric_candidates"], [])
        self.assertIsNone(result["selected_metric_id"])
        self.assertEqual(result["ambiguity"]["reasons"], ["metric_missing"])
        self.assertEqual(
            result["ambiguity"]["clarification_question"],
            "확인할 지표를 알려주세요.",
        )

    def test_explicit_metric_selection_is_normalized_without_asset_metadata(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "이번 달 포인트를 보여줘",
            "selected_metric_ids": ["current_points_balance_sum"],
            "business_terms": {
                "current_points_balance_sum": {
                    "kind": "metric",
                    "aliases": ["사용 가능 포인트 합계"],
                }
            },
        }

        result = normalize_question(payload)

        self.assertEqual(
            result["selected_metric_id"], "current_points_balance_sum"
        )
        self.assertNotIn("assets", payload)

    def test_multiple_metrics_are_ambiguous_without_arbitrary_selection(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "이번 달 객실 매출과 소멸 포인트를 보여줘",
            "business_terms": {
                "room_revenue": {"kind": "metric", "aliases": ["객실 매출"]},
                "expired_points": {"kind": "metric", "aliases": ["소멸 포인트"]},
            },
        }

        result = normalize_question(payload)

        self.assertEqual(
            result["metric_candidates"],
            ["room_revenue", "expired_points"],
        )
        self.assertIsNone(result["selected_metric_id"])
        self.assertEqual(result["ambiguity"]["reasons"], ["metric_ambiguous"])
        self.assertEqual(
            result["ambiguity"]["clarification_question"],
            "확인할 지표를 하나만 선택해 주세요.",
        )

    def test_specific_metric_alias_wins_over_an_overlapping_generic_alias(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "이번 달 소멸 포인트 합계",
            "business_terms": {
                "expired_points": {"kind": "metric", "aliases": ["소멸 포인트"]},
                "current_points_balance_sum": {
                    "kind": "metric",
                    "aliases": ["포인트 합계"],
                },
            },
        }

        result = normalize_question(payload)

        self.assertEqual(result["metric_candidates"], ["expired_points"])

    def test_multiple_dimensions_do_not_make_one_metric_ambiguous(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "이번 달 골드 회원의 객실 매출을 월별로 보여줘",
            "business_terms": {
                "room_revenue": {"kind": "metric", "aliases": ["객실 매출"]},
                "membership_grade": {"kind": "dimension", "aliases": ["골드 회원"]},
                "month": {"kind": "dimension", "aliases": ["월별"]},
            },
        }

        result = normalize_question(payload)

        self.assertEqual(result["selected_metric_id"], "room_revenue")
        self.assertEqual(
            result["dimension_candidates"],
            ["membership_grade", "month"],
        )
        self.assertFalse(result["ambiguity"]["is_ambiguous"])

    def test_missing_period_requests_only_the_missing_meaning(self):
        payload = {**VALID_PAYLOADS["node1_request"], "question": "객실 매출을 보여줘"}
        result = normalize_question(payload)
        self.assertEqual(result["ambiguity"]["reasons"], ["period_missing"])
        self.assertEqual(result["ambiguity"]["clarification_question"], "확인할 기간을 알려주세요.")

    def test_offsetless_or_mismatched_timezone_is_rejected(self):
        offsetless = {**VALID_PAYLOADS["node1_request"], "as_of": "2026-07-30T12:00:00"}
        with self.assertRaises(ContractError):
            normalize_question(offsetless)

        mismatched = {**VALID_PAYLOADS["node1_request"], "as_of": "2026-07-30T12:00:00+00:00"}
        with self.assertRaises(ContractError):
            normalize_question(mismatched)


if __name__ == "__main__":
    unittest.main()
