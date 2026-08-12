import re
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
ACTION_PINS = {
    "actions/checkout": ("93cb6efe18208431cddfb8368fd83d5badbf9bfd", "v5.0.1"),
    "actions/setup-python": ("ece7cb06caefa5fff74198d8649806c4678c61a1", "v6.3.0"),
    "actions/setup-node": ("49933ea5288caeca8642d1e84afbd3f7d6820020", "v4.4.0"),
}


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_runs_only_product_checks_with_pinned_actions():
    workflow = source()
    uses = re.findall(r"(?m)^\s*- uses: ([^\s#]+)\s+#\s+(v\d+\.\d+\.\d+)\s*$", workflow)
    assert len(uses) == 5
    for reference, comment in uses:
        action, _, sha = reference.partition("@")
        assert (sha, comment) == ACTION_PINS[action]
    assert "python -m pytest -p no:cacheprovider tests" in workflow
    assert "npm run test:contracts" in workflow
    assert "docker compose" in workflow
    assert ".agents" not in workflow
    assert "gate_scope" not in workflow


def test_ci_keeps_read_only_permissions_and_bounded_jobs():
    workflow = source()
    assert re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", workflow)
    assert workflow.count("timeout-minutes:") == 4
    assert "needs: [python-contracts, frontend-contracts, compose-config]" in workflow
