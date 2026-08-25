from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB), str(ROOT / "tests" / "data")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_contract_primitives import SemanticMetadataError  # noqa: E402
import author_semantic_catalog as author_catalog  # noqa: E402
from policy_compiler import (  # noqa: E402
    DECISION_CONTRACT_VERSION,
    DECISION_CONTRACT_VERSION_V2,
    compile_authoring_policy,
)
from author_semantic_catalog import (  # noqa: E402
    PublicationReadbackError,
    apply_authoring_release,
)
from release_bundle import ReleaseBinding  # noqa: E402
from release_bundle import (  # noqa: E402
    assemble_catalog_snapshot_bundle,
    rebase_catalog_snapshot_entitlements,
)
from release_datahub import DataHubDiscoveryError  # noqa: E402
from publication_check import (  # noqa: E402
    physical_scope_sha256,
    publication_check,
    verify_expected_release,
)
from native_semantic_shadow import native_semantic_shadow_projection  # noqa: E402
from semantic_authoring import (  # noqa: E402
    AUTHORING_CONTRACT_VERSION,
    AUTHORING_CONTRACT_VERSION_V2,
    AUTHORING_CONTRACT_VERSION_V4,
    CLEAN_CATALOG_SHA256,
    assemble_authoring_bundle,
    build_authoring_candidate,
    build_authoring_bundle,
    migrate_authoring_policy,
    _previous_catalog_sha256,
)
from src.data.governance_contract import catalog_hash  # noqa: E402
from test_datahub_metadata_publication import (  # noqa: E402
    arbitrary_bundle,
    arbitrary_ratio_bundle,
)
from test_release_bundle_builder import _runtime  # noqa: E402
from test_metric_governance_v2 import _v2_bundle  # noqa: E402


def _policy(bundle):
    return {
        "contract_version": AUTHORING_CONTRACT_VERSION,
        "catalog_version": bundle["catalog_version"],
        "policy_version": bundle["policy_version"],
        "schema_context_version": bundle["schema_context"]["version"],
        "governance_entities": deepcopy(bundle["governance_entities"]),
        "assets": [
            {
                "fqn": asset["fqn"],
                "schema_version": asset["schema_version"],
                "seed_version": asset["seed_version"],
                "synthetic": asset["synthetic"],
                "approval_status": asset["approval_status"],
                "entitlements": deepcopy(asset["entitlements"]),
                "grain": deepcopy(asset["grain"]),
                "columns": [
                    {
                        "name": column["name"],
                        "logical_type": column["logical_type"],
                        "is_part_of_key": column["is_part_of_key"],
                        "role": column["role"],
                    }
                    for column in asset["columns"]
                ],
                "owner_urn": asset["owner_urn"],
                "domain_urn": asset["domain_urn"],
                "approved_lifecycle_urn": asset["approved_lifecycle_urn"],
            }
            for asset in bundle["schema_context"]["assets"]
        ],
        "metric_rules": deepcopy(bundle["metric_rules"]),
        "metric_terms": deepcopy(bundle["metric_terms"]),
        "dimensions": deepcopy(bundle["dimensions"]),
        "join_graph": deepcopy(bundle["join_graph"]),
        "time_rules": deepcopy(bundle["time_rules"]),
        "parameter_contract": deepcopy(bundle["parameter_contract"]),
        "query_policy": deepcopy(bundle["query_policy"]),
    }


def _physical(bundle):
    scopes, inventory, datasets, _terms = _runtime(bundle)
    datasets_by_name = {item.name: item for item in datasets}
    ungoverned = {
        name: replace(
            dataset,
            owners=(),
            domain=None,
            lifecycle=None,
            custom_properties={},
        )
        for name, dataset in datasets_by_name.items()
    }
    bindings = tuple(
        ReleaseBinding(relation, ungoverned[relation.fqn])
        for relation in inventory.relations
    )
    return scopes, inventory, tuple(ungoverned.values()), bindings


def _with_ungoverned_candidate(inventory, datasets, name):
    source_relation = inventory.relations[0]
    source_dataset = datasets[0]
    fqn = f"{source_relation.scope.catalog}.{source_relation.scope.schema}.{name}"
    relation = replace(source_relation, name=name)
    dataset = replace(
        source_dataset,
        urn=source_dataset.urn.replace(source_relation.name, name),
        dataset_key_name=f"{source_dataset.dataset_key_name.rsplit('.', 1)[0]}.{name}",
        name=fqn,
        qualified_name=fqn,
        schema_name=f"{source_dataset.schema_name.rsplit('.', 1)[0]}.{name}",
        custom_properties={},
    )
    expanded = replace(
        inventory,
        relations=tuple(
            sorted((*inventory.relations, relation), key=lambda item: item.fqn)
        ),
    )
    return expanded, (*datasets, dataset), dataset


def _decisions(bundle):
    owner = bundle["governance_entities"]["owners"][0]
    lifecycle = bundle["governance_entities"]["approved_lifecycles"][0]
    return {
        "contract_version": DECISION_CONTRACT_VERSION,
        "catalog_version": bundle["catalog_version"],
        "policy_version": bundle["policy_version"],
        "schema_context_version": bundle["schema_context"]["version"],
        "schema_version": bundle["schema_context"]["assets"][0]["schema_version"],
        "seed_version": bundle["schema_context"]["assets"][0]["seed_version"],
        "synthetic": False,
        "owner": deepcopy(owner),
        "approved_lifecycle": deepcopy(lifecycle),
        "roles": ["analyst"],
        "asset_grains": [
            {"fqn": asset["fqn"], **deepcopy(asset["grain"])}
            for asset in bundle["schema_context"]["assets"]
        ],
        "metric_rules": deepcopy(bundle["metric_rules"]),
        "metric_terms": [
            {
                key: deepcopy(term[key])
                for key in ("id", "urn", "name", "definition", "aliases", "unit", "version")
            }
            for term in bundle["metric_terms"]
        ],
        "dimensions": deepcopy(bundle["dimensions"]),
        "join_graph": deepcopy(bundle["join_graph"]),
        "time_rules": {
            **{
                key: deepcopy(value)
                for key, value in bundle["time_rules"].items()
                if key != "fields"
            },
            "fields": [
                {
                    key: deepcopy(value)
                    for key, value in field.items()
                    if key != "native_type"
                }
                for field in bundle["time_rules"]["fields"]
            ],
        },
        "parameter_contract": deepcopy(bundle["parameter_contract"]),
        "query_policy": deepcopy(bundle["query_policy"]),
    }


def test_stdin_policy_binds_only_semantics_to_live_physical_metadata():
    expected = arbitrary_bundle()
    _scopes, _inventory, _datasets, bindings = _physical(expected)

    actual = assemble_authoring_bundle(_policy(expected), bindings)

    assert catalog_hash(actual) == catalog_hash(expected)
    for asset in actual["schema_context"]["assets"]:
        binding = next(item for item in bindings if item.relation.fqn == asset["fqn"])
        assert asset["urn"] == binding.dataset.urn
        assert asset["table_type"] == binding.relation.table_type
        assert [item["native_type"] for item in asset["columns"]] == [
            item.native_type for item in binding.relation.columns
        ]


def test_current_authoring_uses_only_live_datahub_descriptions():
    """재수집된 dataset/field 설명을 stale policy 복사본보다 우선한다."""

    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    _scopes, _inventory, _datasets, bindings = _physical(bundle)
    target = bindings[0]
    live_fields = (
        replace(target.dataset.fields[0], description="Live connector field description."),
        *target.dataset.fields[1:],
    )
    live_target = replace(
        target,
        dataset=replace(
            target.dataset,
            description="Live connector dataset description.",
            fields=live_fields,
        ),
    )
    live_bindings = (live_target, *bindings[1:])

    actual = assemble_authoring_bundle(policy, live_bindings)
    asset = next(
        item
        for item in actual["schema_context"]["assets"]
        if item["fqn"] == live_target.relation.fqn
    )

    assert asset["description"] == "Live connector dataset description."
    assert asset["columns"][0]["description"] == "Live connector field description."
    smuggled = deepcopy(policy)
    smuggled["assets"][0]["description"] = "Stale copied description."
    with pytest.raises(SemanticMetadataError, match="keys differ"):
        assemble_authoring_bundle(smuggled, live_bindings)


def test_compact_decisions_compile_without_copying_live_physical_fields():
    """결정 입력은 578개 물리 필드를 복제하지 않고 live binding으로 policy를 만든다."""

    expected = arbitrary_bundle()
    _scopes, inventory, datasets, _terms = _runtime(expected)
    datasets_by_name = {item.name: item for item in datasets}
    bindings = tuple(
        ReleaseBinding(relation, datasets_by_name[relation.fqn])
        for relation in inventory.relations
    )

    policy = compile_authoring_policy(_decisions(expected), bindings)
    actual = assemble_authoring_bundle(policy, bindings)

    assert [asset["fqn"] for asset in actual["schema_context"]["assets"]] == sorted(
        asset["fqn"] for asset in expected["schema_context"]["assets"]
    )
    assert actual["metric_rules"] == expected["metric_rules"]


def test_policy_roles_accept_only_canonical_roles():
    """발행기는 canonical analyst만 허용하고 임의 Role 문자열을 거부한다."""

    expected = arbitrary_bundle()
    _scopes, inventory, datasets, _terms = _runtime(expected)
    by_name = {item.name: item for item in datasets}
    bindings = tuple(
        ReleaseBinding(relation, by_name[relation.fqn])
        for relation in inventory.relations
    )
    canonical = _decisions(expected)
    assert compile_authoring_policy(canonical, bindings)["assets"][0][
        "entitlements"
    ]["roles"] == ["analyst"]

    invalid = deepcopy(canonical)
    invalid["roles"] = ["unknown-role"]
    with pytest.raises(SemanticMetadataError, match="unsupported role"):
        compile_authoring_policy(invalid, bindings)


def test_v2_decisions_compile_hidden_support_rules_without_publishing_terms():
    """v2 승인 입력은 SUPPORT Rule을 보존하되 Business Term으로 승격하지 않는다."""

    expected = _v2_bundle()
    _scopes, inventory, datasets, _terms = _runtime(expected)
    datasets_by_name = {item.name: item for item in datasets}
    bindings = tuple(
        ReleaseBinding(relation, datasets_by_name[relation.fqn])
        for relation in inventory.relations
    )
    decisions = _decisions(expected)
    decisions["contract_version"] = DECISION_CONTRACT_VERSION_V2

    policy = compile_authoring_policy(decisions, bindings)
    actual = assemble_authoring_bundle(policy, bindings)

    assert policy["contract_version"] == AUTHORING_CONTRACT_VERSION_V4
    assert {item["id"] for item in actual["metric_rules"]} == {
        "amount_total",
        "event_count",
        "account_count",
        "amount_per_event",
    }
    assert {item["id"] for item in actual["metric_terms"]} == {
        "account_count",
        "amount_per_event",
    }


def test_authoring_boundaries_reject_cross_version_metric_contracts():
    """입력 envelope만 v2로 바꿔 governance 필드 누락을 우회할 수 없다."""

    v1 = arbitrary_bundle()
    _scopes, _inventory, _datasets, bindings = _physical(v1)
    v2_policy = _policy(v1)
    v2_policy["contract_version"] = AUTHORING_CONTRACT_VERSION_V2
    with pytest.raises(SemanticMetadataError, match="versions differ"):
        assemble_authoring_bundle(v2_policy, bindings)

    v2 = _v2_bundle()
    _scopes, inventory, datasets, _terms = _runtime(v2)
    by_name = {item.name: item for item in datasets}
    v2_bindings = tuple(
        ReleaseBinding(relation, by_name[relation.fqn])
        for relation in inventory.relations
    )
    with pytest.raises(SemanticMetadataError, match="versions differ"):
        compile_authoring_policy(_decisions(v2), v2_bindings)


def test_compact_decisions_derive_ratio_term_domain_from_live_operands():
    """Derived ratio는 가짜 물리 field 없이 두 column operand의 live domain을 상속한다."""

    expected = arbitrary_ratio_bundle()
    _scopes, inventory, datasets, _terms = _runtime(expected)
    datasets_by_name = {item.name: item for item in datasets}
    bindings = tuple(
        ReleaseBinding(relation, datasets_by_name[relation.fqn])
        for relation in inventory.relations
    )

    policy = compile_authoring_policy(_decisions(expected), bindings)
    actual = assemble_authoring_bundle(policy, bindings)
    ratio = next(item for item in actual["metric_rules"] if item["id"] == "amount_per_event")
    term = next(item for item in actual["metric_terms"] if item["id"] == "amount_per_event")

    assert ratio["source"]["kind"] == "ratio"
    assert term["domain_urn"] == expected["metric_terms"][-1]["domain_urn"]


def test_policy_cannot_smuggle_physical_schema_or_omit_live_assets():
    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    _scopes, _inventory, _datasets, bindings = _physical(bundle)
    policy["assets"][0]["columns"][0]["native_type"] = "invented"
    with pytest.raises(SemanticMetadataError, match="keys differ"):
        assemble_authoring_bundle(policy, bindings)

    policy = _policy(bundle)
    policy["assets"].pop()
    with pytest.raises(SemanticMetadataError, match="exactly cover"):
        assemble_authoring_bundle(policy, bindings)


def test_policy_key_claim_must_match_approved_semantic_grain():
    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    _scopes, _inventory, _datasets, bindings = _physical(bundle)
    policy["assets"][0]["columns"][0]["is_part_of_key"] = False
    with pytest.raises(SemanticMetadataError, match="grain keys differ"):
        assemble_authoring_bundle(policy, bindings)


def test_approved_grain_survives_when_connector_has_no_physical_key():
    """connector가 표현하지 못한 physical key와 승인된 업무 grain을 혼동하지 않는다."""

    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    _scopes, _inventory, _datasets, bindings = _physical(bundle)
    target = bindings[1]
    fields = (
        replace(target.dataset.fields[0], is_part_of_key=False),
        *target.dataset.fields[1:],
    )
    bindings = (
        bindings[0],
        replace(target, dataset=replace(target.dataset, fields=fields)),
    )

    actual = assemble_authoring_bundle(policy, bindings)

    asset = next(
        item
        for item in actual["schema_context"]["assets"]
        if item["fqn"] == target.relation.fqn
    )
    assert asset["columns"][0]["is_part_of_key"] is False
    assert asset["grain"]["keys"] == ["account_id"]

    migrated = migrate_authoring_policy(
        actual,
        catalog_version=actual["catalog_version"],
        policy_version=actual["policy_version"],
        schema_context_version=actual["schema_context"]["version"],
        roles=("analyst",),
    )
    migrated_asset = next(
        item for item in migrated["assets"] if item["fqn"] == target.relation.fqn
    )
    assert migrated_asset["columns"][0]["is_part_of_key"] is True
    assert catalog_hash(assemble_authoring_bundle(migrated, bindings)) == (
        catalog_hash(actual)
    )


def test_checked_synthetic_release_preserves_provenance():
    """검토한 합성 release는 실제 데이터로 위장하지 않고 provenance=true를 보존한다."""

    bundle = arbitrary_bundle()
    for asset in bundle["schema_context"]["assets"]:
        asset["synthetic"] = True
    policy = _policy(bundle)
    _scopes, _inventory, _datasets, bindings = _physical(bundle)

    actual = assemble_authoring_bundle(policy, bindings)

    assert all(asset["synthetic"] is True for asset in actual["schema_context"]["assets"])


def test_async_bootstrap_accepts_ungoverned_base_metadata_without_inference():
    bundle = arbitrary_bundle()
    scopes, inventory, datasets, _bindings = _physical(bundle)

    class TrinoPort:
        async def discover(self, requested):
            assert requested == scopes
            return inventory

    class DataHubPort:
        async def discover_datasets(self, requested):
            assert requested == scopes
            return datasets

    actual = asyncio.run(
        build_authoring_bundle(_policy(bundle), scopes, TrinoPort(), DataHubPort())
    )
    assert catalog_hash(actual) == catalog_hash(bundle)


def test_async_authoring_keeps_explicit_subset_when_base_scope_has_new_asset():
    """수집된 신규 자산은 명시 승인 전 semantic release에 자동 편입되지 않는다."""

    bundle = arbitrary_bundle()
    scopes, inventory, datasets, _bindings = _physical(bundle)
    expanded_inventory, expanded_datasets, candidate_dataset = (
        _with_ungoverned_candidate(
            inventory,
            datasets,
            "unapproved_fact",
        )
    )

    class TrinoPort:
        async def discover(self, requested):
            assert requested == scopes
            return expanded_inventory

    class DataHubPort:
        async def discover_datasets(self, requested):
            assert requested == scopes
            return expanded_datasets

    candidate = asyncio.run(
        build_authoring_candidate(
            _policy(bundle),
            scopes,
            TrinoPort(),
            DataHubPort(),
        )
    )

    assert candidate.previous_catalog_sha256 == CLEAN_CATALOG_SHA256
    assert catalog_hash(candidate.bundle) == catalog_hash(bundle)
    assert candidate_dataset.name not in {
        asset["fqn"] for asset in candidate.bundle["schema_context"]["assets"]
    }


def test_async_authoring_cannot_omit_active_governed_asset():
    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    omitted_fqn = policy["assets"].pop()["fqn"]
    scopes, inventory, datasets, _terms = _runtime(bundle)

    class TrinoPort:
        async def discover(self, requested):
            assert requested == scopes
            return inventory

    class DataHubPort:
        async def discover_datasets(self, requested):
            assert requested == scopes
            return datasets

    with pytest.raises(
        SemanticMetadataError,
        match="cannot omit active governed assets",
    ):
        asyncio.run(
            build_authoring_candidate(
                policy,
                scopes,
                TrinoPort(),
                DataHubPort(),
            )
        )

    assert omitted_fqn not in {asset["fqn"] for asset in policy["assets"]}


def test_authoring_predecessor_ignores_dataset_outside_the_approved_scope():
    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    scopes, inventory, datasets, _terms = _runtime(bundle)
    outside = replace(
        datasets[0],
        urn=datasets[0].urn.replace("ember.core.accounts", "ember.system.metadata"),
        dataset_key_name=datasets[0].dataset_key_name.replace(
            "ember.core.accounts", "ember.system.metadata"
        ),
        name="ember.system.metadata",
        qualified_name="ember.system.metadata",
        schema_name="ember.system.metadata",
        custom_properties={},
    )

    class TrinoPort:
        async def discover(self, requested):
            assert requested == scopes
            return inventory

    class DataHubPort:
        async def discover_datasets(self, requested):
            assert requested == scopes
            return (*datasets, outside)

    candidate = asyncio.run(
        build_authoring_candidate(policy, scopes, TrinoPort(), DataHubPort())
    )

    assert candidate.previous_catalog_sha256 == catalog_hash(bundle)
    assert catalog_hash(candidate.bundle) == catalog_hash(bundle)


def test_predecessor_allows_only_manifest_complete_scope_expansion():
    """기존 release가 완전할 때만 base-ingested 신규 자산을 scope에 추가할 수 있다."""
    bundle = arbitrary_bundle()
    _scopes, _inventory, governed, _terms = _runtime(bundle)
    new_base_asset = replace(
        governed[0],
        urn=governed[0].urn.replace("ember.core.accounts", "ember.core.new_fact"),
        dataset_key_name=governed[0].dataset_key_name.replace(
            "ember.core.accounts", "ember.core.new_fact"
        ),
        name="ember.core.new_fact",
        qualified_name="ember.core.new_fact",
        schema_name="ember.core.new_fact",
        custom_properties={},
    )

    assert _previous_catalog_sha256((*governed, new_base_asset)) == catalog_hash(bundle)

    with pytest.raises(SemanticMetadataError, match="partial or conflicting"):
        _previous_catalog_sha256((governed[0], new_base_asset))


def test_catalog_snapshot_migration_preserves_meaning_but_rediscovers_physical_values():
    source = arbitrary_bundle()
    _scopes, _inventory, datasets, terms = _runtime(source)
    snapshot = assemble_catalog_snapshot_bundle(datasets, terms)
    policy = migrate_authoring_policy(
        snapshot,
        catalog_version="sample-catalog-iceberg.1",
        policy_version="sample-policy-analyst.1",
        schema_context_version="sample-schema-iceberg.1",
        roles=("analyst",),
    )
    _physical_scopes, _physical_inventory, _base, bindings = _physical(source)

    target = assemble_authoring_bundle(policy, bindings)

    assert target["catalog_version"] == "sample-catalog-iceberg.1"
    assert target["policy_version"] == "sample-policy-analyst.1"
    assert target["schema_context"]["version"] == "sample-schema-iceberg.1"
    assert all(
        asset["entitlements"]["roles"] == ["analyst"]
        for asset in target["schema_context"]["assets"]
    )
    assert {
        item["id"]: item for item in policy["metric_rules"]
    } == {
        item["id"]: item for item in source["metric_rules"]
    }
    assert policy["query_policy"] == source["query_policy"]
    assert "native_type" not in policy["assets"][0]["columns"][0]
    assert "nullable" not in policy["assets"][0]["columns"][0]
    assert "ordinal_position" not in policy["assets"][0]["columns"][0]


def test_catalog_snapshot_migration_rejects_unregistered_target_role():
    source = arbitrary_bundle()
    _scopes, _inventory, datasets, terms = _runtime(source)
    snapshot = assemble_catalog_snapshot_bundle(datasets, terms)

    with pytest.raises(SemanticMetadataError, match="roles are unsupported"):
        migrate_authoring_policy(
            snapshot,
            catalog_version="sample-catalog.2",
            policy_version="sample-policy.2",
            schema_context_version="sample-schema.2",
            roles=("unregistered_role",),
        )


def test_catalog_snapshot_rebases_signed_unregistered_source_role_without_aliasing():
    source = arbitrary_bundle()
    for asset in source["schema_context"]["assets"]:
        asset["entitlements"]["roles"] = ["retired_source_role", "analyst"]
    _scopes, _inventory, datasets, terms = _runtime(source)

    rebased = rebase_catalog_snapshot_entitlements(
        datasets,
        terms,
        ("analyst",),
    )

    assert all(
        asset["entitlements"]["roles"] == ["analyst"]
        for asset in rebased["schema_context"]["assets"]
    )


def test_check_mode_is_read_only_and_returns_publish_binding_hashes():
    expected = arbitrary_bundle()
    policy = _policy(expected)
    scopes, inventory, datasets, _bindings = _physical(expected)

    class TrinoPort:
        async def discover(self, _scopes):
            return inventory

    class DataHubPort:
        async def discover_datasets(self, _scopes):
            return datasets

    async def forbidden_publisher(_bundle):
        raise AssertionError("check mode must not publish")

    result = asyncio.run(
        apply_authoring_release(
            policy,
            scopes,
            TrinoPort(),
            DataHubPort(),
            forbidden_publisher,
            actor="urn:li:corpuser:reviewer",
            verify_timeout=1,
            check_only=True,
        )
    )

    assert result["status"] == "CHECKED"
    assert result["publication_check"]["catalog_sha256"] == catalog_hash(expected)
    assert result["publication_check"]["previous_catalog_sha256"] == (
        CLEAN_CATALOG_SHA256
    )


def test_publication_check_binds_policy_physical_scope_catalog_and_actor():
    expected = arbitrary_bundle()
    policy = _policy(expected)
    _scopes, _inventory, _datasets, bindings = _physical(expected)
    bundle = assemble_authoring_bundle(policy, bindings)
    check = publication_check(
        policy,
        bundle,
        actor="urn:li:corpuser:reviewer",
        previous_catalog_sha256=CLEAN_CATALOG_SHA256,
    )
    verify_expected_release(
        check,
        expected_catalog_sha256=check["catalog_sha256"],
        expected_previous_catalog_sha256=check["previous_catalog_sha256"],
    )
    assert physical_scope_sha256(bundle) == check["physical_scope_sha256"]
    assert check["native_semantic_projection_sha256"] == (
        native_semantic_shadow_projection(bundle)["projection_sha256"]
    )

    changed_policy = deepcopy(policy)
    changed_policy["policy_version"] = "unapproved-change"
    changed_check = publication_check(
        changed_policy,
        bundle,
        actor="urn:li:corpuser:reviewer",
        previous_catalog_sha256=CLEAN_CATALOG_SHA256,
    )
    assert changed_check["policy_sha256"] != check["policy_sha256"]
    changed_physical = deepcopy(bundle)
    changed_physical["schema_context"]["assets"][0]["columns"][0]["native_type"] = "double"
    assert physical_scope_sha256(changed_physical) != check["physical_scope_sha256"]
    with pytest.raises(SemanticMetadataError, match="target catalog differs"):
        verify_expected_release(
            check,
            expected_catalog_sha256="1" * 64,
            expected_previous_catalog_sha256=check["previous_catalog_sha256"],
        )


def test_operational_publisher_writes_and_reads_both_semantic_surfaces(monkeypatch):
    bundle = arbitrary_bundle()
    projection_sha256 = native_semantic_shadow_projection(bundle)[
        "projection_sha256"
    ]
    calls = []

    async def legacy_publish(*_args, **_options):
        calls.append("legacy")
        return {"status": "PUBLISHED"}

    class NativeClient:
        def __init__(self, *_args, **_options):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def native_publish(_client, _value, **options):
        assert options["expected_projection_sha256"] == projection_sha256
        calls.append("native_publish")
        return {"published_entity_count": 17}

    async def native_verify(_client, _value, **options):
        assert options["expected_projection_sha256"] == projection_sha256
        calls.append("native_verify")
        return {
            "readback_projection_sha256": projection_sha256,
            "rest_aspect_equality": "100%",
        }

    monkeypatch.setattr(author_catalog, "publish_bundle", legacy_publish)
    monkeypatch.setattr(author_catalog, "DataHubMetadataAdminClient", NativeClient)
    monkeypatch.setattr(
        author_catalog,
        "publish_native_semantic_shadow",
        native_publish,
    )
    monkeypatch.setattr(
        author_catalog,
        "verify_native_semantic_shadow",
        native_verify,
    )

    class Settings:
        base_url = "https://127.0.0.1:28081"
        token = "publish-token"
        ca_file = Path("unused-test-ca.pem")

    result = asyncio.run(
        author_catalog._publish_datahub_release(
            bundle,
            Settings(),
            actor_urn="urn:li:corpuser:service_publisher",
            timeout=1,
        )
    )

    assert calls == ["legacy", "native_publish", "native_verify"]
    assert result["native_semantic_projection_sha256"] == projection_sha256
    assert result["native_semantic_readback_sha256"] == projection_sha256
    assert result["native_semantic_published_entity_count"] == 17


def test_checked_orchestration_retries_transient_readback_and_requires_convergence():
    expected = arbitrary_bundle()
    policy = _policy(expected)
    scopes, inventory, base_datasets, bindings = _physical(expected)
    _unused, _unused_inventory, governed_datasets, governed_terms = _runtime(expected)
    inventory, base_datasets, candidate_dataset = _with_ungoverned_candidate(
        inventory,
        base_datasets,
        "unapproved_during_readback",
    )
    bundle = assemble_authoring_bundle(policy, bindings)
    check = publication_check(
        policy,
        bundle,
        actor="urn:li:corpuser:reviewer",
        previous_catalog_sha256=CLEAN_CATALOG_SHA256,
    )

    class TrinoPort:
        async def discover(self, _scopes):
            return inventory

    class DataHubPort:
        published = False
        transient = True

        async def discover_datasets(self, _scopes):
            if self.published and self.transient:
                self.transient = False
                raise DataHubDiscoveryError("transient readback")
            return (
                (*governed_datasets, candidate_dataset)
                if self.published
                else base_datasets
            )

        async def discover_terms(self, urns):
            by_urn = {item.urn: item for item in governed_terms}
            return tuple(by_urn[urn] for urn in urns)

    datahub = DataHubPort()

    async def publisher(value):
        assert catalog_hash(value) == catalog_hash(expected)
        datahub.published = True
        return {"status": "PUBLISHED", "dataset_count": len(governed_datasets)}

    result = asyncio.run(
        apply_authoring_release(
            policy,
            scopes,
            TrinoPort(),
            datahub,
            publisher,
            actor="urn:li:corpuser:reviewer",
            verify_timeout=1,
            expected_catalog_sha256=check["catalog_sha256"],
            expected_previous_catalog_sha256=check["previous_catalog_sha256"],
        )
    )
    assert result["status"] == "PUBLISHED_AND_VERIFIED"
    assert datahub.transient is False


def test_publication_error_or_nonconvergence_never_reports_success():
    expected = arbitrary_bundle()
    policy = _policy(expected)
    scopes, inventory, base_datasets, bindings = _physical(expected)
    bundle = assemble_authoring_bundle(policy, bindings)
    check = publication_check(
        policy,
        bundle,
        actor="urn:li:corpuser:reviewer",
        previous_catalog_sha256=CLEAN_CATALOG_SHA256,
    )

    class TrinoPort:
        async def discover(self, _scopes):
            return inventory

    class DataHubPort:
        async def discover_datasets(self, _scopes):
            return base_datasets

        async def discover_terms(self, _urns):
            return ()

    async def partial_failure(_bundle):
        raise RuntimeError("partial publication")

    with pytest.raises(RuntimeError, match="partial publication"):
        asyncio.run(
            apply_authoring_release(
                policy,
                scopes,
                TrinoPort(),
                DataHubPort(),
                partial_failure,
                actor="urn:li:corpuser:reviewer",
                verify_timeout=0.01,
                expected_catalog_sha256=check["catalog_sha256"],
                expected_previous_catalog_sha256=check["previous_catalog_sha256"],
            )
        )

    async def no_op_publish(_bundle):
        return {"status": "PUBLISHED"}

    with pytest.raises(PublicationReadbackError):
        asyncio.run(
            apply_authoring_release(
                policy,
                scopes,
                TrinoPort(),
                DataHubPort(),
                no_op_publish,
                actor="urn:li:corpuser:reviewer",
                verify_timeout=0.01,
                expected_catalog_sha256=check["catalog_sha256"],
                expected_previous_catalog_sha256=check["previous_catalog_sha256"],
            )
        )


def test_previous_catalog_hash_blocks_stale_check_and_rollback():
    current = arbitrary_bundle()
    policy = _policy(current)
    scopes, inventory, governed_datasets, governed_terms = _runtime(current)
    _base_scopes, _base_inventory, _base_datasets, bindings = _physical(current)
    target = assemble_authoring_bundle(policy, bindings)
    stale_check = publication_check(
        policy,
        target,
        actor="urn:li:corpuser:reviewer",
        previous_catalog_sha256=CLEAN_CATALOG_SHA256,
    )

    class TrinoPort:
        async def discover(self, _scopes):
            return inventory

    class DataHubPort:
        async def discover_datasets(self, _scopes):
            return governed_datasets

        async def discover_terms(self, urns):
            by_urn = {item.urn: item for item in governed_terms}
            return tuple(by_urn[urn] for urn in urns)

    candidate = asyncio.run(
        build_authoring_candidate(policy, scopes, TrinoPort(), DataHubPort())
    )
    assert candidate.previous_catalog_sha256 == catalog_hash(current)

    published = False

    async def publisher(_bundle):
        nonlocal published
        published = True
        return {"status": "PUBLISHED"}

    with pytest.raises(SemanticMetadataError, match="live predecessor differs"):
        asyncio.run(
            apply_authoring_release(
                policy,
                scopes,
                TrinoPort(),
                DataHubPort(),
                publisher,
                actor="urn:li:corpuser:reviewer",
                verify_timeout=0.1,
                expected_catalog_sha256=stale_check["catalog_sha256"],
                expected_previous_catalog_sha256=(
                    stale_check["previous_catalog_sha256"]
                ),
            )
        )
    assert published is False
