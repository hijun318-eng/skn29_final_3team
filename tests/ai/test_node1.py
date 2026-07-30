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
        self.assertEqual(result["dimension_candidates"], ["membership_grade"])
        self.assertEqual(result["period_candidates"][0]["start"], "2026-07-01T00:00:00+09:00")
        self.assertFalse(result["ambiguity"]["is_ambiguous"])
        self.assertNotIn("asset", result)
        self.assertNotIn("authorized", result)
        self.assertNotIn("gate", result)
        self.assertNotIn("sql", result)

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
