"""실시간 DataHub 거버넌스와 Trino 실행 서비스를 DataPlatform port로 노출하는 얇은 production façade다."""

from __future__ import annotations

import os
from typing import Any, Callable

from app.adapters.datahub_catalog import DataHubCatalogClient
from app.adapters.query_execution import QueryExecutionService
from app.adapters.query_governance import QueryGovernanceEngine
from app.adapters.trino_async import TrinoAsyncClient
from app.adapters.trino_schema import TrinoSchemaInspector


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
        search_mode: str | None = None,
        catalog_ttl_seconds: float | None = None,
        query_timeout_seconds: float | None = None,
        query_state_ttl_seconds: float | None = None,
        query_state_max_entries: int | None = None,
        datahub_client: DataHubCatalogClient | None = None,
        trino_client: TrinoAsyncClient | None = None,
        governance: QueryGovernanceEngine | None = None,
        execution: QueryExecutionService | None = None,
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
            search_mode=search_mode or os.getenv("DATAHUB_SEARCH_MODE", "lexical"),
            catalog_ttl_seconds=(
                catalog_ttl_seconds
                if catalog_ttl_seconds is not None
                else float(os.getenv("DATAHUB_CATALOG_TTL_SECONDS", "86400.0"))
            ),
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

    async def search_assets(
        self,
        query: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """자연어와 인증 context를 live governance에 연결해 권한·schema가 검증된 runtime asset만 반환한다."""
        return await self._governance.search_assets(query, context)

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        """요청 metric id를 active release의 승인 Glossary Term 정의로 해석하며 누락·충돌은 실패로 전파한다."""
        return await self._governance.get_metric_terms(metric_ids)

    async def get_asset_schema(self, urn: str) -> dict[str, Any]:
        """DataHub URN에 대응하고 현재 Trino와 일치하는 column schema만 서비스 계층에 제공한다."""
        return await self._governance.get_asset_schema(urn)

    async def get_active_context_release(self) -> str:
        """완전한 manifest 검증을 통과한 단일 active catalog release 식별자를 반환한다."""
        return await self._governance.active_context_release()

    async def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        """G2 capability가 exact SQL에 결속된 query만 Trino로 실행하고 bounded evidence 결과를 반환한다."""
        return await self._execution.execute(sql, parameters, gate_token)

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        """TTL 내에 보존된 terminal query 상태를 조회하며 만료·미확인 id는 ``NOT_FOUND``로 명시한다."""
        return await self._execution.get_status(query_id)

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        """진행 중인 Trino next URI를 취소하고 local 상태도 ``CANCELLED`` terminal 결과로 정리한다."""
        return await self._execution.cancel(query_id)

    def bind_cancellation(self, check: Callable[[], bool] | None) -> None:
        """현재 async context 전용 취소 predicate를 실행 서비스에 연결해 다른 요청과 상태가 섞이지 않게 한다."""
        self._execution.bind_cancellation(check)

    async def get_source_health(self) -> list[dict[str, Any]]:
        """DataHub와 Trino probe를 병렬 수행해 각 source의 ``HEALTHY``/``UNHEALTHY`` 상태를 독립적으로 반환한다."""
        datahub, trino = await _source_health(self._datahub, self._trino)
        return [
            {"source": "datahub", "status": "HEALTHY" if datahub else "UNHEALTHY"},
            {"source": "trino", "status": "HEALTHY" if trino else "UNHEALTHY"},
        ]

    async def aclose(self) -> None:
        """adapter가 조합한 DataHub·Trino client의 비동기 resource를 모두 정리한다."""
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
