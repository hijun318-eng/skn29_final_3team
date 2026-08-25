"""AST binding과 capability 승인이 끝난 SQL만 Trino에서 실행하고 bounded terminal evidence를 관리한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable

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
        self._lifecycle: ContextVar[
            Callable[[dict[str, Any]], Awaitable[None]] | None
        ] = ContextVar("query_execution_lifecycle", default=None)

    def bind_cancellation(self, check: Callable[[], bool] | None) -> None:
        """현재 request context에만 적용할 취소 predicate를 등록해 concurrent query 사이의 취소 전파를 막는다."""
        self._cancellation.set(check)

    def bind_lifecycle_sink(
        self,
        sink: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        """현재 request의 durable query lifecycle sink만 async context에 결속한다."""

        self._lifecycle.set(sink)

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
        first: QueryPage | None = None
        sql_hash = _sql_hash(sql)
        try:
            first = await self._client.execute(sql, deadline=deadline)
            if first.next_uri:
                self._validate_query_uri(first.query_id, first.next_uri)
                await self._remember_next_uri(first.query_id, first.next_uri)
                try:
                    await self._notify_lifecycle(
                        {
                            "event_type": "SUBMITTED",
                            "query_id": first.query_id,
                            "cancel_uri": first.next_uri,
                            "sql_hash": sql_hash,
                            "status": "RUNNING",
                        }
                    )
                except BaseException:
                    # 실행은 시작됐는데 durable admission을 기록하지 못하면 coordinator에
                    # 남겨 두지 않는다. 취소 확인 실패도 원래 persistence 오류로 숨기지 않는다.
                    await self._cancel_uri_strict(first.next_uri)
                    await self._forget_next_uri(first.query_id)
                    raise
            result = await self._collect(first, deadline)
            await self._notify_lifecycle(
                {
                    "event_type": "TERMINAL",
                    "query_id": first.query_id,
                    "sql_hash": sql_hash,
                    "status": str(result["status"]),
                    "row_count": len(result.get("rows", ())),
                    "scan_bytes": int(result.get("scan_bytes", 0)),
                }
            )
            await self._forget_next_uri(first.query_id)
        except asyncio.CancelledError:
            if first is not None:
                uri = await self._next_uri(first.query_id)
                if uri:
                    await self._cancel_uri_strict(uri)
                    await self._notify_lifecycle(
                        {
                            "event_type": "TERMINAL",
                            "query_id": first.query_id,
                            "sql_hash": sql_hash,
                            "status": "CANCELLED",
                            "row_count": 0,
                            "scan_bytes": 0,
                        }
                    )
                    await self._forget_next_uri(first.query_id)
            raise
        except AdapterError as error:
            if first is not None:
                await self._record_adapter_failure(first.query_id, sql_hash, error)
            if error.code is AdapterErrorCode.TIMEOUT:
                raise TimeoutError(str(error)) from error
            if error.code is AdapterErrorCode.UPSTREAM:
                raise ConnectionError(str(error)) from error
            raise ValueError(str(error)) from error
        except Exception:
            # lifecycle/shape 검증과 같은 local 실패도 이미 제출된 query를 실제로
            # 취소한 뒤에만 upstream으로 전파한다. 실패하면 URI를 durable RUNNING으로
            # 남겨 reconciler가 재시도할 수 있게 한다.
            if first is not None:
                uri = await self._next_uri(first.query_id)
                if uri:
                    await self._cancel_uri_strict(uri)
                    await self._notify_lifecycle(
                        {
                            "event_type": "TERMINAL",
                            "query_id": first.query_id,
                            "sql_hash": sql_hash,
                            "status": "CANCELLED",
                            "row_count": 0,
                            "scan_bytes": 0,
                        }
                    )
                    await self._forget_next_uri(first.query_id)
            raise
        await self._store(result)
        return dict(result)

    async def execute_auxiliary(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        """Context 검증용 query를 main analysis lifecycle receipt와 분리해 실행한다.

        필터 값 존재 확인처럼 본 분석 SQL 전에 실행되는 bounded query는 동일한 AST
        capability·deadline·cancel 규칙을 사용하지만 ``query.query_executions``의 본 실행
        attempt로 기록되면 안 된다. ContextVar token으로 현재 task에서만 sink를 잠시
        비활성화하고, 완료·실패와 무관하게 원래 callback을 정확히 복원한다.
        """

        token = self._lifecycle.set(None)
        try:
            return await self.execute(sql, parameters, gate_token)
        finally:
            self._lifecycle.reset(token)

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
        """현재 process가 기억하는 URI가 있을 때만 coordinator 취소를 확정한다."""
        next_uri = await self._next_uri(query_id)
        if next_uri:
            return await self.cancel_at(query_id, next_uri)
        async with self._lock:
            self._prune_locked()
            state = self._queries.get(query_id)
        return (
            dict(state.result)
            if state is not None
            else {"query_id": query_id, "status": "NOT_FOUND"}
        )

    async def cancel_at(self, query_id: str, next_uri: str) -> dict[str, Any]:
        """재시작 뒤에도 durable same-query URI로 coordinator 취소를 확인한다."""

        try:
            await self._client.cancel_query(
                query_id,
                next_uri,
                deadline=monotonic() + min(1.0, self._timeout_seconds),
            )
            status = "CANCELLED"
        except AdapterError as error:
            if error.code is AdapterErrorCode.NOT_FOUND:
                status = "NOT_FOUND"
            else:
                raise
        async with self._lock:
            self._prune_locked()
            self._next_uris.pop(query_id, None)
            self._queries.pop(query_id, None)
        return {"query_id": query_id, "status": status}

    async def _collect(self, first: QueryPage, deadline: float) -> dict[str, Any]:
        page = first
        query_id = first.query_id
        columns = first.columns
        rows = list(first.rows)
        warnings = list(first.warnings)
        processed_rows = first.processed_rows
        scan_bytes = max(first.processed_bytes, first.physical_input_bytes)
        self._validate_page(page, query_id, columns)
        if self._cancel_requested():
            await self._cancel_uri_strict(page.next_uri)
            return _cancelled_result(query_id)
        while page.next_uri:
            self._validate_query_uri(query_id, page.next_uri)
            await self._remember_next_uri(query_id, page.next_uri)
            await self._notify_lifecycle(
                {
                    "event_type": "HEARTBEAT",
                    "query_id": query_id,
                    "cancel_uri": page.next_uri,
                    "status": "RUNNING",
                }
            )
            if monotonic() >= deadline:
                await self._cancel_uri_strict(page.next_uri)
                raise AdapterError(
                    AdapterErrorCode.TIMEOUT,
                    "query total deadline exceeded",
                )
            if self._cancel_requested():
                await self._cancel_uri_strict(page.next_uri)
                return _cancelled_result(query_id)
            try:
                page = await self._client.next_page(page.next_uri, deadline=deadline)
            except AdapterError as error:
                if error.code is AdapterErrorCode.TIMEOUT:
                    await self._cancel_uri_strict(await self._next_uri(query_id))
                raise
            if page.next_uri:
                await self._remember_next_uri(query_id, page.next_uri)
            self._validate_page(page, query_id, columns)
            columns = page.columns or columns
            rows.extend(page.rows)
            warnings.extend(page.warnings)
            processed_rows = max(processed_rows, page.processed_rows)
            scan_bytes = max(
                scan_bytes,
                page.processed_bytes,
                page.physical_input_bytes,
            )
            if len(rows) > self._max_result_rows:
                await self._cancel_uri_strict(page.next_uri)
                raise AdapterError(
                    AdapterErrorCode.QUERY,
                    "query result exceeds the configured row bound",
                )
        if page.state != "FINISHED":
            raise AdapterError(AdapterErrorCode.QUERY, "query did not finish")
        if len(columns) != len(set(columns)):
            raise AdapterError(AdapterErrorCode.QUERY, "query columns are duplicate")
        shaped = [dict(zip(columns, row, strict=True)) for row in rows]
        warning_messages = tuple(dict.fromkeys(w for w in warnings if w))
        # Trino warning은 진단 정보이며 결과 coverage가 불완전하다는 계약이 아니다.
        # nextUri를 끝까지 소비하고 FINISHED를 확인한 query는 warning 문구와 무관하게
        # 성공으로 유지한다. PARTIAL은 별도의 typed coverage 근거가 생길 때만 허용한다.
        return {
            "query_id": query_id,
            "status": "SUCCEEDED",
            "rows": shaped,
            "processed_rows": processed_rows,
            "scan_bytes": scan_bytes,
            "warnings": warning_messages,
            "warning_count": len(warning_messages),
            "critical_warning_count": 0,
            "result_metadata": result_metadata(shaped, columns),
            "evidence_complete": True,
            "zero_result_suspicious": not shaped,
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

    def _validate_query_uri(self, query_id: str, uri: str) -> None:
        validator = getattr(self._client, "validate_query_uri", None)
        if callable(validator):
            validator(query_id, uri)

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

    async def _notify_lifecycle(self, event: dict[str, Any]) -> None:
        sink = self._lifecycle.get()
        if sink is not None:
            await sink(dict(event))

    async def _record_adapter_failure(
        self,
        query_id: str,
        sql_hash: str,
        error: AdapterError,
    ) -> None:
        uri = await self._next_uri(query_id)
        terminal_status: str | None = None
        if error.code is AdapterErrorCode.CANCELLED:
            terminal_status = "CANCELLED"
        elif error.code is AdapterErrorCode.QUERY and uri is None:
            terminal_status = "FAILED"
        elif uri:
            try:
                await self._cancel_uri_strict(uri)
                terminal_status = "CANCELLED"
            except AdapterError:
                # durable URI를 유지하면 재시작 worker가 실제 취소를 다시 시도한다.
                return
        if terminal_status is not None:
            await self._notify_lifecycle(
                {
                    "event_type": "TERMINAL",
                    "query_id": query_id,
                    "sql_hash": sql_hash,
                    "status": terminal_status,
                    "row_count": 0,
                    "scan_bytes": 0,
                    "error_code": error.code.value,
                }
            )
            await self._forget_next_uri(query_id)

    async def _cancel_uri_strict(self, uri: str | None) -> None:
        if not uri:
            return
        await self._client.cancel(
            uri,
            deadline=monotonic() + min(1.0, self._timeout_seconds),
        )


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


def _sql_hash(sql: str) -> str:
    """Analysis persistence의 canonical string hash와 동일한 SHA-256 receipt를 만든다."""

    encoded = json.dumps(sql, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()
