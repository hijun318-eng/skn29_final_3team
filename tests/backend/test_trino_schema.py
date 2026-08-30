from __future__ import annotations

import asyncio

import pytest

from app.adapters.trino_async import AdapterError, AdapterErrorCode, QueryPage
from app.adapters.trino_schema import TrinoSchemaDriftError, TrinoSchemaInspector


def test_schema_timeout_cancels_the_active_metadata_query() -> None:
    class TimeoutClient:
        def __init__(self) -> None:
            self.executions = 0
            self.cancelled: list[tuple[str, str]] = []

        async def execute(self, _sql: str, *, deadline: float) -> QueryPage:
            self.executions += 1
            if self.executions == 1:
                return QueryPage(
                    query_id="table-query",
                    state="FINISHED",
                    columns=("table_type",),
                    rows=(("BASE TABLE",),),
                    next_uri=None,
                )
            return QueryPage(
                query_id="columns-query",
                state="RUNNING",
                columns=(),
                rows=(),
                next_uri="https://trino:8443/v1/statement/executing/columns-query/1",
            )

        async def next_page(self, _next_uri: str, *, deadline: float) -> QueryPage:
            raise AdapterError(AdapterErrorCode.TIMEOUT, "upstream request timed out")

        async def cancel_query(
            self,
            query_id: str,
            next_uri: str,
            *,
            deadline: float,
        ) -> None:
            self.cancelled.append((query_id, next_uri))

    client = TimeoutClient()
    inspector = TrinoSchemaInspector(client, timeout_seconds=1)  # type: ignore[arg-type]

    with pytest.raises(TrinoSchemaDriftError, match="lookup failed"):
        asyncio.run(inspector.relation("crm.walkerhill_v4_3.crm_customer_map"))

    assert client.cancelled == [
        (
            "columns-query",
            "https://trino:8443/v1/statement/executing/columns-query/1",
        )
    ]


def test_schema_cancel_failure_preserves_the_original_timeout() -> None:
    class CancellationFailureClient:
        async def execute(self, _sql: str, *, deadline: float) -> QueryPage:
            return QueryPage(
                query_id="columns-query",
                state="RUNNING",
                columns=(),
                rows=(),
                next_uri="https://trino:8443/v1/statement/executing/columns-query/1",
            )

        async def next_page(self, _next_uri: str, *, deadline: float) -> QueryPage:
            raise AdapterError(AdapterErrorCode.TIMEOUT, "original timeout")

        async def cancel_query(
            self,
            _query_id: str,
            _next_uri: str,
            *,
            deadline: float,
        ) -> None:
            raise AdapterError(AdapterErrorCode.UPSTREAM, "cancel failed")

    inspector = TrinoSchemaInspector(
        CancellationFailureClient(),  # type: ignore[arg-type]
        timeout_seconds=1,
    )

    with pytest.raises(TrinoSchemaDriftError, match="lookup failed") as captured:
        asyncio.run(inspector.relation("crm.walkerhill_v4_3.crm_customer_map"))

    assert isinstance(captured.value.__cause__, AdapterError)
    assert captured.value.__cause__.code is AdapterErrorCode.TIMEOUT
