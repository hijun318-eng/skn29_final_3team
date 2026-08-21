"""Legacy DataHub readback과 저장소 중립 canonical semantic release의 동등성을 검증한다."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_metadata_values import GovernedMetadataError  # noqa: E402
from app.adapters.legacy_semantic_release import (  # noqa: E402
    LEGACY_DATAHUB_SOURCE_KIND,
    compile_legacy_semantic_release,
)
from app.services.context.semantic_release import (  # noqa: E402
    CANONICAL_SEMANTIC_RELEASE_VERSION,
    CanonicalSemanticRelease,
    CanonicalSemanticReleaseError,
    compare_semantic_releases,
)
from metadata_contract import SemanticMetadataError, validate_bundle  # noqa: E402
from src.data.metric_governance import runtime_governance_version  # noqa: E402
from test_metric_governance_runtime_v2 import (  # noqa: E402
    _engine,
    _runtime_bundle,
    _snapshot,
)


def _with_self_join(bundle: dict) -> dict:
    changed = deepcopy(bundle)
    asset = changed["schema_context"]["assets"][0]
    fqn = asset["fqn"]
    key = asset["grain"]["keys"][0]
    changed["join_graph"]["edges"].append(
        {
            "id": "invalid_self_join",
            "left": fqn,
            "right": fqn,
            "kind": "inner",
            "cardinality": "one_to_one",
            "equality_conditions": [
                {"left_column": key, "right_column": key}
            ],
            "temporal_conditions": [],
            "preaggregation": {
                "required": False,
                "grain": [{"asset_fqn": fqn, "column": key}],
                "keys": [{"asset_fqn": fqn, "column": key}],
            },
        }
    )
    return changed


def test_legacy_snapshot_compiles_to_complete_immutable_release() -> None:
    bundle = _runtime_bundle()
    snapshot = _snapshot(bundle)

    release = compile_legacy_semantic_release(snapshot)

    assert release.format_version == CANONICAL_SEMANTIC_RELEASE_VERSION
    assert release.runtime_contract_version == runtime_governance_version(bundle)
    assert release.source_kind == LEGACY_DATAHUB_SOURCE_KIND
    assert release.catalog_version == bundle["catalog_version"]
    assert {item.fqn for item in release.assets} == {
        item["fqn"] for item in bundle["schema_context"]["assets"]
    }
    assert {item.id for item in release.metrics} == {
        item["id"] for item in bundle["metric_rules"]
    }
    assert {item.id for item in release.joins} == {
        item["id"] for item in bundle["join_graph"]["edges"]
    }
    assert {item.asset_fqn for item in release.adjacency} == {
        item.fqn for item in release.assets
    }

    detached = release.as_bundle()
    detached["query_policy"]["max_limit"] += 1
    assert release.as_bundle()["query_policy"]["max_limit"] != detached["query_policy"][
        "max_limit"
    ]


def test_source_kind_is_not_part_of_canonical_identity() -> None:
    bundle = _runtime_bundle()
    legacy = compile_legacy_semantic_release(_snapshot(bundle))
    native_shadow = CanonicalSemanticRelease.from_validated_bundle(
        legacy.as_bundle(),
        runtime_contract_version=legacy.runtime_contract_version,
        source_kind="datahub_native_shadow",
    )

    comparison = compare_semantic_releases(legacy, native_shadow)

    assert comparison.equivalent is True
    assert comparison.differing_sections == ()
    assert comparison.left_checksum == comparison.right_checksum


def test_comparator_reports_the_changed_contract_section() -> None:
    bundle = _runtime_bundle()
    baseline = compile_legacy_semantic_release(_snapshot(bundle))
    changed_bundle = deepcopy(baseline.as_bundle())
    changed_bundle["query_policy"]["max_limit"] += 1
    changed = CanonicalSemanticRelease.from_validated_bundle(
        changed_bundle,
        runtime_contract_version=baseline.runtime_contract_version,
        source_kind="datahub_native_shadow",
    )

    comparison = compare_semantic_releases(baseline, changed)

    assert comparison.equivalent is False
    assert comparison.differing_sections == ("query_policy",)
    assert comparison.left_checksum != comparison.right_checksum


def test_legacy_adapter_rejects_an_unconfigured_release() -> None:
    snapshot = _snapshot(_runtime_bundle())

    with pytest.raises(GovernedMetadataError, match="configured context release"):
        compile_legacy_semantic_release(snapshot, "missing-release")


def test_publication_contract_rejects_a_self_join_before_release() -> None:
    with pytest.raises(SemanticMetadataError, match="join endpoints"):
        validate_bundle(_with_self_join(_runtime_bundle()))


def test_publication_contract_rejects_preaggregation_across_both_endpoints() -> None:
    bundle = _runtime_bundle()
    edge = bundle["join_graph"]["edges"][0]
    edge["preaggregation"]["keys"].append(
        {
            "asset_fqn": edge["right"],
            "column": edge["equality_conditions"][0]["right_column"],
        }
    )

    with pytest.raises(SemanticMetadataError, match="exactly one endpoint"):
        validate_bundle(bundle)


def test_required_preaggregation_must_target_the_many_endpoint() -> None:
    bundle = _runtime_bundle()
    edge = bundle["join_graph"]["edges"][0]
    right_field = {
        "asset_fqn": edge["right"],
        "column": edge["equality_conditions"][0]["right_column"],
    }
    edge["preaggregation"] = {
        "required": True,
        "grain": [right_field],
        "keys": [right_field],
    }

    with pytest.raises(SemanticMetadataError, match="many endpoint"):
        validate_bundle(bundle)


def test_readiness_uses_the_same_canonical_compile_gate_as_requests() -> None:
    engine = _engine(_runtime_bundle())

    with patch.object(
        engine,
        "_active_release",
        side_effect=GovernedMetadataError("canonical compile failed"),
    ):
        stages, receipt = asyncio.run(engine.catalog_readiness())

    assert stages == {
        "semantic_release": "not_ready",
        "catalog_manifest": "ready",
        "trino_schema": "not_ready",
    }
    assert receipt is None


def test_canonical_compiler_rejects_metric_fields_outside_asset_schema() -> None:
    bundle = _runtime_bundle()
    bundle["metric_rules"][0]["source"]["field"]["column"] = "not_a_column"

    with pytest.raises(CanonicalSemanticReleaseError, match="unknown column"):
        CanonicalSemanticRelease.from_validated_bundle(
            bundle,
            runtime_contract_version=runtime_governance_version(bundle),
            source_kind="datahub_native_shadow",
        )
