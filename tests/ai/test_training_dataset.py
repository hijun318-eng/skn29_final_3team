import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.ai.prompt_registry import get_prompt
from src.ai.training.dataset import (
    DatasetError,
    _validate_sql,
    build_records,
    load_compiled,
    load_specs,
    validate_model_output,
    write_jsonl,
)
from tests.ai.test_contracts import arbitrary_node2_request, arbitrary_node2_response


EXAMPLE = Path("src/ai/training/case_specs.example.jsonl")


class TrainingDatasetTests(unittest.TestCase):
    def test_example_builds_and_round_trips(self):
        specs = load_specs(EXAMPLE)
        records = build_records(specs)
        self.assertEqual(len(records), 4)
        self.assertEqual({record["split"] for record in records}, {"train", "validation", "gold", "acceptance"})
        self.assertEqual(
            [record["node"] for record in records],
            ["node2", "node2", "node2", "node2_repair"],
        )
        for spec in specs:
            expected_fields = (
                {"sql"}
                if spec["node"] == "node2"
                else {"corrected_sql"}
            )
            self.assertEqual(set(spec["expected_output"]), expected_fields)
            for parameter in spec["input"]["parameter_contract"]["parameters"]:
                self.assertEqual(set(parameter), {"name", "type", "scope"})
        for record in records:
            if record["node"] == "node2":
                self.assertEqual(
                    get_prompt("node2.sql_only").text,
                    record["messages"][0]["content"],
                )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dataset.jsonl"
            write_jsonl(output, records)
            self.assertEqual(load_compiled(output), records)

    def test_legacy_lineage_specs_are_not_compiled_for_sql_only_training(self):
        legacy = copy.deepcopy(load_specs(EXAMPLE)[0])
        legacy["expected_output"] = arbitrary_node2_response("quartz")

        with self.assertRaisesRegex(DatasetError, "SQL-only output shape"):
            build_records([legacy])

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
        original = copy.deepcopy(specs[0])
        original["input"] = arbitrary_node2_request("quartz")
        original["expected_output"] = arbitrary_node2_response("quartz")
        changed = copy.deepcopy(original)
        changed["case_id"] = "same-group-different-join-001"
        changed["input"]["join_graph"]["edges"][0]["cardinality"] = "one_to_one"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "join-graph.jsonl"
            path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [original, changed]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DatasetError, "changes join graph"):
                load_specs(path)

    def test_write_sql_is_rejected(self):
        specs = load_specs(EXAMPLE)
        unsafe = copy.deepcopy(specs[0])
        unsafe["expected_output"]["sql"] = (
            "DELETE FROM quartz_catalog.semantic.fact_observations"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.jsonl"
            path.write_text(json.dumps(unsafe, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "READ_ONLY_QUERY_REQUIRED"):
                load_specs(path)

    def test_ast_policy_rejects_dml_multiple_statements_and_star(self):
        unsafe = {
            "READ_ONLY_QUERY_REQUIRED": "DELETE FROM nebula.raw.events",
            "SINGLE_STATEMENT_REQUIRED": "SELECT 1 LIMIT 1; SELECT 2 LIMIT 1",
            "STAR_FORBIDDEN": "SELECT * FROM nebula.raw.events LIMIT 5",
        }
        for code, sql in unsafe.items():
            with self.subTest(code=code):
                with self.assertRaisesRegex(DatasetError, code):
                    _validate_sql(sql)

    def test_keywords_and_comment_tokens_inside_literals_are_not_sql_syntax(self):
        _validate_sql(
            'SELECT "select" FROM "Nebula"."Archive"."Events" '
            "WHERE \"memo\" = 'DROP TABLE x; -- literal text' LIMIT 7"
        )

    def test_ast_lineage_claims_and_placeholders_must_match(self):
        request = arbitrary_node2_request("quartz")
        response = arbitrary_node2_response("quartz")
        mutations = []
        wrong_asset = copy.deepcopy(response)
        wrong_asset["used_assets"] = ["rogue_catalog.semantic.fact_observations"]
        mutations.append((wrong_asset, "used_assets"))
        missing_column = copy.deepcopy(response)
        missing_column["used_columns"].pop()
        mutations.append((missing_column, "used_columns"))
        missing_join = copy.deepcopy(response)
        missing_join["used_joins"] = []
        mutations.append((missing_join, "used_joins"))
        wrong_metric = copy.deepcopy(response)
        wrong_metric["used_metrics"] = ["unresolved_measure"]
        mutations.append((wrong_metric, "used_metrics"))
        wrong_parameter = copy.deepcopy(response)
        wrong_parameter["sql"] = wrong_parameter["sql"].replace(
            ":quartz_status", ":undeclared_status"
        )
        mutations.append((wrong_parameter, "placeholders"))

        for candidate, message in mutations:
            with self.subTest(message=message):
                with self.assertRaisesRegex(DatasetError, message):
                    validate_model_output("node2", candidate, request)

    def test_sql_only_output_uses_request_and_ast_as_authoritative_lineage(self):
        request = arbitrary_node2_request("quartz")
        legacy = arbitrary_node2_response("quartz")

        result = validate_model_output("node2", {"sql": legacy["sql"]}, request)

        self.assertTrue(result.ok, result.violations)
        self.assertEqual(set(legacy["used_assets"]), set(result.physical_tables))

    def test_typed_time_parameters_require_ast_conversion(self):
        request = arbitrary_node2_request("quartz")
        response = arbitrary_node2_response("quartz")
        response["sql"] = response["sql"].replace(
            "from_iso8601_timestamp(:quartz_window_start)",
            ":quartz_window_start",
        )
        with self.assertRaisesRegex(DatasetError, "explicit conversion"):
            validate_model_output("node2", response, request)

    def test_legacy_model_output_fields_are_rejected(self):
        request = arbitrary_node2_request("quartz")
        for field in ("references", "parameters", "model"):
            response = arbitrary_node2_response("quartz")
            response[field] = []
            with self.subTest(field=field):
                with self.assertRaises(DatasetError):
                    validate_model_output("node2", response, request)

        repair = copy.deepcopy(load_specs(EXAMPLE)[-1])
        repair["expected_output"]["model"] = {}
        with self.assertRaises(DatasetError):
            validate_model_output(
                "node2_repair", repair["expected_output"], repair["input"]
            )

    def test_examples_have_no_operational_lineage_or_runtime_values(self):
        text = EXAMPLE.read_text(encoding="utf-8").casefold()
        for forbidden in (
            "context_package",
            '"references"',
            '"parameters":[]',
            "pms.public",
            "crm.dbo",
            "pos.pos_db",
            "synthetic_hotel",
            "room_revenue",
        ):
            self.assertNotIn(forbidden, text)
        self.assertNotRegex(text, r"\b20\d{2}-\d{2}-\d{2}\b")
        for spec in load_specs(EXAMPLE):
            sql_field = "sql" if spec["node"] == "node2" else "corrected_sql"
            self.assertFalse(
                spec["expected_output"][sql_field].lstrip().casefold().startswith("with ")
            )

    def test_stale_node_schema_version_is_rejected(self):
        stale = copy.deepcopy(load_specs(EXAMPLE)[0])
        stale["schema_version"] = "MODEL-stale"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stale.jsonl"
            path.write_text(json.dumps(stale) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "active Node contract"):
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
