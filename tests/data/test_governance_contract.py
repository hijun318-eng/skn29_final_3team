import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/data"))

import src.data.governance_contract as contract  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    DATASET_RUNTIME_PROPERTY_KEYS,
    DATASET_MANIFEST_KEYS,
    RELEASE_MANIFEST_KEYS,
    TERM_RUNTIME_PROPERTY_KEYS,
    TERM_MANIFEST_KEYS,
    canonical_json,
    catalog_hash,
    datahub_schema_sha1,
    dataset_runtime_property_projection,
    glossary_hash,
    release_manifest,
    shared_semantic_hash,
    term_runtime_property_projection,
    trino_schema_hash,
)
from test_datahub_metadata_publication import arbitrary_bundle  # noqa: E402


def test_shared_manifest_has_one_exact_dependency_free_shape():
    bundle = arbitrary_bundle()
    manifest = release_manifest(bundle)
    assert set(manifest) == RELEASE_MANIFEST_KEYS
    assert all(set(item) == DATASET_MANIFEST_KEYS for item in manifest["datasets"])
    assert all(set(item) == TERM_MANIFEST_KEYS for item in manifest["metric_terms"])
    assert manifest == json.loads(canonical_json(manifest))
    assert manifest["catalog_sha256"] == catalog_hash(bundle)
    assert manifest["glossary_sha256"] == glossary_hash(bundle)
    assert manifest["shared_semantic_sha256"] == shared_semantic_hash(bundle)


def test_shared_schema_vectors_cover_order_type_nullability_and_table_type():
    bundle = arbitrary_bundle()
    asset = bundle["schema_context"]["assets"][0]
    manifest_asset = {
        item["urn"]: item for item in release_manifest(bundle)["datasets"]
    }[asset["urn"]]
    assert manifest_asset["schema_sha1"] == datahub_schema_sha1(asset)
    assert manifest_asset["trino_schema_sha256"] == trino_schema_hash(asset)
    for field, replacement in (
        ("table_type", "VIEW"),
        ("native_type", "double"),
        ("nullable", True),
        ("ordinal_position", 99),
    ):
        changed = deepcopy(asset)
        target = changed if field == "table_type" else changed["columns"][0]
        target[field] = replacement
        assert trino_schema_hash(changed) != trino_schema_hash(asset)


def test_glossary_set_order_is_not_hash_authoritative():
    bundle = arbitrary_bundle()
    changed = deepcopy(bundle)
    changed["metric_terms"].reverse()
    assert glossary_hash(changed) == glossary_hash(bundle)


def test_runtime_property_projections_have_one_exact_shared_shape():
    bundle = arbitrary_bundle()
    manifest = release_manifest(bundle)
    asset = bundle["schema_context"]["assets"][0]
    metric = bundle["metric_rules"][0]
    term = next(item for item in bundle["metric_terms"] if item["id"] == metric["id"])
    dataset_properties = dataset_runtime_property_projection(bundle, asset, manifest)
    term_properties = term_runtime_property_projection(term, metric, manifest)
    assert set(dataset_properties) == DATASET_RUNTIME_PROPERTY_KEYS
    assert set(term_properties) == TERM_RUNTIME_PROPERTY_KEYS
    assert "value" not in canonical_json(dataset_properties)


def test_dataset_metric_projection_is_independent_of_policy_input_order():
    """한 asset의 다중 metric은 입력 배열 순서와 무관하게 ID 순으로 직렬화한다."""

    bundle = arbitrary_bundle()
    asset = bundle["schema_context"]["assets"][0]
    bundle["metric_rules"][1]["source"]["field"]["asset_fqn"] = asset["fqn"]
    original = dataset_runtime_property_projection(
        bundle, asset, release_manifest(bundle)
    )["metrics"]

    reordered = deepcopy(bundle)
    reordered["metric_rules"].reverse()
    actual = dataset_runtime_property_projection(
        reordered, asset, release_manifest(reordered)
    )["metrics"]

    assert actual == original
    assert [item["id"] for item in json.loads(actual)] == sorted(
        item["id"] for item in bundle["metric_rules"]
    )


def test_release_manifest_key_check_survives_python_optimization(monkeypatch):
    monkeypatch.setattr(contract, "RELEASE_MANIFEST_KEYS", frozenset({"invalid"}))
    with pytest.raises(ValueError, match="release manifest keys differ"):
        contract.release_manifest(arbitrary_bundle())
