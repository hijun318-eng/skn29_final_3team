import unittest

from src.ai.training.verify_case_specs import _result_hash, _rows_hash


class TrainingVerificationTests(unittest.TestCase):
    def test_result_hash_ignores_row_order(self):
        first = _result_hash('{"name":"B","value":2}\n{"name":"A","value":1}\n')
        second = _result_hash('{"value":1,"name":"A"}\n{"value":2,"name":"B"}\n')

        self.assertEqual(first, second)
        self.assertEqual(first, _rows_hash([{"value": 2, "name": "B"}, {"value": 1, "name": "A"}]))


if __name__ == "__main__":
    unittest.main()
