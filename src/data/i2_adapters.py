"""Typed, dependency-free adapters for the I2 deterministic data slice."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AdapterErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"
    UPSTREAM = "UPSTREAM"


class AdapterError(RuntimeError):
    def __init__(self, code: AdapterErrorCode, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DatasetRef:
    urn: str
    fqn: str


@dataclass(frozen=True)
class SearchPage:
    items: tuple[DatasetRef, ...]
    next_offset: int | None


@dataclass(frozen=True)
class QueryPage:
    query_id: str
    state: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    next_uri: str | None
    warnings: tuple[str, ...] = ()


JsonTransport = Callable[[str, str, Any | None], dict[str, Any]]


def _http_json(method: str, url: str, body: Any | None) -> dict[str, Any]:
    data = None
    content_type = "application/json"
    if isinstance(body, str):
        data = body.encode("utf-8")
        content_type = "text/plain"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": content_type},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
    except HTTPError as error:
        code = AdapterErrorCode.FORBIDDEN if error.code in (401, 403) else AdapterErrorCode.UPSTREAM
        raise AdapterError(code, f"upstream HTTP {error.code}") from error
    except TimeoutError as error:
        raise AdapterError(AdapterErrorCode.TIMEOUT, "upstream request timed out") from error
    except URLError as error:
        raise AdapterError(AdapterErrorCode.UPSTREAM, "upstream request failed") from error
    return {} if not raw else json.loads(raw)


class DataHubAdapter:
    def __init__(self, base_url: str, transport: JsonTransport = _http_json):
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def search(self, query: str, offset: int = 0, limit: int = 20) -> SearchPage:
        params = urlencode({"query": query, "start": offset, "count": limit})
        payload = self.transport("GET", f"{self.base_url}/entities?action=search&{params}", None)
        entities = payload.get("value", {}).get("entities", [])
        items = tuple(
            DatasetRef(
                urn=item["entity"],
                fqn=item.get("matchedFields", [{}])[0].get("value", item["entity"]),
            )
            for item in entities
        )
        if not items and offset == 0:
            raise AdapterError(AdapterErrorCode.NOT_FOUND, "no matching dataset")
        total = int(payload.get("value", {}).get("numEntities", len(items)))
        return SearchPage(items, offset + len(items) if offset + len(items) < total else None)

    def graph(self, urn: str) -> dict[str, Any]:
        return self.transport(
            "GET",
            f"{self.base_url}/relationships?{urlencode({'urn': urn})}",
            None,
        )

    def health(self) -> bool:
        return bool(self.transport("GET", f"{self.base_url}/config", None))


class TrinoAdapter:
    TERMINAL_STATES = {"FINISHED", "FAILED", "CANCELED"}

    def __init__(self, base_url: str, transport: JsonTransport = _http_json):
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    @staticmethod
    def _page(payload: dict[str, Any]) -> QueryPage:
        stats = payload.get("stats", {})
        error = payload.get("error")
        if error:
            raise AdapterError(AdapterErrorCode.UPSTREAM, error.get("message", "query failed"))
        state = stats.get("state", "QUEUED")
        warnings = tuple(item.get("message", "") for item in payload.get("warnings", []))
        columns = tuple(item["name"] for item in payload.get("columns", []))
        rows = tuple(tuple(row) for row in payload.get("data", []))
        next_uri = payload.get("nextUri")
        if state == "CANCELED":
            raise AdapterError(AdapterErrorCode.CANCELLED, "query was cancelled")
        if state == "FINISHED" and next_uri is None and warnings:
            raise AdapterError(AdapterErrorCode.PARTIAL, "; ".join(warnings))
        return QueryPage(payload["id"], state, columns, rows, next_uri, warnings)

    def execute(self, sql: str) -> QueryPage:
        return self._page(self.transport("POST", f"{self.base_url}/v1/statement", sql))

    def next_page(self, next_uri: str) -> QueryPage:
        return self._page(self.transport("GET", next_uri, None))

    def cancel(self, next_uri: str) -> None:
        self.transport("DELETE", next_uri, None)

    def health(self) -> bool:
        return bool(self.transport("GET", f"{self.base_url}/v1/info", None))
