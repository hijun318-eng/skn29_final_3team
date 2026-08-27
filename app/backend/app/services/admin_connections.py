"""관리 화면이 조회할 승인된 dependency 상태를 실제 제한시간 probe로 투영한다.

대상 주소와 credential은 서버 설정과 기존 adapter만 소유하며 요청 body나 query로 받지
않는다. 응답은 공개 이름·상태·지연시간만 포함하고 URL·DSN·token은 노출하지 않는다.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from time import monotonic

import httpx

from app.adapters.trino_async import AdapterError, TrinoAsyncClient
from app.services.readiness import AppDatabaseReadiness


_SOURCE_CATALOGS = (
    ("pms", "PMS", "PostgreSQL"),
    ("pos", "POS", "MySQL"),
    ("crm", "CRM", "SQL Server"),
    ("facility", "Facility", "ClickHouse"),
    ("banquet", "Banquet", "PostgreSQL"),
)
_SOURCE_CATALOG_NAMES = frozenset(item[0] for item in _SOURCE_CATALOGS)


async def _timed_probe(
    connection_id: str,
    name: str,
    kind: str,
    check: Callable[[], Awaitable[bool]],
) -> dict[str, object]:
    """한 고정 probe의 예외를 down으로 닫고 종료 시각과 경과 밀리초를 기록한다."""

    started = monotonic()
    try:
        ready = await check()
    except Exception:
        ready = False
    return {
        "id": connection_id,
        "name": name,
        "kind": kind,
        "status": "ready" if ready else "down",
        "latency_ms": max(0, round((monotonic() - started) * 1000)),
        "checked_at": datetime.now(timezone.utc),
    }


async def _trino_catalog_ready(catalog: str) -> bool:
    """고정 source catalog의 information_schema를 runtime Trino principal로 읽는다.

    요청에서 catalog나 SQL을 받지 않으며 허용 목록 밖 값은 network 호출 전에 거부한다.
    각 호출은 자체 보안 client를 소유하고 성공·실패 모두에서 닫는다.
    """

    if catalog not in _SOURCE_CATALOG_NAMES:
        return False
    timeout = AppDatabaseReadiness._probe_timeout()
    trino: TrinoAsyncClient | None = None
    try:
        trino = TrinoAsyncClient(
            os.getenv("TRINO_URL", "https://trino:8443"),
            os.getenv("TRINO_RUNTIME_USER", ""),
            os.getenv("TRINO_RUNTIME_PASSWORD", ""),
            ca_file=os.getenv("TRINO_TLS_CA_FILE", "/run/secrets/trino-ca.pem"),
            request_timeout_seconds=timeout,
        )
        deadline = monotonic() + timeout
        page = await trino.execute(
            f'SELECT 1 FROM "{catalog}".information_schema.schemata LIMIT 1',
            deadline=deadline,
        )
        rows = list(page.rows)
        for _ in range(100):
            if page.next_uri is None:
                return (
                    page.state == "FINISHED"
                    and bool(rows)
                    and len(rows[0]) == 1
                    and rows[0][0] == 1
                )
            page = await trino.next_page(page.next_uri, deadline=deadline)
            rows.extend(page.rows)
        return False
    except (AdapterError, OSError, ValueError):
        return False
    finally:
        if trino is not None:
            await trino.aclose()


async def probe_admin_connections() -> tuple[dict[str, object], ...]:
    """고정 source 5개와 App PostgreSQL·Trino·DataHub·model을 병렬 확인한다."""

    readiness = AppDatabaseReadiness()

    async def database_ready() -> bool:
        return (await readiness._database_probe())["app_postgres"] == "ready"

    async def trino_ready() -> bool:
        return await readiness._trino_probe() == "ready"

    async def datahub_ready() -> bool:
        return await readiness._datahub_probe() == "ready"

    async def model_ready() -> bool:
        timeout = httpx.Timeout(readiness._probe_timeout())
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "answervice-admin-connection/1.0",
            },
            trust_env=False,
        ) as client:
            return await readiness._model_probe(client) == "ready"

    source_probes = tuple(
        _timed_probe(
            catalog,
            name,
            kind,
            lambda catalog=catalog: _trino_catalog_ready(catalog),
        )
        for catalog, name, kind in _SOURCE_CATALOGS
    )
    return tuple(
        await asyncio.gather(
            *source_probes,
            _timed_probe("app-postgres", "App PostgreSQL", "PostgreSQL", database_ready),
            _timed_probe("trino", "Trino", "HTTPS", trino_ready),
            _timed_probe("datahub", "DataHub", "HTTPS", datahub_ready),
            _timed_probe("model-api", "Model API", "HTTPS", model_ready),
        )
    )
