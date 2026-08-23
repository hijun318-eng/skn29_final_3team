"""Phase 9 JOIN capability·Gold·Acceptance 격리 경계를 검증한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.data.governance_contract import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "infrastructure" / "acceptance"
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ACCEPTANCE), str(BACKEND), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from phase9_multi_asset_join import (  # noqa: E402
    CAPABILITY_FILE,
    GOLD_FILE,
    Phase9Error,
    _gold,
    _validate_boundary,
    _validate_model_call_gate,
    parse_args,
)


def _args(extra: list[str] | None = None):
    return parse_args(
        [
            "--target-project",
            "answervice-phase2b-datahub",
            "--target-server",
            "https://127.0.0.1:38081",
            "--trino-server",
            "https://127.0.0.1:18443",
            "--trino-ca-file",
            str(ROOT / "AGENTS.md"),
            "--database-url",
            "postgresql+psycopg://postgres@127.0.0.1:55440/phase4_runtime_catalog_acceptance",
            *(extra or []),
        ]
    )


def _sealed(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    assert document["status"] == "SEALED"
    assert document["content_sha256"] == canonical_sha256(payload)
    return document


def test_boundary_is_hard_bound_to_the_existing_isolated_acceptance_stack() -> None:
    _validate_boundary(_args())

    with pytest.raises(Phase9Error, match="target DataHub"):
        _validate_boundary(
            _args(["--target-server", "https://127.0.0.1:28081"])
        )
    with pytest.raises(Phase9Error, match="database"):
        _validate_boundary(
            _args(
                [
                    "--database-url",
                    "postgresql+psycopg://postgres@127.0.0.1:5432/answervice",
                ]
            )
        )


def test_gold_seals_each_strategy_and_all_fail_closed_cases() -> None:
    document = _gold()

    assert {item["expected_strategy"] for item in document["cases"]} == {
        "DIRECT_JOIN",
        "PREAGGREGATE",
        "SEMI_JOIN",
    }
    assert {item["kind"] for item in document["negative_cases"]} == {
        "many_to_many",
        "ambiguous_shortest_path",
        "mixed_time_mode",
    }


def test_capability_is_checksum_bound_to_two_range_assets_and_two_operations() -> None:
    document = _sealed(CAPABILITY_FILE)
    assets = document["contract"]["assets"]

    assert document["catalog_sha256"] == (
        "695fe466056ee0e115eba39c985a1264f818faa960b8ba7d97da5f0f7ef4f2ed"
    )
    assert document["contract"]["operations"] == ["aggregate", "breakdown"]
    assert len(assets) == 2
    assert {item["time"]["mode"] for item in assets} == {"range"}
    assert _sealed(GOLD_FILE)["dataset_id"] == "answervice_ko_multi_asset_join.v1"


def test_model_call_gate_allows_only_expected_single_metric_narration() -> None:
    _validate_model_call_gate(["node3", "node3"], 2)

    with pytest.raises(Phase9Error, match="model call boundary"):
        _validate_model_call_gate(["node3", "node1"], 1)
    with pytest.raises(Phase9Error, match="model call boundary"):
        _validate_model_call_gate(["node3"], 2)
