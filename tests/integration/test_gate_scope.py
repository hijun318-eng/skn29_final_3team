import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


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

    def test_current_ledger_has_resolvable_bundle_for_each_role(self) -> None:
        for branch in gate_scope.ROLES:
            with self.subTest(branch=branch):
                bundle = gate_scope.current_bundle(self.ledger, branch)
                self.assertIsNotNone(bundle)
                self.assertEqual(branch, bundle["PERSONAL_BRANCH"])

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

    def test_ledger_health_rejects_duplicate_active_and_dashboard_drift(self) -> None:
        ledger = """| R1 | `R1-W1` | `READY` | `junhee` |
```text
EXECUTION_BUNDLE_ID=R1-W1
STATUS=READY
PERSONAL_BRANCH=junhee
```
```text
EXECUTION_BUNDLE_ID=R1-W2
STATUS=IN_PROGRESS
PERSONAL_BRANCH=junhee
```"""
        errors = gate_scope.ledger_health_errors(ledger)
        self.assertTrue(any("multiple active bundles" in error for error in errors))
        self.assertTrue(any("dashboard row" in error for error in errors))

    def test_current_ledger_dashboard_and_active_bundles_are_consistent(self) -> None:
        self.assertEqual([], gate_scope.ledger_health_errors(self.ledger))

    def test_gate_issuance_allows_only_a_healthy_r1_ledger_change(self) -> None:
        ledger_path = gate_scope.LEDGER.as_posix()
        self.assertEqual(
            [], gate_scope.gate_issuance_errors(self.ledger, "junhee", [ledger_path])
        )
        self.assertIsNone(
            gate_scope.gate_issuance_errors(self.ledger, "seung", [ledger_path])
        )
        self.assertIsNone(
            gate_scope.gate_issuance_errors(
                self.ledger, "junhee", [ledger_path, "AGENTS.md"]
            )
        )

        current = gate_scope.current_bundle(self.ledger, "junhee")
        self.assertIsNotNone(current)
        current_row = (
            f"| R1 | `{current['EXECUTION_BUNDLE_ID']}` | "
            f"`{current['STATUS']}` | `junhee` |"
        )
        broken = self.ledger.replace(
            current_row,
            f"| R1 | `wrong` | `{current['STATUS']}` | `junhee` |",
            1,
        )
        self.assertTrue(
            gate_scope.gate_issuance_errors(broken, "junhee", [ledger_path])
        )

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

    def test_inherited_checkpoint_filters_role_diff_after_exact_hash(self) -> None:
        bundle = {
            "INHERITED_BLOB_PATHS": "src/data/a.py; src/data/b.py",
            "INHERITED_BLOB_SHA256": "a" * 64,
        }
        changed = ["src/data/a.py", "src/data/current.py"]
        with patch.object(
            gate_scope, "aggregate_blob_sha256", return_value="a" * 64
        ):
            role_changed, errors = gate_scope.role_diff(bundle, changed, "HEAD")
        self.assertEqual(["src/data/current.py"], role_changed)
        self.assertEqual([], errors)

    def test_inherited_checkpoint_hash_is_path_and_blob_aggregate(self) -> None:
        with patch.object(gate_scope.subprocess, "run") as run:
            run.side_effect = [
                Mock(returncode=0, stdout=b"alpha"),
                Mock(returncode=0, stdout=b"beta"),
            ]
            actual = gate_scope.aggregate_blob_sha256(
                "HEAD", ["b.txt", "a.txt"]
            )
        expected = hashlib.sha256(
            b"a.txt\0alpha\0b.txt\0beta\0"
        ).hexdigest()
        self.assertEqual(expected, actual)

    def test_inherited_checkpoint_drift_and_missing_blob_fail_closed(self) -> None:
        bundle = {
            "INHERITED_BLOB_PATHS": "src/data/a.py",
            "INHERITED_BLOB_SHA256": "a" * 64,
        }
        for actual, message in (
            ("b" * 64, "drift"),
            (None, "missing"),
        ):
            with self.subTest(actual=actual):
                with patch.object(
                    gate_scope, "aggregate_blob_sha256", return_value=actual
                ):
                    role_changed, errors = gate_scope.role_diff(
                        bundle, ["src/data/a.py"], "HEAD"
                    )
                self.assertEqual(["src/data/a.py"], role_changed)
                self.assertIn(message, errors[0])

    def test_inherited_checkpoint_fields_must_be_declared_together(self) -> None:
        role_changed, errors = gate_scope.role_diff(
            {"INHERITED_BLOB_PATHS": "src/data/a.py"},
            ["src/data/a.py"],
            "HEAD",
        )
        self.assertEqual(["src/data/a.py"], role_changed)
        self.assertIn("must be declared together", errors[0])

    def test_inherited_checkpoint_rejects_non_literal_paths(self) -> None:
        for path in ("../secret", "/absolute", "src/data/**", "src\\data\\a.py"):
            with self.subTest(path=path):
                role_changed, errors = gate_scope.role_diff(
                    {
                        "INHERITED_BLOB_PATHS": path,
                        "INHERITED_BLOB_SHA256": "a" * 64,
                    },
                    [path],
                    "HEAD",
                )
                self.assertEqual([path], role_changed)
                self.assertIn("literal repository paths", errors[0])

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

        with patch.object(
            gate_scope, "current_bundle", return_value=bundle
        ), patch.object(gate_scope, "ledger_health_errors", return_value=[]):
            _, errors = gate_scope.planned_path_errors(
                self.ledger, "junhee", [gate_scope.LEDGER.as_posix()]
            )
        self.assertEqual([], errors)

    def test_bootstrap_requires_matching_clean_executable_workspace(self) -> None:
        bundle = self.generic_bundle()
        bundle["STATUS"] = "READY"
        with patch.object(gate_scope, "current_bundle", return_value=bundle):
            payload = gate_scope.bootstrap_payload(
                self.ledger,
                "seung",
                "codex/process-e2e",
                "C:/repo/worktree",
                True,
            )
        self.assertTrue(
            any("does not match seung" in error for error in payload["errors"])
        )
        self.assertIn("working tree is not clean", payload["errors"])
        self.assertEqual(
            gate_scope.ROLE_MANUALS["seung"], payload["full_reads"][-1]
        )

    def test_bootstrap_blocks_terminal_bundle(self) -> None:
        bundle = self.generic_bundle()
        bundle["STATUS"] = "MERGED_DEV"
        with patch.object(gate_scope, "current_bundle", return_value=bundle):
            payload = gate_scope.bootstrap_payload(
                self.ledger, "seung", "seung", "C:/repo", False
            )
        self.assertIn("does not allow implementation", payload["errors"][0])

    def test_preflight_combines_bootstrap_contract_and_planned_paths(self) -> None:
        bundle = self.generic_bundle()
        bundle.update(
            STATUS="READY",
            PERSONAL_BRANCH="seung",
            BASE_SHA="a" * 40,
            ALLOWED_PATHS="src/data/**;tests/data/**",
        )
        with (
            patch.object(gate_scope, "current_bundle", return_value=bundle),
            patch.object(gate_scope, "ledger_health_errors", return_value=[]),
        ):
            payload = gate_scope.preflight_payload(
                self.ledger,
                "seung",
                "seung",
                "C:/repo",
                False,
                ["src/data/source.py", "app/backend/main.py"],
            )
        self.assertEqual([], payload["contract_errors"])
        self.assertEqual(["app/backend/main.py"], payload["path_errors"])
        self.assertIn("app/backend/main.py", payload["errors"])

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

    def test_next_gate_uses_verified_gate_from_archive_without_promoting_archived_cards(self) -> None:
        active = """```text
EXECUTION_BUNDLE_ID=R1-W5-F25
STATUS=READY
PERSONAL_BRANCH=junhee
TARGET_INTEGRATION_GATE=I5
ALLOWED_PATHS=.github/scripts/gate_scope.py
```
```text
EXECUTION_BUNDLE_ID=R2-W5-F9
STATUS=PLANNED
PERSONAL_BRANCH=seung
TARGET_INTEGRATION_GATE=I5
```"""
        archive = [
            {
                "EXECUTION_BUNDLE_ID": "R1-W4-F5",
                "STATUS": "VERIFIED_GATE",
                "PERSONAL_BRANCH": "junhee",
                "TARGET_INTEGRATION_GATE": "I4",
            },
            {
                "EXECUTION_BUNDLE_ID": "R2-W5-F8",
                "STATUS": "PLANNED",
                "PERSONAL_BRANCH": "seung",
                "TARGET_INTEGRATION_GATE": "I5",
            },
        ]
        lines = "\n".join(
            gate_scope.next_gate_lines(active, "I5", archive, [])
        )
        self.assertIn("Result: `READY_TO_ISSUE`", lines)
        self.assertIn("R2-W5-F9", lines)
        self.assertNotIn("R2-W5-F8", lines)
        self.assertEqual(
            "R1-W5-F25",
            gate_scope.current_bundle(active, "junhee")["EXECUTION_BUNDLE_ID"],
        )

    def test_next_gate_blocks_when_archive_missing_or_has_no_verified_previous_gate(self) -> None:
        archive, errors = gate_scope.load_archive_bundles([])
        lines = "\n".join(
            gate_scope.next_gate_lines(self.ledger, "I5", archive, errors)
        )
        self.assertIn("Result: `BLOCKED`", lines)
        self.assertIn("Gate archive files are missing", lines)

        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "Gate_실행_카드_원장_bad.md"
            malformed.write_text("not a Gate ledger", encoding="utf-8")
            archive, errors = gate_scope.load_archive_bundles([malformed])
        self.assertEqual([], archive)
        self.assertIn("no parseable bundles", errors[0])

        lines = "\n".join(
            gate_scope.next_gate_lines(
                self.ledger,
                "I5",
                [
                    {
                        "STATUS": "VERIFIED_GATE",
                        "PERSONAL_BRANCH": "seung",
                        "TARGET_INTEGRATION_GATE": "I4",
                    }
                ],
                [],
            )
        )
        self.assertIn("Result: `BLOCKED`", lines)
        self.assertIn("I4` has no VERIFIED_GATE", lines)

    def test_current_dashboard_recognizes_archived_i4_verified_gate(self) -> None:
        archive, errors = gate_scope.load_archive_bundles()
        lines = "\n".join(
            gate_scope.next_gate_lines(self.ledger, "I5", archive, errors)
        )
        self.assertEqual([], errors)
        self.assertIn("Previous gate: `I4`", lines)
        self.assertIn("Result: `READY_TO_ISSUE`", lines)

    def test_dashboard_prefers_origin_dev_sha(self) -> None:
        with patch.object(gate_scope.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "a" * 40 + "\n"
            self.assertEqual("a" * 40, gate_scope.latest_dev_sha())

    def test_blocked_dashboard_requests_scoped_rework(self) -> None:
        ledger = """```text
EXECUTION_BUNDLE_ID=R5-W9-TEST
STATUS=BLOCKED
PERSONAL_BRANCH=minji
ALLOWED_PATHS=app/enterprise-react/**
```"""
        dashboard = "\n".join(gate_scope.dashboard_lines(ledger))
        self.assertIn("R5-W9-TEST", dashboard)
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

    def test_ci_pending_is_limited_to_branch_ci_test(self) -> None:
        bundle = self.generic_bundle()
        bundle["TEST_COMMAND_IDS"] = "T1_UNIT;T2_BRANCH_CI"
        handoff = gate_scope.handoff_template(bundle, "seung", "a" * 40, [])
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["NOT_RUN"] = []
        handoff["TEST_RESULTS"] = [
            {
                "id": "T1_UNIT",
                "name": "unit",
                "status": "PASS",
                "evidence": "42 passed",
            },
            {
                "id": "T2_BRANCH_CI",
                "name": "branch CI",
                "status": "CI_PENDING",
                "evidence": "current push starts branch CI",
            },
        ]
        errors, reviews = gate_scope.validate_handoff(
            handoff, bundle, "seung", []
        )
        self.assertEqual([], errors)
        self.assertEqual([], reviews)

        handoff["TEST_RESULTS"][0]["status"] = "CI_PENDING"
        errors, _ = gate_scope.validate_handoff(handoff, bundle, "seung", [])
        self.assertIn(
            "CI_PENDING is allowed only for *_BRANCH_CI tests", errors
        )

    def test_ci_pending_handoff_status_is_not_terminal_pass(self) -> None:
        bundle = self.generic_bundle()
        bundle["STATUS"] = "REVIEW"
        bundle["TEST_COMMAND_IDS"] = "T9_BRANCH_CI"
        handoff = gate_scope.handoff_template(bundle, "seung", "a" * 40, [])
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["NOT_RUN"] = []
        handoff["TEST_RESULTS"] = [
            {
                "id": "T9_BRANCH_CI",
                "name": "branch CI",
                "status": "CI_PENDING",
                "evidence": "current push starts branch CI",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"{bundle['EXECUTION_BUNDLE_ID']}.json"
            path.write_text(json.dumps(handoff), encoding="utf-8")
            with patch.object(gate_scope, "HANDOFFS", Path(directory)):
                status, notes = gate_scope.handoff_status(
                    bundle, "seung", [], "a" * 40
                )
        self.assertEqual("CI_PENDING", status)
        self.assertEqual([], notes)

    def test_ci_pending_is_rejected_for_acceptance(self) -> None:
        bundle = self.generic_bundle()
        bundle["ACCEPTANCE_IDS"] = "AC1"
        handoff = gate_scope.handoff_template(bundle, "seung", "a" * 40, [])
        handoff["COMPLETED_CARDS"] = ["R2-09"]
        handoff["TEST_RESULTS"] = [{"name": "unit", "status": "PASS"}]
        handoff["NOT_RUN"] = []
        handoff["ACCEPTANCE_RESULTS"] = [
            {"id": "AC1", "status": "CI_PENDING", "evidence": "pending"}
        ]
        errors, _ = gate_scope.validate_handoff(handoff, bundle, "seung", [])
        self.assertIn("unsupported acceptance status: CI_PENDING", errors)

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
