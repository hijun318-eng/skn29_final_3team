import re
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
ACTION_PINS = {
    "actions/checkout": ("93cb6efe18208431cddfb8368fd83d5badbf9bfd", "v5.0.1"),
    "actions/setup-python": ("ece7cb06caefa5fff74198d8649806c4678c61a1", "v6.3.0"),
    "actions/setup-node": ("49933ea5288caeca8642d1e84afbd3f7d6820020", "v4.4.0"),
    "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4.6.2"),
    "aquasecurity/trivy-action": ("a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8", "v0.36.0"),
    "pypa/gh-action-pip-audit": ("1220774d901786e6f652ae159f7b6bc8fea6d266", "v1.1.0"),
}


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_runs_only_product_checks_with_pinned_actions():
    workflow = source()
    uses = re.findall(
        r"(?m)^\s+(?:- )?uses: ([^\s#]+)\s+#\s+(v\d+\.\d+\.\d+)\s*$",
        workflow,
    )
    assert len(uses) == 11
    for reference, comment in uses:
        action, _, sha = reference.partition("@")
        assert (sha, comment) == ACTION_PINS[action]
    assert "python -m pytest -p no:cacheprovider tests" in workflow
    assert "npm run test:contracts" in workflow
    assert "docker compose" in workflow
    assert ".agents" not in workflow
    assert "gate_scope" not in workflow


def test_ci_gates_dependencies_sbom_and_application_images():
    workflow = source()
    assert "inputs: app/backend/requirements.txt" in workflow
    assert "npm audit --audit-level=high" in workflow
    assert "format: cyclonedx" in workflow
    assert "path: answervice.cdx.json" in workflow
    assert "docker build -f app/backend/Dockerfile" in workflow
    assert "docker build -f app/enterprise-react/Dockerfile" in workflow
    assert workflow.count("severity: HIGH,CRITICAL") == 2
    assert workflow.count('exit-code: "1"') == 2
    assert workflow.count("version: v0.70.0") == 3


def test_ci_keeps_read_only_permissions_and_bounded_jobs():
    workflow = source()
    assert re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", workflow)
    assert workflow.count("timeout-minutes:") == 5
    assert "needs: [python-contracts, frontend-contracts, compose-config, supply-chain]" in workflow
    assert "SUPPLY_CHAIN: ${{ needs.supply-chain.result }}" in workflow
