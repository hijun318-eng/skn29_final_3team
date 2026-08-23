"""Phase 7 bounded multi-turn Gold와 release-bound availability 봉인을 검증한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.data.governance_contract import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "infrastructure" / "acceptance"
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ACCEPTANCE), str(BACKEND), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from phase7_bounded_multi_turn import _stored_period  # noqa: E402


GOLD_FILE = (
    ROOT
    / "evals"
    / "golden_dialogue"
    / "answervice_ko_bounded_multiturn.v1.json"
)
CAPABILITY_FILE = (
    ROOT
    / "app"
    / "backend"
    / "contracts"
    / "analysis_capability.bounded_multi_turn.v1.json"
)


def _sealed(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    assert document["content_sha256"] == canonical_sha256(payload)
    assert document["status"] == "SEALED"
    return document


def test_phase7_gold_seals_gd01_to_gd03_exact_counts_and_lineage() -> None:
    document = _sealed(GOLD_FILE)
    dialogues = {item["dialogue_id"]: item for item in document["dialogues"]}

    assert set(dialogues) == {"GD-01", "GD-02", "GD-03"}
    assert dialogues["GD-01"]["totals"] == {
        "turns": 3,
        "runs": 3,
        "queries": 3,
        "artifacts": 3,
        "views": 3,
        "report_blocks": 0,
    }
    assert dialogues["GD-02"]["totals"] == {
        "turns": 5,
        "runs": 1,
        "queries": 1,
        "artifacts": 1,
        "views": 4,
        "report_blocks": 2,
    }
    assert dialogues["GD-03"]["initial_blocked_totals"] == {
        "turns": 1,
        "runs": 0,
        "queries": 0,
        "artifacts": 0,
        "views": 0,
        "report_blocks": 0,
    }
    for dialogue in dialogues.values():
        for turn in dialogue["turns"]:
            assert len(turn["source_turns"]) <= 2
            assert all(source < turn["turn"] for source in turn["source_turns"])


def test_phase7_gold_seals_view_order_report_selection_and_real_clock_boundary() -> None:
    dialogues = {
        item["dialogue_id"]: item for item in _sealed(GOLD_FILE)["dialogues"]
    }
    gd02 = dialogues["GD-02"]
    gd03 = dialogues["GD-03"]

    assert [turn.get("view") for turn in gd02["turns"][1:4]] == [
        "LINE",
        "BAR",
        "TABLE",
    ]
    assert gd02["turns"][4]["report_block_views"] == [3, 4]
    assert gd02["turns"][4]["report_block_types"] == ["chart", "table"]
    assert [turn["analysis_operation"] for turn in dialogues["GD-01"]["turns"]] == [
        "time_trend",
        "time_trend",
        "period_comparison",
    ]
    assert gd02["turns"][0]["analysis_operation"] == "time_trend"
    assert gd03["clock_mode"] == "CURRENT_BACKEND_KST"
    assert gd03["turns"][0]["terminal_status"] == "BLOCKED"
    assert gd03["turns"][0]["reason_code"] == "OUT_OF_DATA_RANGE"


def test_phase7_capability_seals_approved_data_range_without_changing_phase6_file() -> None:
    document = _sealed(CAPABILITY_FILE)
    asset = document["contract"]["assets"][0]

    assert asset["fqn"] == "serving.analytics_v4_3.hotel_operations_daily"
    assert asset["data_availability"] == {
        "data_available_from": "2025-07-01",
        "data_available_through": "2025-08-31",
    }
    assert asset["conversation_default_operation"] == "time_trend"
    assert (
        ROOT
        / "app"
        / "backend"
        / "contracts"
        / "analysis_capability.single_asset.v1.json"
    ).is_file()


def test_phase7_acceptance_normalizes_only_one_typed_blocked_period_candidate() -> None:
    slots = {
        "period_relationship": "single",
        "period_candidates": [
            {
                "start": "2026-08-01T00:00:00+09:00",
                "end_exclusive": "2026-08-22T00:00:00+09:00",
                "source_text": "이번 달",
            }
        ],
    }

    assert _stored_period(
        slots,
        "time_range",
        allow_blocked_candidate=True,
    ) == {"start": "2026-08-01", "end_exclusive": "2026-08-22"}
    assert (
        _stored_period(slots, "time_range", allow_blocked_candidate=False) is None
    )
    assert (
        _stored_period(
            {**slots, "period_candidates": slots["period_candidates"] * 2},
            "time_range",
            allow_blocked_candidate=True,
        )
        is None
    )
