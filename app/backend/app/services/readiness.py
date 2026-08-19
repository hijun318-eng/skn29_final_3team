"""APP DB migration·template registry, Trino, DataHub, model, 외부 principal store와 scheduler를 제한 시간의 실제 probe로 확인해 구성요소별 ready 상태를 반환한다."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from time import monotonic

from alembic.config import Config
from alembic.script import ScriptDirectory
import httpx
from sqlalchemy import text

from app.adapters.datahub_catalog import DataHubCatalogClient
from app.adapters.trino_async import TrinoAsyncClient
from app.auth_principal_store import AuthenticationError, principal_store_ready
from app.database import session_scope
from src.modelops.runtime_config import ActiveModelRoute, resolve_active_model_routes


class AppDatabaseReadiness:
    """실제 쿼리로 migration·Template·Trino 사용 가능 상태를 확인한다."""

    async def check(self) -> dict[str, str]:
        """APP database 준비 상태 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다."""
        timeout = httpx.Timeout(self._probe_timeout())
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "answervice-readiness/1.0"},
            trust_env=False,
        ) as client:
            database, trino, datahub, model, auth = await asyncio.gather(
                self._database_probe(),
                self._trino_probe(),
                self._datahub_probe(),
                self._model_probe(client),
                asyncio.to_thread(self._auth_probe),
            )
        probe = database
        probe["trino"] = trino
        probe["datahub"] = datahub
        probe["model"] = model
        probe["auth_session_store"] = auth
        probe["report_scheduler"] = self._report_scheduler_probe()
        return probe

    @staticmethod
    def _auth_probe() -> str:
        principal_file = os.getenv("AUTH_PRINCIPALS_FILE", "").strip()
        secret = os.getenv("AUTH_SESSION_SECRET", "").strip()
        if (
            not os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
            or len(secret) < 32
            or not principal_file
        ):
            return "not_ready"
        try:
            return "ready" if principal_store_ready(Path(principal_file)) else "not_ready"
        except (AuthenticationError, OSError):
            return "not_ready"

    @staticmethod
    def _probe_timeout() -> float:
        try:
            configured = float(os.getenv("READINESS_PROBE_TIMEOUT_SECONDS", "1"))
        except ValueError:
            return 1.0
        return min(2.0, max(0.1, configured))

    @staticmethod
    def _report_scheduler_probe() -> str:
        from app.services.report.scheduler import report_scheduler

        return report_scheduler.status

    @staticmethod
    async def _database_probe() -> dict[str, str]:
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
        if not database_url:
            return {
                "app_postgres": "not_configured",
                "migration": "not_ready",
                "analysis_template_registry": "not_ready",
            }
        try:
            async with session_scope(database_url) as session:
                version_result = await session.execute(
                    text("SELECT version_num FROM governance.alembic_version")
                )
                version = version_result.scalar_one_or_none()
                await session.execute(
                    text(
                        "SELECT template_id FROM context.analysis_templates LIMIT 0"
                    )
                )
            return {
                "app_postgres": "ready",
                "migration": await asyncio.to_thread(
                    AppDatabaseReadiness._migration_status, version
                ),
                "analysis_template_registry": "ready",
            }
        except Exception:
            return {
                "app_postgres": "not_ready",
                "migration": "not_ready",
                "analysis_template_registry": "not_ready",
            }

    @staticmethod
    def _migration_status(version: str | None) -> str:
        backend = Path(__file__).resolve().parents[2]
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "migrations"))
        heads = ScriptDirectory.from_config(config).get_heads()
        if len(heads) != 1:
            raise RuntimeError("Alembic migration graph must have exactly one head")
        return "ready" if version == heads[0] else "not_ready"

    @staticmethod
    async def _trino_probe(client: httpx.AsyncClient | None = None) -> str:
        trino: TrinoAsyncClient | None = None
        try:
            options: dict[str, object] = {
                "ca_file": os.getenv(
                    "TRINO_TLS_CA_FILE", "/run/secrets/trino-ca.pem"
                ),
                "request_timeout_seconds": AppDatabaseReadiness._probe_timeout(),
            }
            # 운영에서는 adapter가 CA·BasicAuth·trust_env=False client를 직접 소유한다.
            # 네트워크 없는 unit test만 MockTransport client를 명시적으로 주입한다.
            if client is not None:
                options["client"] = client
            trino = TrinoAsyncClient(
                os.getenv("TRINO_URL", "https://trino:8443"),
                os.getenv("TRINO_RUNTIME_USER", ""),
                os.getenv("TRINO_RUNTIME_PASSWORD", ""),
                **options,
            )
            deadline = monotonic() + AppDatabaseReadiness._probe_timeout()
            return "ready" if await trino.statement_ready(deadline=deadline) else "not_ready"
        except (OSError, ValueError):
            return "not_ready"
        finally:
            if trino is not None:
                await trino.aclose()

    @staticmethod
    async def _datahub_probe() -> str:
        """canonical HTTPS·Bearer·CA 설정으로 bounded GraphQL root query를 검증한다."""

        try:
            async with DataHubCatalogClient.from_env(
                timeout_seconds=AppDatabaseReadiness._probe_timeout()
            ) as catalog:
                return "ready" if await catalog.health() else "not_ready"
        except (OSError, ValueError):
            return "not_ready"

    @staticmethod
    async def _model_probe(client: httpx.AsyncClient) -> str:
        try:
            routes = resolve_active_model_routes()
        except (OSError, ValueError):
            return "not_ready"
        states = await asyncio.gather(
            *(AppDatabaseReadiness._model_route_ready(client, route) for route in routes)
        )
        return "ready" if states and all(states) else "not_ready"

    @staticmethod
    async def _model_route_ready(
        client: httpx.AsyncClient,
        route: ActiveModelRoute,
    ) -> bool:
        """route credential로 `/v1/models`를 조회해 active model ID의 정확한 존재를 확인한다."""

        for _ in range(2):
            try:
                response = await client.get(
                    f"{route.endpoint}/v1/models",
                    headers={"Authorization": f"Bearer {route.token}"},
                )
                if response.status_code != 200:
                    continue
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if (
                    not isinstance(data, list)
                    or not data
                    or any(
                        not isinstance(item, dict)
                        or not isinstance(item.get("id"), str)
                        or not item["id"]
                        for item in data
                    )
                ):
                    continue
                model_ids = tuple(item["id"] for item in data)
                if len(model_ids) == len(set(model_ids)) and route.model in model_ids:
                    return True
            except (httpx.HTTPError, ValueError):
                pass
        return False
