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

    def generic_bundle(self) -> dict[str, str]:
        bundle = dict(gate_scope.current_bundle(self.ledger, "seung"))
        bundle.pop("TEST_COMMAND_IDS", None)
        bundle.pop("ACCEPTANCE_IDS", None)
        return bundle

    def test_latest_r3_bundle_is_selected(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "daesung")
        self.assertEqual("R3-W4-F7", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("MERGED_DEV", bundle["STATUS"])

    def test_latest_r2_bundle_is_selected(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "seung")
        self.assertEqual("R2-W4-F4", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("MERGED_DEV", bundle["STATUS"])

    def test_latest_r4_bundle_is_selected(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "jaehong")
        self.assertEqual("R4-W4-F8", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("MERGED_DEV", bundle["STATUS"])

    def test_current_bundle_selects_latest_non_planned_card(self) -> None:
        ledger = """```text
EXECUTION_BUNDLE_ID=R1-W1
STATUS=READY
PERSONAL_BRANCH=junhee
ALLOWED_PATHS=docs/**
```
```text
EXECUTION_BUNDLE_ID=R1-W2
STATUS=PLANNED
PERSONAL_BRANCH=junhee
ALLOWED_PATHS=tests/**
```
```text
EXECUTION_BUNDLE_ID=R1-W3
STATUS=IN_PROGRESS
PERSONAL_BRANCH=junhee
ALLOWED_PATHS=.github/**
```"""
        bundle = gate_scope.current_bundle(ledger, "junhee")
        self.assertEqual("R1-W3", bundle["EXECUTION_BUNDLE_ID"])

    def test_latest_r5_bundle_is_selected(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "minji")
        self.assertEqual("R5-W4-F4", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("BLOCKED", bundle["STATUS"])

    def test_terminal_transition_uses_previous_bundle_scope(self) -> None:
        current = {
            "EXECUTION_BUNDLE_ID": "R1-W2",
            "STATUS": "VERIFIED_GATE",
        }
        previous = {
            "EXECUTION_BUNDLE_ID": "R1-W2",
            "STATUS": "IN_PROGRESS",
            "ALLOWED_PATHS": "docs/markdown/collaboration/**",
        }
        self.assertIs(
            previous,
            gate_scope.terminal_transition_scope(current, previous),
        )

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

    def test_blocked_bundle_is_report_only_until_reissued(self) -> None:
        bundle = {
            "EXECUTION_BUNDLE_ID": "R5-W4-F4",
            "STATUS": "BLOCKED",
            "ALLOWED_PATHS": "app/enterprise-react/**",
        }
        patterns = gate_scope.allowed_paths(bundle, "minji")
        self.assertTrue(
            gate_scope.path_allowed(
                "docs/markdown/daily_reports/minji/일일보고.md", patterns
            )
        )
        self.assertFalse(
            gate_scope.path_allowed(
                "app/enterprise-react/src/pages/ReportsPage.jsx", patterns
            )
        )

    def test_changed_paths_decodes_korean_names_without_git_quoting(self) -> None:
        path = "docs/markdown/daily_reports/daesung/일일보고.md"
        with patch.object(gate_scope.subprocess, "run") as run:
            run.return_value.stdout = path.encode("utf-8") + b"\0"
            changed = gate_scope.changed_paths("base", "head", "merge-base")
        self.assertEqual([path], changed)
        command = run.call_args.args[0]
        self.assertIn("-z", command)
        self.assertIn("--diff-filter=ACMRD", command)

    def test_document_only_change_selects_document_job(self) -> None:
        self.assertEqual(
            {
                "python": "false",
                "documents": "true",
                "frontend": "false",
                "compose": "false",
            },
            gate_scope.change_group_outputs(["docs/markdown/02_WBS.md"]),
        )

    def test_workflow_change_selects_every_job(self) -> None:
        self.assertEqual(
            {group: "true" for group in gate_scope.CHANGE_GROUP_PATTERNS},
            gate_scope.change_group_outputs([".github/workflows/ci.yml"]),
        )

    def test_backend_compose_fragment_selects_python_and_compose(self) -> None:
        outputs = gate_scope.change_group_outputs(
            ["app/backend/compose.fragment.yml"]
        )
        self.assertEqual("true", outputs["python"])
        self.assertEqual("true", outputs["compose"])

    def test_planned_paths_require_active_bundle_and_allowed_paths(self) -> None:
        bundle = {
            "EXECUTION_BUNDLE_ID": "R1-W1",
            "STATUS": "IN_PROGRESS",
            "PERSONAL_BRANCH": "junhee",
            "ALLOWED_PATHS": ".github/scripts/gate_scope.py",
        }
        with patch.object(gate_scope, "current_bundle", return_value=bundle):
            _, errors = gate_scope.planned_path_errors(
                self.ledger, "junhee", [".github/scripts/gate_scope.py"]
            )
        self.assertEqual([], errors)

        bundle["STATUS"] = "VERIFIED_GATE"
        with patch.object(gate_scope, "current_bundle", return_value=bundle):
            _, errors = gate_scope.planned_path_errors(
                self.ledger, "junhee", [".github/scripts/gate_scope.py"]
            )
        self.assertIn("does not allow implementation", errors[0])

        with patch.object(gate_scope, "current_bundle", return_value=bundle):
            _, errors = gate_scope.planned_path_errors(
                self.ledger, "junhee", [gate_scope.LEDGER.as_posix()]
            )
        self.assertEqual([], errors)

    def test_bootstrap_requires_matching_clean_executable_workspace(self) -> None:
        payload = gate_scope.bootstrap_payload(
            self.ledger,
            "seung",
            "codex/process-e2e",
            "C:/repo/worktree",
            True,
        )
        self.assertIn("does not match seung", payload["errors"][1])
        self.assertIn("working tree is not clean", payload["errors"])
        self.assertEqual(
            gate_scope.ROLE_MANUALS["seung"], payload["full_reads"][-1]
        )

    def test_bootstrap_blocks_terminal_bundle(self) -> None:
        payload = gate_scope.bootstrap_payload(
            self.ledger, "seung", "seung", "C:/repo", False
        )
        self.assertIn("does not allow implementation", payload["errors"][0])

    def test_stale_base_without_path_overlap_can_continue(self) -> None:
        bundle = {"STATUS": "READY", "BASE_SHA": "issued"}
        with (
            patch.object(gate_scope, "is_ancestor", side_effect=[False, True]),
            patch.object(gate_scope, "changed_paths", return_value=["src/data/a.py"]),
        ):
            status, notes = gate_scope.base_sync_status(
                bundle, "origin/dev", "HEAD", ["src/ai/node1.py"]
            )
        self.assertEqual("SAFE_STALE", status)
        self.assertEqual([], notes)

    def test_stale_base_with_path_overlap_requires_refresh(self) -> None:
        bundle = {"STATUS": "IN_PROGRESS", "BASE_SHA": "issued"}
        with (
            patch.object(gate_scope, "is_ancestor", side_effect=[False, True]),
            patch.object(gate_scope, "changed_paths", return_value=["src/ai/node1.py"]),
        ):
            status, notes = gate_scope.base_sync_status(
                bundle, "origin/dev", "HEAD", ["src/ai/node1.py"]
            )
        self.assertEqual("REFRESH_REQUIRED", status)
        self.assertEqual(["src/ai/node1.py"], notes)

    def test_next_gate_is_inferred_from_active_bundle(self) -> None:
        self.assertEqual("I5", gate_scope.inferred_next_gate(self.ledger))

    def test_dashboard_prefers_origin_dev_sha(self) -> None:
        with patch.object(gate_scope.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "a" * 40 + "\n"
            self.assertEqual("a" * 40, gate_scope.latest_dev_sha())

    def test_blocked_dashboard_requests_scoped_rework(self) -> None:
        dashboard = "\n".join(gate_scope.dashboard_lines(self.ledger))
        self.assertIn("R5-W4-F4", dashboard)
        self.assertIn("Issue owner-scoped REWORK bundle", dashboard)

    def test_valid_handoff_with_external_work_needs_review(self) -> None:
        bundle = self.generic_bundle()
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
        bundle = self.generic_bundle()
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

    def test_declared_test_and_acceptance_ids_require_complete_evidence(self) -> None:
        bundle = dict(gate_scope.current_bundle(self.ledger, "seung"))
        bundle["TEST_COMMAND_IDS"] = "T1;T2"
        bundle["ACCEPTANCE_IDS"] = "AC1;AC2"
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            [],
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["NOT_RUN"] = []
        handoff["TEST_RESULTS"] = [
            {"id": "T1", "name": "data tests", "status": "PASS", "evidence": ""}
        ]
        handoff["ACCEPTANCE_RESULTS"] = [
            {"id": "AC1", "status": "PASS", "evidence": "query id q-1"}
        ]
        errors, _ = gate_scope.validate_handoff(handoff, bundle, "seung", [])
        self.assertIn("TEST_RESULTS missing ids: T2", errors)
        self.assertIn("mapped TEST_RESULTS items need real evidence", errors)
        self.assertIn("ACCEPTANCE_RESULTS missing ids: AC2", errors)

    def test_placeholder_evidence_and_missing_ids_are_rejected(self) -> None:
        bundle = dict(gate_scope.current_bundle(self.ledger, "seung"))
        bundle["TEST_COMMAND_IDS"] = "T1"
        bundle["ACCEPTANCE_IDS"] = "AC1"
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            [],
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["NOT_RUN"] = []
        handoff["TEST_RESULTS"] = [
            {
                "id": "T1",
                "name": "data tests",
                "status": "PASS",
                "evidence": "미실행 사유 입력",
            },
            {"name": "unmapped", "status": "PASS", "evidence": "12 passed"},
        ]
        handoff["ACCEPTANCE_RESULTS"] = [
            {"id": "AC1", "status": "PASS", "evidence": "미검증 사유 입력"},
            {"status": "PASS", "evidence": "trace t-1"},
        ]
        errors, _ = gate_scope.validate_handoff(handoff, bundle, "seung", [])
        self.assertIn("TEST_RESULTS items need id", errors)
        self.assertIn("mapped TEST_RESULTS items need real evidence", errors)
        self.assertIn("ACCEPTANCE_RESULTS items need id", errors)
        self.assertIn(
            "each ACCEPTANCE_RESULTS item needs status and real evidence",
            errors,
        )

    def test_complete_evidence_allows_empty_not_run(self) -> None:
        bundle = dict(gate_scope.current_bundle(self.ledger, "seung"))
        bundle["TEST_COMMAND_IDS"] = "T1"
        bundle["ACCEPTANCE_IDS"] = "AC1"
        handoff = gate_scope.handoff_template(
            bundle,
            "seung",
            "a" * 40,
            [],
        )
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["NOT_RUN"] = []
        handoff["TEST_RESULTS"] = [
            {"id": "T1", "name": "data tests", "status": "PASS", "evidence": "12 passed"}
        ]
        handoff["ACCEPTANCE_RESULTS"] = [
            {"id": "AC1", "status": "PASS", "evidence": "query id q-1"}
        ]
        errors, reviews = gate_scope.validate_handoff(handoff, bundle, "seung", [])
        self.assertEqual([], errors)
        self.assertEqual([], reviews)

    def test_handoff_result_sha_must_match_checked_head(self) -> None:
        bundle = self.generic_bundle()
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
        bundle = self.generic_bundle()
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

    def test_fail_and_submitted_review_block_the_quality_gate(self) -> None:
        """제출된 handoff의 미실행·잔여 위험은 수용 전에 해소해야 한다."""
        self.assertEqual(
            {"FAIL", "REVIEW_REQUIRED"},
            gate_scope.BLOCKING_HANDOFF_STATUSES,
        )
        for status in ("NOT_RUN", "PASS", "N/A"):
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

    def test_residual_risk_report_requires_review_and_blocks_submission(self) -> None:
        """잔여 위험은 보존하되 terminal 제출 수용 전에는 차단한다."""
        bundle = self.generic_bundle()
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
        self.assertIn(status, gate_scope.BLOCKING_HANDOFF_STATUSES)


if __name__ == "__main__":
    unittest.main()
