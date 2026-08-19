"""Trino 비동기 HTTP protocol로 physical release schema를 동적으로 발견한다."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

import httpx
from sqlglot import exp

from release_scope import ReleaseScope


class TrinoDiscoveryError(RuntimeError):
    """Trino가 완전하고 제한된 information_schema inventory를 만들지 못했음을 나타낸다."""


@dataclass(frozen=True)
class PhysicalColumn:
    """Trino information_schema에서 발견한 physical column 하나를 표현한다."""

    ordinal_position: int
    name: str
    native_type: str
    nullable: bool

    def contract_value(self) -> dict[str, object]:
        """정규 hash에 포함할 안정적인 schema contract field만 반환한다."""

        return {
            "ordinal_position": self.ordinal_position,
            "name": self.name,
            "native_type": self.native_type,
            "nullable": self.nullable,
        }


@dataclass(frozen=True)
class PhysicalRelation:
    """runtime scope의 relation과 순서가 보존된 physical column을 표현한다."""

    scope: ReleaseScope
    name: str
    table_type: str
    columns: tuple[PhysicalColumn, ...]

    @property
    def fqn(self) -> str:
        """발견된 scope 구성요소에서 physical fully qualified name을 만든다."""

        return f"{self.scope.catalog}.{self.scope.schema}.{self.name}"


@dataclass(frozen=True)
class TrinoInventory:
    """제한된 physical inventory와 discovery 증거 query ID를 함께 보관한다."""

    relations: tuple[PhysicalRelation, ...]
    query_ids: tuple[str, ...]

    @property
    def column_count(self) -> int:
        """readiness 수량 대조를 위해 발견된 전체 column 수를 계산한다."""

        return sum(len(relation.columns) for relation in self.relations)


class TrinoMetadataClient:
    """인증된 HTTPS 세션으로 connector catalog와 scoped relation만 읽는다.

    실제 network transport를 소유하는 경우에는 password와 repository 밖에서
    배포된 CA 파일을 모두 요구한다. 주입 transport는 응답 protocol을 결정론적으로
    검증하는 ``httpx.MockTransport``에만 허용하므로 운영 호출자가 TLS 검증을
    우회하는 client를 끼워 넣을 수 없다.
    """

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        ca_file: str | Path | None = None,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
        concurrency: int = 8,
        max_relations: int = 2_000,
        max_columns: int = 100_000,
        max_pages: int = 1_000,
    ) -> None:
        endpoint = httpx.URL(base_url)
        if (
            endpoint.scheme != "https"
            or not endpoint.host
            or endpoint.username
            or endpoint.password
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
            or not user.strip()
            or not isinstance(password, str)
            or not password
            or timeout_seconds <= 0
            or concurrency < 1
            or max_relations < 1
            or max_columns < 1
            or max_pages < 1
        ):
            raise ValueError("Trino discovery configuration is invalid")
        self._base_url = str(endpoint).rstrip("/")
        self._origin = _origin(endpoint)
        self._user = user.strip()
        self._timeout = timeout_seconds
        self._concurrency = concurrency
        self._max_relations = max_relations
        self._max_columns = max_columns
        self._max_pages = max_pages
        self._auth = httpx.BasicAuth(self._user, password)
        self._owns_http = http is None
        if http is not None:
            # WHY: 외부 AsyncClient 일반 주입을 허용하면 verify=False transport가 운영
            # 경로로 들어올 수 있다. 네트워크가 없는 MockTransport만 테스트 seam이다.
            if not isinstance(getattr(http, "_transport", None), httpx.MockTransport):
                raise ValueError("only httpx.MockTransport may be injected")
            self._http = http
        else:
            ca_path = _validated_ca_file(ca_file)
            self._http = httpx.AsyncClient(verify=str(ca_path), trust_env=False)

    async def discover(
        self,
        scopes: tuple[ReleaseScope, ...],
    ) -> TrinoInventory:
        """metadata query만 사용해 catalog·relation·column inventory를 발견한다."""

        if not scopes:
            raise TrinoDiscoveryError("release discovery has no Trino scopes")
        catalog_columns, catalog_rows, catalog_query_id = await self._execute(
            _catalog_query()
        )
        if catalog_columns != ("catalog_name", "connector_name"):
            raise TrinoDiscoveryError("system.metadata.catalogs shape is invalid")
        catalogs = _catalogs(catalog_rows)
        requested = {scope.catalog for scope in scopes}
        missing = requested - set(catalogs)
        if missing:
            raise TrinoDiscoveryError(
                f"runtime recipe catalogs are unavailable: {sorted(missing)}"
            )
        relation_specs: list[tuple[ReleaseScope, str, str]] = []
        query_ids = [catalog_query_id]
        for scope in scopes:
            columns, rows, query_id = await self._execute(_relations_query(scope))
            query_ids.append(query_id)
            if columns != ("table_name", "table_type"):
                raise TrinoDiscoveryError("information_schema.tables shape is invalid")
            for row in rows:
                if (
                    len(row) != 2
                    or not isinstance(row[0], str)
                    or not row[0]
                    or not isinstance(row[1], str)
                    or not row[1]
                ):
                    raise TrinoDiscoveryError("information_schema.tables row is invalid")
                relation_specs.append((scope, row[0], row[1]))
                if len(relation_specs) > self._max_relations:
                    raise TrinoDiscoveryError("Trino relation discovery exceeded its bound")
        if not relation_specs:
            raise TrinoDiscoveryError("runtime recipe scopes contain no relations")
        semaphore = asyncio.Semaphore(self._concurrency)

        async def inspect(
            spec: tuple[ReleaseScope, str, str],
        ) -> tuple[PhysicalRelation, str]:
            async with semaphore:
                scope, table, table_type = spec
                columns, rows, query_id = await self._execute(
                    _columns_query(scope, table)
                )
                return (
                    PhysicalRelation(
                        scope,
                        table,
                        table_type,
                        _physical_columns(columns, rows),
                    ),
                    query_id,
                )

        inspected = await asyncio.gather(*(inspect(spec) for spec in relation_specs))
        relations = tuple(sorted((item[0] for item in inspected), key=lambda item: item.fqn))
        query_ids.extend(item[1] for item in inspected)
        column_count = sum(len(item.columns) for item in relations)
        if column_count > self._max_columns:
            raise TrinoDiscoveryError("Trino column discovery exceeded its bound")
        return TrinoInventory(relations, tuple(query_ids))

    async def _execute(
        self,
        expression: exp.Expression,
    ) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...], str]:
        deadline = monotonic() + self._timeout
        payload = await self._request(
            "POST",
            f"{self._base_url}/v1/statement",
            expression.sql(dialect="trino", identify=True),
            deadline,
        )
        query_id = payload.get("id")
        if not isinstance(query_id, str) or not query_id:
            raise TrinoDiscoveryError("Trino response is missing a query id")
        names: tuple[str, ...] = ()
        rows: list[tuple[object, ...]] = []
        pages = 0
        while True:
            pages += 1
            if pages > self._max_pages:
                raise TrinoDiscoveryError("Trino pagination exceeded its bound")
            _raise_query_error(payload)
            raw_columns = payload.get("columns")
            if raw_columns is not None:
                if not isinstance(raw_columns, list):
                    raise TrinoDiscoveryError("Trino columns are invalid")
                try:
                    names = tuple(item["name"] for item in raw_columns)
                except (KeyError, TypeError) as error:
                    raise TrinoDiscoveryError("Trino columns are invalid") from error
            raw_rows = payload.get("data") or []
            if not isinstance(raw_rows, list) or any(not isinstance(row, list) for row in raw_rows):
                raise TrinoDiscoveryError("Trino rows are invalid")
            rows.extend(tuple(row) for row in raw_rows)
            next_uri = payload.get("nextUri")
            if next_uri is None:
                state = (payload.get("stats") or {}).get("state")
                if state != "FINISHED":
                    raise TrinoDiscoveryError("Trino metadata query did not finish")
                break
            self._validate_next_uri(next_uri)
            payload = await self._request("GET", next_uri, None, deadline)
        return names, tuple(rows), query_id

    async def _request(
        self,
        method: str,
        url: str,
        body: str | None,
        deadline: float,
    ) -> dict[str, Any]:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TrinoDiscoveryError("Trino metadata query timed out")
        try:
            response = await self._http.request(
                method,
                url,
                content=body.encode("utf-8") if body is not None else None,
                headers={
                    "X-Trino-User": self._user,
                    "Content-Type": "text/plain; charset=utf-8",
                },
                auth=self._auth,
                timeout=min(self._timeout, remaining),
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            raise TrinoDiscoveryError("Trino metadata query timed out") from error
        except (httpx.HTTPError, ValueError) as error:
            raise TrinoDiscoveryError("Trino metadata request failed") from error
        if not isinstance(payload, dict):
            raise TrinoDiscoveryError("Trino returned a non-object response")
        return payload

    def _validate_next_uri(self, value: object) -> None:
        try:
            uri = httpx.URL(value)
        except (TypeError, ValueError) as error:
            raise TrinoDiscoveryError("Trino nextUri is invalid") from error
        if (
            uri.username
            or uri.password
            or uri.fragment
            or _origin(uri) != self._origin
        ):
            raise TrinoDiscoveryError("Trino nextUri left the configured coordinator")

    async def aclose(self) -> None:
        """이 client가 생성해 소유한 HTTP transport만 닫는다."""

        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> TrinoMetadataClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


def _catalog_query() -> exp.Expression:
    table = exp.Table(
        this=exp.Identifier(this="catalogs", quoted=True),
        db=exp.Identifier(this="metadata", quoted=True),
        catalog=exp.Identifier(this="system", quoted=True),
    )
    return exp.select("catalog_name", "connector_name").from_(table).order_by("catalog_name")


def _relations_query(scope: ReleaseScope) -> exp.Expression:
    return (
        exp.select("table_name", "table_type")
        .from_(_information_schema_table(scope.catalog, "tables"))
        .where(exp.column("table_schema").eq(exp.Literal.string(scope.schema)))
        .order_by("table_name")
    )


def _columns_query(scope: ReleaseScope, table_name: str) -> exp.Expression:
    predicate = exp.and_(
        exp.column("table_schema").eq(exp.Literal.string(scope.schema)),
        exp.column("table_name").eq(exp.Literal.string(table_name)),
    )
    return (
        exp.select("ordinal_position", "column_name", "data_type", "is_nullable")
        .from_(_information_schema_table(scope.catalog, "columns"))
        .where(predicate)
        .order_by("ordinal_position")
    )


def _information_schema_table(catalog: str, name: str) -> exp.Table:
    return exp.Table(
        this=exp.Identifier(this=name, quoted=True),
        db=exp.Identifier(this="information_schema", quoted=True),
        catalog=exp.Identifier(this=catalog, quoted=True),
    )


def _catalogs(rows: tuple[tuple[object, ...], ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        if (
            len(row) != 2
            or not isinstance(row[0], str)
            or not row[0]
            or not isinstance(row[1], str)
            or not row[1]
            or row[0] in result
        ):
            raise TrinoDiscoveryError("system.metadata.catalogs row is invalid")
        if row[1] != "system":
            result[row[0]] = row[1]
    return result


def _physical_columns(
    names: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
) -> tuple[PhysicalColumn, ...]:
    if names != ("ordinal_position", "column_name", "data_type", "is_nullable"):
        raise TrinoDiscoveryError("information_schema.columns shape is invalid")
    result: list[PhysicalColumn] = []
    for expected_ordinal, row in enumerate(rows, start=1):
        if (
            len(row) != 4
            or not isinstance(row[0], int)
            or isinstance(row[0], bool)
            or row[0] != expected_ordinal
            or not isinstance(row[1], str)
            or not row[1]
            or not isinstance(row[2], str)
            or not row[2]
            or row[3] not in {"YES", "NO"}
        ):
            raise TrinoDiscoveryError("information_schema.columns row is invalid")
        result.append(PhysicalColumn(row[0], row[1], row[2], row[3] == "YES"))
    if not result:
        raise TrinoDiscoveryError("Trino relation has no columns")
    return tuple(result)


def _raise_query_error(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    if isinstance(error, dict):
        name = error.get("errorName")
        suffix = f" ({name})" if isinstance(name, str) and name else ""
        raise TrinoDiscoveryError(f"Trino metadata query failed{suffix}")


def _origin(value: httpx.URL) -> tuple[str, str, int]:
    port = value.port or (443 if value.scheme == "https" else 80)
    return value.scheme, str(value.host).casefold(), port


def _validated_ca_file(value: str | Path | None) -> Path:
    """owned HTTP client가 신뢰할 외부 CA 파일을 절대 경로로 확정한다.

    상대 경로나 존재하지 않는 파일을 허용하면 작업 디렉터리 또는 system trust
    store에 따라 신뢰 경계가 달라진다. 따라서 실제 파일인 절대 경로만 받는다.
    """

    if not isinstance(value, (str, Path)):
        raise ValueError("Trino CA file is required")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Trino CA file must be an absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError("Trino CA file is unavailable") from error
    if not resolved.is_file():
        raise ValueError("Trino CA file is unavailable")
    return resolved
