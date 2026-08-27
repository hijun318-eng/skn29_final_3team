import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure/database/datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))
sys.path.insert(0, str(ROOT / "tests/data"))

from release_builder import (  # noqa: E402
    ReleaseNotReady,
    build_active_release_bundle,
    build_release_bundle,
    inspect_release,
)
from release_bundle import SemanticBundleError  # noqa: E402
from release_datahub import (  # noqa: E402
    DataHubDataset,
    DataHubField,
    DataHubTerm,
    NativeEntity,
)
from release_scope import ReleaseScope  # noqa: E402
from release_trino import (  # noqa: E402
    PhysicalColumn,
    PhysicalRelation,
    TrinoInventory,
)
from src.data.governance_contract import (  # noqa: E402
    canonical_json,
    catalog_hash,
    datahub_schema_sha1,
    dataset_runtime_property_projection,
    dimension_member_term_runtime_property_projection,
    dimension_members,
    release_manifest,
    term_runtime_property_projection,
)
from test_datahub_metadata_publication import (  # noqa: E402
    arbitrary_bundle,
    bundle_with_dimension_members,
)
from test_metric_governance_v2 import _v2_bundle  # noqa: E402


PREFIX = "answervice."


class FakeTrino:
    def __init__(self, inventory):
        self.inventory = inventory

    async def discover(self, scopes):
        assert {relation.scope for relation in self.inventory.relations} == set(scopes)
        return self.inventory


class FakeDataHub:
    def __init__(self, datasets, terms):
        self.datasets = tuple(datasets)
        self.terms = {term.urn: term for term in terms}
        self.term_calls = 0

    async def discover_datasets(self, _scopes):
        return self.datasets

    async def discover_terms(self, urns):
        self.term_calls += 1
        return tuple(self.terms[urn] for urn in urns)


def _native(bundle):
    governance = bundle["governance_entities"]
    owner = governance["owners"][0]
    domain = governance["domains"][0]
    lifecycle = governance["approved_lifecycles"][0]
    return (
        NativeEntity(owner["urn"], owner["name"], owner["description"], "CorpGroup"),
        NativeEntity(domain["urn"], domain["name"], domain["description"], "Domain"),
        NativeEntity(
            lifecycle["urn"],
            lifecycle["name"],
            lifecycle["description"],
            "LifecycleStage",
        ),
    )


def _runtime(bundle):
    manifest = release_manifest(bundle)
    owner, domain, lifecycle = _native(bundle)
    scopes = []
    relations = []
    datasets = []
    for asset in bundle["schema_context"]["assets"]:
        catalog, schema, table = asset["fqn"].split(".")
        key_name = asset["dataset_key"]["name"]
        instance = key_name.split(".", 1)[0]
        namespace = asset["schema_name"].rsplit(".", 1)[0]
        scope = ReleaseScope(
            catalog, schema, instance, namespace, asset["dataset_key"]["origin"]
        )
        scopes.append(scope)
        columns = tuple(
            PhysicalColumn(
                item["ordinal_position"],
                item["name"],
                item["native_type"],
                item["nullable"],
            )
            for item in asset["columns"]
        )
        relations.append(PhysicalRelation(scope, table, asset["table_type"], columns))
        properties = dataset_runtime_property_projection(bundle, asset, manifest)
        datasets.append(
            DataHubDataset(
                urn=asset["urn"],
                dataset_key_name=key_name,
                origin=asset["dataset_key"]["origin"],
                platform_urn=asset["platform_urn"],
                name=asset["fqn"],
                qualified_name=asset["fqn"],
                description=asset["description"],
                schema_name=asset["schema_name"],
                schema_version=asset["schema_metadata_version"],
                schema_hash=asset["datahub_schema_hash"],
                removed=False,
                owners=(owner,),
                domain=domain,
                lifecycle=lifecycle,
                custom_properties={f"{PREFIX}{key}": value for key, value in properties.items()},
                fields=tuple(
                    DataHubField(
                        item["name"],
                        item["native_type"],
                        item["nullable"],
                        item["is_part_of_key"],
                        item["description"],
                    )
                    for item in asset["columns"]
                ),
            )
        )
    metrics = {item["id"]: item for item in bundle["metric_rules"]}
    terms = []
    for definition in bundle["metric_terms"]:
        properties = term_runtime_property_projection(
            definition, metrics[definition["id"]], manifest
        )
        terms.append(
            DataHubTerm(
                urn=definition["urn"],
                exists=True,
                name=definition["name"],
                description=definition["definition"],
                removed=False,
                owners=(owner,),
                domain=domain,
                lifecycle=lifecycle,
                custom_properties={f"{PREFIX}{key}": value for key, value in properties.items()},
            )
        )
    for definition in dimension_members(bundle):
        properties = dimension_member_term_runtime_property_projection(
            definition,
            manifest,
        )
        terms.append(
            DataHubTerm(
                urn=definition["urn"],
                exists=True,
                name=definition["name"],
                description=definition["definition"],
                removed=False,
                owners=(owner,),
                domain=domain,
                lifecycle=lifecycle,
                custom_properties={
                    f"{PREFIX}{key}": value for key, value in properties.items()
                },
            )
        )
    inventory = TrinoInventory(tuple(relations), ("query-catalogs", "query-columns"))
    return tuple(sorted(scopes)), inventory, tuple(datasets), tuple(terms)


def test_dynamic_release_is_built_only_after_both_readiness_stages_pass():
    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    result = asyncio.run(
        inspect_release(
            scopes,
            FakeTrino(inventory),
            FakeDataHub(datasets, terms),
        )
    )

    assert result.report.base_ingestion.status == "READY"
    assert result.report.semantic_release.status == "READY"
    assert result.report.base_ingestion.expected_dataset_count == 2
    assert result.report.base_ingestion.expected_column_count == 9
    assert result.bundle is not None
    assert catalog_hash(result.bundle) == catalog_hash(bundle)
    assert release_manifest(result.bundle) == release_manifest(bundle)


def test_release_identity_uses_qualified_name_not_business_display_name():
    """DataHub 업무 표시명은 보존하되 실행 FQN은 qualifiedName으로 대조한다."""

    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    business_named = replace(datasets[0], name="객실 매출 업무 데이터")

    result = asyncio.run(
        inspect_release(
            scopes,
            FakeTrino(inventory),
            FakeDataHub((business_named, *datasets[1:]), terms),
        )
    )

    assert result.report.semantic_release.status == "READY"
    assert result.bundle is not None
    assert catalog_hash(result.bundle) == catalog_hash(bundle)


def test_v2_release_readback_preserves_hidden_support_rules():
    """live Dataset property가 Glossary에 없는 SUPPORT Rule까지 동일하게 복원한다."""

    bundle = _v2_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    result = asyncio.run(
        inspect_release(scopes, FakeTrino(inventory), FakeDataHub(datasets, terms))
    )

    assert result.report.semantic_release.status == "READY"
    assert result.bundle is not None
    assert {item["id"] for item in result.bundle["metric_rules"]} == {
        "amount_total",
        "event_count",
        "account_count",
        "amount_per_event",
    }
    assert {item["id"] for item in result.bundle["metric_terms"]} == {
        "account_count",
        "amount_per_event",
    }
    assert release_manifest(result.bundle) == release_manifest(bundle)


def test_dimension_member_terms_round_trip_through_live_release_readback():
    bundle = bundle_with_dimension_members()
    scopes, inventory, datasets, terms = _runtime(bundle)

    result = asyncio.run(
        inspect_release(scopes, FakeTrino(inventory), FakeDataHub(datasets, terms))
    )

    assert result.report.semantic_release.status == "READY"
    assert result.report.semantic_release.expected_term_count == 4
    assert result.bundle is not None
    assert catalog_hash(result.bundle) == catalog_hash(bundle)
    assert release_manifest(result.bundle) == release_manifest(bundle)
    assert {
        item["urn"]: item for item in result.bundle["dimensions"][0]["members"]
    } == {
        item["urn"]: item for item in bundle["dimensions"][0]["members"]
    }


def test_missing_base_dataset_is_distinct_and_blocks_term_lookup():
    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    datahub = FakeDataHub(datasets[:-1], terms)
    result = asyncio.run(inspect_release(scopes, FakeTrino(inventory), datahub))

    assert result.bundle is None
    assert result.report.base_ingestion.status == "NOT_READY"
    assert result.report.base_ingestion.expected_dataset_count == 2
    assert result.report.base_ingestion.observed_dataset_count == 1
    assert result.report.semantic_release.status == "NOT_READY"
    assert "base_ingestion_not_ready" in result.report.semantic_release.issues
    assert datahub.term_calls == 0

    with pytest.raises(ReleaseNotReady):
        asyncio.run(build_release_bundle(scopes, FakeTrino(inventory), datahub))


def test_complete_base_schema_does_not_imply_semantic_readiness():
    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    first = datasets[0]
    ungoverned = replace(first, custom_properties={}, lifecycle=None)
    datahub = FakeDataHub((ungoverned, *datasets[1:]), terms)
    result = asyncio.run(inspect_release(scopes, FakeTrino(inventory), datahub))

    assert result.report.base_ingestion.status == "READY"
    assert result.report.semantic_release.status == "NOT_READY"
    assert any(issue.startswith("semantic_properties:") for issue in result.report.semantic_release.issues)
    assert any(issue.startswith("approved_lifecycle:") for issue in result.report.semantic_release.issues)
    assert result.bundle is None
    assert datahub.term_calls == 0


def test_active_release_ignores_only_completely_ungoverned_physical_candidates():
    """manifest 밖 신규 Dataset은 strict authoring을 막되 현재 active read-back에는 섞이지 않는다."""

    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    source = datasets[0]
    source_relation = inventory.relations[0]
    candidate_name = "review_candidate"
    candidate = replace(
        source,
        urn="urn:li:dataset:(urn:li:dataPlatform:test,review_candidate,PROD)",
        dataset_key_name=(
            f"{source.dataset_key_name.split('.', 1)[0]}.{candidate_name}"
        ),
        name=f"{source_relation.scope.catalog}.{source_relation.scope.schema}.{candidate_name}",
        qualified_name=(
            f"{source_relation.scope.catalog}.{source_relation.scope.schema}.{candidate_name}"
        ),
        schema_name=(
            f"{source.schema_name.rsplit('.', 1)[0]}.{candidate_name}"
        ),
        custom_properties={},
        owners=(),
        domain=None,
        lifecycle=None,
    )
    candidate_relation = PhysicalRelation(
        source_relation.scope,
        candidate_name,
        source_relation.table_type,
        source_relation.columns,
    )
    expanded_inventory = TrinoInventory(
        tuple(sorted((*inventory.relations, candidate_relation), key=lambda item: item.fqn)),
        inventory.query_ids,
    )
    datahub = FakeDataHub((*datasets, candidate), terms)

    strict = asyncio.run(
        inspect_release(scopes, FakeTrino(expanded_inventory), datahub)
    )
    active = asyncio.run(
        build_active_release_bundle(
            scopes,
            FakeTrino(expanded_inventory),
            datahub,
        )
    )

    assert strict.bundle is None
    assert strict.report.base_ingestion.status == "READY"
    assert strict.report.semantic_release.status == "NOT_READY"
    assert catalog_hash(active) == catalog_hash(bundle)
    assert candidate_name not in {
        item["fqn"].rsplit(".", 1)[-1]
        for item in active["schema_context"]["assets"]
    }


def test_active_release_does_not_hide_partially_governed_candidates():
    """answervice property가 일부라도 있는 후보는 무거버넌스로 가장해 제외할 수 없다."""

    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    partial = replace(
        datasets[0],
        urn="urn:li:dataset:(urn:li:dataPlatform:test,partial_candidate,PROD)",
        custom_properties={f"{PREFIX}contract_version": "partial"},
    )
    with pytest.raises(SemanticBundleError):
        asyncio.run(
            build_active_release_bundle(
                scopes,
                FakeTrino(inventory),
                FakeDataHub((*datasets, partial), terms),
            )
        )


def test_coordinated_shape_with_stale_hash_still_fails_closed():
    bundle = arbitrary_bundle()
    scopes, inventory, datasets, terms = _runtime(bundle)
    first = datasets[0]
    properties = dict(first.custom_properties)
    policy = {
        "dialect": "trino",
        "statement_type": "select",
        "read_only": True,
        "require_limit": True,
        "max_limit": 1,
        "allowed_functions": ["sum", "count"],
        "allowed_catalogs": ["ember", "quartz"],
    }
    properties[f"{PREFIX}query_policy"] = canonical_json(policy)
    tampered = replace(first, custom_properties=properties)
    result = asyncio.run(
        inspect_release(
            scopes,
            FakeTrino(inventory),
            FakeDataHub((tampered, *datasets[1:]), terms),
        )
    )

    assert result.report.base_ingestion.status == "READY"
    assert result.report.semantic_release.status == "NOT_READY"
    assert result.bundle is None
