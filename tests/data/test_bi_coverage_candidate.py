"""범용 BI serving/semantic 후보가 SQL 근거와 분리되지 않는지 검증한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
if str(DATAHUB) not in sys.path:
    sys.path.insert(0, str(DATAHUB))

from runtime_governance_draft import build_draft  # noqa: E402
from src.data.analysis_capability_contract import (  # noqa: E402
    ANALYSIS_CAPABILITY_VERSION,
    compile_analysis_capability_contract,
)


CANDIDATE_PATH = ROOT / "evals" / "semantic_review" / "answervice_bi_coverage.v1.json"
SQL_DIRECTORY = (
    ROOT / "infrastructure" / "database" / "serving_candidates" / "walkerhill_bi_v1"
)


def _candidate() -> dict:
    return json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))


def test_candidate_is_review_only_and_checksum_bound_to_sql() -> None:
    candidate = _candidate()
    draft = build_draft(
        SQL_DIRECTORY,
        candidate["serving_schema"],
        candidate["release_id"],
    )

    assert candidate["state"] == "REVIEW_REQUIRED"
    assert candidate["runtime_source"] is False
    assert candidate["source_sql_sha256"] == draft.source_sha256
    assert {item["fqn"] for item in candidate["views"]} == {
        view.fqn for view in draft.views
    }


def test_every_candidate_grain_dimension_and_metric_is_backed_by_a_view_column() -> None:
    candidate = _candidate()
    draft = build_draft(
        SQL_DIRECTORY,
        candidate["serving_schema"],
        candidate["release_id"],
    )
    fields_by_view = {
        view.fqn: {field.name for field in view.fields}
        for view in draft.views
    }
    all_fields = set().union(*fields_by_view.values())

    for view in candidate["views"]:
        assert set(view["grain_keys"]) <= fields_by_view[view["fqn"]]
    for family in candidate["dimension_families"]:
        assert set(family["columns"]) <= all_fields

    metrics = {item["id"]: item for item in candidate["metrics"]}
    assert len(metrics) == len(candidate["metrics"])
    assert sum(item["visibility"] == "BUSINESS" for item in metrics.values()) >= 40
    for metric in metrics.values():
        if "asset" in metric:
            assert metric["column"] in fields_by_view[metric["asset"]]
        else:
            assert len(metric["operands"]) == 2
            assert all(operand in metrics for operand in metric["operands"])


def test_candidate_declares_generic_analysis_operations_not_question_templates() -> None:
    candidate = _candidate()

    assert set(candidate["planning_contract"]["operations"]) == {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }
    serialized = json.dumps(candidate, ensure_ascii=False)
    assert "지난달 전체 객실 매출은 얼마야" not in serialized
    assert "이번 달 식음 매출이 가장 높은 업장은 어디야" not in serialized


def test_candidate_planning_contract_binds_every_asset_to_real_schema_fields() -> None:
    candidate = _candidate()
    draft = build_draft(
        SQL_DIRECTORY,
        candidate["serving_schema"],
        candidate["release_id"],
    )
    fields_by_view = {
        view.fqn: frozenset(field.name for field in view.fields)
        for view in draft.views
    }
    family_columns = {
        item["id"]: frozenset(item["columns"])
        for item in candidate["dimension_families"]
    }

    contract = compile_analysis_capability_contract(
        candidate["planning_contract"],
        available_fields_by_asset=fields_by_view,
        dimension_family_columns=family_columns,
    )

    assert contract.version == ANALYSIS_CAPABILITY_VERSION
    assert contract.max_metrics_per_plan == 4
    assert {item.asset_fqn for item in contract.assets} == set(fields_by_view)
    assert {
        item["asset"]
        for item in candidate["metrics"]
        if "asset" in item
    } <= {item.asset_fqn for item in contract.assets}


def test_snapshot_and_range_time_modes_are_not_conflated() -> None:
    candidate = _candidate()
    assets = {
        item["fqn"]: item for item in candidate["planning_contract"]["assets"]
    }

    snapshot = assets["serving.analytics_v4_3.membership_current_snapshot"]
    assert snapshot["time"] == {
        "mode": "latest_snapshot",
        "field": "snapshot_date",
        "default": "max_source_value_lte_as_of",
    }
    assert all(
        item["time"]["mode"] == "range"
        and item["time"]["default"] == "required_period"
        for fqn, item in assets.items()
        if fqn != "serving.analytics_v4_3.membership_current_snapshot"
    )
