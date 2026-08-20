"""Semantic 후보에서 생성되는 범용 구조 회귀 Gate의 결정성과 차단 경계를 검증한다."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from itertools import combinations
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.services.analysis.logical_plan import (  # noqa: E402
    active_analysis_capabilities,
)
from evals.catalog_regression import (  # noqa: E402
    CatalogRegressionError,
    build_catalog_regression,
    evaluate_catalog_observations,
)
from runtime_governance_draft import build_draft  # noqa: E402
from src.data.analysis_capability_contract import (  # noqa: E402
    compile_analysis_capability_contract,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


CANDIDATE_PATH = (
    ROOT / "evals" / "semantic_review" / "answervice_bi_coverage.v1.json"
)
SQL_DIRECTORY = (
    ROOT / "infrastructure" / "database" / "serving_candidates" / "walkerhill_bi_v1"
)


def _candidate() -> dict:
    return json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))


def _capability(candidate: dict):
    draft = build_draft(
        SQL_DIRECTORY,
        candidate["serving_schema"],
        candidate["release_id"],
    )
    assert candidate["source_sql_sha256"] == draft.source_sha256
    return compile_analysis_capability_contract(
        candidate["planning_contract"],
        available_fields_by_asset={
            view.fqn: frozenset(field.name for field in view.fields)
            for view in draft.views
        },
        dimension_family_columns={
            item["id"]: frozenset(item["columns"])
            for item in candidate["dimension_families"]
        },
    )


def _report(candidate: dict | None = None, *, evidence: object | None = None) -> dict:
    value = candidate or _candidate()
    return build_catalog_regression(
        value,
        _capability(value),
        active_analysis_capabilities(),
        runtime_evidence_value=evidence,
    )


def test_real_candidate_generates_deterministic_release_bound_matrix() -> None:
    candidate = _candidate()
    first = _report(candidate)
    second = _report(candidate)

    assert first == second
    assert first["candidate_sha256"] == canonical_sha256(candidate)
    assert first["source_sql_sha256"] == candidate["source_sql_sha256"]
    assert first["case_content_sha256"] == canonical_sha256(first["cases"])
    assert first["business_metric_count"] == 44
    assert first["support_metric_count"] == 5


def test_matrix_covers_all_business_metrics_operations_and_every_metric_pair() -> None:
    candidate = _candidate()
    report = _report(candidate)
    business_ids = sorted(
        item["id"]
        for item in candidate["metrics"]
        if item["visibility"] == "BUSINESS"
    )
    support_ids = {
        item["id"]
        for item in candidate["metrics"]
        if item["visibility"] == "SUPPORT"
    }
    cases = report["cases"]

    assert {
        metric_id for case in cases for metric_id in case["metric_ids"]
    } == set(business_ids)
    assert not support_ids.intersection(
        metric_id for case in cases for metric_id in case["metric_ids"]
    )
    assert {case["operation"] for case in cases} == {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }
    pair_cases = {
        tuple(case["metric_ids"])
        for case in cases
        if len(case["metric_ids"]) == 2
    }
    assert pair_cases == set(combinations(business_ids, 2))
    assert report["summary"]["metric_arity_counts"] == {
        "1": sum(len(case["metric_ids"]) == 1 for case in cases),
        "2": len(pair_cases),
    }

    serialized = json.dumps(cases, ensure_ascii=False, sort_keys=True)
    for forbidden in ('"question"', '"utterance"', '"normalized_question"', '"sql"'):
        assert forbidden not in serialized


def test_cross_asset_pairs_are_explicitly_blocked_without_join_graph() -> None:
    report = _report()
    pair_cases = [
        case for case in report["cases"] if len(case["metric_ids"]) == 2
    ]
    cross_asset = [case for case in pair_cases if len(case["asset_fqns"]) > 1]
    same_asset = [case for case in pair_cases if len(case["asset_fqns"]) == 1]

    assert cross_asset
    assert same_asset
    assert all(
        "JOIN_GRAPH_REQUIRED" in case["technical_blockers"]
        for case in cross_asset
    )
    assert any(case["structural_status"] == "READY" for case in same_asset)


def test_time_and_comparison_gaps_are_visible_instead_of_silently_enabled() -> None:
    candidate = _candidate()
    report = _report(candidate)
    single_cases = [
        case for case in report["cases"] if len(case["metric_ids"]) == 1
    ]
    trend_cases = [case for case in single_cases if case["operation"] == "time_trend"]
    comparison_cases = [
        case for case in single_cases if case["operation"] == "period_comparison"
    ]
    snapshot_assets = {
        item["fqn"]
        for item in candidate["planning_contract"]["assets"]
        if item["time"]["mode"] == "latest_snapshot"
    }
    unsupported_ids = {
        item["id"]
        for item in candidate["metrics"]
        if "operands" in item or item.get("aggregation") == "exists"
    }

    assert trend_cases and all(
        "TIME_GRAIN_CONTRACT_REQUIRED" in case["technical_blockers"]
        for case in trend_cases
    )
    assert comparison_cases and all(
        "COMPARISON_WINDOW_CONTRACT_REQUIRED" in case["technical_blockers"]
        for case in comparison_cases
    )
    assert all(
        "TIME_MODE_NOT_IMPLEMENTED" in case["technical_blockers"]
        for case in single_cases
        if set(case["asset_fqns"]) <= snapshot_assets
    )
    assert all(
        "PERIOD_COMPARISON_AGGREGATION_UNSUPPORTED"
        in case["technical_blockers"]
        for case in comparison_cases
        if case["metric_ids"][0] in unsupported_ids
    )


def test_review_candidate_cannot_be_scored_even_when_observations_exist() -> None:
    report = _report()

    assert report["scorable"] is False
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["global_blockers"] == [
        "SEMANTIC_APPROVAL_REQUIRED",
        "RUNTIME_SOURCE_DISABLED",
        "ACTIVE_RELEASE_READBACK_REQUIRED",
    ]
    with pytest.raises(CatalogRegressionError, match="cannot be scored"):
        evaluate_catalog_observations(report, (), repeat=1)


def test_approved_readback_bound_matrix_scores_exact_repeated_observations() -> None:
    candidate = _candidate()
    candidate["state"] = "APPROVED"
    candidate["runtime_source"] = True
    evidence = {
        "active_release_id": candidate["release_id"],
        "candidate_sha256": canonical_sha256(candidate),
        "verified": True,
    }
    report = _report(candidate, evidence=evidence)
    observations = [
        {
            "case_id": case["case_id"],
            "attempt": attempt,
            "latency_ms": float(attempt),
            "output": deepcopy(case["expected"]),
        }
        for case in report["cases"]
        for attempt in (1, 2)
    ]

    score = evaluate_catalog_observations(report, observations, repeat=2)

    assert report["scorable"] is True
    assert report["global_blockers"] == []
    assert score["total"] == report["case_count"]
    assert score["passed"] == report["case_count"]
    assert score["deterministic"] == report["case_count"]
    assert score["accuracy"] == 1.0
    assert set(score["operation_accuracy"]) == {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }


def test_business_visibility_change_invalidates_case_matrix_checksum() -> None:
    original = _candidate()
    changed = deepcopy(original)
    changed_metric = next(
        item for item in changed["metrics"] if item["visibility"] == "BUSINESS"
    )
    changed_metric["visibility"] = "SUPPORT"

    before = _report(original)
    after = _report(changed)

    assert before["candidate_sha256"] != after["candidate_sha256"]
    assert before["case_content_sha256"] != after["case_content_sha256"]
    assert after["business_metric_count"] == before["business_metric_count"] - 1
