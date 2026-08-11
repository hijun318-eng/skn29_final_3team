import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.ai.training.dataset import DatasetError, build_records, load_compiled, load_specs, write_jsonl


EXAMPLE = Path("src/ai/training/case_specs.example.jsonl")


class TrainingDatasetTests(unittest.TestCase):
    def test_example_builds_and_round_trips(self):
        specs = load_specs(EXAMPLE)
        records = build_records(specs)
        self.assertEqual(len(records), 4)
        self.assertEqual({record["split"] for record in records}, {"train", "validation", "gold", "acceptance"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dataset.jsonl"
            write_jsonl(output, records)
            self.assertEqual(load_compiled(output), records)

    def test_split_leakage_is_rejected(self):
        specs = load_specs(EXAMPLE)
        leaked = copy.deepcopy(specs[0])
        leaked["case_id"] = "gold-leaked-001"
        leaked["split"] = "gold"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "leaked.jsonl"
            path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [specs[0], leaked]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DatasetError, "leaks across"):
                load_specs(path)

    def test_join_graph_cannot_change_inside_scenario_group(self):
        specs = load_specs(EXAMPLE)
        changed = copy.deepcopy(specs[0])
        changed["case_id"] = "same-group-different-join-001"
        changed["input"]["context_package"]["joins"] = [
            {
                "id": "approved-join",
                "left": "pms.stays",
                "right": "crm.accounts",
                "cardinality": "many-to-one",
                "status": "approved",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "join-graph.jsonl"
            path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [specs[0], changed]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DatasetError, "changes join graph"):
                load_specs(path)

    def test_write_sql_is_rejected(self):
        specs = load_specs(EXAMPLE)
        unsafe = copy.deepcopy(specs[0])
        unsafe["expected_output"]["sql"] = "DELETE FROM pms.public.pms_stays"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.jsonl"
            path.write_text(json.dumps(unsafe, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "SELECT or WITH"):
                load_specs(path)

    def test_possible_pii_is_rejected(self):
        specs = load_specs(EXAMPLE)
        pii = copy.deepcopy(specs[0])
        pii["input"]["normalized_question"] = "test@example.com 고객의 매출"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pii.jsonl"
            path.write_text(json.dumps(pii, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "possible email"):
                load_specs(path)


if __name__ == "__main__":
    unittest.main()
