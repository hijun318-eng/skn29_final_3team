"""AST binding과 capability 승인이 끝난 SQL만 Trino에서 실행하고 bounded terminal evidence를 관리한다."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from app.adapters.query_result_values import result_metadata
from app.adapters.trino_async import (
    AdapterError,
    AdapterErrorCode,
    QueryPage,
    TrinoAsyncClient,
)
from app.query_capability import verify_query_capability


@dataclass(frozen=True)
class QueryState:
    """완료된 query 결과와 monotonic 만료 시각을 묶어 stale evidence 재사용을 제한한다."""
    result: dict[str, Any]
    expires_at: float


class QueryExecutionService:
    """exact SQL capability 확인부터 pagination·deadline·cancel·TTL 상태 보존까지 Trino lifecycle을 소유한다."""

    def __init__(
        self,
        client: TrinoAsyncClient,
        *,
        timeout_seconds: float = 30.0,
        state_ttl_seconds: float = 300.0,
        state_max_entries: int = 200,
        max_result_rows: int = 1_000,
    ) -> None:
        if (
            timeout_seconds <= 0
            or state_ttl_seconds <= 0
            or state_max_entries < 1
            or max_result_rows < 1
        ):
            raise ValueError("Trino execution bounds must be positive")
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._state_ttl_seconds = state_ttl_seconds
        self._state_max_entries = state_max_entries
        self._max_result_rows = max_result_rows
        self._queries: OrderedDict[str, QueryState] = OrderedDict()
        self._next_uris: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()
        self._cancellation: ContextVar[Callable[[], bool] | None] = ContextVar(
            "query_execution_cancellation",
            default=None,
        )

    def bind_cancellation(self, check: Callable[[], bool] | None) -> None:
        """현재 request context에만 적용할 취소 predicate를 등록해 concurrent query 사이의 취소 전파를 막는다."""
        self._cancellation.set(check)

    async def execute(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        """parameter가 이미 AST에 binding되고 G2 token이 exact SQL과 일치할 때만 deadline 안에서 실행한다."""
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("executable SQL is required")
        if parameters:
            raise ValueError("SQL parameters must be bound by the Phase 3 AST binder")
        # token이 package hash뿐 아니라 SQL 원문에도 결속되어 승인 뒤 statement 교체를 차단한다.
        if not verify_query_capability(sql, gate_token):
            raise ValueError("G2 query capability does not match executable SQL")
        deadline = monotonic() + self._timeout_seconds
        try:
            first = await self._client.execute(sql, deadline=deadline)
            result = await self._collect(first, deadline)
        except AdapterError as error:
            if error.code is AdapterErrorCode.TIMEOUT:
                raise TimeoutError(str(error)) from error
            if error.code is AdapterErrorCode.UPSTREAM:
                raise ConnectionError(str(error)) from error
            raise ValueError(str(error)) from error
        await self._store(result)
        return dict(result)

    async def get_status(self, query_id: str) -> dict[str, Any]:
        """TTL 내 terminal 결과만 반환하고 만료된 query를 ``NOT_FOUND``로 처리해 stale 성공 재사용을 막는다."""
        async with self._lock:
            self._prune_locked()
            state = self._queries.get(query_id)
            if state is not None:
                self._queries.move_to_end(query_id)
        return (
            dict(state.result)
            if state is not None
            else {"query_id": query_id, "status": "NOT_FOUND"}
        )

    async def cancel(self, query_id: str) -> dict[str, Any]:
        """기억한 coordinator next URI를 취소하고 terminal cache에서 제거한 뒤 ``CANCELLED`` 결과를 반환한다."""
        next_uri = await self._next_uri(query_id)
        if next_uri:
            await self._cancel_uri(next_uri)
        async with self._lock:
            self._prune_locked()
            state = self._queries.pop(query_id, None)
        result = dict(state.result) if state else {"query_id": query_id}
        result["status"] = "CANCELLED"
        return result

    async def _collect(self, first: QueryPage, deadline: float) -> dict[str, Any]:
        page = first
        query_id = first.query_id
        columns = first.columns
        rows = list(first.rows)
        warnings = list(first.warnings)
        self._validate_page(page, query_id, columns)
        if self._cancel_requested():
            await self._cancel_uri(page.next_uri)
            return _cancelled_result(query_id)
        while page.next_uri:
            await self._remember_next_uri(query_id, page.next_uri)
            if monotonic() >= deadline:
                await self._cancel_uri(page.next_uri)
                raise AdapterError(
                    AdapterErrorCode.TIMEOUT,
                    "query total deadline exceeded",
                )
            if self._cancel_requested():
                await self._cancel_uri(page.next_uri)
                return _cancelled_result(query_id)
            try:
                page = await self._client.next_page(page.next_uri, deadline=deadline)
            except AdapterError as error:
                if error.code is AdapterErrorCode.TIMEOUT:
                    await self._cancel_uri(await self._next_uri(query_id))
                raise
            self._validate_page(page, query_id, columns)
            columns = page.columns or columns
            rows.extend(page.rows)
            warnings.extend(page.warnings)
            if len(rows) > self._max_result_rows:
                await self._cancel_uri(page.next_uri)
                raise AdapterError(
                    AdapterErrorCode.QUERY,
                    "query result exceeds the configured row bound",
                )
        await self._forget_next_uri(query_id)
        if page.state != "FINISHED":
            raise AdapterError(AdapterErrorCode.QUERY, "query did not finish")
        if len(columns) != len(set(columns)):
            raise AdapterError(AdapterErrorCode.QUERY, "query columns are duplicate")
        shaped = [dict(zip(columns, row, strict=True)) for row in rows]
        critical_warnings = [
            w for w in warnings
            if not ("exceeds the soft limit" in w.lower() or "distinct_aggregations_strategy" in w.lower())
        ]
        return {
            "query_id": query_id,
            "status": "PARTIAL" if critical_warnings else "SUCCEEDED",
            "rows": shaped,
            "result_metadata": result_metadata(shaped, columns),
            "evidence_complete": True,
            "zero_result_suspicious": False,
            "filters": {},
            "sampling": {
                "applied": False,
                "returned_rows": len(shaped),
                "total_rows": len(shaped),
            },
            "masking": {"applied": False, "fields": ()},
        }

    @staticmethod
    def _validate_page(
        page: QueryPage,
        query_id: str,
        established_columns: tuple[str, ...],
    ) -> None:
        if page.query_id != query_id:
            raise AdapterError(AdapterErrorCode.QUERY, "Trino query id changed")
        if established_columns and page.columns and page.columns != established_columns:
            raise AdapterError(AdapterErrorCode.QUERY, "Trino columns changed between pages")
        width = len(page.columns or established_columns)
        if any(len(row) != width for row in page.rows):
            raise AdapterError(AdapterErrorCode.QUERY, "Trino row width is invalid")

    def _cancel_requested(self) -> bool:
        check = self._cancellation.get()
        return bool(check and check())

    async def _store(self, result: dict[str, Any]) -> None:
        async with self._lock:
            self._prune_locked()
            while len(self._queries) >= self._state_max_entries:
                self._queries.popitem(last=False)
            self._queries[str(result["query_id"])] = QueryState(
                dict(result),
                monotonic() + self._state_ttl_seconds,
            )

    async def _remember_next_uri(self, query_id: str, uri: str) -> None:
        async with self._lock:
            self._prune_locked()
            self._next_uris[query_id] = (
                uri,
                monotonic() + self._state_ttl_seconds,
            )

    async def _next_uri(self, query_id: str) -> str | None:
        async with self._lock:
            self._prune_locked()
            state = self._next_uris.get(query_id)
            return state[0] if state else None

    async def _forget_next_uri(self, query_id: str) -> None:
        async with self._lock:
            self._next_uris.pop(query_id, None)

    def _prune_locked(self) -> None:
        now = monotonic()
        # 만료 값을 남기면 과거 권한·schema로 실행한 결과가 현재 증거처럼 재사용되므로 조회 전에 항상 제거한다.
        for query_id, state in tuple(self._queries.items()):
            if state.expires_at <= now:
                self._queries.pop(query_id, None)
        for query_id, (_uri, expires_at) in tuple(self._next_uris.items()):
            if expires_at <= now:
                self._next_uris.pop(query_id, None)

    async def _cancel_uri(self, uri: str | None) -> None:
        if not uri:
            return
        try:
            await self._client.cancel(
                uri,
                deadline=monotonic() + min(1.0, self._timeout_seconds),
            )
        except AdapterError:
            # 취소는 best-effort cleanup이며 원래 timeout/cancel 결과를 upstream cleanup 오류로 덮지 않는다.
            pass


def _cancelled_result(query_id: str) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "status": "CANCELLED",
        "rows": [],
        "evidence_complete": False,
        "zero_result_suspicious": False,
        "filters": {},
        "sampling": {"applied": False, "returned_rows": 0, "total_rows": 0},
        "masking": {"applied": False, "fields": ()},
    }
