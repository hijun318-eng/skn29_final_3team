import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
SPEC = importlib.util.spec_from_file_location(
    "agent_workflow", ROOT / ".github/scripts/agent_workflow.py"
)
agent_workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_workflow)
sys.path.pop(0)


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


class AgentWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bootstrap = {
            "bundle": "R1-W5-F24",
            "status": "READY",
            "errors": [],
        }

    def run_with(
        self, git_results, *, branch="junhee", ff_only_dev=False, bootstrap=None
    ):
        with (
            patch.object(agent_workflow.shutil, "which", return_value="git"),
            patch.object(agent_workflow, "git", side_effect=git_results) as git,
            patch.object(agent_workflow.Path, "read_text", return_value="ledger"),
            patch.object(
                agent_workflow.gate_scope,
                "preflight_payload",
                return_value=bootstrap or self.bootstrap,
            ) as preflight,
        ):
            return agent_workflow.run(branch, ff_only_dev), git, preflight

    def test_clean_branch_diagnosis_is_read_only(self) -> None:
        payload, git, _ = self.run_with(
            [
                completed("C:/repo"), completed("junhee"), completed(), completed(),
                completed(), completed(),
            ]
        )
        self.assertEqual("PASS", payload["result"])
        self.assertEqual("none", payload["action"])
        self.assertNotIn("merge", [call.args[0] for call in git.call_args_list])

    def test_dirty_branch_fails_closed(self) -> None:
        dirty = {**self.bootstrap, "errors": ["working tree is not clean"]}
        payload, _, _ = self.run_with(
            [
                completed("C:/repo"), completed("junhee"), completed(" M file"),
                completed(), completed(), completed(returncode=1),
            ],
            bootstrap=dirty,
        )
        self.assertEqual("FAIL", payload["result"])

    def test_default_reports_available_fast_forward_without_merging(self) -> None:
        payload, git, _ = self.run_with(
            [
                completed("C:/repo"), completed("junhee"), completed(), completed(),
                completed(), completed(returncode=1),
            ]
        )
        self.assertEqual("fast-forward-available", payload["action"])
        self.assertFalse(any(call.args[:2] == ("merge", "--ff-only") for call in git.call_args_list))

    def test_ff_only_dev_runs_only_fast_forward_then_preflight(self) -> None:
        payload, git, preflight = self.run_with(
            [
                completed("C:/repo"), completed("junhee"), completed(), completed(),
                completed(), completed(returncode=1), completed(),
                completed("junhee"), completed(),
            ],
            ff_only_dev=True,
        )
        self.assertEqual("PASS", payload["result"])
        self.assertEqual("fast-forwarded", payload["action"])
        self.assertIn(
            unittest.mock.call("merge", "--ff-only", "origin/dev"),
            git.call_args_list,
        )
        self.assertTrue(
            {"fetch", "push", "reset", "rebase", "stash"}.isdisjoint(
                call.args[0] for call in git.call_args_list
            )
        )
        self.assertEqual(2, preflight.call_count)

    def test_diverged_branch_fails_closed(self) -> None:
        payload, _, _ = self.run_with(
            [
                completed("C:/repo"), completed("junhee"), completed(), completed(),
                completed(returncode=1), completed(returncode=1),
            ]
        )
        self.assertEqual("FAIL", payload["result"])
        self.assertIn("diverged", payload["errors"][-1])

    def test_non_personal_branch_and_missing_git_fail_closed(self) -> None:
        with patch.object(agent_workflow.shutil, "which", return_value="git"):
            payload = agent_workflow.run("dev")
        self.assertEqual("FAIL", payload["result"])
        with patch.object(agent_workflow.shutil, "which", return_value=None):
            payload = agent_workflow.run("junhee")
        self.assertEqual(["git tool is not available"], payload["errors"])


if __name__ == "__main__":
    unittest.main()
