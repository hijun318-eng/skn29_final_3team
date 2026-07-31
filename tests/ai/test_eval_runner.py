import copy
import unittest

from evals.runner import EvaluationError, evaluate_cases
from src.ai.fake_model import FakeModelAdapter
from tests.ai.test_contracts import VALID_PAYLOADS


def valid_case():
    adapter = FakeModelAdapter()
    request = copy.deepcopy(VALID_PAYLOADS["node3_request"])
    return {
        "case_id": "required30-node3-001",
        "node": "node3",
        "request": request,
        "expected_output": adapter.generate("node3", request),
    }


class EvaluationRunnerTests(unittest.TestCase):
    def test_result_and_hash_are_reproducible(self):
        first = evaluate_cases([valid_case()])
        second = evaluate_cases([valid_case()])

        self.assertEqual(first, second)
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["passed"], 1)
        self.assertEqual(first["failed"], 0)

    def test_expected_output_mismatch_fails(self):
        case = valid_case()
        case["expected_output"]["explanation"] = "unsupported"
        result = evaluate_cases([case])
        self.assertEqual(result["failed"], 1)

    def test_missing_extra_and_duplicate_case_ids_are_rejected(self):
        missing = valid_case()
        missing.pop("expected_output")
        with self.assertRaises(EvaluationError):
            evaluate_cases([missing])

        extra = valid_case()
        extra["unexpected"] = True
        with self.assertRaises(EvaluationError):
            evaluate_cases([extra])

        case = valid_case()
        with self.assertRaises(EvaluationError):
            evaluate_cases([case, case])


if __name__ == "__main__":
    unittest.main()
