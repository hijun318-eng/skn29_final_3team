"""자연어 요청을 live DataHub 의미·어휘 증거에 연결하고 권한·release·Trino schema를 함께 검증한다."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any, Mapping

from app.adapters.catalog_snapshot import CatalogSnapshot, CatalogSnapshotLoader
from app.adapters.catalog_snapshot import DEFAULT_CATALOG_RELEASE_TTL_SECONDS
from app.adapters.datahub_catalog import (
    DataHubCatalogError,
    DataHubCatalogClient,
    DataHubSearchHit,
    DataHubSearchUnavailableError,
    DataHubSemanticSearchError,
)
from app.adapters.datahub_query_plan import (
    DataHubQueryPlanError,
    GovernedPhraseIndex,
    plan_search_queries,
)
from app.adapters.datahub_metadata import (
    GovernedDataset,
    GovernedMetadataError,
)
from app.adapters.datahub_metadata_types import GlossaryMetricTerm, metric_rule_matches
from app.adapters.legacy_semantic_release import compile_legacy_semantic_release
from app.adapters.query_search_evidence import (
    compact_candidate_assets as _compact_candidate_assets,
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
from app.adapters.runtime_catalog_repository import (
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
    RuntimeCatalogRepositoryError,
)
from app.adapters.runtime_catalog_projection import (
    DATAHUB_GLOSSARY_MIGRATION_SOURCE,
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
from app.runtime_release import product_release_receipt
from app.services.context.builder import ContextBuildError
from app.services.context.contract import GovernedJoin
from app.services.context.semantic_release import CanonicalMetric, CanonicalSemanticRelease
from src.data.governance_contract import (
    canonical_json,
    metric_source_kind,
    ratio_operand_ids,
    RATIO_ZERO_POLICIES,
)
from src.data.analysis_capability_contract import (
    AnalysisCapabilityContract,
    AnalysisCapabilityError,
    apply_analysis_capability_contract,
)
from src.data.metric_governance import business_metric_ids


logger = logging.getLogger("uvicorn.error")

# 질문 검색이 사용할 수 있는 retrieval 전략. 값의 의미는 문서·설정 계약이므로 조용히
# 바꾸지 않는다.
#   ``lexical``          DataHub 질문 검색을 호출하지 않고 canonical snapshot 어휘 증거만 쓴다.
#   ``lexical_shadow``   production 결정은 ``lexical``과 동일하고, DataHub bounded lexical
#                        검색을 shadow로 함께 측정한다. shadow 실패는 요청을 실패시키지 않는다.
#   ``datahub_lexical``  DataHub bounded lexical 검색 순위를 1차 retrieval 신호로 쓴다.
#                        검색 실패는 fail-closed다.
#   ``hybrid``           DataHub semantic 검색을 1차 신호로 쓴다(현재 배포에서는 비활성).
SEARCH_MODES = frozenset(
    {"lexical", "lexical_shadow", "datahub_lexical", "hybrid"}
)
_CANDIDATE_ENTITY_TYPES = ("DATASET", "GLOSSARY_TERM")
# 후보 검색은 bounded top-K만 읽는다. 상한을 넘겨 읽어도 backend가 다시 권한·거버넌스로
# 걸러내므로 요청 비용만 늘어난다.
DEFAULT_CANDIDATE_SEARCH_COUNT = 20
DEFAULT_CANDIDATE_SEARCH_VARIANTS = 3
MAX_CANDIDATE_SEARCH_COUNT = 50
DEFAULT_MAX_SHADOW_SEARCHES = 8


class QueryGovernanceEngine:
    """정적 질문 분기 없이 DataHub 검색 증거로 asset을 선택하고 join·entitlement·schema drift를 fail-closed로 통제한다."""

    MAX_REQUEST_ASSETS = 8
    MAX_CANDIDATE_METRICS = 24

    def __init__(
        self,
        catalog: DataHubCatalogClient,
        schema_inspector: TrinoSchemaInspector,
        *,
        expected_context_release: str | None = None,
        max_request_assets: int = MAX_REQUEST_ASSETS,
        max_candidate_metrics: int = MAX_CANDIDATE_METRICS,
        search_mode: str = "datahub_lexical",
        catalog_ttl_seconds: float | None = None,
        candidate_search_count: int = DEFAULT_CANDIDATE_SEARCH_COUNT,
        candidate_search_variants: int = DEFAULT_CANDIDATE_SEARCH_VARIANTS,
        max_shadow_searches: int = DEFAULT_MAX_SHADOW_SEARCHES,
        projection_repository: PostgresRuntimeCatalogProjectionRepository | None = None,
        analysis_capability: AnalysisCapabilityContract | None = None,
    ) -> None:
        if expected_context_release is not None and not expected_context_release.strip():
            raise ValueError("expected context release cannot be blank")
        if max_request_assets < 1:
            raise ValueError("request asset limit must be positive")
        if max_candidate_metrics < 1:
            raise ValueError("candidate metric limit must be positive")
        if search_mode not in SEARCH_MODES:
            raise ValueError(
                "DataHub search mode must be one of " + ", ".join(sorted(SEARCH_MODES))
            )
        if not 1 <= candidate_search_count <= MAX_CANDIDATE_SEARCH_COUNT:
            raise ValueError("candidate search count is outside the bounded range")
        if not 1 <= candidate_search_variants <= DEFAULT_CANDIDATE_SEARCH_VARIANTS:
            raise ValueError("candidate search variants are outside the bounded range")
        if max_shadow_searches < 1:
            raise ValueError("shadow search concurrency bound must be positive")
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
        # Production runtime은 active DB projection만 읽는다. Legacy loader는 명시적으로
        # projection repository를 주입하지 않은 compiler/test 호환 경로에만 남긴다.
        self._loader = (
            CatalogSnapshotLoader(catalog, ttl_seconds=ttl)
            if projection_repository is None
            else None
        )
        self._projection_repository = projection_repository
        self._analysis_capability = analysis_capability
        self._schema = schema_inspector
        self._expected_release = expected_context_release
        self._max_request_assets = max_request_assets
        self._max_candidate_metrics = max_candidate_metrics
        self._search_mode = search_mode
        self._candidate_search_count = candidate_search_count
        self._candidate_search_variants = candidate_search_variants
        self._max_shadow_searches = max_shadow_searches
        self._shadow_tasks: set[asyncio.Task[tuple[DataHubSearchHit, ...]]] = set()
        self._compiled_snapshot: CatalogSnapshot | None = None
        self._compiled_release: CanonicalSemanticRelease | None = None
        self._phrase_index_snapshot: CatalogSnapshot | None = None
        self._phrase_index: GovernedPhraseIndex | None = None

    async def search_asset_candidates(
        self,
        query: str,
        context: dict[str, Any],
    ) -> AssetCandidateSet:
        """질문 해석용 후보를 실행 parameter·Trino schema binding 없이 release receipt와 반환한다."""

        (
            release,
            selected,
            graph,
            terms,
            asset_priorities,
            search_metric_ranks,
            active_projection,
        ) = await self._search_selection(query, context, for_interpretation=True)
        preferred_metric_ids = self._preferred_metric_ids(context)
        try:
            projected_assets = self._project_assets(
                selected,
                graph,
                terms,
                context,
                candidate=True,
            )
            if active_projection is not None:
                for asset in projected_assets:
                    asset["product_release_id"] = (
                        active_projection.product_release_id
                    )
            if self._analysis_capability is not None:
                projected_assets = apply_analysis_capability_contract(
                    self._analysis_capability,
                    projected_assets,
                )
            assets = _compact_candidate_assets(
                projected_assets,
                terms,
                query,
                _unicode_tokens(query),
                asset_priorities,
                self._max_candidate_metrics,
                preferred_metric_ids,
                search_metric_ranks,
                self._search_mode == "datahub_lexical",
            )
            if active_projection is not None:
                source_by_metric = {
                    str(item["metric_id"]): item
                    for item in active_projection.projection.source_selection["metrics"]
                    if item["visibility"] == "BUSINESS"
                }
                for asset in assets:
                    for metric in asset.get("metrics", ()):
                        if (
                            not isinstance(metric, dict)
                            or metric.get("visibility", "BUSINESS") != "BUSINESS"
                        ):
                            continue
                        source = source_by_metric.get(str(metric.get("id") or ""))
                        if source is None or len(source["source_urns"]) != 1:
                            raise GovernedMetadataError(
                                "candidate Metric source authority receipt is incomplete"
                            )
                        metric["source_authority"] = source["source"]
                        metric["source_urn"] = source["source_urns"][0]
            selectable_metric_ids = {
                str(metric.get("id") or "")
                for asset in assets
                for metric in asset.get("metrics", ())
                if isinstance(metric, dict)
                and metric.get("candidate_selectable") is True
            }
            if not selectable_metric_ids:
                raise NoMetricMatchError(
                    "no governed metric has evidence for the request"
                )
            if not set(preferred_metric_ids).issubset(selectable_metric_ids):
                raise NoEntitledAssetsError(
                    "preferred metrics are not selectable for the request principal"
                )
            logger.info(
                "datahub_candidate_projection mode=%s selected_assets=%d "
                "selected_metric_ids=%s",
                self._search_mode,
                len(assets),
                sorted(selectable_metric_ids),
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
            product_release_id=(
                active_projection.product_release_id
                if active_projection is not None
                else None
            ),
            runtime_projection_checksum=(
                active_projection.projection.projection_sha256
                if active_projection is not None
                else None
            ),
            source_authority=(
                str(
                    active_projection.projection.source_selection["sections"][
                        "business_metric"
                    ]
                )
                if active_projection is not None
                else DATAHUB_GLOSSARY_MIGRATION_SOURCE
            ),
            retrieval_mode=self._search_mode,
        )

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Node 1 선택을 동일 active release에 다시 결속해 최소 권한 실행 subgraph로 확장한다."""

        try:
            snapshot, release, active_projection = await self._load_runtime_catalog(
                product_release_id=selection.receipt_product_release_id
            )
            if (
                release.catalog_version != selection.receipt_context_release
                or release.catalog_checksum != selection.receipt_catalog_checksum
                or release.canonical_checksum
                != selection.receipt_canonical_checksum
            ):
                raise ReleaseReceiptChangedError(
                    "active semantic release changed after candidate retrieval"
                )
            if self._projection_repository is not None and (
                active_projection is None
                or selection.receipt_product_release_id
                != active_projection.product_release_id
                or selection.receipt_runtime_projection_checksum
                != active_projection.projection.projection_sha256
            ):
                raise ReleaseReceiptChangedError(
                    "active runtime projection changed after candidate retrieval"
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
            if active_projection is not None:
                # Caller context나 DataHub 자유 텍스트가 아니라, 방금 receipt까지
                # 재검증한 active pointer의 제품 release만 실행 자산에 결속한다.
                for asset in assets:
                    asset["product_release_id"] = active_projection.product_release_id
            if self._analysis_capability is not None:
                assets = apply_analysis_capability_contract(
                    self._analysis_capability,
                    assets,
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
            AnalysisCapabilityError,
            DataHubCatalogError,
            GovernedMetadataError,
            RuntimeCatalogRepositoryError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error

    async def _search_selection(
        self,
        query: str,
        context: dict[str, Any],
        *,
        for_interpretation: bool,
    ) -> tuple[
        CanonicalSemanticRelease,
        tuple[GovernedDataset, ...],
        tuple[GovernedJoin, ...],
        dict[str, GlossaryMetricTerm],
        dict[str, int],
        dict[str, int],
        ActiveRuntimeCatalogProjection | None,
    ]:
        """질문 증거로 bounded 후보 scope를 고르고 검증된 release 객체와 함께 반환한다."""

        query_tokens = _unicode_tokens(query)
        if not query_tokens:
            raise NoMetricMatchError("the request has no searchable Unicode tokens")
        try:
            snapshot, release, active_projection = await self._load_runtime_catalog(
                context
            )
            datasets = self._datasets_for_release(snapshot, release)
            terms = self._required_terms(snapshot, datasets)
            governed_phrases = (
                self._governed_query_hints(snapshot, terms, query)
                if self._search_mode in {"lexical_shadow", "datahub_lexical"}
                else ()
            )
            semantic_hits = await self._load_search_evidence(
                query,
                governed_phrases=governed_phrases,
            )
            term_ids_by_urn = {term.urn: metric_id for metric_id, term in terms.items()}
            search_metric_ranks = {
                term_ids_by_urn[hit.urn]: rank
                for rank, hit in enumerate(semantic_hits)
                if hit.urn in term_ids_by_urn
            }
            # 전환 전 local mode는 snapshot overlap을 유지한다. 명시적 DataHub
            # lexical mode만 search hit 없는 Dataset으로 조용히 되돌아가지 않는다.
            ranked = _ranked_matches(
                query_tokens,
                datasets,
                terms,
                semantic_hits,
                search_only=self._search_mode == "datahub_lexical",
            )
            preferred_metric_ids = self._preferred_metric_ids(context)
            preferred_datasets = self._preferred_metric_datasets(
                preferred_metric_ids,
                datasets,
                terms,
            )
            ordered_by_fqn: dict[str, GovernedDataset] = {}
            for item in (*preferred_datasets, *(entry[1] for entry in ranked)):
                ordered_by_fqn.setdefault(item.fqn, item)
            ordered_datasets = tuple(ordered_by_fqn.values())
            if not ordered_datasets:
                raise NoMetricMatchError(
                    "no governed DataHub asset matches the request"
                )
            if preferred_datasets and not all(
                item.entitled(context) for item in preferred_datasets
            ):
                raise NoEntitledAssetsError(
                    "preferred DataHub metric asset is outside the request entitlement"
                )
            entitled = [item for item in ordered_datasets if item.entitled(context)]
            # 권한 필터 전후 후보 수만 남긴다. 미인가 asset의 URN·이름은 로그에도 남기지
            # 않아야 trace가 권한 우회 경로가 되지 않는다.
            logger.info(
                "datahub_search_selection mode=%s release=%s catalog_checksum=%s "
                "search_hits=%d candidates_before_entitlement=%d "
                "candidates_after_entitlement=%d",
                self._search_mode,
                release.catalog_version,
                release.catalog_checksum,
                len(semantic_hits),
                len(ordered_datasets),
                len(entitled),
            )
            if not entitled:
                raise NoEntitledAssetsError(
                    "no matching DataHub asset is entitled for this request"
                )
            # seed entitlement만으로는 부족하다. join·metric dependency로 끌려온 중간 asset의
            # schema와 관계도 노출되므로 확장 결과 전체를 _select_connected가 다시 검증한다.
            selected, graph = (
                self._select_interpretation_scope(
                    tuple(entitled),
                    datasets,
                    context,
                    release.joins,
                )
                if for_interpretation
                else self._select_connected(
                    tuple(entitled),
                    datasets,
                    context,
                    release.joins,
                )
            )
            if not {item.fqn for item in preferred_datasets}.issubset(
                {item.fqn for item in selected}
            ):
                raise UnsupportedSemanticError(
                    "preferred metrics do not share a bounded governed candidate component"
                )
            if not for_interpretation:
                self._validate_common_contracts(selected)
            selected_fqns = {item.fqn for item in selected}
            asset_priorities = {
                item.fqn: len(ordered_datasets) - index
                for index, item in enumerate(ordered_datasets)
                if item.fqn in selected_fqns
            }
        except NoEntitledAssetsError:
            raise
        except (
            ContextBuildError,
            DataHubCatalogError,
            GovernedMetadataError,
            RuntimeCatalogRepositoryError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error
        return (
            release,
            selected,
            graph,
            terms,
            asset_priorities,
            search_metric_ranks,
            active_projection,
        )

    def _select_interpretation_scope(
        self,
        seeds: tuple[GovernedDataset, ...],
        datasets: tuple[GovernedDataset, ...],
        context: dict[str, Any],
        edges: tuple[GovernedJoin, ...],
    ) -> tuple[tuple[GovernedDataset, ...], tuple[GovernedJoin, ...]]:
        """JOIN 가능성을 선결하지 않고 완전한 seed dependency component를 bounded 후보 범위에 합친다."""

        by_fqn = {item.fqn: item for item in datasets}
        selected: set[str] = set()
        denied_dependency = False
        for seed in seeds:
            component = self._seed_component(seed, by_fqn, edges)
            if (
                component
                and component.issubset(by_fqn)
                and any(not by_fqn[name].entitled(context) for name in component)
            ):
                denied_dependency = True
                continue
            if not self._valid_candidate_component(component, by_fqn, context):
                continue
            expanded = selected | component
            if self._valid_interpretation_scope(expanded, by_fqn, context):
                selected = expanded
        if not selected:
            if denied_dependency:
                raise NoEntitledAssetsError(
                    "a matching metric dependency is outside the request entitlement"
                )
            # active release 자체의 무결성은 snapshot compile/readiness에서 이미
            # 검증한다. 질문 검색 seed 중 실행 가능한 component가 하나도 없는 것은
            # infrastructure 장애가 아니라 안전한 retrieval abstention이다.
            raise NoMetricMatchError(
                "no governed interpretation candidate forms a bounded contract scope"
            )
        return tuple(by_fqn[name] for name in sorted(selected)), edges

    def _valid_interpretation_scope(
        self,
        selected: set[str],
        by_fqn: dict[str, GovernedDataset],
        context: dict[str, Any],
    ) -> bool:
        """후보 union에는 실행 JOIN·query policy 대신 bounded 권한과 단일 calendar만 요구한다."""

        if (
            not selected
            or not selected.issubset(by_fqn)
            or len(selected) > self._max_request_assets
            or not any(by_fqn[name].metrics for name in selected)
            or not all(by_fqn[name].entitled(context) for name in selected)
        ):
            return False
        calendar_ids = {
            str(by_fqn[name].time_metadata.get("calendar_id") or "")
            for name in selected
        }
        return len(calendar_ids) == 1 and "" not in calendar_ids

    @staticmethod
    def _preferred_metric_ids(context: dict[str, Any]) -> tuple[str, ...]:
        """서버가 확정한 멀티턴 Metric 힌트만 중복 없는 비권위 후보 우선순위로 읽는다."""

        raw = context.get("preferred_metric_ids") or ()
        if not isinstance(raw, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            raise MetadataUnavailableError(
                "preferred metric candidate context is invalid"
            )
        return tuple(dict.fromkeys(item.strip() for item in raw))

    @staticmethod
    def _preferred_metric_datasets(
        metric_ids: tuple[str, ...],
        datasets: tuple[GovernedDataset, ...],
        terms: dict[str, GlossaryMetricTerm],
    ) -> tuple[GovernedDataset, ...]:
        """column Metric 또는 ratio operand가 속한 Dataset을 active release에서 정확히 찾는다."""

        if not metric_ids:
            return ()
        dataset_by_metric_id = {
            str(metric["id"]): dataset
            for dataset in datasets
            for metric in dataset.metrics
        }
        resolved_ids: set[str] = set()
        required_datasets: list[GovernedDataset] = []
        for metric_id in metric_ids:
            direct = dataset_by_metric_id.get(metric_id)
            if direct is not None:
                resolved_ids.add(metric_id)
                required_datasets.append(direct)
                continue
            term = terms.get(metric_id)
            operands = (
                ratio_operand_ids(term.metric_rule)
                if term is not None
                else None
            )
            operand_datasets = tuple(
                dataset_by_metric_id.get(operand_id)
                for operand_id in (operands or ())
            )
            if operands is not None and all(
                item is not None for item in operand_datasets
            ):
                resolved_ids.add(metric_id)
                required_datasets.extend(
                    item for item in operand_datasets if item is not None
                )
        if resolved_ids != set(metric_ids):
            raise NoMetricMatchError(
                "preferred metric is outside the active semantic release"
            )
        unique_by_fqn: dict[str, GovernedDataset] = {}
        for item in required_datasets:
            unique_by_fqn.setdefault(item.fqn, item)
        return tuple(unique_by_fqn.values())

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

    async def _load_runtime_catalog(
        self,
        context: Mapping[str, Any] | None = None,
        *,
        product_release_id: str | None = None,
    ) -> tuple[
        CatalogSnapshot,
        CanonicalSemanticRelease,
        ActiveRuntimeCatalogProjection | None,
    ]:
        """Production에서는 명시 product release 또는 active DB projection만 읽는다."""

        if self._projection_repository is not None:
            requested_product_release = product_release_id
            if requested_product_release is None and context is not None:
                raw_product_release = context.get("product_release_id")
                if raw_product_release is not None:
                    if (
                        not isinstance(raw_product_release, str)
                        or not raw_product_release.strip()
                    ):
                        raise RuntimeCatalogRepositoryError(
                            "request product release receipt is invalid"
                        )
                    requested_product_release = raw_product_release
            active = (
                await self._projection_repository.load_product_release(
                    requested_product_release
                )
                if requested_product_release is not None
                else await self._projection_repository.load_active()
            )
            projection = active.projection
            if (
                requested_product_release is None
                and
                self._expected_release is not None
                and projection.catalog_release_id != self._expected_release
            ):
                raise RuntimeCatalogRepositoryError(
                    "active runtime projection is not the configured release"
                )
            return projection.snapshot, projection.release, active
        if self._loader is None:  # pragma: no cover - 생성자가 보장한다.
            raise RuntimeCatalogRepositoryError("runtime catalog loader is unavailable")
        snapshot = await self._loader.load()
        return snapshot, self._active_release(snapshot), None

    async def get_asset_schema(
        self,
        urn: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """active release 안의 URN만 선택하고 live ``information_schema`` 일치 후 column 계약을 반환한다."""
        try:
            snapshot, release, _active = await self._load_runtime_catalog(context)
            datasets = self._datasets_for_release(snapshot, release)
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
            RuntimeCatalogRepositoryError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """중복 없는 metric id를 dataset rule과 일치하는 Glossary Term으로 해석하며 누락·충돌은 거부한다."""
        if not metric_ids or len(metric_ids) != len(set(metric_ids)):
            raise MetadataUnavailableError("metric ids must be non-empty and unique")
        try:
            snapshot, release, _active = await self._load_runtime_catalog(context)
            datasets = self._datasets_for_release(snapshot, release)
            required = self._required_terms(snapshot, datasets)
        except (
            DataHubCatalogError,
            GovernedMetadataError,
            RuntimeCatalogRepositoryError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error
        missing = set(metric_ids) - set(required)
        if missing:
            raise MetadataUnavailableError(
                "DataHub metric glossary is missing requested governed terms"
            )
        return {metric_id: required[metric_id].as_dict() for metric_id in metric_ids}

    async def active_context_release(
        self,
        product_release_id: str | None = None,
    ) -> str:
        """완전한 manifest와 전체 live Trino schema 검증을 통과한 context release를 반환한다."""
        try:
            snapshot, release, _active = await self._load_runtime_catalog(
                product_release_id=product_release_id
            )
            datasets = self._datasets_for_release(snapshot, release)
            await self._schema.verify(datasets)
        except (
            DataHubCatalogError,
            GovernedMetadataError,
            RuntimeCatalogRepositoryError,
            TrinoSchemaDriftError,
        ) as error:
            raise MetadataUnavailableError(str(error)) from error
        return datasets[0].context_release

    async def catalog_readiness(
        self,
        product_release_id: str | None = None,
    ) -> tuple[dict[str, str], str | None]:
        """transport 이후 semantic identity·manifest membership·전체 Trino fingerprint를 단계별 검증한다."""

        failed = {
            "semantic_release": "not_ready",
            "catalog_manifest": "not_ready",
            "trino_schema": "not_ready",
        }
        try:
            if self._projection_repository is not None:
                snapshot, release, active_projection = (
                    await self._load_runtime_catalog(
                        product_release_id=product_release_id
                    )
                )
            else:
                if self._loader is None:  # pragma: no cover - 생성자가 보장한다.
                    raise RuntimeCatalogRepositoryError(
                        "runtime catalog loader is unavailable"
                    )
                active_projection = None
                snapshot = await self._loader.load()
                release = None
            datasets = coherent_release_datasets(snapshot, self._expected_release)
        except (
            DataHubCatalogError,
            GovernedMetadataError,
            RuntimeCatalogRepositoryError,
        ):
            return failed, None
        stages = dict(failed)
        try:
            validate_release_manifest(snapshot, datasets)
        except GovernedMetadataError:
            return stages, None
        stages["catalog_manifest"] = "ready"
        try:
            if release is None:
                release = self._active_release(snapshot)
            datasets = self._datasets_for_release(snapshot, release)
        except GovernedMetadataError:
            # manifest와 canonical compiler는 독립 단계다. manifest가 유효해도 실제
            # 요청과 같은 canonical compile 경계가 실패하면 semantic 단계만 닫는다.
            return stages, None
        stages["semantic_release"] = "ready"
        try:
            await self._schema.verify(datasets)
        except TrinoSchemaDriftError:
            return stages, None
        stages["trino_schema"] = "ready"
        receipt = (
            active_projection.product_release_id
            if active_projection is not None
            else product_release_receipt(release)
        )
        return stages, receipt

    async def _load_search_evidence(
        self,
        query: str,
        *,
        governed_phrases: tuple[str, ...] = (),
    ) -> tuple[DataHubSearchHit, ...]:
        """설정된 retrieval 전략으로 질문 검색 증거만 조립한다.

        canonical snapshot은 호출자가 먼저 확정하며, 여기서는 active release의 exact
        label·alias hint와 DataHub rank만 다룬다. ``lexical_shadow``의 shadow 실패는
        production 결정에 영향을 주지 않으며, ``datahub_lexical``/``hybrid``의 검색 실패는
        로컬 전체 scan으로 되돌아가지 않고 fail-closed로 닫는다.
        """

        if self._search_mode == "lexical":
            return ()
        if self._search_mode == "lexical_shadow":
            # shadow 결과는 로그 측정용이며 production 후보 선택에 들어가지 않는다.
            self._schedule_shadow_candidate_hits(
                query,
                governed_phrases=governed_phrases,
            )
            return ()
        if self._search_mode == "datahub_lexical":
            return await self._candidate_hits(
                query,
                governed_phrases=governed_phrases,
            )
        try:
            return await self._catalog.semantic_search(query)
        except DataHubSemanticSearchError as error:
            raise MetadataUnavailableError(
                "DataHub semantic search capability is unavailable"
            ) from error

    def _governed_query_hints(
        self,
        snapshot: CatalogSnapshot,
        terms: dict[str, GlossaryMetricTerm],
        query: str,
    ) -> tuple[str, ...]:
        """active release label·alias trie에서 질문에 실제 포함된 exact 힌트만 찾는다.

        trie는 snapshot identity마다 한 번만 만들며 질문별 전체 Glossary scan을 하지 않는다.
        이 결과는 DataHub query formulation일 뿐 metric rank나 후보 승인을 결정하지 않는다.
        """

        if self._phrase_index_snapshot is not snapshot or self._phrase_index is None:
            try:
                self._phrase_index = GovernedPhraseIndex(
                    phrase
                    for term in terms.values()
                    for phrase in (term.label, *term.aliases)
                )
            except ValueError as error:
                raise GovernedMetadataError(
                    "active release search phrases are invalid"
                ) from error
            self._phrase_index_snapshot = snapshot
        try:
            return self._phrase_index.match(
                query,
                max_hints=self._candidate_search_variants,
            )
        except DataHubQueryPlanError as error:
            raise NoMetricMatchError(str(error)) from error

    async def _candidate_hits(
        self,
        query: str,
        *,
        governed_phrases: tuple[str, ...] = (),
        shadow: bool = False,
    ) -> tuple[DataHubSearchHit, ...]:
        """bounded query plan을 병렬 실행해 DataHub 반환 순위 기반 후보를 모은다.

        같은 URN이 여러 변형에서 나오면 variant별 rank만으로 RRF 결합한다. 요청 수는
        plan 변형 수로 상한이 정해지고, 각 요청은 client timeout을 그대로 쓴다.
        검색 실패는 ``MetadataUnavailableError``로 닫아 전체 카탈로그 scan으로의 조용한
        fallback을 막는다.
        """

        started = time.monotonic()
        try:
            variants = plan_search_queries(
                query,
                max_variants=self._candidate_search_variants,
                governed_phrases=governed_phrases,
            )
        except DataHubQueryPlanError as error:
            raise NoMetricMatchError(str(error)) from error
        pages = await asyncio.gather(
            *(
                self._catalog.search_candidates(
                    variant.query,
                    entity_types=_CANDIDATE_ENTITY_TYPES,
                    count=self._candidate_search_count,
                )
                for variant in variants
            ),
            return_exceptions=True,
        )
        cancellation = next(
            (item for item in pages if isinstance(item, asyncio.CancelledError)),
            None,
        )
        if cancellation is not None:
            raise cancellation
        failure = next(
            (item for item in pages if isinstance(item, Exception)),
            None,
        )
        if failure is not None:
            category = (
                failure.category
                if isinstance(failure, DataHubSearchUnavailableError)
                else "protocol"
            )
            self._log_search(
                query_plan=variants,
                hits=(),
                elapsed=time.monotonic() - started,
                shadow=shadow,
                error_category=category,
            )
            raise MetadataUnavailableError(
                "DataHub candidate search is unavailable"
            ) from failure
        result = self._fuse_candidate_hits(
            tuple(item for item in pages if isinstance(item, tuple))
        )
        self._log_search(
            query_plan=variants,
            hits=result,
            elapsed=time.monotonic() - started,
            shadow=shadow,
            error_category=None,
        )
        return result

    async def _shadow_candidate_hits(
        self,
        query: str,
        *,
        governed_phrases: tuple[str, ...] = (),
    ) -> tuple[DataHubSearchHit, ...]:
        """production 결정과 분리된 shadow 측정으로만 DataHub 검색을 호출한다.

        shadow는 품질 gate 전 단계이므로 어떤 실패도 요청을 실패시키지 않는다. 대신 실패
        분류를 로그에 남겨 전환 판단의 근거로 쓴다.
        """

        try:
            return await self._candidate_hits(
                query,
                governed_phrases=governed_phrases,
                shadow=True,
            )
        except (MetadataUnavailableError, NoMetricMatchError, DataHubCatalogError):
            return ()

    def _schedule_shadow_candidate_hits(
        self,
        query: str,
        *,
        governed_phrases: tuple[str, ...],
    ) -> None:
        """production 응답과 분리된 bounded background shadow 검색을 예약한다.

        요청 폭주 시 task를 무제한 쌓지 않고 새 shadow 관측만 버린다. production lexical
        결정은 어느 경우에도 바꾸지 않으며 질문 원문은 로그에 남기지 않는다.
        """

        if len(self._shadow_tasks) >= self._max_shadow_searches:
            logger.info(
                "datahub_search mode=%s shadow=true api=searchAcrossEntities "
                "requests=0 error=capacity",
                self._search_mode,
            )
            return
        task = asyncio.create_task(
            self._shadow_candidate_hits(
                query,
                governed_phrases=governed_phrases,
            )
        )
        self._shadow_tasks.add(task)
        task.add_done_callback(self._finish_shadow_task)

    def _finish_shadow_task(
        self,
        task: asyncio.Task[tuple[DataHubSearchHit, ...]],
    ) -> None:
        """완료 task를 회수하고 예상 밖 결함도 원문 없이 type만 기록한다."""

        self._shadow_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "datahub_search mode=%s shadow=true api=searchAcrossEntities "
                "requests=0 error_type=%s",
                self._search_mode,
                type(error).__name__,
            )

    async def _drain_shadow_tasks(self) -> None:
        """현재 예약된 shadow 관측이 끝날 때까지 기다리는 test·운영 drain 경계다."""

        tasks = tuple(self._shadow_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def aclose(self) -> None:
        """adapter shutdown 전에 남은 shadow I/O를 취소하고 task 예외를 모두 회수한다."""

        tasks = tuple(self._shadow_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._shadow_tasks.clear()

    @staticmethod
    def _fuse_candidate_hits(
        pages: tuple[tuple[DataHubSearchHit, ...], ...],
    ) -> tuple[DataHubSearchHit, ...]:
        """여러 DataHub rank 목록을 reciprocal-rank fusion으로 결정적으로 결합한다.

        GraphQL이 내부 numeric score를 공개한다고 가정하지 않는다. 각 variant의 반환
        위치만 사용하고, 같은 URN의 entity type이 다르면 검색 계약 위반으로 닫는다.
        """

        records: dict[str, dict[str, Any]] = {}
        for page in pages:
            for rank, hit in enumerate(page, start=1):
                record = records.setdefault(
                    hit.urn,
                    {
                        "entity_type": hit.entity_type,
                        "score": 0.0,
                        "best_rank": rank,
                    },
                )
                if record["entity_type"] != hit.entity_type:
                    raise MetadataUnavailableError(
                        "DataHub candidate search returned conflicting entity types"
                    )
                record["score"] = float(record["score"]) + 1.0 / (60 + rank)
                record["best_rank"] = min(int(record["best_rank"]), rank)
        ordered = sorted(
            records.items(),
            key=lambda item: (
                -float(item[1]["score"]),
                int(item[1]["best_rank"]),
                item[0],
            ),
        )
        return tuple(
            DataHubSearchHit(
                urn,
                str(record["entity_type"]),
            )
            for urn, record in ordered
        )

    def _log_search(
        self,
        *,
        query_plan: tuple[Any, ...],
        hits: tuple[DataHubSearchHit, ...],
        elapsed: float,
        shadow: bool,
        error_category: str | None,
    ) -> None:
        """검색 경로의 관측값만 남기고 질문 원문·후보 값은 로그에 넣지 않는다."""

        counts: dict[str, int] = {}
        for hit in hits:
            counts[hit.entity_type] = counts.get(hit.entity_type, 0) + 1
        logger.info(
            "datahub_search mode=%s shadow=%s api=searchAcrossEntities plan=%s "
            "requests=%d hits=%s ranked_urns=%d highlighting=disabled "
            "latency_ms=%d error=%s",
            self._search_mode,
            shadow,
            [(variant.label, variant.token_count) for variant in query_plan],
            len(query_plan),
            counts,
            len(hits),
            int(elapsed * 1000),
            error_category or "none",
        )

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
        requested_fields = {
            f"{item.asset_fqn}.{item.column}"
            for item in selection.field_references
        }
        # 이 단계의 field reference에는 차원과 필터가 함께 들어온다. 전역 승인 dimension과
        # exact JOIN path까지만 확인하고, 출력 차원의 Metric 공통 binding은 AnalysisPlan이
        # 별도로 강제한다. 그래야 one-side Measure에 many-side 필터만 적용하는 SEMI_JOIN이
        # Metric 차원으로 잘못 선언되지 않아도 실행 component를 구성할 수 있다.
        if not requested_fields.issubset(release_dimension_fields):
            raise UnsupportedSemanticError(
                "selected field is outside the governed release dimensions"
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
