from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "infrastructure" / "database" / "walkerhill_v4"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_candidate_is_deterministic_and_passes_data_gates(tmp_path: Path) -> None:
    first = tmp_path / "first"
    replay = tmp_path / "replay"
    period = ("--start", "2025-01-01", "--end-exclusive", "2025-02-01")

    run(V4 / "generate.py", "--output", first, *period)
    run(V4 / "generate.py", "--output", replay, *period)
    run(
        V4 / "validate.py",
        "--candidate",
        first,
        "--determinism-reference",
        replay,
    )

    first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    replay_manifest = json.loads((replay / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((first / "validation_report.json").read_text(encoding="utf-8"))

    assert first_manifest["files"] == replay_manifest["files"]
    assert first_manifest["catalog"] == replay_manifest["catalog"]
    assert report["data_gates_passed"] is True
    assert report["promotion_eligible"] is False
    assert report["promotion_state"] == "DATA_VALIDATED"


def test_contract_references_only_declared_assets() -> None:
    product = json.loads((V4 / "product_contract.v2.json").read_text(encoding="utf-8"))
    schema = json.loads((V4 / "schema_contract.v2.json").read_text(encoding="utf-8"))
    dataset_ids = {dataset["id"] for dataset in schema["datasets"]}

    metric_assets = {".".join(metric["source"].split(".")[:2]) for metric in product["metrics"]}
    join_assets = {
        join[side]
        for join in product["approved_joins"]
        for side in ("left", "right")
    }

    assert metric_assets <= dataset_ids
    assert join_assets <= dataset_ids
    assert len(dataset_ids) == len(schema["datasets"])


def test_runtime_namespaces_do_not_replace_legacy_assets() -> None:
    schema = json.loads((V4 / "schema_contract.v2.json").read_text(encoding="utf-8"))
    for dataset in schema["datasets"]:
        domain = dataset["id"].split(".", 1)[0]
        if domain == "reference":
            assert dataset["fqn"].startswith("serving.reference.v4_")
        elif domain == "serving":
            assert dataset["fqn"].startswith("serving.analytics.v4_")
        else:
            assert ".walkerhill_v4." in dataset["fqn"]


def test_datahub_bindings_and_heldout_cases_are_contract_bound() -> None:
    sync = load_module("walkerhill_v4_sync", V4 / "sync_datahub.py")
    heldout = load_module("walkerhill_v4_heldout", V4 / "evaluate_heldout.py")
    schema = json.loads((V4 / "schema_contract.v2.json").read_text(encoding="utf-8"))
    cases = json.loads((V4 / "heldout_cases.v1.json").read_text(encoding="utf-8"))["cases"]
    fqns = {dataset["fqn"] for dataset in schema["datasets"]}

    assert len({sync.dataset_urn(dataset) for dataset in schema["datasets"]}) == 33
    assert len(cases) == 10
    for case in cases:
        assert set(case["allowed_assets"]) <= fqns
        assert heldout.g2_validate(case)["status"] == "PASS"


def test_legacy_deprecation_map_covers_the_old_serving_contract() -> None:
    legacy = load_module("walkerhill_v4_legacy", V4 / "deprecate_legacy.py")
    contract = json.loads(legacy.LEGACY_CONTRACT.read_text(encoding="utf-8"))

    assert {view["name"] for view in contract["views"]} == set(legacy.REPLACEMENTS)
    assert all(
        replacement is None or replacement.startswith("serving_v4.serving.analytics.v4_")
        for replacement in legacy.REPLACEMENTS.values()
    )
    registry = json.loads(legacy.SOURCE_REGISTRY.read_text(encoding="utf-8"))
    source_keys = {
        f"{source['source_id']}.{entity['table']}"
        for source in registry["sources"]
        for entity in source["entities"]
    }
    assert source_keys == set(legacy.SOURCE_REPLACEMENT_IDS)
