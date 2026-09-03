"""Git canonical metadata manifest의 exact inventory와 review gate 계약을 검증한다."""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
METADATA = DATAHUB / "metadata"
for entry in (str(ROOT), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_metadata_manifest import (  # noqa: E402
    REVIEW_REQUIRED,
    compile_semantic_authoring_policy,
    load_canonical_metadata_manifest,
    validate_canonical_metadata_document,
)
from bootstrap_canonical_metadata_manifest import (  # noqa: E402
    _dataset_operational_contract,
    _event_fields,
    _event_time_contract,
    _metric_validation_query,
    _repair_utf8_mojibake,
    _temporal_column_names,
)


def test_checked_in_manifest_preserves_active_exact_inventory_as_ready_catalog() -> None:
    manifest = load_canonical_metadata_manifest(METADATA)

    assert manifest.status == "READY"
    assert manifest.inventory == {
        "domains": 6,
        "owner_groups": 1,
        "datasets": 53,
        "columns": 592,
        "glossary_terms": 16,
        "business_metrics": 13,
        "support_metrics": 4,
        "quality_policies": 53,
        "lineage_edges": 41,
        "source_roots": 38,
        "lineage_exceptions": 0,
    }
    assert len(manifest.content_sha256) == 64
    assert manifest.review_required == ()
    document = manifest.as_document()
    assert all(
        dataset["business_name"] != REVIEW_REQUIRED
        for dataset in document["datasets"]
    )
    assert all(
        column["sensitivity"] != "REVIEW_REQUIRED"
        and column["pii_type"] != "REVIEW_REQUIRED"
        for dataset in document["datasets"]
        for column in dataset["columns"]
    )
    assert all(dataset["primary_key"] != "REVIEW_REQUIRED" for dataset in document["datasets"])
    assert all(
        dataset["update_frequency"] != REVIEW_REQUIRED
        and dataset["freshness_slo"] != REVIEW_REQUIRED
        for dataset in document["datasets"]
    )
    assert all(
        policy["freshness"] != REVIEW_REQUIRED
        for policy in document["quality_policies"]
    )
    quality_by_dataset = {
        policy["dataset_id"]: policy for policy in document["quality_policies"]
    }
    assert all(
        dataset["event_time"] != REVIEW_REQUIRED
        for dataset in document["datasets"]
    )
    assert all(
        policy["timestamp_validity"] != REVIEW_REQUIRED
        for policy in document["quality_policies"]
    )
    for dataset in document["datasets"]:
        if dataset["event_time"] == "NOT_APPLICABLE":
            assert dataset["event_time"] == "NOT_APPLICABLE"
            assert (
                quality_by_dataset[dataset["dataset_id"]]["timestamp_validity"]
                == "NOT_APPLICABLE"
            )
    assert all(metric["null_policy"] != "REVIEW_REQUIRED" for metric in document["metrics"])
    assert all(
        metric["validation_query"] != REVIEW_REQUIRED
        for metric in document["metrics"]
    )
    assert all(
        metric["user_selectable"] is False
        for metric in document["metrics"]
        if metric["visibility"] == "INTERNAL_SUPPORT"
    )


def test_stable_manifest_ids_do_not_embed_release_versions() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    unstable = re.compile(r"(?:^|[._-])v\d+(?:[._-]\d+)+|20\d{6}", re.IGNORECASE)

    identities = [item["dataset_id"] for item in document["datasets"]]
    identities.extend(item["term_id"] for item in document["glossary_terms"])
    identities.extend(item["metric_id"] for item in document["metrics"])

    assert not [identity for identity in identities if unstable.search(identity)]


def test_ready_manifest_compiles_complete_existing_authoring_contract() -> None:
    """Git 정본은 물리 schema를 복사하지 않고 기존 authoring 정책 전체를 만든다."""

    manifest = load_canonical_metadata_manifest(METADATA)
    first = compile_semantic_authoring_policy(manifest)
    second = compile_semantic_authoring_policy(manifest)

    assert first == second
    assert first["catalog_version"] == "walkerhill-analysis-semantics-v1.20260827.1"
    assert len(first["assets"]) == 53
    assert len(first["metric_rules"]) == 17
    assert len(first["metric_terms"]) == 13
    assert {item["version"] for item in first["metric_terms"]} == {
        "walkerhill-analysis-semantics-glossary-v1.20260826.1"
    }
    assert all("description" not in item for item in first["assets"])
    assert all(
        "native_type" not in column and "nullable" not in column
        for asset in first["assets"]
        for column in asset["columns"]
    )
    assert {column["role"] for asset in first["assets"] for column in asset["columns"]} <= {
        "identifier",
        "dimension",
        "measure",
        "time",
        "attribute",
    }


def test_occupancy_rate_allows_the_governed_hotel_dimension() -> None:
    """전체 KPI와 호텔별 비교가 같은 승인된 ratio 계약을 사용한다."""

    manifest = load_canonical_metadata_manifest(METADATA)
    document = manifest.as_document()
    metric = next(
        item for item in document["metrics"] if item["metric_id"] == "occupancy_rate"
    )
    assert metric["allowed_dimensions"] == [
        {
            "asset_fqn": "serving.analytics_v4_3.hotel_operations_daily",
            "column": "hotel_code",
        }
    ]

    policy = compile_semantic_authoring_policy(manifest)
    occupancy = next(
        item for item in policy["metric_rules"] if item["id"] == "occupancy_rate"
    )
    assert occupancy["dimensions"] == []


def test_authoring_compile_rejects_glossary_and_metric_semantic_drift() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    term = next(
        item for item in document["glossary_terms"] if item["term_id"] == "room_revenue"
    )
    term["aliases"] = [*term["aliases"], "검토되지 않은 별칭"]
    manifest = validate_canonical_metadata_document(document)

    with pytest.raises(ValueError, match="Metric and Glossary semantics differ"):
        compile_semantic_authoring_policy(manifest)


def test_review_required_dataset_cannot_claim_certified_lifecycle() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    tampered = copy.deepcopy(document)
    tampered["datasets"][0]["business_name"] = REVIEW_REQUIRED
    tampered["datasets"][0]["lifecycle"] = "CERTIFIED"

    with pytest.raises(ValueError, match="CERTIFIED.*REVIEW_REQUIRED"):
        validate_canonical_metadata_document(tampered)


def test_metric_validation_query_must_be_a_single_read_only_select() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    tampered = copy.deepcopy(document)
    tampered["metrics"][0]["validation_query"] = "DELETE FROM serving.sample"

    with pytest.raises(ValueError, match="Metric validation query.*read-only"):
        validate_canonical_metadata_document(tampered)


def test_quality_schema_fingerprint_must_match_its_dataset_contract() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    tampered = copy.deepcopy(document)
    tampered["quality_policies"][0]["schema_fingerprint_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="quality schema fingerprint"):
        validate_canonical_metadata_document(tampered)


def test_quality_keys_and_timestamp_must_match_their_dataset_contract() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    tampered_keys = copy.deepcopy(document)
    tampered_keys["quality_policies"][0]["required_keys"] = "NOT_NULL:other_id"

    with pytest.raises(ValueError, match="quality required keys"):
        validate_canonical_metadata_document(tampered_keys)

    tampered_timestamp = copy.deepcopy(document)
    tampered_timestamp["quality_policies"][0]["timestamp_validity"] = (
        "VALID_DATE_OR_TIMESTAMP:other_date"
    )

    with pytest.raises(ValueError, match="quality timestamp rule"):
        validate_canonical_metadata_document(tampered_timestamp)


def test_certified_dataset_cannot_keep_a_draft_quality_policy() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    tampered = copy.deepcopy(document)
    dataset_id = tampered["datasets"][0]["dataset_id"]
    tampered["datasets"][0]["lifecycle"] = "CERTIFIED"
    policy = next(
        item for item in tampered["quality_policies"] if item["dataset_id"] == dataset_id
    )
    policy["status"] = "DRAFT"

    with pytest.raises(ValueError, match="ENFORCED quality policy"):
        validate_canonical_metadata_document(tampered)


def test_every_dataset_has_resolved_lineage_root_or_upstream_membership() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    policies = {
        item["dataset_id"]: item for item in document["quality_policies"]
    }

    assert all(policies[item["dataset_id"]]["lineage"] != REVIEW_REQUIRED for item in document["datasets"])
    assert {
        item["dataset_id"]
        for item in document["datasets"]
        if item["source_system"] == "SERVING"
    } == {
        dataset_id
        for dataset_id, policy in policies.items()
        if policy["lineage"]["mode"] == "UPSTREAM"
    }


def test_lineage_rejects_serving_root_and_unresolved_upstream() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    serving = next(
        item for item in document["quality_policies"] if item["dataset_id"].startswith("serving.")
    )
    serving["lineage"] = {"mode": "SOURCE_ROOT"}

    with pytest.raises(ValueError, match="Serving Dataset cannot claim SOURCE_ROOT"):
        validate_canonical_metadata_document(document)

    document = load_canonical_metadata_manifest(METADATA).as_document()
    serving = next(
        item for item in document["quality_policies"] if item["dataset_id"].startswith("serving.")
    )
    serving["lineage"] = {
        "mode": "UPSTREAM",
        "upstream_dataset_ids": ["missing.dataset"],
    }

    with pytest.raises(ValueError, match="upstream Dataset reference"):
        validate_canonical_metadata_document(document)


def test_manifest_checksum_is_independent_of_yaml_mapping_order() -> None:
    first = load_canonical_metadata_manifest(METADATA)
    second_document = {
        key: first.as_document()[key]
        for key in reversed(tuple(first.as_document()))
    }

    second = validate_canonical_metadata_document(second_document)

    assert second.content_sha256 == first.content_sha256


def test_event_fields_include_all_dataset_date_and_timestamp_axes() -> None:
    dataset = {
        "grain": {"kind": "periodic", "keys": ["business_date", "hotel_code"]},
        "time_metadata": {
            "fields": [
                {
                    "field": {
                        "asset_fqn": "serving.analytics_v4_3.sample_daily",
                        "column": "reported_at",
                    }
                },
                {
                    "field": {
                        "asset_fqn": "serving.analytics_v4_3.other_daily",
                        "column": "other_date",
                    }
                },
            ]
        },
    }
    columns = [
        {"name": "business_date", "logical_type": "date", "data_type": "DATE"},
        {"name": "hotel_code", "logical_type": "string", "data_type": "VARCHAR"},
        {
            "name": "reported_at",
            "logical_type": "time",
            "data_type": "TIMESTAMP WITH TIME ZONE",
        },
        {
            "name": "loaded_at",
            "logical_type": "time",
            "data_type": "TIMESTAMP WITH TIME ZONE",
        },
    ]

    assert _event_fields(
        dataset,
        "serving.analytics_v4_3.sample_daily",
        columns,
    ) == ["business_date", "loaded_at", "reported_at"]


def test_single_temporal_column_is_the_unambiguous_event_time() -> None:
    dataset = {
        "grain": {"kind": "row", "keys": ["transaction_id"]},
        "time_metadata": {"fields": []},
    }
    columns = [
        {"name": "transaction_id", "logical_type": "string", "data_type": "VARCHAR"},
        {
            "name": "posted_at",
            "logical_type": "time",
            "data_type": "DATETIME(6)",
        },
    ]

    assert _event_fields(dataset, "pms.sample.transactions", columns) == [
        "posted_at"
    ]


def test_dataset_without_temporal_columns_marks_event_time_not_applicable() -> None:
    columns = [
        {"name": "room_type_code", "logical_type": "string", "data_type": "VARCHAR"},
        {"name": "display_name", "logical_type": "string", "data_type": "VARCHAR"},
    ]

    assert _event_time_contract([], columns) == "NOT_APPLICABLE"


def test_multiple_temporal_columns_are_preserved_as_distinct_axes() -> None:
    dataset = {
        "grain": {"kind": "event", "keys": ["stay_id"]},
        "time_metadata": {"fields": []},
    }
    columns = [
        {
            "name": "checkin_at",
            "logical_type": "time",
            "data_type": "TIMESTAMP WITH TIME ZONE",
        },
        {
            "name": "checkout_at",
            "logical_type": "time",
            "data_type": "TIMESTAMP WITH TIME ZONE",
        },
    ]

    fields = _event_fields(dataset, "pms.sample.stays", columns)
    assert fields == ["checkin_at", "checkout_at"]
    assert _event_time_contract(fields, columns) == fields


def test_time_of_day_columns_are_not_dataset_event_axes() -> None:
    columns = [
        {"name": "open_time", "logical_type": "time", "data_type": "TIME"},
        {"name": "close_time", "logical_type": "time", "data_type": "TIME"},
    ]

    assert _temporal_column_names(columns) == []
    assert _event_time_contract([], columns) == "NOT_APPLICABLE"


def test_ratio_metric_validation_query_is_derived_from_leaf_metric_rules() -> None:
    rules = {
        "revenue": {
            "id": "revenue",
            "aggregation": "sum",
            "source": {
                "kind": "column",
                "field": {
                    "asset_fqn": "serving.analytics.sample_daily",
                    "column": "revenue_krw",
                },
            },
            "time_field": {
                "asset_fqn": "serving.analytics.sample_daily",
                "column": "business_date",
            },
        },
        "orders": {
            "id": "orders",
            "aggregation": "count_distinct",
            "source": {
                "kind": "column",
                "field": {
                    "asset_fqn": "serving.analytics.sample_daily",
                    "column": "order_id",
                },
            },
            "time_field": {
                "asset_fqn": "serving.analytics.sample_daily",
                "column": "business_date",
            },
        },
    }
    ratio = {
        "id": "average_order_value",
        "aggregation": "ratio",
        "source": {
            "kind": "ratio",
            "numerator_metric_id": "revenue",
            "denominator_metric_id": "orders",
            "zero_policy": "null_on_zero_denominator",
        },
        "time_field": None,
    }

    query = _metric_validation_query(ratio, {**rules, ratio["id"]: ratio})

    assert "SUM(revenue_krw) AS numerator_value" in query
    assert "COUNT(DISTINCT order_id) AS denominator_value" in query
    assert "COUNT_IF(business_date IS NULL)" in query
    assert "FROM serving.analytics.sample_daily" in query


def test_utf8_mojibake_repair_is_reversible_and_does_not_change_valid_text() -> None:
    original = "합성 주문 원장"
    corrupted = original.encode("utf-8").decode("latin-1")

    assert _repair_utf8_mojibake(corrupted) == original
    assert _repair_utf8_mojibake(original) == original


def test_checked_in_manifest_does_not_preserve_reversible_utf8_mojibake() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    descriptions = [dataset["description"] for dataset in document["datasets"]]
    descriptions.extend(
        column["description"]
        for dataset in document["datasets"]
        for column in dataset["columns"]
        if "description" in column
    )

    assert not [
        value for value in descriptions if _repair_utf8_mojibake(value) != value
    ]


def test_active_release_verifier_forces_utf8mb4_client_decoding() -> None:
    runner = (
        ROOT
        / "infrastructure"
        / "database"
        / "scripts"
        / "verify-release-sources.ps1"
    ).read_text(encoding="utf-8")

    assert "mysql --default-character-set=utf8mb4" in runner


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (
            "pms",
            {
                "update_frequency": "ON_DATA_RELEASE",
                "freshness_slo": "ACTIVE_DATA_RELEASE_SEED_VERSION_MATCH",
                "freshness_check": "SEED_VERSION_MATCHES_ACTIVE_DATA_RELEASE",
            },
        ),
        (
            "serving",
            {
                "update_frequency": "QUERY_TIME_VIEW",
                "freshness_slo": "UPSTREAM_ACTIVE_DATA_RELEASE_WATERMARK",
                "freshness_check": "UPSTREAM_FRESHNESS_PROPAGATED",
            },
        ),
    ],
)
def test_synthetic_dataset_operational_contract_uses_release_semantics(
    scope: str,
    expected: dict[str, str],
) -> None:
    assert _dataset_operational_contract(scope, synthetic=True) == expected


def test_non_synthetic_dataset_operational_contract_requires_review() -> None:
    assert _dataset_operational_contract("pms", synthetic=False) == {
        "update_frequency": "REVIEW_REQUIRED",
        "freshness_slo": "REVIEW_REQUIRED",
        "freshness_check": "REVIEW_REQUIRED",
    }
