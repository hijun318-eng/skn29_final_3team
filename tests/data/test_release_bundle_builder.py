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

from release_builder import ReleaseNotReady, build_release_bundle, inspect_release  # noqa: E402
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
    release_manifest,
    term_runtime_property_projection,
)
from test_datahub_metadata_publication import arbitrary_bundle  # noqa: E402


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
                schema_hash=datahub_schema_sha1(asset),
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
