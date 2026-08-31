import re
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
ACTION_PINS = {
    "actions/checkout": ("93cb6efe18208431cddfb8368fd83d5badbf9bfd", "v5.0.1"),
    "actions/setup-python": ("ece7cb06caefa5fff74198d8649806c4678c61a1", "v6.3.0"),
    "actions/setup-node": ("49933ea5288caeca8642d1e84afbd3f7d6820020", "v4.4.0"),
}
JOB_TIMEOUTS = {
    "python-tests": 25,
    "ml-runtime-tests": 15,
    "rag-tests": 15,
    "node2-serverless-tests": 10,
    "frontend": 20,
    "compose-config": 10,
    "quality": 5,
}


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_actions_use_immutable_official_pins_with_exact_version_comments():
    uses = re.findall(r"(?m)^\s*- uses: ([^\s#]+)\s+#\s+(v\d+\.\d+\.\d+)\s*$", _workflow())
    assert len(uses) == 11
    for reference, comment in uses:
        action, separator, sha = reference.partition("@")
        assert separator and action in ACTION_PINS
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        assert (sha, comment) == ACTION_PINS[action]


def test_all_jobs_have_bounded_timeouts():
    source = _workflow()
    jobs_source = source[source.index("jobs:") :]
    matches = list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]*):\s*$", jobs_source))
    jobs = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(jobs_source)
        jobs[match.group(1)] = jobs_source[match.end() : end]
    assert set(jobs) == set(JOB_TIMEOUTS)
    for job, timeout in JOB_TIMEOUTS.items():
        assert re.findall(r"(?m)^    timeout-minutes: (\d+)\s*$", jobs[job]) == [str(timeout)]


def test_workflow_is_not_role_or_handoff_scoped():
    source = _workflow()
    for obsolete in (
        "role-scope",
        "handoff",
        "gate_scope.py",
        "junhee",
        "seung",
        "daesung",
        "jaehong",
        "minji",
    ):
        assert obsolete not in source
    assert "python -m pytest -p no:cacheprovider tests -q" in source
    trigger_source = source[source.index("on:") : source.index("permissions:")]
    assert re.search(r"(?m)^  push:\s*$", trigger_source)
    assert "branches:" not in trigger_source
    assert "pull_request:" in source


def test_workflow_keeps_read_only_permission_and_common_quality_gate():
    source = _workflow()
    assert source.count("permissions:") == 1
    assert re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", source)
    assert 'python-version: "3.12"' in source
    assert source.count("app/backend/requirements.lock.txt") == 2
    assert "--constraint app/backend/requirements.lock.txt" in source
    for required_job in (
        "python-tests",
        "ml-runtime-tests",
        "rag-tests",
        "node2-serverless-tests",
        "frontend",
        "compose-config",
    ):
        assert required_job in source
    assert 'if [[ "$result" != "success" ]]; then' in source


def test_ml_runtime_has_an_isolated_exact_pin_gate():
    source = _workflow()

    assert "--ignore=tests/backend/test_ml_prediction_integration.py" in source
    assert "--ignore=tests/ml" in source
    assert source.count("src/ml/room_demand_v3/requirements.txt") == 2
    assert "pytest==9.1.0" in source
    assert "SQLAlchemy==2.0.52" in source
    assert "tests/backend/test_ml_prediction_integration.py" in source
    assert "tests/ml -q" in source
    assert "--basetemp=.tmp/pytest-ml-runtime-ci" in source
    assert "ML_RUNTIME_TESTS: ${{ needs.ml-runtime-tests.result }}" in source
    assert '"$ML_RUNTIME_TESTS" \\' in source


def test_inactive_node2_candidate_evidence_is_visible_but_not_a_core_gate():
    source = _workflow()

    assert "--ignore=tests/ai/test_training_dataset.py" in source
    assert source.count("continue-on-error: true") == 2
    assert "Node2 inactive image receipt" in source
    assert "Node2 inactive training contract" in source
