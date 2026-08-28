"""페이지 단위 DataHub readback을 하나의 checksum 검증된 runtime catalog snapshot으로 조립한다."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic

from app.adapters.datahub_catalog import DataHubCatalogClient
from app.adapters.datahub_metadata import (
    GlossaryDimensionMemberTerm,
    GlossaryMetricTerm,
    GovernedDataset,
    parse_dataset,
    parse_dimension_member_term,
    parse_glossary_term,
)
from app.adapters.datahub_metadata_values import (
    GovernedMetadataError,
    dataset_has_runtime_governance,
    dimension_member_term_record,
    required_text,
    term_has_runtime_governance,
)

DEFAULT_CATALOG_RELEASE_TTL_SECONDS = 86_400.0

__all__ = [
    "CatalogSnapshot",
    "CatalogSnapshotLoader",
    "DEFAULT_CATALOG_RELEASE_TTL_SECONDS",
]


@dataclass(frozen=True)
class CatalogSnapshot:
    """같은 시점에 검증한 dataset·metric term·native governance index를 하나의 불변 조회 단위로 묶는다."""
    datasets_by_urn: dict[str, GovernedDataset]
    datasets_by_fqn: dict[str, GovernedDataset]
    terms_by_urn: dict[str, GlossaryMetricTerm]
    terms_by_id: dict[str, GlossaryMetricTerm]
    governance_entities: dict[str, tuple[dict[str, str], ...]]
    dimension_member_terms_by_urn: dict[
        str, GlossaryDimensionMemberTerm
    ] = field(default_factory=dict)


class CatalogSnapshotLoader:
    """동시 DataHub readback을 single-flight로 합치고 검증된 snapshot을 TTL 동안 안전하게 재사용한다."""
    def __init__(
        self,
        client: DataHubCatalogClient,
        *,
        max_concurrency: int = 8,
        ttl_seconds: float = DEFAULT_CATALOG_RELEASE_TTL_SECONDS,
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

    async def invalidate(self) -> None:
        """활성 release generation 변경 시 다음 load가 fresh readback을 수행하게 한다.

        이미 시작된 readback은 그 호출자에게만 완료될 수 있도록 취소하지 않는다.
        다만 inflight 참조를 분리해 완료된 이전 결과가 새 generation cache로 게시되지
        못하게 하고, 다음 호출은 즉시 별도의 fresh readback을 시작한다.
        """

        async with self._lock:
            self._snapshot = None
            self._expires_at = 0.0
            self._inflight = None

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
        # Soft-deleted historical Term은 search 결과나 customProperties가 남아 있을 수
        # 있다. 현재 release membership에서 제외하되, 활성 dataset manifest가 여전히
        # 그 Term을 참조하면 아래 release 검증이 누락으로 fail-closed한다.
        active_term_records = _active_term_records(raw_terms)
        parsed_terms = tuple(
            parse_glossary_term(item)
            for item in active_term_records
            if not dimension_member_term_record(item)
        )
        parsed_members = tuple(
            parse_dimension_member_term(item)
            for item in active_term_records
            if dimension_member_term_record(item)
        )
        terms = tuple(
            term
            for term in parsed_terms
            if not active_checksums or term.catalog_checksum in active_checksums
        )
        members = tuple(
            term
            for term in parsed_members
            if not active_checksums or term.catalog_checksum in active_checksums
        )
        if not datasets:
            raise GovernedMetadataError(
                "DataHub has no approved runtime-governed datasets"
            )
        declared = _declared_governance(datasets, terms, members)
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
            dimension_member_terms_by_urn=_unique_index(
                members,
                "urn",
                "dimension member term URN",
            ),
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

        tasks = [asyncio.create_task(one(urn)) for urn in urns]
        try:
            return tuple(await asyncio.gather(*tasks))
        except BaseException:
            # gather는 첫 오류를 호출자에게 전달한 뒤 아직 실행 중인 sibling을 자동
            # 취소하지 않는다. token cleanup·client close와 요청이 경쟁하지 않도록 모든
            # sibling을 취소하고 terminal 상태를 회수한 뒤 원래 오류를 전파한다.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


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


def _active_term_records(values):
    """Rest.li status가 완전한 활성 Term만 runtime parser 입력으로 남긴다."""

    result = []
    for value in values:
        status = value.get("status") if isinstance(value, dict) else None
        if not isinstance(status, dict) or not isinstance(status.get("removed"), bool):
            raise GovernedMetadataError("DataHub glossary term status is incomplete")
        if status["removed"] is False:
            result.append(value)
    return tuple(result)

def _unique_index(values, attribute: str, label: str):
    result = {}
    for value in values:
        key = getattr(value, attribute)
        if key in result:
            raise GovernedMetadataError(f"DataHub {label} is duplicate")
        result[key] = value
    return result


def _declared_governance(datasets, terms, members=()) -> dict[str, set[str]]:
    result = {
        "owners": set(),
        "domains": set(),
        "approved_lifecycles": set(),
    }
    for dataset in datasets:
        for name in result:
            result[name].update(dataset.governance_urns[name])
    for term in (*terms, *members):
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
