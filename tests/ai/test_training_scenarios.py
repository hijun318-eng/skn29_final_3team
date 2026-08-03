import unittest
from collections import Counter

from src.ai.training.build_case_specs import build_case, select, select_coverage, select_held_out
from src.ai.training.generate_scenarios import generate


class TrainingScenarioTests(unittest.TestCase):
    def test_generation_is_deterministic_and_matches_the_manifest(self):
        first = generate()
        second = generate()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2_000)
        self.assertEqual(
            Counter(record["domain"] for record in first),
            Counter({"pms": 720, "crm": 440, "pms_crm": 360, "pos": 280, "facility": 120, "banquet": 80}),
        )
        self.assertEqual(
            Counter(record["target_split"] for record in first),
            Counter({"train": 1_200, "validation": 150, "gold": 120, "acceptance": 30, "reserve": 500}),
        )
        self.assertEqual(
            Counter(record["node"] for record in first),
            Counter({"node2": 1_600, "node2_repair": 400}),
        )
        self.assertEqual(
            Counter(record["context_shape"] for record in first),
            Counter({"minimal": 1_400, "distractor": 600}),
        )
        self.assertEqual(
            Counter(record["repair_error_code"] for record in first if record["repair_error_code"]),
            Counter(
                {
                    "RESOURCE_POLICY_MISSING": 120,
                    "REFERENCE_MISSING": 80,
                    "REFERENCE_OUTSIDE_CONTEXT": 70,
                    "SQL_REFERENCE_MISMATCH": 80,
                    "PARAMETERS_INVALID": 50,
                }
            ),
        )

    def test_full_training_selection_excludes_held_out_and_reserve_rows(self):
        selected = select(generate(), 0)

        self.assertEqual(len(selected), 1_350)
        self.assertEqual(
            Counter(record["target_split"] for record in selected),
            Counter({"train": 1_200, "validation": 150}),
        )

    def test_coverage_selection_includes_every_metric_and_repair_code(self):
        selected = select_coverage(generate())

        self.assertEqual(len(selected), 37)
        self.assertEqual(len({record["metric_id"] for record in selected}), 32)
        self.assertEqual(
            {record["repair_error_code"] for record in selected if record["node"] == "node2_repair"},
            {"RESOURCE_POLICY_MISSING", "REFERENCE_MISSING", "REFERENCE_OUTSIDE_CONTEXT", "SQL_REFERENCE_MISMATCH", "PARAMETERS_INVALID"},
        )

    def test_held_out_selection_is_explicit_and_does_not_leak(self):
        records = generate()
        selected = select_held_out(records)
        training_groups = {
            record["scenario_group"]
            for record in records
            if record["target_split"] in {"train", "validation"}
        }
        cases = [build_case(record, approved=True) for record in selected]

        self.assertEqual(
            Counter(case["split"] for case in cases),
            Counter({"gold": 120, "acceptance": 30}),
        )
        self.assertEqual({"APPROVED"}, {case["review_status"] for case in cases})
        self.assertTrue(training_groups.isdisjoint(case["scenario_group"] for case in cases))
        with self.assertRaisesRegex(ValueError, "only held-out"):
            build_case(next(record for record in records if record["target_split"] == "train"), approved=True)

    def test_full_training_questions_are_korean_and_do_not_leak_across_splits(self):
        cases = [build_case(record) for record in select(generate(), 0)]
        question_sql = []
        for case in cases:
            question = case["input"]["normalized_question"]
            output = case["expected_output"]
            sql = output.get("sql", output.get("corrected_sql"))
            self.assertNotIn("scalar", question)
            self.assertNotIn("trend", question)
            self.assertNotIn("comparison", question)
            question_sql.append((question, " ".join(sql.split()).lower()))

        self.assertEqual(len(question_sql), len(set(question_sql)))


if __name__ == "__main__":
    unittest.main()
