import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_merge_preflight",
    ROOT
    / ".agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py",
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class MergePreflightTest(unittest.TestCase):
    def test_source_ci_requires_completed_success(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 0,
            json.dumps(
                [{"databaseId": 1, "status": "completed", "conclusion": "success"}]
            ),
            "",
        )
        with patch.object(preflight.subprocess, "run", return_value=completed):
            self.assertEqual("success", preflight.source_ci("junhee", "a" * 40)["conclusion"])

        pending = subprocess.CompletedProcess(
            [], 0,
            json.dumps(
                [{"databaseId": 2, "status": "in_progress", "conclusion": ""}]
            ),
            "",
        )
        with patch.object(preflight.subprocess, "run", return_value=pending):
            self.assertNotEqual(
                "completed", preflight.source_ci("junhee", "b" * 40)["status"]
            )

    def test_source_phase_blocks_pending_ci(self) -> None:
        sha = "a" * 40

        def fake_ref(name: str) -> str | None:
            return None if name in preflight.OPERATION_MARKERS else sha

        with (
            patch.object(
                preflight.sys,
                "argv",
                ["preflight", "--source", "junhee", "--phase", "source"],
            ),
            patch.object(preflight, "git", side_effect=["junhee", ""]),
            patch.object(preflight, "ref", side_effect=fake_ref),
            patch.object(
                preflight,
                "source_ci",
                return_value={
                    "databaseId": 2,
                    "status": "in_progress",
                    "conclusion": "",
                },
            ),
        ):
            self.assertEqual(1, preflight.main())

    def test_batch_preflight_reports_all_source_failures(self) -> None:
        sha = "a" * 40
        with (
            patch.object(preflight, "git", side_effect=["dev", "", "", "dirty"]),
            patch.object(preflight, "ref", side_effect=[sha] * 6),
            patch.object(
                preflight,
                "worktree_roots",
                return_value={"junhee": "C:/junhee", "seung": "C:/seung"},
            ),
            patch.object(
                preflight,
                "source_ci",
                return_value={"status": "completed", "conclusion": "success"},
            ),
        ):
            payload = preflight.batch_payload(["junhee", "seung"])
        self.assertEqual([], payload["sources"][0]["errors"])
        self.assertIn("working tree", payload["sources"][1]["errors"][0])
        self.assertIn("seung:", payload["errors"][0])

    def test_current_bundle_status_uses_last_non_planned_card(self) -> None:
        ledger = """```text
STATUS=MERGED_DEV
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W1
```
```text
STATUS=PLANNED
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W2
```
"""
        with patch.object(preflight.Path, "exists", return_value=True), patch.object(
            preflight.Path, "read_text", return_value=ledger
        ):
            self.assertEqual("MERGED_DEV", preflight.current_bundle_status("seung"))

    def test_final_phase_requires_terminal_source_card(self) -> None:
        sha = "a" * 40

        def fake_ref(name: str) -> str | None:
            return None if name in preflight.OPERATION_MARKERS else sha

        with (
            patch.object(
                preflight.sys,
                "argv",
                [
                    "preflight",
                    "--source",
                    "junhee",
                    "--phase",
                    "final",
                    "--base",
                    sha,
                ],
            ),
            patch.object(preflight, "git", side_effect=["dev", ""]),
            patch.object(preflight, "ref", side_effect=fake_ref),
            patch.object(preflight, "is_ancestor", return_value=True),
            patch.object(
                preflight, "current_bundle_status", return_value="IN_PROGRESS"
            ),
        ):
            self.assertEqual(1, preflight.main())


if __name__ == "__main__":
    unittest.main()
