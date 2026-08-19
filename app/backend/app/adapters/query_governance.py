"""자연어 요청을 live DataHub 의미·어휘 증거에 연결하고 권한·release·Trino schema를 함께 검증한다."""

from __future__ import annotations

import os
import unicodedata
from typing import Any

from app.adapters.catalog_snapshot import CatalogSnapshot, CatalogSnapshotLoader
from app.adapters.catalog_snapshot import DEFAULT_CATALOG_RELEASE_TTL_SECONDS
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
from app.adapters.query_join_graph import (
    common_join_graph,
    connect_fqns,
    metric_dependencies,
    other_endpoints,
    shortest_path,
)
from app.adapters.release_manifest import (
    coherent_release_datasets,
    validate_release_manifest,
)
from app.adapters.trino_schema import TrinoSchemaDriftError, TrinoSchemaInspector
from app.ports.data_platform import MetadataUnavailableError, NoEntitledAssetsError
from app.services.context.builder import ContextBuildError
from app.services.context.contract import GovernedJoin
from src.data.governance_contract import (
    canonical_json,
    metric_source_kind,
    ratio_operand_ids,
    RATIO_ZERO_POLICIES,
)


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
        # 과거 분석 데이터의 metadata는 운영자가 release 단위로만 변경하므로 snapshot과
        # readiness receipt는 같은 하루 경계를 쓴다. release 발행 시 Backend를 재기동하고,
        # 만료 뒤 재검증 실패는 직전 성공 snapshot으로 대체하지 않고 fail-closed로 닫는다.
        ttl = (
            catalog_ttl_seconds
            if catalog_ttl_seconds is not None
            else float(
                os.getenv(
                    "DATAHUB_CATALOG_TTL_SECONDS",
                    str(DEFAULT_CATALOG_RELEASE_TTL_SECONDS),
                )
            )
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
            # seed entitlement만으로는 부족하다. join·metric dependency로 끌려온 중간 asset의
            # schema와 관계도 노출되므로 확장 결과 전체를 _select_connected가 다시 검증한다.
            selected, graph = self._select_connected(
                tuple(item[1] for item in entitled),
                datasets,
                context,
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
        runtime_assets = [
            item.runtime_asset(
                term_map,
                join_ids_by_fqn[item.fqn],
                selected_graph,
                raw_parameters,
            )
            for item in selected
        ]
        return _with_ratio_metrics(runtime_assets, terms)

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
        """완전한 manifest와 전체 live Trino schema 검증을 통과한 context release를 반환한다."""
        try:
            snapshot = await self._loader.load()
            datasets = self._active_datasets(snapshot)
            await self._schema.verify(datasets)
        except (
            DataHubCatalogError,
            GovernedMetadataError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error
        return datasets[0].context_release

    async def catalog_readiness(self) -> tuple[dict[str, str], str | None]:
        """transport 이후 semantic identity·manifest membership·전체 Trino fingerprint를 단계별 검증한다."""

        failed = {
            "semantic_release": "not_ready",
            "catalog_manifest": "not_ready",
            "trino_schema": "not_ready",
        }
        try:
            snapshot = await self._loader.load()
            datasets = coherent_release_datasets(snapshot, self._expected_release)
        except (DataHubCatalogError, GovernedMetadataError):
            return failed, None
        stages = {**failed, "semantic_release": "ready"}
        try:
            validate_release_manifest(snapshot, datasets)
        except GovernedMetadataError:
            return stages, None
        stages["catalog_manifest"] = "ready"
        try:
            await self._schema.verify(datasets)
        except TrinoSchemaDriftError:
            return stages, None
        stages["trino_schema"] = "ready"
        receipt = f"{datasets[0].context_release}:{datasets[0].catalog_checksum}"
        return stages, receipt

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
        datasets = coherent_release_datasets(snapshot, self._expected_release)
        validate_release_manifest(snapshot, datasets)
        return datasets

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
            if metric_source_kind(term.metric_rule) != "ratio" or term.id in result:
                continue
            if term.domain_urn not in domain_urns or term.catalog_checksum not in checksums:
                # 이 release에 속하지 않는 ratio term이다 — 이 스코프의 대상이 아니므로 건너뛴다.
                continue
            operands = ratio_operand_ids(term.metric_rule)
            source = term.metric_rule.get("source")
            numerator_id, denominator_id = operands or (None, None)
            zero_policy = source.get("zero_policy") if isinstance(source, dict) else None
            if (
                operands is None
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
        context: dict[str, Any],
    ) -> tuple[tuple[GovernedDataset, ...], tuple[GovernedJoin, ...]]:
        """seed·metric dependency·join 경로로 확장한 asset 집합 전체가 ``entitled(context)``를 만족할 때만 반환한다."""

        by_fqn = {item.fqn: item for item in datasets}
        graph = common_join_graph(datasets)
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
                if seed.fqn in by_fqn and (seed.fqn == anchor or shortest_path(anchor, seed.fqn, edges)):
                    selected.add(seed.fqn)
            dependencies = metric_dependencies(tuple(by_fqn[name] for name in selected))
            for dep in dependencies:
                if dep in by_fqn and (dep == anchor or shortest_path(anchor, dep, edges)):
                    selected.add(dep)
            metric_seeds = {name for name in selected if by_fqn[name].metrics}
            if not metric_seeds:
                for seed in tuple(selected):
                    adjacent = sorted(
                        other
                        for edge in edges
                        for other in other_endpoints(edge, seed)
                        if other in by_fqn and by_fqn[other].metrics
                    )
                    if adjacent:
                        selected.add(adjacent[0])
                        metric_seeds.add(adjacent[0])
            selected = connect_fqns(selected, edges, anchor)
            if (
                metric_seeds
                and selected.issubset(by_fqn)
                and len(selected) <= self._max_request_assets
                # 확장으로 들어온 dependency·경유 asset 하나라도 권한이 없으면 이 anchor를 버리고
                # 다음 후보를 시도한다. 끝까지 없으면 아래에서 fail-closed로 닫는다.
                and all(by_fqn[name].entitled(context) for name in selected)
            ):
                return (
                    tuple(by_fqn[name] for name in sorted(selected)),
                    edges,
                )
        raise GovernedMetadataError(
            "governed request assets cannot form an entitled bounded metric join context"
        )

    @staticmethod
    def _validate_common_contracts(
        datasets: tuple[GovernedDataset, ...],
    ) -> None:
        for attribute in ("policy_version", "query_policy"):
            values = {
                canonical_json(getattr(item, attribute))
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
    values.extend(
        term.searchable_text
        for term in terms.values()
        if term.urn in dataset.dataset_terms
    )
    for dimension in dataset.dimensions:
        if dimension.get("asset_fqn") == dataset.fqn:
            values.extend(map(str, dimension.get("aliases", ())))
    return _unicode_tokens(" ".join(values))


def _with_ratio_metrics(assets, terms):
    """선택 asset의 두 column operand가 모두 있을 때만 derived ratio를 runtime 후보로 투영한다."""

    result = []
    metric_asset_indexes: dict[str, int] = {}
    for index, asset in enumerate(assets):
        item = dict(asset)
        metrics = [dict(metric) for metric in asset.get("metrics", ())]
        item["metrics"] = metrics
        result.append(item)
        for metric in metrics:
            metric_id = str(metric.get("id") or "")
            if metric_id:
                metric_asset_indexes[metric_id] = index
    for term in sorted(terms.values(), key=lambda item: item.id):
        if metric_source_kind(term.metric_rule) != "ratio":
            continue
        operands = ratio_operand_ids(term.metric_rule)
        source = term.metric_rule.get("source")
        if (
            operands is None
            or not isinstance(source, dict)
            or any(operand not in metric_asset_indexes for operand in operands)
        ):
            continue
        carrier = metric_asset_indexes[operands[0]]
        result[carrier]["metrics"].append(
            {
                "id": term.id,
                "asset_fqn": "",
                "field": "",
                "aggregation": "ratio",
                "time_field": "",
                "required_filters": [],
                "result_field": term.metric_rule["result_field"],
                "unit": term.unit,
                "reduction": "ratio",
                "numerator_metric_id": operands[0],
                "denominator_metric_id": operands[1],
                "zero_policy": source["zero_policy"],
            }
        )
    return result


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
