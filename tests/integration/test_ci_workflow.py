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
    "frontend": 20,
    "compose-config": 10,
    "quality": 5,
}


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_actions_use_immutable_official_pins_with_exact_version_comments():
    uses = re.findall(r"(?m)^\s*- uses: ([^\s#]+)\s+#\s+(v\d+\.\d+\.\d+)\s*$", _workflow())
    assert len(uses) == 5
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
    assert "needs: [python-tests, frontend, compose-config]" in source
    assert 'if [[ "$result" != "success" ]]; then' in source
