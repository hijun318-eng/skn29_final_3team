import copy

import pytest

from src.ai.training.build_case_specs import (
    IncompleteScenarioError,
    build_case,
    select_specs,
    summarize,
)


FULL_SPECS = [
    {
        "case_id": "case-zeta",
        "split": "validation",
        "node": "node2",
        "domain": "review-stream-one",
        "scenario_group": "reviewed-zeta",
        "synthetic": True,
        "schema_version": "test-contract",
        "seed_version": "human-review-1",
        "review_status": "APPROVED",
        "trino_status": "NOT_RUN",
        "result_sha256": None,
        "input": {
            "resolved_request": {"intent": "reviewed aggregate"},
            "schema_context": {
                "assets": [
                    {
                        "urn": "urn:example:zeta-observation",
                        "fqn": "zeta_space.observation_log.readings",
                        "columns": [
                            {"name": "observed_at", "native_type": "timestamp"},
                            {"name": "reading", "native_type": "double"},
                        ],
                    }
                ]
            },
            "metric_rules": [{"id": "reviewed_measure", "aggregation": "sum"}],
            "join_graph": {"edges": []},
            "time_rules": {"interval": "half_open"},
            "parameter_contract": [],
            "query_policy": {"max_limit": 100},
        },
        "expected_output": {
            "sql": "SELECT SUM(reading) AS total_reading FROM zeta_space.observation_log.readings LIMIT 100",
            "references": ["urn:example:zeta-observation"],
            "parameters": [],
        },
    },
    {
        "case_id": "case-alpha",
        "split": "train",
        "node": "node2_repair",
        "domain": "review-stream-two",
        "scenario_group": "reviewed-alpha",
        "synthetic": True,
        "schema_version": "test-contract",
        "seed_version": "human-review-2",
        "review_status": "AUTO_PASSED",
        "trino_status": "NOT_RUN",
        "result_sha256": None,
        "input": {
            "resolved_request": {"intent": "reviewed repair"},
            "schema_context": {
                "assets": [
                    {
                        "urn": "urn:example:alpha-sample",
                        "fqn": "alpha_lab.samples.measurements",
                        "columns": [
                            {"name": "sample_key", "native_type": "varchar"},
                            {"name": "magnitude", "native_type": "decimal"},
                        ],
                    }
                ]
            },
            "metric_rules": [{"id": "reviewed_magnitude", "aggregation": "avg"}],
            "join_graph": {"edges": []},
            "time_rules": {},
            "parameter_contract": [],
            "query_policy": {"max_limit": 50},
        },
        "expected_output": {
            "corrected_sql": "SELECT AVG(magnitude) AS mean_magnitude FROM alpha_lab.samples.measurements LIMIT 50",
            "references": ["urn:example:alpha-sample"],
            "parameters": [],
        },
    },
]


def test_selection_is_deterministic_and_preserves_reviewed_specs_verbatim():
    source = copy.deepcopy(FULL_SPECS)

    selected = select_specs(reversed(source))

    assert [item["case_id"] for item in selected] == ["case-alpha", "case-zeta"]
    assert selected == [source[1], source[0]]
    selected[0]["input"]["resolved_request"]["intent"] = "mutated"
    assert source[1]["input"]["resolved_request"]["intent"] == "reviewed repair"


def test_selection_uses_only_explicit_metadata_filters_and_limit():
    selected = select_specs(
        FULL_SPECS,
        splits=["validation"],
        nodes=["node2"],
        review_statuses=["APPROVED"],
        case_ids=["case-zeta"],
        limit=1,
    )

    assert selected == [FULL_SPECS[0]]
    assert summarize(FULL_SPECS) == {
        "total": 2,
        "splits": {"train": 1, "validation": 1},
        "nodes": {"node2": 1, "node2_repair": 1},
        "review_statuses": {"APPROVED": 1, "AUTO_PASSED": 1},
    }


def test_selection_rejects_negative_limit():
    with pytest.raises(ValueError, match="non-negative"):
        select_specs(FULL_SPECS, limit=-1)


def test_incomplete_scenario_ledger_is_rejected_instead_of_completed():
    ledger_row = {
        "candidate_id": "ledger-only",
        "target_split": "train",
        "shape": "aggregate",
    }

    with pytest.raises(IncompleteScenarioError, match="human-authored full spec"):
        build_case(ledger_row)
