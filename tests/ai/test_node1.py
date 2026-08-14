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

    def test_explicit_korean_month_range_becomes_one_half_open_period(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "2026년 5월과 6월 객실 매출을 보여줘",
        }

        result = normalize_question(payload)

        self.assertEqual(
            result["period_candidates"],
            [{
                "start": "2026-05-01T00:00:00+09:00",
                "end_exclusive": "2026-07-01T00:00:00+09:00",
                "source_text": "2026년 5월과 6월",
            }],
        )

    def test_relative_periods_follow_as_of_and_seoul_calendar(self):
        expected = {
            "지난달": ("2026-06-01T00:00:00+09:00", "2026-07-01T00:00:00+09:00"),
            "지난 주": ("2026-07-20T00:00:00+09:00", "2026-07-27T00:00:00+09:00"),
            "이번 주": ("2026-07-27T00:00:00+09:00", "2026-07-30T00:00:00+09:00"),
            "최근 30일": ("2026-06-30T00:00:00+09:00", "2026-07-30T00:00:00+09:00"),
            "어제": ("2026-07-29T00:00:00+09:00", "2026-07-30T00:00:00+09:00"),
            "지난 분기": ("2026-04-01T00:00:00+09:00", "2026-07-01T00:00:00+09:00"),
        }
        for phrase, boundaries in expected.items():
            with self.subTest(phrase=phrase):
                payload = {
                    **VALID_PAYLOADS["node1_request"],
                    "question": f"{phrase} 객실 매출을 보여줘",
                }

                period = normalize_question(payload)["period_candidates"][0]

                self.assertEqual(boundaries, (period["start"], period["end_exclusive"]))
                self.assertEqual(phrase, period["source_text"])

    def test_last_month_crosses_year_boundary_without_guessing(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "지난달 객실 매출을 보여줘",
            "as_of": "2026-01-05T00:00:00+09:00",
        }

        period = normalize_question(payload)["period_candidates"][0]

        self.assertEqual("2025-12-01T00:00:00+09:00", period["start"])
        self.assertEqual("2026-01-01T00:00:00+09:00", period["end_exclusive"])

    def test_out_of_range_relative_duration_is_not_invented(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "최근 999일 객실 매출을 보여줘",
        }

        result = normalize_question(payload)

        self.assertEqual([], result["period_candidates"])
        self.assertIn("period_missing", result["ambiguity"]["reasons"])

    def test_alternative_months_remain_separate_candidates_until_user_selects(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "2026년 5월 또는 6월 객실 매출을 보여줘",
        }

        result = normalize_question(payload)

        self.assertEqual(
            [item["start"] for item in result["period_candidates"]],
            ["2026-05-01T00:00:00+09:00", "2026-06-01T00:00:00+09:00"],
        )

    def test_selected_period_marker_seals_one_candidate(self):
        payload = {
            **VALID_PAYLOADS["node1_request"],
            "question": "2026년 5월 또는 6월 객실 매출 (선택한 기간: 6월)",
        }

        result = normalize_question(payload)

        self.assertEqual(len(result["period_candidates"]), 1)
        self.assertEqual(
            result["period_candidates"][0]["start"],
            "2026-06-01T00:00:00+09:00",
        )

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
