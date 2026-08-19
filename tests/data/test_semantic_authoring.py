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
from policy_compiler import (  # noqa: E402
    DECISION_CONTRACT_VERSION,
    compile_authoring_policy,
)
from author_semantic_catalog import (  # noqa: E402
    PublicationReadbackError,
    apply_authoring_release,
)
from release_bundle import ReleaseBinding  # noqa: E402
from release_datahub import DataHubDiscoveryError  # noqa: E402
from publication_check import (  # noqa: E402
    physical_scope_sha256,
    publication_check,
    verify_expected_release,
)
from semantic_authoring import (  # noqa: E402
    AUTHORING_CONTRACT_VERSION,
    CLEAN_CATALOG_SHA256,
    assemble_authoring_bundle,
    build_authoring_candidate,
    build_authoring_bundle,
)
from src.data.governance_contract import catalog_hash  # noqa: E402
from test_datahub_metadata_publication import (  # noqa: E402
    arbitrary_bundle,
    arbitrary_ratio_bundle,
)
from test_release_bundle_builder import _runtime  # noqa: E402


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
                "description": asset["description"],
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
                        "description": column["description"],
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


def test_policy_key_claim_must_match_live_datahub_key_metadata():
    bundle = arbitrary_bundle()
    policy = _policy(bundle)
    _scopes, _inventory, _datasets, bindings = _physical(bundle)
    policy["assets"][0]["columns"][0]["is_part_of_key"] = False
    with pytest.raises(SemanticMetadataError, match="column identity"):
        assemble_authoring_bundle(policy, bindings)


def test_checked_policy_may_promote_a_key_missing_from_view_ingestion():
    """view ingestion이 표현하지 못한 grain key는 검토한 policy가 선언해 발행한다."""

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

    promoted = actual["schema_context"]["assets"][1]["columns"][0]
    assert promoted["is_part_of_key"] is True


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


def test_checked_orchestration_retries_transient_readback_and_requires_convergence():
    expected = arbitrary_bundle()
    policy = _policy(expected)
    scopes, inventory, base_datasets, bindings = _physical(expected)
    _unused, _unused_inventory, governed_datasets, governed_terms = _runtime(expected)
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
            return governed_datasets if self.published else base_datasets

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
