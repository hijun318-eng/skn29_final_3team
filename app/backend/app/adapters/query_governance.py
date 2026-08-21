"""자연어 요청을 live DataHub 의미·어휘 증거에 연결하고 권한·release·Trino schema를 함께 검증한다."""

from __future__ import annotations

import os
from collections import deque
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
from app.adapters.datahub_metadata_types import GlossaryMetricTerm, metric_rule_matches
from app.adapters.legacy_semantic_release import compile_legacy_semantic_release
from app.adapters.query_search_evidence import (
    gather_snapshot_and_semantic as _gather_snapshot_and_semantic,
    ranked_matches as _ranked_matches,
    unicode_tokens as _unicode_tokens,
    with_ratio_metrics as _with_ratio_metrics,
)
from app.adapters.query_join_graph import (
    connect_fqns,
    metric_dependencies,
    other_endpoints,
)
from app.adapters.release_manifest import (
    coherent_release_datasets,
    validate_release_manifest,
)
from app.adapters.trino_schema import TrinoSchemaDriftError, TrinoSchemaInspector
from app.ports.data_platform import (
    AssetCandidateSet,
    ExecutionAssetSelection,
    MetadataUnavailableError,
    NoEntitledAssetsError,
    NoMetricMatchError,
    ReleaseReceiptChangedError,
    UnsupportedSemanticError,
)
from app.services.context.builder import ContextBuildError
from app.services.context.contract import GovernedJoin
from app.services.context.semantic_release import CanonicalMetric, CanonicalSemanticRelease
from src.data.governance_contract import (
    canonical_json,
    metric_source_kind,
    ratio_operand_ids,
    RATIO_ZERO_POLICIES,
)
from src.data.metric_governance import business_metric_ids


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
        self._compiled_snapshot: CatalogSnapshot | None = None
        self._compiled_release: CanonicalSemanticRelease | None = None

    async def search_assets(
        self,
        query: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Unicode token과 semantic hit로 asset을 순위화한 뒤 권한 있는 연결 graph만 runtime context로 반환한다."""

        _release, selected, graph, terms = await self._search_selection(
            query,
            context,
        )
        try:
            await self._schema.verify(selected)
            return self._project_assets(
                selected,
                graph,
                terms,
                context,
                candidate=False,
            )
        except NoEntitledAssetsError:
            raise
        except (GovernedMetadataError, TrinoSchemaDriftError) as error:
            raise MetadataUnavailableError(str(error)) from error

    async def search_asset_candidates(
        self,
        query: str,
        context: dict[str, Any],
    ) -> AssetCandidateSet:
        """질문 해석용 후보를 실행 parameter·Trino schema binding 없이 release receipt와 반환한다."""

        release, selected, graph, terms = await self._search_selection(
            query,
            context,
        )
        try:
            assets = self._project_assets(
                selected,
                graph,
                terms,
                context,
                candidate=True,
            )
        except NoEntitledAssetsError:
            raise
        except GovernedMetadataError as error:
            raise MetadataUnavailableError(str(error)) from error
        return AssetCandidateSet(
            assets=tuple(assets),
            context_release=release.catalog_version,
            catalog_checksum=release.catalog_checksum,
            canonical_checksum=release.canonical_checksum,
        )

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Node 1 선택을 동일 active release에 다시 결속해 최소 권한 실행 subgraph로 확장한다."""

        try:
            snapshot = await self._loader.load()
            release = self._active_release(snapshot)
            if (
                release.catalog_version != selection.receipt_context_release
                or release.catalog_checksum != selection.receipt_catalog_checksum
                or release.canonical_checksum
                != selection.receipt_canonical_checksum
            ):
                raise ReleaseReceiptChangedError(
                    "active semantic release changed after candidate retrieval"
                )
            datasets = self._datasets_for_release(snapshot, release)
            terms = self._required_terms(snapshot, datasets)
            selected, graph = self._execution_component(
                release,
                datasets,
                terms,
                selection,
                context,
            )
            await self._schema.verify(selected)
            assets = self._project_assets(
                selected,
                graph,
                terms,
                context,
                candidate=False,
            )
            projected_metric_ids = {
                str(metric.get("id") or "")
                for asset in assets
                for metric in asset.get("metrics", ())
                if isinstance(metric, dict)
            }
            if not set(selection.execution_metric_ids).issubset(
                projected_metric_ids
            ):
                raise NoEntitledAssetsError(
                    "selected metrics are not executable for the request principal"
                )
            return assets
        except (
            NoEntitledAssetsError,
            ReleaseReceiptChangedError,
            UnsupportedSemanticError,
        ):
            raise
        except (
            ContextBuildError,
            DataHubCatalogError,
            GovernedMetadataError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error

    async def _search_selection(
        self,
        query: str,
        context: dict[str, Any],
    ) -> tuple[
        CanonicalSemanticRelease,
        tuple[GovernedDataset, ...],
        tuple[GovernedJoin, ...],
        dict[str, GlossaryMetricTerm],
    ]:
        """질문 증거로 bounded 후보 component를 고르고 검증된 release 객체와 함께 반환한다."""

        query_tokens = _unicode_tokens(query)
        if not query_tokens:
            raise NoMetricMatchError("the request has no searchable Unicode tokens")
        try:
            snapshot, semantic_hits = await self._load_search_evidence(query)
            release = self._active_release(snapshot)
            datasets = self._datasets_for_release(snapshot, release)
            terms = self._required_terms(snapshot, datasets)
            # lexical과 semantic 증거를 함께 요구 가능한 일반 경로로 유지해 특정 질문용 키워드 사전을 만들지 않는다.
            ranked = _ranked_matches(query_tokens, datasets, terms, semantic_hits)
            if not ranked:
                raise NoMetricMatchError(
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
                release.joins,
            )
            self._validate_common_contracts(selected)
        except NoEntitledAssetsError:
            raise
        except (
            ContextBuildError,
            DataHubCatalogError,
            GovernedMetadataError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error
        return release, selected, graph, terms

    @staticmethod
    def _project_assets(
        selected: tuple[GovernedDataset, ...],
        graph: tuple[GovernedJoin, ...],
        terms: dict[str, GlossaryMetricTerm],
        context: dict[str, Any],
        *,
        candidate: bool,
    ) -> list[dict[str, Any]]:
        """검증된 node를 후보 또는 실행 projection으로 만들고 공개 Metric 존재를 강제한다."""

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
        governed_assets = _with_ratio_metrics(
            [
                item.candidate_asset(
                    term_map,
                    join_ids_by_fqn[item.fqn],
                    selected_graph,
                    context,
                )
                if candidate
                else item.runtime_asset(
                    term_map,
                    join_ids_by_fqn[item.fqn],
                    selected_graph,
                    raw_parameters,
                    context,
                )
                for item in selected
            ],
            terms,
            context,
        )
        if not any(
            metric.get("visibility", "BUSINESS") == "BUSINESS"
            for asset in governed_assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict)
        ):
            raise NoEntitledAssetsError(
                "no matching DataHub business metric is entitled for this request"
            )
        return governed_assets

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
            release = self._active_release(snapshot)
            datasets = self._datasets_for_release(snapshot, release)
        except GovernedMetadataError:
            # Legacy manifest가 유효해도 canonical compiler와 실행 계약이 불일치하면
            # 실제 요청은 실패한다. readiness도 같은 실행 경계를 통과해야 한다.
            stages["semantic_release"] = "not_ready"
            return stages, None
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
        release = self._active_release(snapshot)
        return self._datasets_for_release(snapshot, release)

    def _active_release(
        self,
        snapshot: CatalogSnapshot,
    ) -> CanonicalSemanticRelease:
        """같은 cached snapshot은 한 번만 canonical typed graph로 컴파일해 원자적으로 재사용한다."""

        if self._compiled_snapshot is snapshot and self._compiled_release is not None:
            return self._compiled_release
        release = compile_legacy_semantic_release(
            snapshot,
            self._expected_release,
        )
        # 완성된 불변 projection만 게시한다. 컴파일 도중 실패하면 직전 release로
        # fallback하지 않고 예외를 전파해 요청을 fail-closed한다.
        self._compiled_snapshot = snapshot
        self._compiled_release = release
        return release

    @staticmethod
    def _datasets_for_release(
        snapshot: CatalogSnapshot,
        release: CanonicalSemanticRelease,
    ) -> tuple[GovernedDataset, ...]:
        """canonical release membership 순서대로 기존 runtime dataset projection을 연결한다."""

        try:
            datasets = tuple(
                snapshot.datasets_by_fqn[item.fqn] for item in release.assets
            )
        except KeyError as error:  # pragma: no cover - compiler membership 검증의 이중 방어다.
            raise GovernedMetadataError(
                "canonical release references an unavailable runtime dataset"
            ) from error
        if {item.catalog_checksum for item in datasets} != {release.catalog_checksum}:
            raise GovernedMetadataError(
                "canonical release dataset membership changed after compilation"
            )
        return datasets

    @staticmethod
    def _required_terms(
        snapshot: CatalogSnapshot,
        datasets: tuple[GovernedDataset, ...],
    ):
        result = {}
        for dataset in datasets:
            for metric in dataset.metrics:
                if metric.get("visibility") == "SUPPORT":
                    if metric.get("term_urn") is not None:
                        raise GovernedMetadataError(
                            "DataHub support metric exposes a Glossary term"
                        )
                    continue
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
        published_rules = (
            {str(item["id"]): item for item in datasets[0].metric_rules}
            if datasets[0].metric_rules
            else {term.id: term.metric_rule for term in snapshot.terms_by_id.values()}
        )
        for term in snapshot.terms_by_id.values():
            if metric_source_kind(term.metric_rule) != "ratio" or term.id in result:
                continue
            if term.domain_urn not in domain_urns or term.catalog_checksum not in checksums:
                # 이 release에 속하지 않는 ratio term이다 — 이 스코프의 대상이 아니므로 건너뛴다.
                continue
            published = published_rules.get(term.id)
            operands = ratio_operand_ids(term.metric_rule)
            source = term.metric_rule.get("source")
            numerator_id, denominator_id = operands or (None, None)
            zero_policy = source.get("zero_policy") if isinstance(source, dict) else None
            if (
                operands is None
                or published is None
                or canonical_json(published) != canonical_json(term.metric_rule)
                or numerator_id not in published_rules
                or denominator_id not in published_rules
                or metric_source_kind(published_rules[numerator_id]) != "column"
                or metric_source_kind(published_rules[denominator_id]) != "column"
                or zero_policy not in RATIO_ZERO_POLICIES
            ):
                raise GovernedMetadataError(
                    "DataHub ratio metric term references an ungoverned numerator or denominator"
                )
            result[term.id] = term
        if set(result) != business_metric_ids(published_rules.values()):
            raise GovernedMetadataError(
                "DataHub business metric Glossary coverage is incomplete"
            )
        return result

    def _execution_component(
        self,
        release: CanonicalSemanticRelease,
        datasets: tuple[GovernedDataset, ...],
        terms: dict[str, GlossaryMetricTerm],
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> tuple[tuple[GovernedDataset, ...], tuple[GovernedJoin, ...]]:
        """선택 Metric·필드가 요구하는 exact release path만 실행 component로 해결한다."""

        metrics_by_id = {item.id: item for item in release.metrics}
        selected_metrics = tuple(
            metrics_by_id.get(metric_id)
            for metric_id in selection.execution_metric_ids
        )
        output_metrics = tuple(
            metrics_by_id.get(metric_id)
            for metric_id in selection.output_metric_ids
        )
        if any(item is None for item in (*selected_metrics, *output_metrics)):
            raise UnsupportedSemanticError(
                "selected metric is outside the active semantic release"
            )
        executable = tuple(item for item in selected_metrics if item is not None)
        outputs = tuple(item for item in output_metrics if item is not None)
        if any(item.visibility != "BUSINESS" for item in outputs):
            raise UnsupportedSemanticError(
                "execution output contains a non-business metric"
            )

        expected_ids = set(selection.output_metric_ids)
        for metric_id in selection.output_metric_ids:
            term = terms.get(metric_id)
            operands = (
                ratio_operand_ids(term.metric_rule)
                if term is not None
                else None
            )
            if operands is not None:
                expected_ids.update(operands)
        if set(selection.execution_metric_ids) != expected_ids:
            raise UnsupportedSemanticError(
                "execution metric dependencies differ from the active release"
            )

        release_dimension_fields = {
            f"{item.asset_fqn}.{item.column}" for item in release.dimensions
        }
        allowed_field_sets = [
            self._metric_dimension_scope(
                item.id,
                metrics_by_id,
                terms,
                frozenset(),
            )
            for item in outputs
        ]
        common_fields = (
            set.intersection(*allowed_field_sets) if allowed_field_sets else set()
        ) & release_dimension_fields
        requested_fields = {
            f"{item.asset_fqn}.{item.column}"
            for item in selection.field_references
        }
        if not requested_fields.issubset(common_fields):
            raise UnsupportedSemanticError(
                "selected field is not a common governed metric dimension"
            )

        required_fqns = {
            fqn for metric in executable for fqn in metric.source_assets
        } | {item.asset_fqn for item in selection.field_references}
        if not required_fqns:
            raise UnsupportedSemanticError("execution selection has no source asset")
        edge_scopes = [set(item.allowed_join_ids) for item in executable]
        allowed_edge_ids = (
            set.intersection(*edge_scopes) if edge_scopes else set()
        )
        allowed_edges = tuple(
            edge for edge in release.joins if edge.id in allowed_edge_ids
        )
        anchor = min(required_fqns)
        connected, used_edges = self._execution_paths(
            required_fqns,
            allowed_edges,
            anchor,
        )
        if not required_fqns.issubset(connected):
            raise UnsupportedSemanticError(
                "selected metrics and dimensions have no unique commonly approved join path"
            )
        by_fqn = {item.fqn: item for item in datasets}
        if connected.issubset(by_fqn) and not all(
            by_fqn[name].entitled(context) for name in connected
        ):
            raise NoEntitledAssetsError(
                "execution subgraph contains an asset outside the request entitlement"
            )
        if not self._valid_candidate_component(connected, by_fqn, context):
            raise UnsupportedSemanticError(
                "execution subgraph is not an entitled bounded contract component"
            )
        return tuple(by_fqn[name] for name in sorted(connected)), used_edges

    @staticmethod
    def _metric_dimension_scope(
        metric_id: str,
        metrics_by_id: dict[str, CanonicalMetric],
        terms: dict[str, GlossaryMetricTerm],
        visiting: frozenset[str],
    ) -> set[str]:
        """column Metric 차원 또는 ratio operand의 공통 차원을 실행 선택 범위로 계산한다."""

        metric = metrics_by_id.get(metric_id)
        if metric is None or metric_id in visiting:
            raise UnsupportedSemanticError(
                "selected metric dimension dependencies are invalid"
            )
        if metric.source_kind != "ratio":
            return set(metric.dimension_fields)
        term = terms.get(metric_id)
        operands = ratio_operand_ids(term.metric_rule) if term is not None else None
        if operands is None:
            raise UnsupportedSemanticError(
                "selected ratio metric has no governed dimension dependencies"
            )
        scopes = [
            QueryGovernanceEngine._metric_dimension_scope(
                operand_id,
                metrics_by_id,
                terms,
                visiting | {metric_id},
            )
            for operand_id in operands
        ]
        return set.intersection(*scopes)

    @staticmethod
    def _execution_paths(
        required: set[str],
        edges: tuple[GovernedJoin, ...],
        anchor: str,
    ) -> tuple[set[str], tuple[GovernedJoin, ...]]:
        """유일한 승인 최단 경로만 선택해 실행 graph의 불필요하거나 모호한 edge를 제거한다."""

        if anchor not in required:
            return set(), ()
        connected = {anchor}
        used: dict[str, GovernedJoin] = {}
        for target in sorted(required - {anchor}):
            path_edges = QueryGovernanceEngine._unique_shortest_edge_path(
                anchor,
                target,
                edges,
            )
            if not path_edges:
                return set(), ()
            for edge in path_edges:
                connected.update((edge.left, edge.right))
                used[edge.id] = edge
        return connected, tuple(used[name] for name in sorted(used))

    @staticmethod
    def _unique_shortest_edge_path(
        start: str,
        target: str,
        edges: tuple[GovernedJoin, ...],
    ) -> tuple[GovernedJoin, ...]:
        """병렬 edge와 동률 우회 경로가 없는 경우에만 유일한 최단 edge 경로를 반환한다."""

        adjacency: dict[str, list[tuple[str, GovernedJoin]]] = {}
        for edge in edges:
            adjacency.setdefault(edge.left, []).append((edge.right, edge))
            adjacency.setdefault(edge.right, []).append((edge.left, edge))
        distances = {start: 0}
        path_counts = {start: 1}
        predecessors: dict[str, tuple[str, GovernedJoin]] = {}
        queue = deque([start])
        target_distance: int | None = None
        while queue:
            current = queue.popleft()
            distance = distances[current]
            if target_distance is not None and distance >= target_distance:
                continue
            for neighbor, edge in sorted(
                adjacency.get(current, ()),
                key=lambda item: (item[0], item[1].id),
            ):
                candidate_distance = distance + 1
                known_distance = distances.get(neighbor)
                if known_distance is None:
                    distances[neighbor] = candidate_distance
                    path_counts[neighbor] = path_counts[current]
                    if path_counts[current] == 1:
                        predecessors[neighbor] = (current, edge)
                    queue.append(neighbor)
                    if neighbor == target:
                        target_distance = candidate_distance
                elif known_distance == candidate_distance:
                    path_counts[neighbor] = min(
                        2,
                        path_counts[neighbor] + path_counts[current],
                    )
                    predecessors.pop(neighbor, None)
        if path_counts.get(target) != 1:
            return ()
        result: list[GovernedJoin] = []
        current = target
        while current != start:
            predecessor = predecessors.get(current)
            if predecessor is None:  # pragma: no cover - 단일 경로 count와 함께 유지되는 불변식이다.
                return ()
            current, edge = predecessor
            result.append(edge)
        return tuple(reversed(result))

    def _select_connected(
        self,
        seeds: tuple[GovernedDataset, ...],
        datasets: tuple[GovernedDataset, ...],
        context: dict[str, Any],
        edges: tuple[GovernedJoin, ...],
    ) -> tuple[tuple[GovernedDataset, ...], tuple[GovernedJoin, ...]]:
        """순위 seed의 완전한 dependency component만 bounded context에 원자적으로 추가한다."""

        by_fqn = {item.fqn: item for item in datasets}
        for candidate_anchor in seeds:
            anchor = candidate_anchor.fqn
            selected = self._seed_component(candidate_anchor, by_fqn, edges)
            if not self._valid_candidate_component(
                selected,
                by_fqn,
                context,
            ):
                continue
            for seed in seeds:
                component = self._seed_component(seed, by_fqn, edges)
                required = selected | component
                connected = connect_fqns(required, edges, anchor)
                # 한 seed의 dependency나 경유 node 일부만 넣으면 Node 1에 실행 불가능한
                # 후보를 노출한다. 전체 component가 들어오지 않으면 그 seed만 건너뛴다.
                if required.issubset(connected) and self._valid_candidate_component(
                    connected,
                    by_fqn,
                    context,
                ):
                    selected = connected
            return tuple(by_fqn[name] for name in sorted(selected)), edges
        raise GovernedMetadataError(
            "governed request assets cannot form an entitled bounded metric join context"
        )

    @staticmethod
    def _seed_component(
        seed: GovernedDataset,
        by_fqn: dict[str, GovernedDataset],
        edges: tuple[GovernedJoin, ...],
    ) -> set[str]:
        """seed가 Node 1 후보로 유효하기 위한 metric·dimension·경로 폐쇄 집합을 만든다."""

        required = {seed.fqn}
        if not seed.metrics:
            adjacent = sorted(
                other
                for edge in edges
                for other in other_endpoints(edge, seed.fqn)
                if other in by_fqn and by_fqn[other].metrics
            )
            if not adjacent:
                return set()
            required.add(adjacent[0])
        required.update(
            metric_dependencies(tuple(by_fqn[name] for name in required))
        )
        if not required.issubset(by_fqn):
            return set()
        connected = connect_fqns(required, edges, seed.fqn)
        return connected if required.issubset(connected) else set()

    def _valid_candidate_component(
        self,
        selected: set[str],
        by_fqn: dict[str, GovernedDataset],
        context: dict[str, Any],
    ) -> bool:
        """bounded·entitled·공통 실행 계약을 모두 만족하는 완전한 후보 집합인지 판정한다."""

        if (
            not selected
            or not selected.issubset(by_fqn)
            or len(selected) > self._max_request_assets
            or not any(by_fqn[name].metrics for name in selected)
            or not all(by_fqn[name].entitled(context) for name in selected)
        ):
            return False
        try:
            self._validate_common_contracts(
                tuple(by_fqn[name] for name in sorted(selected))
            )
        except GovernedMetadataError:
            return False
        return True

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
