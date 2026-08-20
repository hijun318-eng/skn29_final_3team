"""실제 Trino에서 release의 Source 수량·View·cross-source·timeout/cancel 계약을 검증한다."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.adapters.trino_async import (  # noqa: E402
    AdapterError,
    AdapterErrorCode,
    QueryPage,
    TrinoAsyncClient,
)
from inspect_release_views import build_plan  # noqa: E402


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
QUERY_ID = re.compile(r"^[A-Za-z0-9_:-]{3,128}$")


@dataclass(frozen=True)
class QueryReceipt:
    """한 live statement의 식별자·실행시간·반환 행 수·SQL hash만 보존한다."""

    query_id: str
    duration_seconds: float
    row_count: int
    sql_sha256: str

    def value(self) -> dict[str, object]:
        """secret이나 SQL 원문 없이 JSON receipt 필드를 반환한다."""

        return {
            "query_id": self.query_id,
            "duration_seconds": self.duration_seconds,
            "row_count": self.row_count,
            "sql_sha256": self.sql_sha256,
        }


def _required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"required process environment is missing: {name}")
    return value


def _identifier(value: object, label: str) -> str:
    text = str(value or "")
    if IDENTIFIER.fullmatch(text) is None:
        raise ValueError(f"{label} is not a safe Trino identifier")
    return text


def _quoted(*parts: str) -> str:
    return ".".join(f'"{_identifier(part, "identifier")}"' for part in parts)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _release(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("release manifest shape is invalid")
    release_root = manifest_path.parent
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("release file receipt is invalid")
        relative = item.get("relative_path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("release file receipt is invalid")
        path = (release_root / relative).resolve(strict=True)
        if release_root.resolve() not in path.parents:
            raise ValueError("release file escaped its directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected.casefold():
            raise ValueError(f"release checksum mismatch: {relative}")
    return manifest, release_root


def _configured_catalogs(
    catalog_directory: Path, serving_catalog: str
) -> tuple[str, ...]:
    names = tuple(
        sorted(
            _identifier(path.stem, "catalog file")
            for path in catalog_directory.glob("*.properties")
            if path.stem != serving_catalog
        )
    )
    if not names:
        raise ValueError("source catalog configuration is empty")
    return names


def _source_catalogs(paths: tuple[Path, ...], serving_catalog: str) -> tuple[str, ...]:
    """release SQL이 실제 참조하는 source catalog만 AST에서 추출한다."""

    names: set[str] = set()
    for path in paths:
        for statement in parse(
            path.read_text(encoding="utf-8-sig"),
            read="trino",
            error_level=ErrorLevel.RAISE,
        ):
            for table in statement.find_all(exp.Table):
                catalog = str(table.catalog)
                if catalog and catalog != serving_catalog:
                    names.add(_identifier(catalog, "source catalog"))
    if not names:
        raise ValueError("release SQL references no source catalogs")
    return tuple(sorted(names))


async def _query(
    client: TrinoAsyncClient,
    sql: str,
    *,
    timeout_seconds: float = 180.0,
    max_pages: int = 2_000,
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], QueryReceipt]:
    started = monotonic()
    deadline = started + timeout_seconds
    page = await client.execute(sql, deadline=deadline)
    query_id = page.query_id
    columns = page.columns
    rows = list(page.rows)
    for _ in range(max_pages):
        if page.next_uri is None:
            if page.state != "FINISHED":
                raise RuntimeError(f"query did not finish: {query_id}")
            receipt = QueryReceipt(
                query_id=query_id,
                duration_seconds=round(monotonic() - started, 3),
                row_count=len(rows),
                sql_sha256=_sha256(sql),
            )
            return columns, tuple(rows), receipt
        page = await client.next_page(page.next_uri, deadline=deadline)
        if columns and page.columns and page.columns != columns:
            raise RuntimeError("Trino columns changed between pages")
        columns = page.columns or columns
        rows.extend(page.rows)
    raise RuntimeError("Trino query exceeded the page bound")


async def _source_inventory(
    client: TrinoAsyncClient,
    catalogs: tuple[str, ...],
    source_schema: str,
) -> tuple[list[dict[str, object]], int, int, tuple[str, int]]:
    inventory: list[dict[str, object]] = []
    total_tables = 0
    total_rows = 0
    largest = ("", -1)
    for catalog in catalogs:
        sql = (
            "SELECT table_name FROM "
            f"{_quoted(catalog, 'information_schema', 'tables')} "
            f"WHERE table_schema = '{source_schema}' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        columns, rows, discovery = await _query(client, sql)
        if columns != ("table_name",) or not rows:
            raise RuntimeError(f"source catalog has no release tables: {catalog}")
        tables: list[dict[str, object]] = []
        for row in rows:
            table = _identifier(row[0], "live table")
            count_sql = f"SELECT count(*) AS row_count FROM {_quoted(catalog, source_schema, table)}"
            count_columns, count_rows, count_receipt = await _query(client, count_sql)
            if count_columns != ("row_count",) or len(count_rows) != 1:
                raise RuntimeError(f"table count shape is invalid: {catalog}.{table}")
            count = count_rows[0][0]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise RuntimeError(f"table count is invalid: {catalog}.{table}")
            fqn = f"{catalog}.{source_schema}.{table}"
            tables.append(
                {
                    "fqn": fqn,
                    "row_count": count,
                    "count_query": count_receipt.value(),
                }
            )
            total_tables += 1
            total_rows += count
            if count > largest[1]:
                largest = (fqn, count)
        inventory.append(
            {
                "catalog": catalog,
                "table_count": len(tables),
                "row_count": sum(int(item["row_count"]) for item in tables),
                "discovery_query": discovery.value(),
                "tables": tables,
            }
        )
    return inventory, total_tables, total_rows, largest


async def _serving_inventory(
    client: TrinoAsyncClient,
    serving_catalog: str,
    serving_schema: str,
    declared_views: tuple[str, ...],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    sql = (
        "SELECT table_name FROM "
        f"{_quoted(serving_catalog, 'information_schema', 'tables')} "
        f"WHERE table_schema = '{serving_schema}' AND table_type = 'VIEW' "
        "ORDER BY table_name"
    )
    columns, rows, discovery = await _query(client, sql)
    if columns != ("table_name",):
        raise RuntimeError("serving inventory shape is invalid")
    observed = tuple(
        f"{serving_catalog}.{serving_schema}.{_identifier(row[0], 'live view')}"
        for row in rows
    )
    if observed != declared_views:
        raise RuntimeError("live serving View identities differ from release SQL")
    probes: list[dict[str, object]] = []
    for fqn in declared_views:
        catalog, schema, table = fqn.split(".")
        probe_sql = f"SELECT * FROM {_quoted(catalog, schema, table)} LIMIT 1"
        _, probe_rows, receipt = await _query(client, probe_sql)
        probes.append(
            {
                "view": fqn,
                "returned_rows": len(probe_rows),
                "query": receipt.value(),
            }
        )
    return {
        "view_count": len(observed),
        "views": observed,
        "discovery_query": discovery.value(),
    }, probes


def _cross_source_statement(
    paths: tuple[Path, ...], required_catalogs: frozenset[str]
) -> tuple[str, tuple[str, ...]]:
    for path in paths:
        for statement in parse(
            path.read_text(encoding="utf-8-sig"),
            read="trino",
            error_level=ErrorLevel.RAISE,
        ):
            if not isinstance(statement, exp.Query):
                continue
            catalogs = frozenset(
                str(table.catalog)
                for table in statement.find_all(exp.Table)
                if table.catalog
            )
            if required_catalogs.issubset(catalogs):
                sql = statement.sql(dialect="trino")
                return f"SELECT * FROM ({sql}) AS raw_smoke LIMIT 1", tuple(sorted(catalogs))
    raise ValueError("release has no required raw cross-source validation statement")


async def _timeout_cancel(
    client: TrinoAsyncClient,
    largest_table: str,
) -> dict[str, object]:
    parts = tuple(_identifier(part, "largest table") for part in largest_table.split("."))
    if len(parts) != 3:
        raise ValueError("largest table FQN is invalid")
    table = _quoted(*parts)
    sql = f"SELECT count(*) FROM {table} a CROSS JOIN {table} b CROSS JOIN {table} c"
    page = await client.execute(sql, deadline=monotonic() + 15.0)
    query_id = page.query_id
    next_uri = page.next_uri
    if next_uri is None:
        raise RuntimeError("timeout probe finished before it could be cancelled")
    deadline = monotonic() + 0.25
    timed_out = False
    try:
        while next_uri is not None:
            page = await client.next_page(next_uri, deadline=deadline)
            next_uri = page.next_uri
    except AdapterError as error:
        if error.code is not AdapterErrorCode.TIMEOUT:
            raise
        timed_out = True
    if not timed_out or next_uri is None:
        raise RuntimeError("live timeout path was not observed")
    await client.cancel(next_uri, deadline=monotonic() + 5.0)
    terminal_error: AdapterErrorCode | None = None
    for _ in range(10):
        try:
            page = await client.next_page(next_uri, deadline=monotonic() + 2.0)
            next_uri = page.next_uri or next_uri
        except AdapterError as error:
            if error.code is AdapterErrorCode.CANCELLED:
                terminal_error = error.code
                break
            if error.code is not AdapterErrorCode.UPSTREAM:
                raise
        await asyncio.sleep(0.2)
    if terminal_error is None:
        # DELETE가 2xx로 수락된 뒤 coordinator가 page를 즉시 폐기하면 GET은 404가 될
        # 수 있다. 이 경우에도 cancel request 성공은 실제 coordinator acknowledgement다.
        # 다만 CANCELLED page와 구분해 receipt에 명시하고 성공을 terminal state로 꾸미지 않는다.
        terminal_state = "COORDINATOR_ACKNOWLEDGED_AND_PAGE_REMOVED"
    else:
        terminal_state = terminal_error.value
    if not QUERY_ID.fullmatch(query_id):
        raise RuntimeError("timeout probe query id is invalid")
    return {
        "query_id": query_id,
        "source_table": largest_table,
        "sql_sha256": _sha256(sql),
        "timeout_observed": True,
        "cancel_sent": True,
        "terminal_state": terminal_state,
        "terminal_page_observed": terminal_error is not None,
    }


async def verify(args: argparse.Namespace) -> dict[str, object]:
    """같은 release·principal로 모든 D0/D1 live 검증을 실행해 PASS receipt를 만든다."""

    manifest, release_root = _release(args.manifest.resolve(strict=True))
    release_id = str(manifest.get("release_id") or "")
    expected = manifest.get("expected") or {}
    source_schema = _identifier((manifest.get("namespaces") or {}).get("source"), "source schema")
    serving_namespace = str((manifest.get("namespaces") or {}).get("serving") or "")
    serving_parts = serving_namespace.split(".")
    if len(serving_parts) != 2:
        raise ValueError("serving namespace must use catalog.schema form")
    serving_catalog, serving_schema = (
        _identifier(serving_parts[0], "serving catalog"),
        _identifier(serving_parts[1], "serving schema"),
    )
    plan = build_plan(args.manifest.resolve(strict=True), serving_namespace)
    serving_paths = tuple(
        (release_root / str(item["relative_path"])).resolve(strict=True)
        for item in plan["files"]
    )
    declared_views = tuple(str(item) for item in plan["views"])
    configured_catalogs = _configured_catalogs(
        args.catalog_directory.resolve(strict=True), serving_catalog
    )
    catalogs = _source_catalogs(serving_paths, serving_catalog)
    if not set(catalogs).issubset(configured_catalogs):
        raise ValueError("release source catalogs are absent from runtime configuration")
    required_raw = frozenset(_identifier(item, "required raw catalog") for item in args.required_raw_catalog)
    if not required_raw.issubset(catalogs):
        raise ValueError("required raw catalogs are absent from runtime configuration")

    async with TrinoAsyncClient(
        _required_env("ANSWERVICE_VERIFY_TRINO_URL"),
        _required_env("ANSWERVICE_VERIFY_TRINO_USER"),
        _required_env("ANSWERVICE_VERIFY_TRINO_PASSWORD"),
        ca_file=_required_env("ANSWERVICE_VERIFY_TRINO_CA_FILE"),
        request_timeout_seconds=30.0,
    ) as client:
        sources, table_count, row_count, largest = await _source_inventory(
            client, catalogs, source_schema
        )
        if table_count != int(expected.get("physical_tables", -1)):
            raise RuntimeError("live physical table count differs from release manifest")
        if row_count != int(expected.get("rows", -1)):
            raise RuntimeError("live row count differs from release manifest")
        serving, view_probes = await _serving_inventory(
            client, serving_catalog, serving_schema, declared_views
        )
        if serving["view_count"] != int(expected.get("serving_views", -1)):
            raise RuntimeError("live serving View count differs from release manifest")
        raw_sql, raw_catalogs = _cross_source_statement(serving_paths, required_raw)
        _, raw_rows, raw_receipt = await _query(client, raw_sql)
        cancel_receipt = await _timeout_cancel(client, largest[0])

    return {
        "schema_version": "answervice.d0-d1-trino-receipt.v1",
        "release_id": release_id,
        "base_sha": _required_env("ANSWERVICE_VERIFY_BASE_SHA"),
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observed": {
            "physical_tables": table_count,
            "rows": row_count,
            "serving_views": serving["view_count"],
        },
        "source_inventory": sources,
        "serving_inventory": serving,
        "view_smoke_queries": view_probes,
        "raw_cross_source_smoke": {
            "required_catalogs": sorted(required_raw),
            "observed_catalogs": raw_catalogs,
            "returned_rows": len(raw_rows),
            "query": raw_receipt.value(),
        },
        "timeout_cancel": cancel_receipt,
        "status": "PASS",
    }


def main() -> int:
    """경로와 raw catalog 계약을 받아 live receipt JSON을 원자적으로 기록한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--catalog-directory", required=True, type=Path)
    parser.add_argument("--required-raw-catalog", nargs="+", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = asyncio.run(verify(args))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(output)
    print(
        "TRINO_RELEASE_VERIFIED|"
        f"tables={receipt['observed']['physical_tables']}|"
        f"rows={receipt['observed']['rows']}|"
        f"views={receipt['observed']['serving_views']}|{output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
