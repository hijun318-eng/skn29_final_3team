"""DataHub live snapshot을 승인 release manifest의 membership·count·checksum과 대조하는 검증 모듈이다.

권위 있는 입력은 dataset custom property로 발행된 release manifest와 같은 시점에 읽은
``CatalogSnapshot``이다. 이 모듈은 DataHub·Trino I/O를 수행하지 않고 이미 읽어온 값만 비교하며,
불일치는 모두 ``GovernedMetadataError``로 닫아 부분 catalog가 성공으로 통과하지 못하게 한다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.adapters.datahub_metadata import GlossaryMetricTerm, GovernedDataset
from app.adapters.datahub_metadata_values import GovernedMetadataError
from app.adapters.datahub_metadata_types import metric_rule_matches
from src.data.governance_contract import (
    MANIFEST_DATASET_KEYS,
    MANIFEST_KEYS,
    MANIFEST_TERM_KEYS,
    asset_semantic_hash,
    catalog_hash,
    canonical_json,
    canonical_sha256,
    glossary_hash,
    metric_source_kind,
    ratio_operand_ids,
    RATIO_ZERO_POLICIES,
    shared_semantic_hash,
)

if TYPE_CHECKING:  # 순환 import를 만들지 않도록 snapshot 타입은 검사 시점에만 참조한다.
    from app.adapters.catalog_snapshot import CatalogSnapshot


def coherent_release_datasets(
    snapshot: CatalogSnapshot,
    expected_release: str | None,
) -> tuple[GovernedDataset, ...]:
    """구성된 release 선택값과 catalog/policy checksum이 하나로 수렴한 dataset 집합을 반환한다."""

    datasets = tuple(snapshot.datasets_by_fqn.values())
    if expected_release is not None:
        datasets = tuple(
            item for item in datasets if item.context_release == expected_release
        )
        if not datasets:
            raise GovernedMetadataError(
                "DataHub does not contain the configured context release"
            )
    releases = {item.context_release for item in datasets}
    checksums = {item.catalog_checksum for item in datasets}
    policies = {item.policy_version for item in datasets}
    if len(releases) != 1 or len(checksums) != 1 or len(policies) != 1:
        raise GovernedMetadataError(
            "DataHub runtime catalog does not resolve one coherent active release"
        )
    return tuple(sorted(datasets, key=lambda item: item.fqn))


def validate_release_manifest(
    snapshot: CatalogSnapshot,
    datasets: tuple[GovernedDataset, ...],
) -> None:
    """선택 dataset의 단일 manifest를 전체 snapshot membership·count·semantic checksum과 대조하고 불일치를 거부한다."""
    if not datasets:
        raise GovernedMetadataError("DataHub release has no governed datasets")
    # 각 엔터티의 부분 checksum만 믿지 않고 전체 membership을 재계산해야 누락된 DataHub 페이지도 검출된다.
    manifests = {canonical_json(item.release_manifest) for item in datasets}
    if len(manifests) != 1:
        raise GovernedMetadataError("DataHub datasets disagree on the release manifest")
    manifest = json.loads(next(iter(manifests)))
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise GovernedMetadataError("DataHub release manifest fields are invalid")
    manifest_hash = canonical_sha256(manifest)
    if (
        {item.manifest_checksum for item in datasets} != {manifest_hash}
        or {item.context_release for item in datasets} != {manifest["catalog_version"]}
        or {item.catalog_checksum for item in datasets} != {manifest["catalog_sha256"]}
    ):
        raise GovernedMetadataError("DataHub release manifest identity is inconsistent")
    manifest_datasets = manifest["datasets"]
    manifest_terms = manifest["metric_terms"]
    if not isinstance(manifest_datasets, list) or not isinstance(manifest_terms, list):
        raise GovernedMetadataError("DataHub release manifest membership is invalid")
    expected_datasets = {}
    for item in manifest_datasets:
        if not isinstance(item, dict) or set(item) != MANIFEST_DATASET_KEYS:
            raise GovernedMetadataError("DataHub manifest dataset entry is invalid")
        urn = str(item["urn"])
        if urn in expected_datasets:
            raise GovernedMetadataError("DataHub manifest dataset URNs are duplicate")
        expected_datasets[urn] = item
    same_catalog = {
        urn: item
        for urn, item in snapshot.datasets_by_urn.items()
        if item.catalog_checksum == manifest["catalog_sha256"]
    }
    if set(same_catalog) != set(expected_datasets):
        raise GovernedMetadataError("DataHub release dataset membership is incomplete")
    for urn, dataset in same_catalog.items():
        expected = expected_datasets[urn]
        if (
            expected["fqn"] != dataset.fqn
            or expected["schema_sha1"] != dataset.schema_hash
            or expected["table_type"] != dataset.table_type
            or expected["trino_schema_sha256"] != dataset.trino_schema_checksum
            or expected["column_count"] != len(dataset.columns)
        ):
            raise GovernedMetadataError("DataHub release dataset fingerprint differs")
    expected_terms = {}
    for item in manifest_terms:
        if not isinstance(item, dict) or set(item) != MANIFEST_TERM_KEYS:
            raise GovernedMetadataError("DataHub manifest metric term entry is invalid")
        urn = str(item["urn"])
        if urn in expected_terms:
            raise GovernedMetadataError("DataHub manifest metric term URNs are duplicate")
        expected_terms[urn] = item
    same_catalog_terms = {
        urn: item
        for urn, item in snapshot.terms_by_urn.items()
        if item.catalog_checksum == manifest["catalog_sha256"]
    }
    if set(same_catalog_terms) != set(expected_terms) or any(
        term.id != expected_terms[urn]["id"]
        for urn, term in same_catalog_terms.items()
    ):
        raise GovernedMetadataError("DataHub release glossary membership is incomplete")
    bundle = _catalog_bundle(
        same_catalog, same_catalog_terms, snapshot.governance_entities
    )
    glossary_digest = glossary_hash(bundle)
    if (
        {item.checksum for item in same_catalog_terms.values()} != {glossary_digest}
        or manifest["glossary_sha256"] != glossary_digest
        or manifest["shared_semantic_sha256"] != shared_semantic_hash(bundle)
        or manifest["catalog_sha256"] != catalog_hash(bundle)
        or manifest["dataset_count"] != len(same_catalog)
        or manifest["metric_term_count"] != len(same_catalog_terms)
        or manifest["column_count"] != sum(len(item.columns) for item in same_catalog.values())
    ):
        raise GovernedMetadataError("DataHub release manifest counts or hashes differ")
    for urn, dataset in same_catalog.items():
        expected = expected_datasets[urn]["semantic_sha256"]
        actual = asset_semantic_hash(bundle, dataset.catalog_asset)
        if dataset.semantic_checksum != expected or expected != actual:
            raise GovernedMetadataError("DataHub dataset semantic checksum differs")
    for urn, term in same_catalog_terms.items():
        expected = expected_terms[urn]["semantic_sha256"]
        if expected != canonical_sha256(_term_projection(term)):
            raise GovernedMetadataError("DataHub metric term semantic checksum differs")


def _catalog_bundle(datasets, terms, governance_entities):
    ordered_datasets = sorted(datasets.values(), key=lambda value: value.urn)
    ordered_terms = sorted(terms.values(), key=lambda value: value.urn)
    representative = ordered_datasets[0]
    shared_attributes = (
        "context_release", "policy_version", "schema_context_version",
        "governance_urns", "dimensions", "join_graph", "time_rules",
        "parameter_contract", "query_policy",
    )
    for name in shared_attributes:
        if len({canonical_json(getattr(item, name)) for item in ordered_datasets}) != 1:
            raise GovernedMetadataError(
                f"DataHub release datasets disagree on {name}"
            )
    runtime_metrics = [
        (dataset, metric)
        for dataset in ordered_datasets
        for metric in dataset.metrics
    ]
    column_terms = [
        term for term in ordered_terms if metric_source_kind(term.metric_rule) == "column"
    ]
    ratio_terms = [
        term for term in ordered_terms if metric_source_kind(term.metric_rule) == "ratio"
    ]
    if (
        len(runtime_metrics) != len(column_terms)
        or len(column_terms) + len(ratio_terms) != len(ordered_terms)
    ):
        raise GovernedMetadataError(
            "DataHub runtime metrics differ from the release glossary"
        )
    for term in column_terms:
        matches = [
            (dataset, metric)
            for dataset, metric in runtime_metrics
            if metric["id"] == term.id
            and term.domain_urn == dataset.domain_urn
            and metric_rule_matches(dataset, metric, term)
        ]
        if len(matches) != 1:
            raise GovernedMetadataError(
                "DataHub runtime metric and glossary rule differ"
            )
    column_term_ids = {term.id for term in column_terms}
    dataset_by_metric_id = {
        str(metric["id"]): dataset for dataset, metric in runtime_metrics
    }
    for term in ratio_terms:
        operands = ratio_operand_ids(term.metric_rule)
        source = term.metric_rule.get("source")
        numerator_id, denominator_id = operands or (None, None)
        numerator_dataset = dataset_by_metric_id.get(str(numerator_id))
        denominator_dataset = dataset_by_metric_id.get(str(denominator_id))
        if (
            operands is None
            or numerator_id not in column_term_ids
            or denominator_id not in column_term_ids
            or numerator_dataset is None
            or denominator_dataset is None
            or numerator_dataset.domain_urn != denominator_dataset.domain_urn
            or term.domain_urn != numerator_dataset.domain_urn
            or not isinstance(source, dict)
            or source.get("zero_policy") not in RATIO_ZERO_POLICIES
            or term.urn not in numerator_dataset.dataset_terms
            or term.urn not in denominator_dataset.dataset_terms
        ):
            raise GovernedMetadataError(
                "DataHub ratio metric glossary term references an ungoverned numerator or denominator"
            )
    governance_urns = representative.governance_urns
    actual_governance_urns = {
        name: {item["urn"] for item in values}
        for name, values in governance_entities.items()
    }
    if actual_governance_urns != {
        name: set(values) for name, values in governance_urns.items()
    }:
        raise GovernedMetadataError(
            "DataHub native governance details differ from the release URNs"
        )
    for term in ordered_terms:
        if (
            not term.owner_urns.issubset(governance_urns["owners"])
            or term.domain_urn not in governance_urns["domains"]
            or term.lifecycle_urn not in governance_urns["approved_lifecycles"]
        ):
            raise GovernedMetadataError(
                "DataHub glossary governance is outside the release"
            )
    return {
        "catalog_version": representative.context_release,
        "policy_version": representative.policy_version,
        "governance_entities": {
            name: [dict(item) for item in values]
            for name, values in governance_entities.items()
        },
        "schema_context": {
            "version": representative.schema_context_version,
            "assets": [item.catalog_asset for item in ordered_datasets],
        },
        "metric_rules": [item.metric_rule for item in ordered_terms],
        "metric_terms": [_term_projection(item) for item in ordered_terms],
        "dimensions": list(representative.dimensions),
        "join_graph": representative.join_graph,
        "time_rules": representative.time_rules,
        "parameter_contract": representative.parameter_contract,
        "query_policy": representative.query_policy,
    }


def _term_projection(value: GlossaryMetricTerm) -> dict[str, object]:
    if len(value.owner_urns) != 1:
        raise GovernedMetadataError("DataHub metric term must have one native owner")
    return {
        "id": value.id,
        "urn": value.urn,
        "name": value.label,
        "definition": value.definition,
        "aliases": list(value.aliases),
        "unit": value.unit,
        "version": value.version,
        "approval_status": "APPROVED",
        "owner_urn": next(iter(value.owner_urns)),
        "domain_urn": value.domain_urn,
        "approved_lifecycle_urn": value.lifecycle_urn,
    }
