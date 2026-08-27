"""관리 연결 화면의 9개 고정 probe와 Trino source 경계를 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "app" / "backend"), str(ROOT)]

from app.adapters.trino_async import AdapterError, AdapterErrorCode  # noqa: E402
from app.services.admin_connections import (  # noqa: E402
    _SOURCE_CATALOGS,
    _trino_catalog_ready,
    probe_admin_connections,
)
from app.services.readiness import AppDatabaseReadiness  # noqa: E402


@pytest.mark.asyncio
async def test_source_catalog_probe_uses_only_fixed_read_only_sql_and_closes() -> None:
    calls: list[tuple[str, float]] = []
    closed: list[bool] = []

    class Trino:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def execute(self, sql: str, *, deadline: float):
            calls.append((sql, deadline))
            return SimpleNamespace(
                state="FINISHED", rows=((1,),), next_uri=None
            )

        async def aclose(self) -> None:
            closed.append(True)

    environment = {
        "TRINO_URL": "https://trino:8443",
        "TRINO_RUNTIME_USER": "runtime-user",
        "TRINO_RUNTIME_PASSWORD": "runtime-password",
        "TRINO_TLS_CA_FILE": "C:/server-owned/trino-ca.pem",
    }
    with patch.dict("os.environ", environment, clear=True), patch(
        "app.services.admin_connections.TrinoAsyncClient", Trino
    ):
        results = [
            await _trino_catalog_ready(catalog)
            for catalog, _name, _kind in _SOURCE_CATALOGS
        ]
        assert not await _trino_catalog_ready("client-supplied")

    assert results == [True] * 5
    assert len(closed) == 5
    assert [sql for sql, _deadline in calls] == [
        f'SELECT 1 FROM "{catalog}".information_schema.schemata LIMIT 1'
        for catalog, _name, _kind in _SOURCE_CATALOGS
    ]
    assert all(deadline > 0 for _sql, deadline in calls)


@pytest.mark.asyncio
async def test_source_catalog_probe_closes_after_bounded_transport_failure() -> None:
    state = {"closed": False, "deadline": 0.0}

    class TimedOutTrino:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def execute(self, _sql: str, *, deadline: float):
            state["deadline"] = deadline
            raise AdapterError(AdapterErrorCode.TIMEOUT, "timed out")

        async def aclose(self) -> None:
            state["closed"] = True

    with patch(
        "app.services.admin_connections.TrinoAsyncClient", TimedOutTrino
    ):
        assert not await _trino_catalog_ready("pms")

    assert state["deadline"] > 0
    assert state["closed"] is True


@pytest.mark.asyncio
async def test_admin_connection_projection_contains_exact_nine_server_targets() -> None:
    with (
        patch.object(
            AppDatabaseReadiness,
            "_database_probe",
            AsyncMock(return_value={"app_postgres": "ready"}),
        ),
        patch.object(
            AppDatabaseReadiness,
            "_trino_probe",
            AsyncMock(return_value="ready"),
        ),
        patch.object(
            AppDatabaseReadiness,
            "_datahub_probe",
            AsyncMock(return_value="ready"),
        ),
        patch.object(
            AppDatabaseReadiness,
            "_model_probe",
            AsyncMock(return_value="ready"),
        ),
        patch(
            "app.services.admin_connections._trino_catalog_ready",
            AsyncMock(return_value=True),
        ),
    ):
        rows = await probe_admin_connections()

    assert [row["id"] for row in rows] == [
        "pms",
        "pos",
        "crm",
        "facility",
        "banquet",
        "app-postgres",
        "trino",
        "datahub",
        "model-api",
    ]
    assert all(row["status"] == "ready" for row in rows)
