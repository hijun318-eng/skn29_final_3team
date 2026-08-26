from __future__ import annotations

import ast
from pathlib import Path
import unittest


MIGRATIONS = Path(__file__).resolve().parents[2] / "app" / "backend" / "migrations" / "versions"


class ReportMigrationTest(unittest.TestCase):
    def test_report_registration_is_one_new_migration_after_existing_head(self):
        source = (MIGRATIONS / "20260804_04_report_registration.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }

        self.assertEqual(
            {"revision": "20260804_04", "down_revision": "20260731_03"},
            values,
        )
        for table in (
            "report_definitions",
            "report_definition_versions",
            "report_blocks",
            "report_runs",
            "report_block_runs",
        ):
            self.assertIn(f"CREATE TABLE report_v1.{table}", source)
        self.assertIn("report_approved_version_immutable", source)
        self.assertIn("report_approved_blocks_immutable", source)
        self.assertIn("report_run_requires_approved_definition", source)
        self.assertNotIn("worker", source.lower())
        self.assertNotIn("schedule", source.lower())

    def test_report_v11_is_a_new_additive_migration_after_report_v1(self):
        source = (MIGRATIONS / "20260804_05_report_v11_registration.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }
        self.assertEqual(
            {"revision": "20260804_05", "down_revision": "20260804_04"},
            values,
        )
        for field in ("block_type", " x smallint", " y smallint", " w smallint", " h smallint", "content text"):
            self.assertIn(field, source)
        self.assertIn("columns = w", source)
        self.assertIn("x + w <= 12", source)
        self.assertIn("report_block_artifact_check", source)
        self.assertIn("CREATE TABLE report_v1.report_manual_run_commands", source)
        self.assertIn("report_manual_command_requires_approved_definition", source)
        self.assertIn("UNIQUE (definition_id, definition_version, idempotency_key)", source)
        self.assertIn("CHECK (btrim(idempotency_key) <> '')", source)
        self.assertIn("GRANT DELETE ON report_v1.report_blocks", source)
        self.assertIn("GRANT SELECT, INSERT, UPDATE ON report_v1.report_manual_run_commands", source)
        self.assertNotIn("worker", source.lower())
        self.assertNotIn("schedule", source.lower())

    def test_report_schedule_is_additive_and_references_approved_versions_and_runs(self):
        source = (MIGRATIONS / "20260812_10_report_schedules.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }

        self.assertEqual(
            {"revision": "20260812_10", "down_revision": "20260812_09"},
            values,
        )
        self.assertIn("CREATE TABLE report_v1.report_schedules", source)
        self.assertIn("REFERENCES report_v1.report_definition_versions", source)
        self.assertIn("REFERENCES report_v1.report_runs", source)
        self.assertIn("CHECK (cadence IN ('daily', 'weekly', 'monthly'))", source)
        self.assertIn("CHECK (timezone_name = 'Asia/Seoul')", source)
        self.assertIn("GRANT SELECT, INSERT, UPDATE ON report_v1.report_schedules", source)

    def test_report_assistant_persists_success_and_failure_without_prompt_text(self):
        source = (MIGRATIONS / "20260812_11_report_assistant.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('revision = "20260812_11"', source)
        self.assertIn('down_revision = "20260812_10"', source)
        self.assertIn("CREATE TABLE report_v1.report_assistant_requests", source)
        self.assertIn("artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts", source)
        self.assertIn("instruction_hash varchar(64)", source)
        self.assertIn("prompt_hash varchar(64)", source)
        self.assertIn("status IN ('running', 'success', 'failed')", source)
        self.assertNotIn("instruction text", source)

    def test_report_assistant_session_extension_preserves_legacy_status(self):
        """새 migration은 기존 표를 재생성하지 않고 phase·승인 계획·owner index만 추가한다."""

        source = (MIGRATIONS / "20260826_38_report_assistant_sessions.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('down_revision = "20260826_37"', source)
        self.assertIn("ADD COLUMN phase varchar(24)", source)
        self.assertIn("ADD COLUMN analysis_plan_json jsonb", source)
        self.assertIn("report_assistant_owner_phase_idx", source)
        self.assertNotIn("DROP TABLE report_v1.report_assistant_requests", source)

    def test_report_assistant_result_lineage_is_additive(self):
        """3단계 migration은 query·checksum lineage를 새 revision으로만 추가한다."""

        source = (MIGRATIONS / "20260826_39_report_assistant_result_lineage.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('down_revision = "20260826_38"', source)
        self.assertIn("ADD COLUMN result_query_id", source)
        self.assertIn("ADD COLUMN result_artifact_checksum", source)
        self.assertIn("report_assistant_result_lineage_check", source)

    def test_report_assistant_revision_cas_is_additive(self):
        """4단계 migration은 기존 version을 바꾸지 않고 revision token만 추가한다."""

        source = (MIGRATIONS / "20260826_40_report_assistant_revision_cas.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('down_revision = "20260826_39"', source)
        self.assertIn("ADD COLUMN revision bigint NOT NULL DEFAULT 1", source)
        self.assertNotIn("DROP TABLE report_v1.report_definition_versions", source)

    def test_report_assistant_patch_audit_is_additive(self):
        """실구현 2단계 migration은 기존 요청을 보존하고 검증 patch 감사값만 추가한다."""

        source = (MIGRATIONS / "20260826_41_report_assistant_patch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('down_revision = "20260826_40"', source)
        self.assertIn("ADD COLUMN report_patch_json jsonb", source)
        self.assertNotIn("DROP TABLE report_v1.report_assistant_requests", source)

    def test_report_assistant_turn_history_is_owner_session_bound(self):
        """실구현 4단계 migration은 세션별 순번과 bounded 대화 원문을 별도 표에 둔다."""

        source = (MIGRATIONS / "20260826_42_report_assistant_turns.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('down_revision = "20260826_41"', source)
        self.assertIn("CREATE TABLE report_v1.report_assistant_turns", source)
        self.assertIn("PRIMARY KEY (assistant_request_id, turn_number)", source)
        self.assertIn("REFERENCES report_v1.report_assistant_requests", source)
        self.assertIn("change_kind IN ('clarification', 'existing_artifact', 'new_data')", source)

    def test_report_assistant_patch_approval_adds_phase_without_rewriting_history(self):
        """새 migration은 patch 요청 ID를 추가하고 완료 phase의 잘못된 계획 제약을 수정한다."""

        source = (MIGRATIONS / "20260826_43_report_assistant_patch_approval.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('down_revision = "20260826_42"', source)
        self.assertIn("ADD COLUMN patch_request_id uuid", source)
        self.assertIn("'waiting_patch_approval'", source)
        self.assertIn("phase IN ('ready', 'completed', 'failed', 'cancelled')", source)
        self.assertNotIn("DROP TABLE report_v1.report_assistant_requests", source)

    def test_report_assistant_evaluation_is_additive_and_excludes_sensitive_payloads(self):
        """품질 migration은 요청별 한 건만 저장하고 raw prompt·SQL column을 만들지 않는다."""

        source = (MIGRATIONS / "20260826_44_report_assistant_evaluations.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('down_revision = "20260826_43"', source)
        self.assertIn("CREATE TABLE report_v1.report_assistant_evaluations", source)
        self.assertIn("assistant_request_id uuid NOT NULL UNIQUE", source)
        self.assertIn("input_tokens integer", source)
        self.assertIn("estimated_cost numeric", source)
        self.assertNotIn("raw_prompt", source)
        self.assertNotIn("raw_model_response", source)
        self.assertNotIn("sql_text", source)

    def test_report_assistant_retry_lineage_is_additive_and_idempotent(self):
        """재시도 migration은 원본을 보존하고 실패 요청별 자식 하나만 허용한다."""

        source = (MIGRATIONS / "20260826_45_report_assistant_retry_lineage.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('down_revision = "20260826_44"', source)
        self.assertIn("ADD COLUMN retry_of_assistant_request_id uuid", source)
        self.assertIn("ADD COLUMN retry_created_at timestamptz", source)
        self.assertIn("CREATE UNIQUE INDEX report_assistant_retry_source_idx", source)
        self.assertNotIn("DROP TABLE report_v1.report_assistant_requests", source)

    def test_query_generation_mode_records_llm_without_fallback(self):
        source = (MIGRATIONS / "20260813_14_query_generation_mode_llm.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('revision = "20260813_14"', source)
        self.assertIn('down_revision = "20260813_13"', source)
        upgrade = source.split("def downgrade", 1)[0]
        self.assertIn("generation_mode = 'LLM'", upgrade)
        self.assertIn("generation_mode IN ('LLM', 'TEMPLATE')", upgrade)
        self.assertIn("FALLBACK query history must be reviewed", upgrade)

    def test_report_replay_migration_persists_lineage_and_typed_failure(self):
        source = (MIGRATIONS / "20260814_20_report_replay_lineage.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('revision = "20260814_20"', source)
        self.assertIn('down_revision = "20260814_19"', source)
        self.assertIn("analysis_definition_id", source)
        self.assertIn("analysis_definition_version", source)
        self.assertIn("request_id uuid REFERENCES chat.analysis_requests", source)
        self.assertIn("failure_code", source)
        self.assertIn("report_block_run_failure_check", source)
        self.assertIn("status IN ('queued','running','success','partial','failed','cancelled')", source)

    def test_aggregate_artifact_block_migration_extends_every_data_constraint(self):
        source = (MIGRATIONS / "20260814_22_report_artifact_blocks.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('revision = "20260814_22"', source)
        self.assertIn('down_revision = "20260814_21"', source)
        self.assertIn("block_type IN ('table', 'chart', 'artifact', 'text')", source)
        self.assertGreaterEqual(
            source.count("block_type IN ('table', 'chart', 'artifact')"),
            2,
        )
        self.assertIn("artifact_id IS NOT NULL", source)
        self.assertIn("analysis_definition_id IS NOT NULL", source)
        self.assertIn("must be converted before downgrade", source)

    def test_report_display_settings_are_additive_after_artifact_blocks(self):
        source = (MIGRATIONS / "20260814_23_report_display_settings.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('revision = "20260814_23"', source)
        self.assertIn('down_revision = "20260814_22"', source)
        self.assertIn("ALTER TABLE report_v1.report_definition_versions", source)
        self.assertIn("orientation varchar(16) NOT NULL DEFAULT 'portrait'", source)
        self.assertIn("currency_display_unit varchar(24) NOT NULL DEFAULT 'auto'", source)
        self.assertIn("ALTER TABLE report_v1.report_documents", source)
        for value in ("auto", "one", "thousand", "million", "hundredMillion", "billion"):
            self.assertIn(f"'{value}'", source)

    def test_phase4_report_receipts_are_additive_complete_and_immutable(self):
        source = (MIGRATIONS / "20260822_32_report_release_receipts.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('revision = "20260822_32"', source)
        self.assertIn('down_revision = "20260822_31"', source)
        for table in ("report_definition_versions", "report_runs"):
            self.assertIn(f"ALTER TABLE report_v1.{table}", source)
        for column in (
            "product_release_id",
            "permission_snapshot_id",
            "semantic_release_id",
        ):
            self.assertGreaterEqual(source.count(column), 4)
        self.assertIn("report_definition_release_receipt_complete", source)
        self.assertIn("report_run_release_receipt_complete", source)
        self.assertIn("REFERENCES governance.product_release_manifests", source)
        self.assertIn("Report release receipt is immutable", source)
        self.assertIn("report_definition_release_receipt_immutable", source)
        self.assertIn("report_run_release_receipt_immutable", source)


if __name__ == "__main__":
    unittest.main()
