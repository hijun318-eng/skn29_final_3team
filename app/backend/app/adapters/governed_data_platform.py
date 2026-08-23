"""실시간 DataHub 거버넌스와 Trino 실행 서비스를 DataPlatform port로 노출하는 얇은 production façade다."""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

from app.adapters.datahub_catalog import DataHubCatalogClient
from app.adapters.query_execution import QueryExecutionService
from app.adapters.query_governance import QueryGovernanceEngine
from app.adapters.runtime_catalog_repository import (
    PostgresRuntimeCatalogProjectionRepository,
)
from app.adapters.trino_async import TrinoAsyncClient
from app.adapters.trino_schema import TrinoSchemaInspector
from app.ports.data_platform import AssetCandidateSet, ExecutionAssetSelection


class GovernedDataPlatformAdapter:
    """catalog·schema 검증과 query lifecycle을 조합하되 각 도메인 구현 책임은 전용 서비스에 위임한다."""

    def __init__(
        self,
        trino_url: str,
        trino_user: str,
        datahub_url: str | None = None,
        datahub_token: str | None = None,
        *,
        trino_password: str | None = None,
        trino_ca_file: str | None = None,
        datahub_ca_file: str | None = None,
        expected_context_release: str | None = None,
        max_candidate_metrics: int = QueryGovernanceEngine.MAX_CANDIDATE_METRICS,
        search_mode: str | None = None,
        catalog_ttl_seconds: float | None = None,
        query_timeout_seconds: float | None = None,
        query_state_ttl_seconds: float | None = None,
        query_state_max_entries: int | None = None,
        datahub_client: DataHubCatalogClient | None = None,
        trino_client: TrinoAsyncClient | None = None,
        governance: QueryGovernanceEngine | None = None,
        execution: QueryExecutionService | None = None,
        projection_repository: PostgresRuntimeCatalogProjectionRepository | None = None,
    ) -> None:
        if datahub_client is None and any(
            value is not None
            for value in (datahub_url, datahub_token, datahub_ca_file)
        ):
            raise ValueError(
                "production DataHub must use the canonical read service environment"
            )
        self._datahub = datahub_client or DataHubCatalogClient.from_env()
        self._trino = trino_client or TrinoAsyncClient(
            trino_url,
            trino_user,
            trino_password or "",
            ca_file=trino_ca_file,
        )
        self._governance = governance or QueryGovernanceEngine(
            self._datahub,
            TrinoSchemaInspector(self._trino),
            expected_context_release=expected_context_release,
            max_candidate_metrics=max_candidate_metrics,
            search_mode=search_mode
            or os.getenv("DATAHUB_SEARCH_MODE", "datahub_lexical"),
            # QueryGovernanceEngine 하나가 환경 기본값을 소유해야 adapter별 TTL drift가 없다.
            catalog_ttl_seconds=catalog_ttl_seconds,
            projection_repository=projection_repository,
        )
        self._execution = execution or QueryExecutionService(
            self._trino,
            timeout_seconds=(
                query_timeout_seconds
                if query_timeout_seconds is not None
                else float(os.getenv("TRINO_QUERY_TIMEOUT_SECONDS", "30"))
            ),
            state_ttl_seconds=(
                query_state_ttl_seconds
                if query_state_ttl_seconds is not None
                else float(os.getenv("TRINO_QUERY_STATE_TTL_SECONDS", "300"))
            ),
            state_max_entries=(
                query_state_max_entries
                if query_state_max_entries is not None
                else int(os.getenv("TRINO_QUERY_STATE_MAX_ENTRIES", "200"))
            ),
        )

    async def search_asset_candidates(
        self,
        query: str,
        context: dict[str, Any],
    ) -> AssetCandidateSet:
        """실행 값이나 Trino schema를 먼저 요구하지 않는 승인 후보와 release receipt를 반환한다."""

        return await self._governance.search_asset_candidates(query, context)

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Node 1 선택을 active release 전체에서 다시 해결해 검증된 실행 subgraph를 반환한다."""

        return await self._governance.resolve_execution_assets(selection, context)

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
        context: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """요청 metric id를 active release의 승인 Glossary Term 정의로 해석하며 누락·충돌은 실패로 전파한다."""
        return await self._governance.get_metric_terms(metric_ids, context)

    async def get_asset_schema(
        self,
        urn: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """DataHub URN에 대응하고 현재 Trino와 일치하는 column schema만 서비스 계층에 제공한다."""
        return await self._governance.get_asset_schema(urn, context)

    async def get_active_context_release(self) -> str:
        """완전한 manifest 검증을 통과한 단일 active catalog release 식별자를 반환한다."""
        return await self._governance.active_context_release()

    async def get_catalog_readiness(self) -> tuple[dict[str, str], str | None]:
        """semantic release·manifest·전체 Trino schema 단계와 checksum-bound receipt를 반환한다."""

        return await self._governance.catalog_readiness()

    async def get_product_release_readiness(
        self,
        product_release_id: str,
    ) -> tuple[dict[str, str], str | None, str | None]:
        """active pointer와 무관하게 고정 product release의 실행 가능성을 검증한다."""

        stages, receipt = await self._governance.catalog_readiness(
            product_release_id
        )
        if receipt != product_release_id or any(
            value != "ready" for value in stages.values()
        ):
            return stages, receipt, None
        semantic_release = await self._governance.active_context_release(
            product_release_id
        )
        return stages, receipt, semantic_release

    async def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        """G2 capability가 exact SQL에 결속된 query만 Trino로 실행하고 bounded evidence 결과를 반환한다."""
        return await self._execution.execute(sql, parameters, gate_token)

    async def execute_auxiliary_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        """필터 값 검증 query를 본 분석의 durable lifecycle attempt와 분리한다."""

        return await self._execution.execute_auxiliary(sql, parameters, gate_token)

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        """TTL 내에 보존된 terminal query 상태를 조회하며 만료·미확인 id는 ``NOT_FOUND``로 명시한다."""
        return await self._execution.get_status(query_id)

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        """진행 중인 Trino next URI를 취소하고 local 상태도 ``CANCELLED`` terminal 결과로 정리한다."""
        return await self._execution.cancel(query_id)

    async def cancel_query_at(
        self,
        query_id: str,
        cancel_uri: str,
    ) -> dict[str, Any]:
        """process 재시작과 무관하게 DB에 남은 exact coordinator URI로 query를 취소한다."""

        return await self._execution.cancel_at(query_id, cancel_uri)

    def bind_cancellation(self, check: Callable[[], bool] | None) -> None:
        """현재 async context 전용 취소 predicate를 실행 서비스에 연결해 다른 요청과 상태가 섞이지 않게 한다."""
        self._execution.bind_cancellation(check)

    def bind_query_lifecycle(
        self,
        sink: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        """현재 async request의 durable query lifecycle callback을 실행 서비스에 결속한다."""

        self._execution.bind_lifecycle_sink(sink)

    async def get_source_health(self) -> list[dict[str, Any]]:
        """DataHub와 Trino probe를 병렬 수행해 각 source의 ``HEALTHY``/``UNHEALTHY`` 상태를 독립적으로 반환한다."""
        datahub, trino = await _source_health(self._datahub, self._trino)
        return [
            {"source": "datahub", "status": "HEALTHY" if datahub else "UNHEALTHY"},
            {"source": "trino", "status": "HEALTHY" if trino else "UNHEALTHY"},
        ]

    async def aclose(self) -> None:
        """adapter가 조합한 DataHub·Trino client의 비동기 resource를 모두 정리한다."""
        await self._governance.aclose()
        await self._datahub.aclose()
        await self._trino.aclose()

    async def __aenter__(self) -> GovernedDataPlatformAdapter:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


async def _source_health(datahub, trino) -> tuple[bool, bool]:
    import asyncio

    values = await asyncio.gather(datahub.health(), trino.health())
    return bool(values[0]), bool(values[1])
