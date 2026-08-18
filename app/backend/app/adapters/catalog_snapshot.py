"""페이지 단위 DataHub readback을 하나의 checksum 검증된 runtime catalog snapshot으로 조립한다."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic

from app.adapters.datahub_catalog import DataHubCatalogClient
from app.adapters.datahub_metadata import (
    GlossaryMetricTerm,
    GovernedDataset,
    parse_dataset,
    parse_glossary_term,
)
from app.adapters.datahub_metadata_values import (
    GovernedMetadataError,
    dataset_has_runtime_governance,
    required_text,
    term_has_runtime_governance,
)
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
    shared_semantic_hash,
)


@dataclass(frozen=True)
class CatalogSnapshot:
    """같은 시점에 검증한 dataset·metric term·native governance index를 하나의 불변 조회 단위로 묶는다."""
    datasets_by_urn: dict[str, GovernedDataset]
    datasets_by_fqn: dict[str, GovernedDataset]
    terms_by_urn: dict[str, GlossaryMetricTerm]
    terms_by_id: dict[str, GlossaryMetricTerm]
    governance_entities: dict[str, tuple[dict[str, str], ...]]


class CatalogSnapshotLoader:
    """동시 DataHub readback을 single-flight로 합치고 짧은 TTL 동안만 완전 검증된 snapshot을 재사용한다."""
    def __init__(
        self,
        client: DataHubCatalogClient,
        *,
        max_concurrency: int = 8,
        ttl_seconds: float = 5.0,
    ) -> None:
        if max_concurrency < 1 or ttl_seconds <= 0:
            raise ValueError("DataHub metadata concurrency and TTL must be positive")
        self._client = client
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._snapshot: CatalogSnapshot | None = None
        self._expires_at = 0.0
        self._inflight: asyncio.Task[CatalogSnapshot] | None = None

    async def load(self) -> CatalogSnapshot:
        """TTL 안의 snapshot만 반환하며 만료 후 재조회 실패를 stale 성공으로 대체하지 않고 typed 오류를 전파한다."""
        now = monotonic()
        if self._snapshot is not None and now < self._expires_at:
            return self._snapshot
        async with self._lock:
            now = monotonic()
            if self._snapshot is not None and now < self._expires_at:
                return self._snapshot
            # 같은 expiry에 몰린 요청은 하나의 readback을 공유해야 서로 다른 catalog 시점을 섞지 않는다.
            if self._inflight is None:
                self._inflight = asyncio.create_task(self._load_uncached())
            task = self._inflight
        try:
            snapshot = await asyncio.shield(task)
        except Exception:
            async with self._lock:
                if self._inflight is task:
                    self._inflight = None
            raise
        async with self._lock:
            if self._inflight is task:
                self._snapshot = snapshot
                self._expires_at = monotonic() + self._ttl_seconds
                self._inflight = None
        return snapshot

    async def _load_uncached(self) -> CatalogSnapshot:
        dataset_hits, term_hits = await asyncio.gather(
            self._client.list_datasets(),
            self._client.list_glossary_terms(),
        )
        raw_datasets, raw_terms, raw_lifecycles = await asyncio.gather(
            self._fetch_all(
                tuple(hit.urn for hit in dataset_hits),
                self._client.get_dataset,
            ),
            self._fetch_all(
                tuple(hit.urn for hit in term_hits),
                self._client.get_glossary_term,
            ),
            self._client.list_lifecycle_stages(),
        )
        governed_raw_terms = tuple(
            term for term in raw_terms if term_has_runtime_governance(term)
        )
        raw_term_statuses = await self._fetch_all(
            tuple(term["urn"] for term in governed_raw_terms),
            self._client.get_entity_status,
        )
        raw_terms = tuple(
            _term_with_rest_status(term, status, raw_lifecycles)
            for term, status in zip(governed_raw_terms, raw_term_statuses)
        )
        datasets = tuple(
            parse_dataset(item)
            for item in raw_datasets
            if dataset_has_runtime_governance(item)
        )
        active_checksums = {dataset.catalog_checksum for dataset in datasets}
        parsed_terms = tuple(parse_glossary_term(item) for item in raw_terms)
        terms = tuple(
            term
            for term in parsed_terms
            if not active_checksums or term.catalog_checksum in active_checksums
        )
        if not datasets:
            raise GovernedMetadataError(
                "DataHub has no approved runtime-governed datasets"
            )
        declared = _declared_governance(datasets, terms)
        raw_owners, raw_domains = await asyncio.gather(
            self._fetch_all(
                tuple(sorted(declared["owners"])), self._client.get_corp_group
            ),
            self._fetch_all(
                tuple(sorted(declared["domains"])), self._client.get_domain
            ),
        )
        governance_entities = _governance_entities(
            declared, raw_owners, raw_domains, raw_lifecycles
        )
        return CatalogSnapshot(
            datasets_by_urn=_unique_index(datasets, "urn", "dataset URN"),
            datasets_by_fqn=_unique_index(datasets, "fqn", "dataset FQN"),
            terms_by_urn=_unique_index(terms, "urn", "glossary term URN"),
            terms_by_id=_unique_index(terms, "id", "metric id"),
            governance_entities=governance_entities,
        )

    async def _fetch_all(self, urns, fetch):
        async def one(urn: str):
            async with self._semaphore:
                value = await fetch(urn)
            if value.get("urn") != urn:
                raise GovernedMetadataError(
                    "DataHub entity response does not match its search URN"
                )
            return value

        return tuple(await asyncio.gather(*(one(urn) for urn in urns)))


def _term_with_rest_status(term, status_record, lifecycle_stages):
    """Rest.li status URN을 live lifecycle 정의와 결합해 term parser 입력을 만든다."""

    if not isinstance(term, dict) or not isinstance(status_record, dict):
        raise GovernedMetadataError("DataHub glossary term status is invalid")
    status = status_record.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("removed"), bool):
        raise GovernedMetadataError("DataHub glossary term status is incomplete")
    lifecycle_urn = status.get("lifecycleStage")
    stages = {
        item.get("urn"): item
        for item in lifecycle_stages
        if isinstance(item, dict) and isinstance(item.get("urn"), str)
    }
    if len(stages) != len(lifecycle_stages) or lifecycle_urn not in stages:
        raise GovernedMetadataError("DataHub glossary lifecycle definition is unavailable")
    normalized = {
        "removed": status["removed"],
        "lifecycleStage": dict(stages[lifecycle_urn]),
    }
    graph_status = term.get("status")
    if graph_status is not None and graph_status != normalized:
        raise GovernedMetadataError("DataHub glossary status read APIs disagree")
    result = dict(term)
    result["status"] = normalized
    return result


def validate_release_manifest(
    snapshot: CatalogSnapshot,
    datasets: tuple[GovernedDataset, ...],
) -> None:
    """선택 dataset의 단일 manifest를 전체 snapshot membership·count·semantic checksum과 대조하고 불일치를 거부한다."""
    if not datasets:
        raise GovernedMetadataError("DataHub release has no governed datasets")
    # 각 엔터티의 부분 checksum만 믿지 않고 전체 membership을 재계산해야 누락된 DataHub 페이지도 검출된다.
    manifests = {_canonical(item.release_manifest) for item in datasets}
    if len(manifests) != 1:
        raise GovernedMetadataError("DataHub datasets disagree on the release manifest")
    manifest = json.loads(next(iter(manifests)))
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise GovernedMetadataError("DataHub release manifest fields are invalid")
    manifest_hash = _sha256(manifest)
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
        if expected != _sha256(_term_projection(term)):
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
        if len({_canonical(getattr(item, name)) for item in ordered_datasets}) != 1:
            raise GovernedMetadataError(
                f"DataHub release datasets disagree on {name}"
            )
    runtime_metrics = [
        (dataset, metric)
        for dataset in ordered_datasets
        for metric in dataset.metrics
    ]
    if len(runtime_metrics) != len(ordered_terms):
        raise GovernedMetadataError(
            "DataHub runtime metrics differ from the release glossary"
        )
    for term in ordered_terms:
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


def _unique_index(values, attribute: str, label: str):
    result = {}
    for value in values:
        key = getattr(value, attribute)
        if key in result:
            raise GovernedMetadataError(f"DataHub {label} is duplicate")
        result[key] = value
    return result


def _declared_governance(datasets, terms) -> dict[str, set[str]]:
    result = {
        "owners": set(),
        "domains": set(),
        "approved_lifecycles": set(),
    }
    for dataset in datasets:
        for name in result:
            result[name].update(dataset.governance_urns[name])
    for term in terms:
        result["owners"].update(term.owner_urns)
        result["domains"].add(term.domain_urn)
        result["approved_lifecycles"].add(term.lifecycle_urn)
    if any(not values for values in result.values()):
        raise GovernedMetadataError("DataHub governance declarations are incomplete")
    return result


def _governance_entities(
    declared,
    owners,
    domains,
    lifecycle_stages,
) -> dict[str, tuple[dict[str, str], ...]]:
    owner_values = []
    for value in owners:
        properties = value.get("properties") if isinstance(value, dict) else None
        if not isinstance(properties, dict):
            raise GovernedMetadataError("DataHub CorpGroup properties are missing")
        owner_values.append(
            {
                "urn": required_text(value.get("urn"), "CorpGroup URN"),
                "name": required_text(
                    properties.get("displayName"), "CorpGroup display name"
                ),
                "description": required_text(
                    properties.get("description"), "CorpGroup description"
                ),
            }
        )
    domain_values = []
    for value in domains:
        properties = value.get("properties") if isinstance(value, dict) else None
        if not isinstance(properties, dict):
            raise GovernedMetadataError("DataHub Domain properties are missing")
        domain_values.append(
            {
                "urn": required_text(value.get("urn"), "Domain URN"),
                "name": required_text(properties.get("name"), "Domain name"),
                "description": required_text(
                    properties.get("description"), "Domain description"
                ),
            }
        )
    lifecycle_values = [
        {
            "urn": required_text(item.get("urn"), "lifecycle URN"),
            "name": required_text(item.get("name"), "lifecycle name"),
            "description": required_text(
                item.get("description"), "lifecycle description"
            ),
        }
        for item in lifecycle_stages
        if isinstance(item, dict)
        and item.get("urn") in declared["approved_lifecycles"]
    ]
    result = {
        "owners": tuple(sorted(owner_values, key=lambda item: item["urn"])),
        "domains": tuple(sorted(domain_values, key=lambda item: item["urn"])),
        "approved_lifecycles": tuple(
            sorted(lifecycle_values, key=lambda item: item["urn"])
        ),
    }
    if {
        name: {item["urn"] for item in values}
        for name, values in result.items()
    } != declared:
        raise GovernedMetadataError(
            "DataHub native governance entity membership is incomplete"
        )
    return result


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


def _sha256(value: object) -> str:
    return canonical_sha256(value)


def _canonical(value: object) -> str:
    return canonical_json(value)
