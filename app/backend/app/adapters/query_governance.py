"""자연어 요청을 live DataHub 의미·어휘 증거에 연결하고 권한·release·Trino schema를 함께 검증한다."""

from __future__ import annotations

import json
import unicodedata
from collections import deque
from typing import Any

from app.adapters.catalog_snapshot import (
    CatalogSnapshot,
    CatalogSnapshotLoader,
    validate_release_manifest,
)
from app.adapters.datahub_catalog import (
    DataHubCatalogError,
    DataHubCatalogClient,
    DataHubSemanticSearchError,
)
from app.adapters.datahub_metadata import (
    GovernedDataset,
    GovernedMetadataError,
)
from app.adapters.datahub_metadata_types import metric_rule_matches
from app.adapters.trino_schema import TrinoSchemaDriftError, TrinoSchemaInspector
from app.ports.data_platform import MetadataUnavailableError, NoEntitledAssetsError
from app.services.context.builder import ContextBuildError
from app.services.context.values import RATIO_ZERO_POLICIES
from app.services.context.contract import GovernedJoin


class QueryGovernanceEngine:
    """정적 질문 분기 없이 DataHub 검색 증거로 asset을 선택하고 join·entitlement·schema drift를 fail-closed로 통제한다."""

    MAX_REQUEST_ASSETS = 8

    def __init__(
        self,
        catalog: DataHubCatalogClient,
        schema_inspector: TrinoSchemaInspector,
        *,
        expected_context_release: str | None = None,
        max_request_assets: int = MAX_REQUEST_ASSETS,
        search_mode: str = "hybrid",
        catalog_ttl_seconds: float | None = None,
    ) -> None:
        if expected_context_release is not None and not expected_context_release.strip():
            raise ValueError("expected context release cannot be blank")
        if max_request_assets < 1:
            raise ValueError("request asset limit must be positive")
        if search_mode not in {"lexical", "hybrid"}:
            raise ValueError("DataHub search mode must be lexical or hybrid")
        self._catalog = catalog
        ttl = (
            catalog_ttl_seconds
            if catalog_ttl_seconds is not None
            else float(os.getenv("DATAHUB_CATALOG_TTL_SECONDS", "86400.0"))
        )
        self._loader = CatalogSnapshotLoader(catalog, ttl_seconds=ttl)
        self._schema = schema_inspector
        self._expected_release = expected_context_release
        self._max_request_assets = max_request_assets
        self._search_mode = search_mode

    async def search_assets(
        self,
        query: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Unicode token과 semantic hit로 asset을 순위화한 뒤 권한 있는 연결 graph만 runtime context로 반환한다."""
        query_tokens = _unicode_tokens(query)
        if not query_tokens:
            raise NoEntitledAssetsError("the request has no searchable Unicode tokens")
        try:
            snapshot, semantic_hits = await self._load_search_evidence(query)
            datasets = self._active_datasets(snapshot)
            terms = self._required_terms(snapshot, datasets)
            # lexical과 semantic 증거를 함께 요구 가능한 일반 경로로 유지해 특정 질문용 키워드 사전을 만들지 않는다.
            ranked = _ranked_matches(query_tokens, datasets, terms, semantic_hits)
            if not ranked:
                raise NoEntitledAssetsError(
                    "no governed DataHub asset matches the request"
                )
            entitled = [item for item in ranked if item[1].entitled(context)]
            if not entitled:
                raise NoEntitledAssetsError(
                    "no matching DataHub asset is entitled for this request"
                )
            # join dependency를 확장하기 전에 entitlement를 적용해야 비권한 asset의 schema와 관계가 노출되지 않는다.
            selected, graph = self._select_connected(
                tuple(item[1] for item in entitled),
                datasets,
            )
            self._validate_common_contracts(selected)
            await self._schema.verify(selected)
        except NoEntitledAssetsError:
            raise
        except (
            ContextBuildError,
            DataHubCatalogError,
            GovernedMetadataError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error
        term_map = {term.urn: term for term in terms.values()}
        raw_parameters = context.get("parameters") or {}
        if not isinstance(raw_parameters, dict):
            raise MetadataUnavailableError("runtime request parameters are invalid")
        selected_fqns = {item.fqn for item in selected}
        selected_edges = [
            edge
            for edge in graph
            if edge.left in selected_fqns and edge.right in selected_fqns
        ]
        selected_graph = {"edges": [edge.as_dict() for edge in selected_edges]}
        join_ids_by_fqn = {
            item.fqn: tuple(
                edge.id
                for edge in selected_edges
                if item.fqn in {edge.left, edge.right}
            )
            for item in selected
        }
        return [
            item.runtime_asset(
                term_map,
                join_ids_by_fqn[item.fqn],
                selected_graph,
                raw_parameters,
            )
            for item in selected
        ]

    async def get_asset_schema(self, urn: str) -> dict[str, Any]:
        """active release 안의 URN만 선택하고 live ``information_schema`` 일치 후 column 계약을 반환한다."""
        try:
            snapshot = await self._loader.load()
            datasets = self._active_datasets(snapshot)
            dataset = next((item for item in datasets if item.urn == urn), None)
            if dataset is None:
                raise GovernedMetadataError(
                    "DataHub asset is outside the complete active release"
                )
            await self._schema.verify((dataset,))
            return dataset.schema_payload()
        except (
            DataHubCatalogError,
            GovernedMetadataError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        """중복 없는 metric id를 dataset rule과 일치하는 Glossary Term으로 해석하며 누락·충돌은 거부한다."""
        if not metric_ids or len(metric_ids) != len(set(metric_ids)):
            raise MetadataUnavailableError("metric ids must be non-empty and unique")
        try:
            snapshot = await self._loader.load()
            datasets = self._active_datasets(snapshot)
            required = self._required_terms(snapshot, datasets)
        except (DataHubCatalogError, GovernedMetadataError) as error:
            raise MetadataUnavailableError(str(error)) from error
        missing = set(metric_ids) - set(required)
        if missing:
            raise MetadataUnavailableError(
                "DataHub metric glossary is missing requested governed terms"
            )
        return {metric_id: required[metric_id].as_dict() for metric_id in metric_ids}

    async def active_context_release(self) -> str:
        """단일 release·catalog checksum·policy와 완전한 manifest 검증을 통과한 context release를 반환한다."""
        try:
            snapshot = await self._loader.load()
            datasets = self._active_datasets(snapshot)
        except (DataHubCatalogError, GovernedMetadataError) as error:
            raise MetadataUnavailableError(str(error)) from error
        return datasets[0].context_release

    async def _load_search_evidence(self, query: str):
        """명시된 lexical 또는 hybrid 전략으로 snapshot과 검색 증거를 조립한다."""

        if self._search_mode == "lexical":
            return await self._loader.load(), ()
        try:
            return await _gather_snapshot_and_semantic(
                self._loader,
                self._catalog,
                query,
            )
        except DataHubSemanticSearchError as error:
            raise MetadataUnavailableError(
                "DataHub semantic search capability is unavailable"
            ) from error

    def _active_datasets(
        self,
        snapshot: CatalogSnapshot,
    ) -> tuple[GovernedDataset, ...]:
        values = tuple(snapshot.datasets_by_fqn.values())
        if self._expected_release is not None:
            values = tuple(
                item
                for item in values
                if item.context_release == self._expected_release
            )
            if not values:
                raise GovernedMetadataError(
                    "DataHub does not contain the configured context release"
                )
        releases = {item.context_release for item in values}
        checksums = {item.catalog_checksum for item in values}
        policies = {item.policy_version for item in values}
        if len(releases) != 1 or len(checksums) != 1 or len(policies) != 1:
            raise GovernedMetadataError(
                "DataHub runtime catalog does not resolve one coherent active release"
            )
        validate_release_manifest(snapshot, values)
        return tuple(sorted(values, key=lambda item: item.fqn))

    @staticmethod
    def _required_terms(
        snapshot: CatalogSnapshot,
        datasets: tuple[GovernedDataset, ...],
    ):
        result = {}
        for dataset in datasets:
            for metric in dataset.metrics:
                term_urn = str(metric["term_urn"])
                term = snapshot.terms_by_urn.get(term_urn)
                if (
                    term is None
                    or term.id != metric["id"]
                    or term.domain_urn != dataset.domain_urn
                    or term.catalog_checksum != dataset.catalog_checksum
                    or not metric_rule_matches(dataset, metric, term)
                ):
                    raise GovernedMetadataError(
                        "DataHub metric rule and glossary governance differ"
                    )
                previous = result.get(term.id)
                if previous is not None and previous != term:
                    raise GovernedMetadataError(
                        "DataHub metric id resolves to conflicting glossary terms"
                    )
                result[term.id] = term
        if not result:
            raise GovernedMetadataError("DataHub has no governed metric terms")
        domain_urns = {dataset.domain_urn for dataset in datasets}
        checksums = {dataset.catalog_checksum for dataset in datasets}
        for term in snapshot.terms_by_id.values():
            if term.metric_rule.get("kind") != "ratio" or term.id in result:
                continue
            if term.domain_urn not in domain_urns or term.catalog_checksum not in checksums:
                # 이 release에 속하지 않는 ratio term이다 — 이 스코프의 대상이 아니므로 건너뛴다.
                continue
            numerator_id = term.metric_rule.get("numerator_metric_id")
            denominator_id = term.metric_rule.get("denominator_metric_id")
            zero_policy = term.metric_rule.get("zero_policy")
            if (
                not isinstance(numerator_id, str)
                or not isinstance(denominator_id, str)
                or numerator_id == denominator_id
                or numerator_id not in result
                or denominator_id not in result
                or zero_policy not in RATIO_ZERO_POLICIES
            ):
                raise GovernedMetadataError(
                    "DataHub ratio metric term references an ungoverned numerator or denominator"
                )
            result[term.id] = term
        return result

    def _select_connected(
        self,
        seeds: tuple[GovernedDataset, ...],
        datasets: tuple[GovernedDataset, ...],
    ) -> tuple[tuple[GovernedDataset, ...], tuple[GovernedJoin, ...]]:
        by_fqn = {item.fqn: item for item in datasets}
        graph = _common_join_graph(datasets)
        approved = {
            item.fqn: frozenset(str(column["name"]) for column in item.columns)
            for item in datasets
        }
        edges = tuple(
            GovernedJoin.from_mapping(item, approved_assets=approved)
            for item in graph["edges"]
        )
        for candidate_anchor in seeds:
            anchor = candidate_anchor.fqn
            selected = {anchor}
            for seed in seeds:
                if seed.fqn in by_fqn and (seed.fqn == anchor or _shortest_path(anchor, seed.fqn, edges)):
                    selected.add(seed.fqn)
            dependencies = _metric_dependencies(tuple(by_fqn[name] for name in selected))
            for dep in dependencies:
                if dep in by_fqn and (dep == anchor or _shortest_path(anchor, dep, edges)):
                    selected.add(dep)
            metric_seeds = {name for name in selected if by_fqn[name].metrics}
            if not metric_seeds:
                for seed in tuple(selected):
                    adjacent = sorted(
                        other
                        for edge in edges
                        for other in _other_endpoints(edge, seed)
                        if other in by_fqn and by_fqn[other].metrics
                    )
                    if adjacent:
                        selected.add(adjacent[0])
                        metric_seeds.add(adjacent[0])
            selected = _connect_fqns(selected, edges, anchor)
            if (
                metric_seeds
                and selected.issubset(by_fqn)
                and len(selected) <= self._max_request_assets
            ):
                return (
                    tuple(by_fqn[name] for name in sorted(selected)),
                    edges,
                )
        raise GovernedMetadataError(
            "governed request assets cannot form a bounded metric join context"
        )

    @staticmethod
    def _validate_common_contracts(
        datasets: tuple[GovernedDataset, ...],
    ) -> None:
        for attribute in ("policy_version", "query_policy"):
            values = {
                _canonical(getattr(item, attribute))
                for item in datasets
            }
            if len(values) != 1:
                raise GovernedMetadataError(
                    f"selected DataHub assets disagree on {attribute}"
                )
        calendar_ids = {
            item.time_metadata.get("calendar_id")
            for item in datasets
            if isinstance(getattr(item, "time_metadata", None), dict)
        }
        if len(calendar_ids) > 1:
            raise GovernedMetadataError(
                "selected DataHub assets disagree on calendar_id"
            )


async def _gather_snapshot_and_semantic(loader, catalog, query):
    import asyncio

    return tuple(
        await asyncio.gather(loader.load(), catalog.semantic_search(query))
    )


def _ranked_matches(query_tokens, datasets, terms, semantic_hits):
    semantic_rank = {hit.urn: index for index, hit in enumerate(semantic_hits)}
    ranked = []
    for dataset in datasets:
        asset_tokens = _dataset_tokens(dataset, terms)
        overlap = len(query_tokens & asset_tokens)
        rank = semantic_rank.get(dataset.urn)
        if overlap or rank is not None:
            score = (rank is not None, overlap, -(rank or 0), dataset.fqn)
            ranked.append((score, dataset))
    return tuple(item for item in sorted(ranked, key=lambda item: item[0], reverse=True))


def _dataset_tokens(dataset, terms):
    values = [dataset.name, dataset.description, dataset.fqn]
    values.extend(str(column["name"]) for column in dataset.columns)
    for metric in dataset.metrics:
        term = terms.get(str(metric["id"]))
        if term is not None:
            values.append(term.searchable_text)
    for dimension in dataset.dimensions:
        if dimension.get("asset_fqn") == dataset.fqn:
            values.extend(map(str, dimension.get("aliases", ())))
    return _unicode_tokens(" ".join(values))


def _unicode_tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for character in normalized:
        category = unicodedata.category(character)
        if category[:1] in {"L", "N", "M"} or character == "_":
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))

    # 한국어 조사/접미사 분리 및 파싱 지원으로 자유 형식 자연어 질의 매칭력 극대화
    korean_particles = (
        "에서는", "에서", "으로", "에는", "별로", "마다", "부터", "까지",
        "은", "는", "이", "가", "을", "를", "의", "에", "로", "별", "도", "과", "와", "만",
    )
    expanded = set(tokens)
    for tok in tokens:
        for p in korean_particles:
            if len(tok) > len(p) + 1 and tok.endswith(p):
                expanded.add(tok[:-len(p)])
                break
    return frozenset(expanded)


def _common_join_graph(datasets):
    values = {_canonical(item.join_graph) for item in datasets}
    if len(values) != 1:
        raise GovernedMetadataError("DataHub assets disagree on the governed join graph")
    graph = json.loads(next(iter(values)))
    if set(graph) != {"edges"} or not isinstance(graph["edges"], list):
        raise GovernedMetadataError("DataHub governed join graph is invalid")
    return graph


def _metric_dependencies(datasets):
    result = {item.fqn for item in datasets}
    for dataset in datasets:
        for metric in dataset.metrics:
            result.update(
                str(item["asset_fqn"])
                for item in metric.get("dimensions", ())
            )
    return result


def _other_endpoints(edge, fqn):
    if edge.left == fqn:
        return (edge.right,)
    if edge.right == fqn:
        return (edge.left,)
    return ()


def _connect_fqns(selected, edges, anchor=None):
    selected = set(selected)
    if len(selected) < 2:
        return selected
    root = anchor if anchor in selected else sorted(selected)[0]
    result = {root}
    for target in sorted(selected - {root}):
        path = _shortest_path(root, target, edges)
        if path:
            result.update(path)
    return result


def _shortest_path(start, target, edges):
    queue = deque([(start, (start,))])
    seen = {start}
    while queue:
        current, path = queue.popleft()
        for edge in edges:
            for neighbor in _other_endpoints(edge, current):
                if neighbor == target:
                    return (*path, neighbor)
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, (*path, neighbor)))
    return ()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
