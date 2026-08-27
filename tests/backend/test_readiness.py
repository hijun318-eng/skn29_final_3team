from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from sys import path
from unittest.mock import AsyncMock, MagicMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory
import httpx


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.readiness import AppDatabaseReadiness


def current_migration_head() -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


class _Session:
    def __init__(self, results):
        self._results = iter(results)
        self.queries = []

    async def execute(self, query):
        self.queries.append(str(query))
        return next(self._results)


class AppDatabaseReadinessMigrationTest(unittest.IsolatedAsyncioTestCase):
    def test_probe_timeout_uses_bounded_two_second_production_budget(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(2.0, AppDatabaseReadiness._probe_timeout())
        for configured, expected in (
            ("0.01", 0.1),
            ("1.5", 1.5),
            ("20", 2.0),
            ("invalid", 2.0),
        ):
            with self.subTest(configured=configured), patch.dict(
                "os.environ",
                {"READINESS_PROBE_TIMEOUT_SECONDS": configured},
                clear=True,
            ):
                self.assertEqual(expected, AppDatabaseReadiness._probe_timeout())

    async def test_empty_analysis_template_registry_is_ready(self) -> None:
        current_head = current_migration_head()
        session = _Session([
            MagicMock(scalar_one_or_none=lambda: current_head),
            MagicMock(),
        ])

        @asynccontextmanager
        async def scope(*_args, **_kwargs):
            yield session

        with patch("app.services.readiness.session_scope", scope), patch.dict(
            "os.environ",
            {"APP_RUNTIME_DATABASE_URL": "postgresql://readiness"},
        ):
            result = await AppDatabaseReadiness._database_probe()

        self.assertEqual("ready", result["analysis_template_registry"])
        self.assertIn("LIMIT 0", session.queries[1])
        self.assertNotIn("status = 'APPROVED'", session.queries[1])

    async def test_no_database_or_database_error_fail_closed(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                "not_configured",
                (await AppDatabaseReadiness._database_probe())["app_postgres"],
            )

        @asynccontextmanager
        async def unavailable(*_args, **_kwargs):
            raise RuntimeError("database unavailable")
            yield

        with patch("app.services.readiness.session_scope", unavailable), patch.dict(
            "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://readiness"}
        ):
            self.assertEqual(
                {
                    "app_postgres": "not_ready",
                    "migration": "not_ready",
                    "analysis_template_registry": "not_ready",
                },
                await AppDatabaseReadiness._database_probe(),
            )

    def test_current_migration_head_is_ready(self) -> None:
        self.assertEqual(
            "ready", AppDatabaseReadiness._migration_status(current_migration_head())
        )

    def test_old_or_unknown_migration_head_is_not_ready(self) -> None:
        for version in ("20260731_03", "unknown", None):
            with self.subTest(version=version):
                self.assertEqual(
                    "not_ready", AppDatabaseReadiness._migration_status(version)
                )

    def test_multiple_migration_heads_fail_closed(self) -> None:
        with patch(
            "app.services.readiness.ScriptDirectory.from_config"
        ) as from_config:
            from_config.return_value.get_heads.return_value = ["head_a", "head_b"]
            with self.assertRaisesRegex(RuntimeError, "exactly one head"):
                AppDatabaseReadiness._migration_status("head_a")

    async def test_real_dependencies_and_model_are_all_probed(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.host == "trino":
                return httpx.Response(
                    200,
                    json={
                        "id": "query-readiness",
                        "stats": {"state": "FINISHED"},
                        "columns": [{"name": "_col0"}],
                        "data": [[1]],
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "gpt-5.4-mini"}]},
                request=request,
            )

        with patch.dict(
            "os.environ",
            {
                "TRINO_URL": "https://trino:8443",
                "TRINO_RUNTIME_USER": "runtime-user",
                "TRINO_RUNTIME_PASSWORD": "runtime-password",
                "TRINO_TLS_CA_FILE": "mock-ca.pem",
                "OPENAI_ENDPOINT": "https://model.invalid",
                "OPENAI_API_KEY": "token",
                "OPENAI_MODEL": "gpt-5.4-mini",
            },
            clear=True,
        ):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                self.assertEqual("ready", await AppDatabaseReadiness._trino_probe(client))
                self.assertEqual("ready", await AppDatabaseReadiness._model_probe(client))
        trino_request = next(item for item in requests if item.url.host == "trino")
        self.assertEqual("SELECT 1", trino_request.content.decode("utf-8"))
        self.assertEqual("runtime-user", trino_request.headers["x-trino-user"])
        self.assertTrue(trino_request.headers["authorization"].startswith("Basic "))

    async def test_auth_readiness_requires_database_and_session_secret(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual("not_ready", await AppDatabaseReadiness._auth_probe())

    async def test_auth_readiness_requires_an_active_database_account(self) -> None:
        environment = {
            "APP_RUNTIME_DATABASE_URL": "postgresql://readiness",
            "AUTH_SESSION_SECRET": "s" * 32,
        }
        for active, expected in ((True, "ready"), (False, "not_ready")):
            with self.subTest(active=active):
                account_probe = AsyncMock(return_value=active)
                with (
                    patch.dict("os.environ", environment, clear=True),
                    patch(
                        "app.services.readiness.auth_account_store_ready",
                        account_probe,
                    ),
                ):
                    self.assertEqual(expected, await AppDatabaseReadiness._auth_probe())
                account_probe.assert_awaited_once_with("postgresql://readiness")

    async def test_trino_probe_follows_same_origin_pages_to_terminal_success(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "id": "query-readiness",
                        "stats": {"state": "RUNNING"},
                        "nextUri": "https://trino:8443/v1/statement/query-readiness/1",
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "id": "query-readiness",
                    "stats": {"state": "FINISHED"},
                    "columns": [{"name": "_col0"}],
                    "data": [[1]],
                },
                request=request,
            )

        environment = {
            "TRINO_URL": "https://trino:8443",
            "TRINO_RUNTIME_USER": "runtime-user",
            "TRINO_RUNTIME_PASSWORD": "runtime-password",
            "TRINO_TLS_CA_FILE": "unused-by-mock.pem",
        }
        with patch.dict("os.environ", environment, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                self.assertEqual("ready", await AppDatabaseReadiness._trino_probe(client))

        self.assertEqual(["POST", "GET"], [request.method for request in requests])
        self.assertTrue(all(request.headers["x-trino-user"] == "runtime-user" for request in requests))
        self.assertTrue(all(request.headers["authorization"].startswith("Basic ") for request in requests))

    async def test_trino_probe_rejects_wrong_password_and_impersonation(self) -> None:
        for name, status, user in (
            ("wrong-password", 401, "runtime-user"),
            ("impersonation", 403, "another-user"),
        ):
            with self.subTest(name=name):
                async def denied(request: httpx.Request, response_status: int = status) -> httpx.Response:
                    return httpx.Response(response_status, request=request)

                environment = {
                    "TRINO_URL": "https://trino:8443",
                    "TRINO_RUNTIME_USER": user,
                    "TRINO_RUNTIME_PASSWORD": "invalid-credential",
                    "TRINO_TLS_CA_FILE": "unused-by-mock.pem",
                }
                with patch.dict("os.environ", environment, clear=True):
                    async with httpx.AsyncClient(
                        transport=httpx.MockTransport(denied)
                    ) as client:
                        self.assertEqual(
                            "not_ready",
                            await AppDatabaseReadiness._trino_probe(client),
                        )

    async def test_trino_production_probe_owns_its_secure_client(self) -> None:
        constructor: dict[str, object] = {}

        class OwnedTrino:
            def __init__(self, *args: object, **kwargs: object) -> None:
                constructor["args"] = args
                constructor["kwargs"] = kwargs

            async def statement_ready(self, *, deadline: float) -> bool:
                constructor["deadline"] = deadline
                return True

            async def aclose(self) -> None:
                constructor["closed"] = True

        with patch.dict(
            "os.environ",
            {
                "TRINO_URL": "https://trino:8443",
                "TRINO_RUNTIME_USER": "runtime-user",
                "TRINO_RUNTIME_PASSWORD": "runtime-password",
                "TRINO_TLS_CA_FILE": "C:/external/trino-ca.pem",
            },
            clear=True,
        ), patch("app.services.readiness.TrinoAsyncClient", OwnedTrino):
            self.assertEqual("ready", await AppDatabaseReadiness._trino_probe())

        self.assertNotIn("client", constructor["kwargs"])
        self.assertEqual("C:/external/trino-ca.pem", constructor["kwargs"]["ca_file"])
        self.assertTrue(constructor["closed"])

    async def test_check_never_passes_shared_model_client_to_trino_or_datahub(self) -> None:
        probe = AppDatabaseReadiness()
        with (
            patch.object(probe, "_database_probe", AsyncMock(return_value={})),
            patch.object(probe, "_trino_probe", AsyncMock(return_value="ready")) as trino,
            patch.object(probe, "_datahub_probe", AsyncMock(return_value="ready")) as datahub,
            patch.object(
                probe,
                "_catalog_release_probe",
                AsyncMock(
                    return_value={
                        "semantic_release": "ready",
                        "catalog_manifest": "ready",
                        "trino_schema": "ready",
                    }
                ),
            ),
            patch.object(probe, "_model_probe", AsyncMock(return_value="ready")),
            patch.object(probe, "_auth_probe", AsyncMock(return_value="ready")),
            patch.object(probe, "_report_scheduler_probe", return_value="ready"),
        ):
            result = await probe.check()

        trino.assert_awaited_once_with()
        datahub.assert_awaited_once_with()
        self.assertEqual("ready", result["trino"])
        self.assertEqual("ready", result["datahub_transport"])
        self.assertEqual("ready", result["catalog_manifest"])

    async def test_datahub_probe_uses_canonical_environment_client(self) -> None:
        class Catalog:
            entered = False
            exited = False

            async def __aenter__(self):
                self.entered = True
                return self

            async def __aexit__(self, *_args: object) -> None:
                self.exited = True

            async def health(self) -> bool:
                return True

        catalog = Catalog()
        with patch(
            "app.services.readiness.DataHubCatalogClient.from_env",
            return_value=catalog,
        ) as factory:
            self.assertEqual("ready", await AppDatabaseReadiness._datahub_probe())

        factory.assert_called_once_with(
            timeout_seconds=AppDatabaseReadiness._probe_timeout()
        )
        self.assertTrue(catalog.entered)
        self.assertTrue(catalog.exited)

    async def test_catalog_release_probe_caches_only_complete_checksum_receipt(self) -> None:
        class Platform:
            calls = 0

            async def get_catalog_readiness(self):
                self.calls += 1
                return (
                    {
                        "semantic_release": "ready",
                        "catalog_manifest": "ready",
                        "trino_schema": "ready",
                    },
                    "release-1:" + "a" * 64,
                )

        platform = Platform()
        probe = AppDatabaseReadiness(lambda: platform)
        first = await probe._catalog_release_probe()
        second = await probe._catalog_release_probe()

        self.assertEqual(first, second)
        self.assertEqual(1, platform.calls)

    async def test_catalog_release_cache_is_namespaced_by_active_generation(self) -> None:
        class Platform:
            calls = 0
            identity = ("runtime-catalog:a", "product-a", 1)

            async def get_catalog_cache_identity(self):
                return self.identity

            async def get_catalog_readiness(self):
                self.calls += 1
                return (
                    {
                        "semantic_release": "ready",
                        "catalog_manifest": "ready",
                        "trino_schema": "ready",
                    },
                    self.identity[1],
                )

        platform = Platform()
        probe = AppDatabaseReadiness(lambda: platform)
        first = await probe._catalog_release_probe()
        cached = await probe._catalog_release_probe()
        platform.identity = ("runtime-catalog:a", "product-a", 2)
        refreshed = await probe._catalog_release_probe()

        self.assertEqual(first, cached)
        self.assertEqual(first, refreshed)
        self.assertEqual(2, platform.calls)

    def test_catalog_release_cache_ttl_defaults_and_caps_at_one_day(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            default = AppDatabaseReadiness._release_cache_ttl()
        with patch.dict(
            "os.environ",
            {"RELEASE_READINESS_CACHE_TTL_SECONDS": "172800"},
            clear=True,
        ):
            capped = AppDatabaseReadiness._release_cache_ttl()
        with patch.dict(
            "os.environ",
            {"RELEASE_READINESS_CACHE_TTL_SECONDS": "invalid"},
            clear=True,
        ):
            invalid = AppDatabaseReadiness._release_cache_ttl()

        self.assertEqual(86_400.0, default)
        self.assertEqual(86_400.0, capped)
        self.assertEqual(86_400.0, invalid)

    async def test_catalog_release_cache_expiry_never_returns_stale_success(self) -> None:
        class Platform:
            calls = 0

            async def get_catalog_readiness(self):
                self.calls += 1
                if self.calls == 1:
                    return (
                        {
                            "semantic_release": "ready",
                            "catalog_manifest": "ready",
                            "trino_schema": "ready",
                        },
                        "release-1:" + "a" * 64,
                    )
                return (
                    {
                        "semantic_release": "ready",
                        "catalog_manifest": "not_ready",
                        "trino_schema": "not_ready",
                    },
                    None,
                )

        platform = Platform()
        probe = AppDatabaseReadiness(lambda: platform)
        self.assertEqual(
            "ready", (await probe._catalog_release_probe())["catalog_manifest"]
        )
        probe._release_cache_expires_at = 0.0
        expired = await probe._catalog_release_probe()

        self.assertEqual("not_ready", expired["catalog_manifest"])
        self.assertEqual("not_ready", expired["trino_schema"])
        self.assertIsNone(probe._release_cache)

    async def test_catalog_release_probe_timeout_fails_closed(self) -> None:
        class Platform:
            async def get_catalog_readiness(self):
                await asyncio.sleep(0.1)
                raise AssertionError("cancelled release probe must not complete")

        probe = AppDatabaseReadiness(lambda: Platform())
        with patch.object(probe, "_release_probe_timeout", return_value=0.01):
            result = await probe._catalog_release_probe()

        self.assertEqual(
            {
                "semantic_release": "not_ready",
                "catalog_manifest": "not_ready",
                "trino_schema": "not_ready",
            },
            result,
        )

    async def test_catalog_release_provider_contract_error_fails_closed(self) -> None:
        class PlatformWithoutReadinessContract:
            pass

        probe = AppDatabaseReadiness(lambda: PlatformWithoutReadinessContract())

        self.assertEqual(
            {
                "semantic_release": "not_ready",
                "catalog_manifest": "not_ready",
                "trino_schema": "not_ready",
            },
            await probe._catalog_release_probe(),
        )

    async def test_model_probe_retries_one_transient_timeout(self) -> None:
        environment = {
            "OPENAI_ENDPOINT": "https://model.invalid",
            "OPENAI_API_KEY": "token",
            "OPENAI_MODEL": "gpt-5.4-mini",
        }
        attempts = 0

        async def transient(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectTimeout("timeout", request=request)
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-5.4-mini"}]},
                request=request,
            )

        with patch.dict("os.environ", environment, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(transient)) as client:
                self.assertEqual("ready", await AppDatabaseReadiness._model_probe(client))
                self.assertEqual(2, attempts)

        attempts = 0

        async def unavailable_model(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectTimeout("timeout", request=request)

        with patch.dict("os.environ", environment, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable_model)) as client:
                self.assertEqual("not_ready", await AppDatabaseReadiness._model_probe(client))
                self.assertEqual(2, attempts)

    async def test_model_probe_checks_every_route_token_and_exact_model_id(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            models = {
                "primary.model.invalid": "gpt-5.4-mini",
                "node2.model.invalid": "answervice-sql",
            }
            return httpx.Response(
                200,
                json={"data": [{"id": models[request.url.host]}]},
                request=request,
            )

        environment = {
            "OPENAI_ENDPOINT": "https://primary.model.invalid",
            "OPENAI_API_KEY": "primary-token",
            "OPENAI_MODEL": "gpt-5.4-mini",
            "NODE2_MODEL_PROVIDER": "qwen",
            "NODE2_MODEL_ENDPOINT": "https://node2.model.invalid/openai",
            "NODE2_MODEL_API_TOKEN": "node2-token",
            "NODE2_MODEL": "answervice-sql",
        }
        with patch.dict("os.environ", environment, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                self.assertEqual("ready", await AppDatabaseReadiness._model_probe(client))

        self.assertEqual(
            {
                ("primary.model.invalid", "/v1/models", "Bearer primary-token"),
                ("node2.model.invalid", "/openai/v1/models", "Bearer node2-token"),
            },
            {
                (request.url.host, request.url.path, request.headers["authorization"])
                for request in requests
            },
        )

    async def test_model_probe_rejects_invalid_route_token(self) -> None:
        attempts = 0

        async def authenticated(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            status = (
                200
                if request.headers.get("authorization") == "Bearer expected-token"
                else 401
            )
            return httpx.Response(
                status,
                json={"data": [{"id": "gpt-5.4-mini"}]},
                request=request,
            )

        with patch.dict(
            "os.environ",
            {
                "OPENAI_ENDPOINT": "https://primary.model.invalid",
                "OPENAI_API_KEY": "wrong-token",
                "OPENAI_MODEL": "gpt-5.4-mini",
            },
            clear=True,
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(authenticated)
            ) as client:
                self.assertEqual(
                    "not_ready",
                    await AppDatabaseReadiness._model_probe(client),
                )
        self.assertEqual(2, attempts)

    async def test_model_probe_rejects_partial_route_and_missing_or_malformed_models(self) -> None:
        base = {
            "OPENAI_ENDPOINT": "https://primary.model.invalid",
            "OPENAI_API_KEY": "primary-token",
            "OPENAI_MODEL": "gpt-5.4-mini",
        }
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                json={"data": [{"id": "another-model"}]},
                request=request,
            )

        partial = base | {"NODE2_MODEL": "answervice-sql"}
        with patch.dict("os.environ", partial, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                self.assertEqual("not_ready", await AppDatabaseReadiness._model_probe(client))
        self.assertEqual(0, calls)

        with patch.dict("os.environ", base, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                self.assertEqual("not_ready", await AppDatabaseReadiness._model_probe(client))
        self.assertEqual(2, calls)

        async def malformed(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"name": "gpt-5.4-mini"}]}, request=request)

        with patch.dict("os.environ", base, clear=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as client:
                self.assertEqual("not_ready", await AppDatabaseReadiness._model_probe(client))


if __name__ == "__main__":
    unittest.main()
