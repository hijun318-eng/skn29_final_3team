from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from app.api.mcp_router import _tool_registry
from app.services.rag_gateway import (
    RAG_TOOL_DESCRIPTION,
    RAG_TOOL_ID,
    RAG_TOOL_INPUT_SCHEMA,
    RAG_TOOL_OUTPUT_SCHEMA,
    RAG_TOOL_ROLES,
    RAG_TOOL_SEMANTIC_VERSION,
    RAG_TOOL_TIMEOUT_SECONDS,
    RAG_TOOL_TRANSPORT,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    ROOT
    / "app/backend/migrations/versions/20260831_64_mcp_candidate_descriptors.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mcp_candidate_64", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("MCP candidate migration module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalized_sql(statement: str) -> str:
    return " ".join(statement.upper().split())


def _capture_sql(module: ModuleType, direction: str) -> tuple[str, ...]:
    statements: list[str] = []
    with patch.object(module.op, "execute", side_effect=statements.append):
        getattr(module, direction)()
    return tuple(_normalized_sql(statement) for statement in statements)


def _registry_lock_predicate(statement: str) -> str:
    match = re.search(
        r"PERFORM 1 FROM TOOLING\.TOOL_REGISTRY WHERE (.*?) FOR UPDATE;",
        statement,
    )
    if match is None:
        raise AssertionError("exact tooling.tool_registry row lock is missing")
    return match.group(1)


def _registry_mutation_predicate(statement: str, verb: str) -> str:
    if verb == "UPDATE":
        pattern = (
            r"UPDATE TOOLING\.TOOL_REGISTRY SET .*? WHERE (.*?); "
            r"GET DIAGNOSTICS"
        )
    elif verb == "DELETE":
        pattern = (
            r"DELETE FROM TOOLING\.TOOL_REGISTRY WHERE (.*?); "
            r"GET DIAGNOSTICS"
        )
    else:
        raise ValueError(f"unsupported registry mutation: {verb}")
    match = re.search(pattern, statement)
    if match is None:
        raise AssertionError(f"tooling.tool_registry {verb.lower()} is missing")
    return match.group(1)


def _predicate_terms(predicate: str) -> set[str]:
    return {term.strip(" ()") for term in predicate.split(" AND ")}


def _assert_nested_objects_are_closed(test: unittest.TestCase, value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            test.assertIs(
                False,
                value.get("additionalProperties"),
                f"open object schema: {value}",
            )
        for nested in value.values():
            _assert_nested_objects_are_closed(test, nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_nested_objects_are_closed(test, nested)


class MCPCandidateDescriptorMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migration = _load_migration()

    def test_migration_extends_rate_limit_head_and_keeps_candidates_disabled(self) -> None:
        """신규 candidate는 63 뒤에서만 등록되고 handler 없이 비활성 상태다."""

        self.assertEqual("20260831_64", self.migration.revision)
        self.assertEqual("20260831_63", self.migration.down_revision)
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for tool_code in ("analysis.run", "rag.answer", "ml.predict"):
            self.assertIn(tool_code, source)
        self.assertNotIn("is_enabled = true", source.lower())
        self.assertGreaterEqual(source.lower().count("is_enabled = false"), 4)
        self.assertIn("affected <> 1", source)
        self.assertIn("historical runs must be preserved", source)
        self.assertGreaterEqual(source.count("input_schema_json ="), 4)
        self.assertGreaterEqual(source.count("output_schema_json ="), 4)
        self.assertGreaterEqual(source.count("transport = 'MCP_STREAMABLE_HTTP'"), 3)

        active_code_descriptors = tuple(
            descriptor.name for descriptor in _tool_registry()._descriptors
        )
        self.assertEqual(("analysis.get_run",), active_code_descriptors)

    def test_each_candidate_is_disabled_and_has_no_runtime_handler(self) -> None:
        """세 candidate 모두 DB 경계에만 있고 운영 dispatcher에는 조립되지 않는다."""

        runtime_names = {
            descriptor.name for descriptor in _tool_registry()._descriptors
        }
        statements = _capture_sql(self.migration, "upgrade")
        candidates = (
            (
                "analysis.run",
                self.migration.ANALYSIS_RUN_TOOL_ID,
                "0.1.0-CANDIDATE",
            ),
            (
                "rag.answer",
                self.migration.RAG_ANSWER_TOOL_ID,
                "1.2.0-CANDIDATE",
            ),
            (
                "ml.predict",
                self.migration.ML_PREDICT_TOOL_ID,
                "0.1.0-CANDIDATE",
            ),
        )
        for tool_code, tool_id, version in candidates:
            with self.subTest(tool_code=tool_code):
                self.assertNotIn(tool_code, runtime_names)
                matching = tuple(
                    statement
                    for statement in statements
                    if f"TOOL_ID = '{tool_id.upper()}'" in statement
                    or f"'{tool_id.upper()}', '{tool_code.upper()}'" in statement
                )
                self.assertTrue(matching)
                rendered = " ".join(matching)
                self.assertIn(tool_code.upper(), rendered)
                self.assertIn(version, rendered)
                self.assertIn("IS_ENABLED", rendered)
                self.assertRegex(
                    rendered,
                    r"IS_ENABLED = FALSE|IS_ENABLED\) VALUES \( .* FALSE \)",
                )

    def test_upgrade_locks_exact_rag_predecessor_before_run_check(self) -> None:
        statements = _capture_sql(self.migration, "upgrade")
        rag_update = next(
            statement
            for statement in statements
            if "UPDATE TOOLING.TOOL_REGISTRY" in statement
            and "TOOL_CODE = 'RAG.ANSWER'" in statement
        )

        lock_terms = _predicate_terms(_registry_lock_predicate(rag_update))
        update_terms = _predicate_terms(
            _registry_mutation_predicate(rag_update, "UPDATE")
        )
        self.assertEqual(update_terms, lock_terms)
        self.assertIn(
            f"TOOL_ID = '{self.migration.RAG_ANSWER_TOOL_ID.upper()}'",
            lock_terms,
        )
        self.assertIn("TOOL_CODE = 'RAG.ANSWER'", lock_terms)
        self.assertIn("SEMANTIC_VERSION = '1.1.0'", lock_terms)

        lock_at = rag_update.index("FOR UPDATE;")
        run_check_at = rag_update.index(
            "FROM TOOLING.TOOL_RUNS "
            f"WHERE TOOL_ID = '{self.migration.RAG_ANSWER_TOOL_ID.upper()}'"
        )
        update_at = rag_update.index("UPDATE TOOLING.TOOL_REGISTRY")
        self.assertLess(lock_at, run_check_at)
        self.assertLess(run_check_at, update_at)

    def test_downgrade_locks_exact_receipts_and_checks_candidate_children(self) -> None:
        statements = _capture_sql(self.migration, "downgrade")
        rag_update = next(
            statement
            for statement in statements
            if "UPDATE TOOLING.TOOL_REGISTRY" in statement
            and "TOOL_CODE = 'RAG.ANSWER'" in statement
        )
        self.assertEqual(
            _predicate_terms(_registry_mutation_predicate(rag_update, "UPDATE")),
            _predicate_terms(_registry_lock_predicate(rag_update)),
        )

        for tool_id, tool_code in (
            (self.migration.ANALYSIS_RUN_TOOL_ID, "analysis.run"),
            (self.migration.ML_PREDICT_TOOL_ID, "ml.predict"),
        ):
            with self.subTest(tool_code=tool_code):
                normalized_tool_id = tool_id.upper()
                candidate_delete = next(
                    statement
                    for statement in statements
                    if "DELETE FROM TOOLING.TOOL_REGISTRY" in statement
                    and f"TOOL_ID = '{normalized_tool_id}'" in statement
                )
                lock_terms = _predicate_terms(
                    _registry_lock_predicate(candidate_delete)
                )
                delete_terms = _predicate_terms(
                    _registry_mutation_predicate(candidate_delete, "DELETE")
                )
                self.assertEqual(delete_terms, lock_terms)
                self.assertIn(f"TOOL_ID = '{normalized_tool_id}'", lock_terms)
                self.assertIn(f"TOOL_CODE = '{tool_code.upper()}'", lock_terms)
                self.assertIn("SEMANTIC_VERSION = '0.1.0-CANDIDATE'", lock_terms)

                lock_at = candidate_delete.index("FOR UPDATE;")
                run_check_at = candidate_delete.index(
                    "FROM TOOLING.TOOL_RUNS "
                    f"WHERE TOOL_ID = '{normalized_tool_id}'"
                )
                quota_check_at = candidate_delete.index(
                    "FROM TOOLING.TOOL_RATE_LIMIT_WINDOWS "
                    f"WHERE TOOL_ID = '{normalized_tool_id}'"
                )
                delete_at = candidate_delete.index(
                    "DELETE FROM TOOLING.TOOL_REGISTRY"
                )
                self.assertLess(lock_at, run_check_at)
                self.assertLess(lock_at, quota_check_at)
                self.assertLess(run_check_at, delete_at)
                self.assertLess(quota_check_at, delete_at)

    def test_candidate_schemas_are_valid_and_recursively_closed(self) -> None:
        """Candidate input/output은 Draft 2020-12와 nested closed 계약을 만족한다."""

        for name in (
            "ANALYSIS_RUN_INPUT_SCHEMA",
            "ANALYSIS_RUN_OUTPUT_SCHEMA",
            "RAG_ANSWER_INPUT_SCHEMA",
            "RAG_ANSWER_OUTPUT_SCHEMA",
            "ML_PREDICT_INPUT_SCHEMA",
            "ML_PREDICT_OUTPUT_SCHEMA",
        ):
            with self.subTest(name=name):
                schema = getattr(self.migration, name)
                Draft202012Validator.check_schema(schema)
                _assert_nested_objects_are_closed(self, schema)

    def test_rag_runtime_activation_descriptor_exactly_matches_migration(self) -> None:
        """Runtime activation receipt cannot drift from the disabled DB candidate."""

        self.assertEqual(str(RAG_TOOL_ID), self.migration.RAG_ANSWER_TOOL_ID)
        self.assertEqual("1.2.0-candidate", RAG_TOOL_SEMANTIC_VERSION)
        self.assertEqual(
            self.migration.RAG_ANSWER_INPUT_SCHEMA,
            RAG_TOOL_INPUT_SCHEMA,
        )
        self.assertEqual(
            self.migration.RAG_ANSWER_OUTPUT_SCHEMA,
            RAG_TOOL_OUTPUT_SCHEMA,
        )
        self.assertEqual(
            "Answer only from approved internal documents with citation-bound evidence.",
            RAG_TOOL_DESCRIPTION,
        )
        self.assertEqual("MCP_STREAMABLE_HTTP", RAG_TOOL_TRANSPORT)
        self.assertEqual(30, RAG_TOOL_TIMEOUT_SECONDS)
        self.assertEqual(("analyst",), RAG_TOOL_ROLES)

    def test_migration_json_does_not_create_sqlalchemy_bind_tokens(self) -> None:
        """JSON scalar 앞 공백을 보존해 ``:false``·``:16`` bind 오인을 막는다."""

        serialized = self.migration._json(
            self.migration.ANALYSIS_RUN_INPUT_SCHEMA
        )
        self.assertIn('"additionalProperties": false', serialized)
        self.assertIn('"minLength": 16', serialized)
        self.assertNotIn('"additionalProperties":false', serialized)
        self.assertNotIn('"minLength":16', serialized)

    def test_rag_candidate_matches_multiturn_and_status_projections(self) -> None:
        """RAG input은 query-only도 허용하고 상태별 공개 결과 shape를 구분한다."""

        input_validator = Draft202012Validator(
            self.migration.RAG_ANSWER_INPUT_SCHEMA,
            format_checker=FormatChecker(),
        )
        input_validator.validate({"query": "회계팀 승인 지침을 찾아줘"})
        input_validator.validate(
            {
                "query": "앞서 본 지침과 비교해줘",
                "recent_utterances": ["회계 지침을 찾아줘"],
                "selected_document_ids": ["finance/manual:001"],
            }
        )
        with self.assertRaises(Exception):
            input_validator.validate(
                {
                    "query": "비교해줘",
                    "recent_utterances": ["1", "2", "3", "4"],
                }
            )

        output_validator = Draft202012Validator(
            self.migration.RAG_ANSWER_OUTPUT_SCHEMA,
            format_checker=FormatChecker(),
        )
        answer = {
            "status": "ANSWER",
            "trace_id": "trace-rag",
            "answer": {"text": "승인된 근거 답변"},
            "citations": [
                {"evidence_id": "evidence-1", "citation": "FINANCE-001 p.2"}
            ],
            "evidence_bundle": [],
        }
        output_validator.validate(answer)
        conflict = {
            "status": "CONFLICT",
            "trace_id": "trace-conflict",
            "conflicts": [
                {
                    "description": "두 승인 문서의 적용 시점이 다릅니다.",
                    "evidence_ids": ["evidence-old", "evidence-new"],
                }
            ],
            "evidence_bundle": [],
        }
        output_validator.validate(conflict)
        with self.assertRaises(Exception):
            output_validator.validate({**conflict, "answer": {"text": "invalid"}})
        with self.assertRaises(Exception):
            output_validator.validate(
                {
                    "status": "ANSWER",
                    "trace_id": "trace-missing-answer",
                    "evidence_bundle": [],
                }
            )

    def test_ml_candidate_uses_actual_prediction_names_and_provenance(self) -> None:
        """ML 교체 seam은 typed 입력과 현행 runtime의 핵심 예측 receipt를 고정한다."""

        input_schema = self.migration.ML_PREDICT_INPUT_SCHEMA
        self.assertEqual(
            ["property_id", "as_of", "horizon_days"],
            input_schema["required"],
        )
        properties = self.migration.ML_PREDICT_OUTPUT_SCHEMA["properties"]
        daily = properties["daily_forecasts"]["items"]["properties"]
        self.assertIn("predicted_available_rooms", daily)
        self.assertIn("predicted_occupancy_rate", daily)
        self.assertNotIn("occupancy_rate", daily)
        self.assertIn("model_hash", properties)
        self.assertIn("provenance", properties)
        self.assertEqual(
            0,
            daily["total_available_rooms"]["exclusiveMinimum"],
        )

    def test_analysis_candidate_uses_persisted_runtime_statuses(self) -> None:
        """analysis.run 응답은 실제 analysis request 상태 집합을 사용한다."""

        statuses = set(
            self.migration.ANALYSIS_RUN_OUTPUT_SCHEMA["properties"]["status"][
                "enum"
            ]
        )
        self.assertIn("RECEIVED", statuses)
        self.assertIn("PARTIAL", statuses)
        self.assertIn("DENIED", statuses)
        self.assertNotIn("PENDING", statuses)


if __name__ == "__main__":
    unittest.main()
