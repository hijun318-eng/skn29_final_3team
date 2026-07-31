import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gate_scope", ROOT / ".github/scripts/gate_scope.py"
)
gate_scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate_scope)


class GateScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = gate_scope.LEDGER.read_text(encoding="utf-8")

    def test_latest_r4_executable_bundle_is_selected(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "jaehong")
        self.assertEqual("R4-W1-F3", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("READY", bundle["STATUS"])

    def test_ready_bundle_uses_exact_allowed_paths(self) -> None:
        bundle = {
            "EXECUTION_BUNDLE_ID": "R2-W2",
            "STATUS": "READY",
            "ALLOWED_PATHS": "infrastructure/database/**",
        }
        patterns = gate_scope.allowed_paths(bundle, "seung")
        self.assertTrue(
            gate_scope.path_allowed(
                "infrastructure/database/datahub/compose.fragment.yml", patterns
            )
        )
        self.assertFalse(
            gate_scope.path_allowed("compose.yml", patterns)
        )
        self.assertTrue(
            gate_scope.path_allowed("handoffs/R2-W2.json", patterns)
        )

    def test_merged_bundle_is_report_only(self) -> None:
        bundle = {
            "EXECUTION_BUNDLE_ID": "R4-W1-F2",
            "STATUS": "MERGED_DEV",
        }
        patterns = gate_scope.allowed_paths(bundle, "jaehong")
        self.assertTrue(
            gate_scope.path_allowed(
                "docs/markdown/daily_reports/jaehong/일일보고.md", patterns
            )
        )
        self.assertTrue(
            gate_scope.path_allowed(
                "docs/markdown/daily_reports/team_summaries/3주차/20260730.md",
                patterns,
            )
        )
        self.assertTrue(
            gate_scope.path_allowed(
                ".agents/skills/update-project-reports/scripts/validate_reports.py",
                patterns,
            )
        )
        self.assertFalse(
            gate_scope.path_allowed(
                "app/backend/scripts/verify-container.ps1", patterns
            )
        )
        self.assertEqual(
            ("N/A", []),
            gate_scope.handoff_status(bundle, "jaehong"),
        )

    def test_changed_paths_decodes_korean_names_without_git_quoting(self) -> None:
        path = "docs/markdown/daily_reports/daesung/일일보고.md"
        with patch.object(gate_scope.subprocess, "run") as run:
            run.return_value.stdout = path.encode("utf-8") + b"\0"
            changed = gate_scope.changed_paths("base", "head", "merge-base")
        self.assertEqual([path], changed)
        command = run.call_args.args[0]
        self.assertIn("-z", command)

    def test_valid_handoff_with_external_work_needs_review(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "seung")
        changed = ["infrastructure/database/datahub/compose.fragment.yml"]
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            changed,
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["TEST_RESULTS"] = [{"name": "data tests", "status": "PASS"}]
        handoff["NOT_RUN"] = []
        handoff["EXTERNAL_APPROVAL_REQUIRED"] = ["DataHub image pull"]
        errors, reviews = gate_scope.validate_handoff(
            handoff,
            bundle,
            "seung",
            changed,
        )
        self.assertEqual([], errors)
        self.assertIn("external approval is required", reviews)

    def test_handoff_changed_files_must_match_git_diff(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "seung")
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            ["tests/data/test_source_registry.py"],
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["TEST_RESULTS"] = [{"name": "data tests", "status": "PASS"}]
        handoff["NOT_RUN"] = []
        errors, _ = gate_scope.validate_handoff(
            handoff,
            bundle,
            "seung",
            ["tests/data/another_test.py"],
        )
        self.assertIn("CHANGED_FILES does not match the git diff", errors)

    def test_handoff_result_sha_must_match_checked_head(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "seung")
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            [],
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["TEST_RESULTS"] = [{"name": "data tests", "status": "PASS"}]
        handoff["NOT_RUN"] = []
        errors, _ = gate_scope.validate_handoff(
            handoff,
            bundle,
            "seung",
            [],
            "b" * 40,
        )
        self.assertIn(
            "RESULT_SHA must match the checked git head or precede only "
            "its handoff manifest in the role diff",
            errors,
        )

    def test_result_sha_allows_only_a_following_handoff_manifest(self) -> None:
        manifest = "handoffs/R2-W1-F3.json"
        product = "src/data/r2_w1_contract.v1.json"
        with (
            patch.object(gate_scope.subprocess, "run") as run,
            patch.object(
                gate_scope,
                "changed_paths",
                return_value=[".github/scripts/gate_scope.py", manifest],
            ) as changed,
        ):
            run.return_value.returncode = 0
            self.assertTrue(
                gate_scope.result_sha_matches_checked_head(
                    "a" * 40,
                    "b" * 40,
                    manifest,
                    [product, manifest],
                )
            )
            changed.return_value = [
                ".github/scripts/gate_scope.py",
                manifest,
                product,
            ]
            self.assertFalse(
                gate_scope.result_sha_matches_checked_head(
                    "a" * 40,
                    "b" * 40,
                    manifest,
                    [product, manifest],
                )
            )

    def test_review_bundle_requires_manifest(self) -> None:
        bundle = {
            "EXECUTION_BUNDLE_ID": "R2-W2",
            "STATUS": "REVIEW",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(gate_scope, "HANDOFFS", Path(directory)):
                status, notes = gate_scope.handoff_status(bundle, "seung")
        self.assertEqual("FAIL", status)
        self.assertIn("required manifest is missing", notes[0])

    def test_submitted_manifest_is_loaded_and_validated(self) -> None:
        bundle = dict(gate_scope.current_bundle(self.ledger, "seung"))
        bundle["STATUS"] = "REVIEW"
        changed = ["tests/data/test_source_registry.py"]
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            changed,
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["TEST_RESULTS"] = [{"name": "data tests", "status": "PASS"}]
        handoff["NOT_RUN"] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"{bundle['EXECUTION_BUNDLE_ID']}.json"
            path.write_text(json.dumps(handoff), encoding="utf-8")
            with patch.object(gate_scope, "HANDOFFS", Path(directory)):
                status, notes = gate_scope.handoff_status(
                    bundle,
                    "seung",
                    changed,
                )
        self.assertEqual("PASS", status)
        self.assertEqual([], notes)

    def test_only_fail_blocks_the_automated_quality_gate(self) -> None:
        """미제출·잔여 위험 보고는 R1 검토 대상이며 CI 차단 대상이 아니다."""
        self.assertEqual({"FAIL"}, gate_scope.BLOCKING_HANDOFF_STATUSES)
        for status in ("NOT_RUN", "REVIEW_REQUIRED", "PASS", "N/A"):
            self.assertNotIn(status, gate_scope.BLOCKING_HANDOFF_STATUSES)

    def test_unsubmitted_manifest_is_not_run_and_does_not_block(self) -> None:
        """READY·BLOCKED 묶음이 manifest 제출 전 상시 실패하지 않아야 한다."""
        for branch in gate_scope.ROLES:
            bundle = gate_scope.current_bundle(self.ledger, branch)
            if bundle is None or bundle["STATUS"] in gate_scope.TERMINAL_STATUSES:
                continue
            with self.subTest(branch=branch):
                with tempfile.TemporaryDirectory() as directory:
                    with patch.object(gate_scope, "HANDOFFS", Path(directory)):
                        status, notes = gate_scope.handoff_status(bundle, branch)
                expected = "FAIL" if bundle["STATUS"] == "REVIEW" else "NOT_RUN"
                self.assertEqual(expected, status)
                self.assertTrue(notes)
                if expected == "NOT_RUN":
                    self.assertNotIn(
                        status, gate_scope.BLOCKING_HANDOFF_STATUSES
                    )

    def test_residual_risk_report_is_review_not_block(self) -> None:
        """잔여 위험을 적어도 REVIEW_REQUIRED일 뿐 Gate를 차단하지 않는다."""
        bundle = dict(gate_scope.current_bundle(self.ledger, "seung"))
        bundle["STATUS"] = "REVIEW"
        changed = ["tests/data/test_source_registry.py"]
        handoff = gate_scope.handoff_template(bundle, "seung", "a" * 40, changed)
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["TEST_RESULTS"] = [{"name": "data tests", "status": "PASS"}]
        handoff["NOT_RUN"] = []
        handoff["RESIDUAL_RISKS"] = ["DataHub container 실기동 미검증"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"{bundle['EXECUTION_BUNDLE_ID']}.json"
            path.write_text(json.dumps(handoff), encoding="utf-8")
            with patch.object(gate_scope, "HANDOFFS", Path(directory)):
                status, notes = gate_scope.handoff_status(
                    bundle,
                    "seung",
                    changed,
                )
        self.assertEqual("REVIEW_REQUIRED", status)
        self.assertIn("residual risk exists", notes)
        self.assertNotIn(status, gate_scope.BLOCKING_HANDOFF_STATUSES)


if __name__ == "__main__":
    unittest.main()
