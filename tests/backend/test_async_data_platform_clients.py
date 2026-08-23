from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock, patch

import httpx


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import (
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.governed_data_platform import GovernedDataPlatformAdapter
from app.adapters.trino_async import (
    AdapterError,
    AdapterErrorCode,
    QueryPage,
    TrinoAsyncClient,
)
from app.query_capability import issue_query_capability


class DataHubCatalogClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_glossary_status_from_restli_current_aspect(self) -> None:
        """GraphQL null status 대신 인증된 Rest.li current aspect를 사용한다."""

        urn = "urn:li:glossaryTerm:revenue"

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual("Bearer catalog-token", request.headers["authorization"])
            self.assertIn("aspects=List(status)", str(request.url))
            return httpx.Response(200, json={
                "urn": urn,
                "aspects": {"status": {"value": {
                    "removed": False,
                    "lifecycleStage": "urn:li:lifecycleStageType:approved",
                }}},
            })

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DataHubCatalogClient(
            "http://datahub:8080", "catalog-token", client=http
        )
        try:
            result = await client.get_entity_status(urn)
        finally:
            await http.aclose()

        self.assertEqual(urn, result["urn"])
        self.assertFalse(result["status"]["removed"])

    async def test_rejects_credentialed_or_fragmented_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            DataHubCatalogClient("http://user:secret@datahub:8080")
        with self.assertRaises(ValueError):
            DataHubCatalogClient("http://datahub:8080/#fragment")

    async def test_uses_graphql_variables_and_bearer_token(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "dataset": {
                            "urn": "urn:dataset:one",
                            "status": {"removed": False},
                        }
                    }
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DataHubCatalogClient(
            "http://datahub:8080",
            "secret",
            client=http,
        )
        try:
            dataset = await client.get_dataset("urn:dataset:one")
        finally:
            await http.aclose()

        self.assertEqual(dataset["urn"], "urn:dataset:one")
        self.assertEqual(requests[0].headers["authorization"], "Bearer secret")
        self.assertEqual(
            requests[0].read().decode("utf-8").count("urn:dataset:one"),
            1,
        )
        self.assertNotIn("urn:dataset:one", requests[0].url.path)

    async def test_graphql_errors_fail_closed(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errors": [{"message": "denied"}]})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DataHubCatalogClient("http://datahub:8080", client=http)
        try:
            with self.assertRaises(DataHubCatalogError):
                await client.get_glossary_term("urn:term:one")
        finally:
            await http.aclose()

    async def test_health_maps_transport_failure_to_false(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DataHubCatalogClient("http://datahub:8080", client=http)
        try:
            self.assertFalse(await client.health())
        finally:
            await http.aclose()

    async def test_health_requires_bearer_and_exact_graphql_root_shape(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.headers.get("authorization") != "Bearer catalog-token":
                return httpx.Response(401, json={"message": "unauthorized"})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "me": {
                            "corpUser": {
                                "urn": "urn:li:corpuser:service_catalog_reader"
                            }
                        }
                    }
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        authenticated = DataHubCatalogClient(
            "http://datahub:8080",
            "catalog-token",
            client=http,
            expected_actor_urn="urn:li:corpuser:service_catalog_reader",
        )
        unauthenticated = DataHubCatalogClient("http://datahub:8080", client=http)
        try:
            self.assertTrue(await authenticated.health())
            self.assertFalse(await unauthenticated.health())
        finally:
            await http.aclose()
        self.assertEqual("/api/graphql", requests[0].url.path)
        self.assertIn("DataHubHealth", requests[0].read().decode("utf-8"))

    async def test_injected_network_client_cannot_bypass_tls_contract(self) -> None:
        network_client = httpx.AsyncClient()
        try:
            with self.assertRaisesRegex(ValueError, "MockTransport"):
                DataHubCatalogClient(
                    "https://datahub:8443",
                    "catalog-token",
                    client=network_client,
                )
        finally:
            await network_client.aclose()

    async def test_owned_transport_uses_ssl_context_and_disables_proxy(self) -> None:
        owned_http = AsyncMock()
        tls_context = object()
        ca_file = Path(__file__).resolve()
        with (
            patch(
                "app.adapters.datahub_catalog.ssl.create_default_context",
                return_value=tls_context,
            ) as context_factory,
            patch(
                "app.adapters.datahub_catalog.httpx.AsyncClient",
                return_value=owned_http,
            ) as client_factory,
        ):
            client = DataHubCatalogClient(
                "https://datahub:8443",
                "catalog-token",
                ca_file=ca_file,
                expected_actor_urn="urn:li:corpuser:service_catalog_reader",
            )
            await client.aclose()

        context_factory.assert_called_once_with(cafile=str(ca_file))
        kwargs = client_factory.call_args.kwargs
        self.assertIs(kwargs["verify"], tls_context)
        self.assertFalse(kwargs["trust_env"])
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer catalog-token"})
        owned_http.aclose.assert_awaited_once_with()

    async def test_duplicate_scrolled_urn_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            cursor = body["variables"]["input"].get("scrollId")
            return httpx.Response(
                200,
                json={"data": {"scrollAcrossEntities": {
                    "count": 1,
                    "nextScrollId": "next" if cursor is None else "final",
                    "searchResults": [{
                        "entity": {"urn": "urn:li:dataset:duplicate", "type": "DATASET"},
                        "matchedFields": [],
                    }],
                }}},
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DataHubCatalogClient(
            "http://datahub:8080", client=http, page_size=1, max_entities=2
        )
        try:
            with self.assertRaisesRegex(DataHubCatalogError, "duplicate"):
                await client.list_datasets()
        finally:
            await http.aclose()


class TrinoAsyncClientTests(unittest.IsolatedAsyncioTestCase):
    def test_typed_user_cancelled_payload_maps_to_cancelled(self) -> None:
        with self.assertRaises(AdapterError) as raised:
            TrinoAsyncClient._page({
                "id": "query-1",
                "stats": {"state": "FAILED"},
                "error": {
                    "errorName": "USER_CANCELED",
                    "errorType": "USER_ERROR",
                    "message": "upstream-localized-message",
                },
            })

        self.assertEqual(AdapterErrorCode.CANCELLED, raised.exception.code)

    async def test_rejects_cross_origin_or_credentialed_next_uri(self) -> None:
        called = False

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TrinoAsyncClient(
            "https://trino:8443", "service-user", "test-password", client=http
        )
        try:
            for uri in (
                "http://trino:8443/v1/statement/query/1",
                "https://attacker.invalid/v1/statement/query/1",
                "https://user:secret@trino:8443/v1/statement/query/1",
                "https://trino:8443/v1/statement/query/1#fragment",
            ):
                with self.subTest(uri=uri):
                    with self.assertRaises(AdapterError) as raised:
                        await client.next_page(uri)
                    self.assertEqual(AdapterErrorCode.UPSTREAM, raised.exception.code)
        finally:
            await http.aclose()
        self.assertFalse(called)

    async def test_statement_page_and_cancel_preserve_protocol(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "id": "query-1",
                        "stats": {"state": "RUNNING"},
                        "columns": [{"name": "value"}],
                        "data": [[1]],
                        "nextUri": "https://trino:8443/next/query-1",
                    },
                )
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(
                200,
                json={
                    "id": "query-1",
                    "stats": {"state": "FINISHED"},
                    "data": [[2]],
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TrinoAsyncClient(
            "https://trino:8443",
            "service-user",
            "test-password",
            client=http,
        )
        try:
            first = await client.execute(
                "SELECT 1",
                deadline=monotonic() + 5,
            )
            second = await client.next_page(
                first.next_uri or "",
                deadline=monotonic() + 5,
            )
            await client.cancel(
                "https://trino:8443/next/query-1",
                deadline=monotonic() + 5,
            )
            await client.cancel_query(
                "query-1",
                "https://trino:8443/next/query-1",
                deadline=monotonic() + 5,
            )
            with self.assertRaises(AdapterError) as raised:
                await client.cancel_query(
                    "other-query",
                    "https://trino:8443/next/query-1",
                    deadline=monotonic() + 5,
                )
        finally:
            await http.aclose()

        self.assertEqual(first.rows, ((1,),))
        self.assertEqual(second.rows, ((2,),))
        self.assertEqual(raised.exception.code, AdapterErrorCode.UPSTREAM)
        self.assertEqual(
            [item.method for item in requests],
            ["POST", "GET", "DELETE", "DELETE"],
        )
        self.assertTrue(
            all(item.headers["x-trino-user"] == "service-user" for item in requests)
        )
        self.assertTrue(
            all(item.headers["authorization"].startswith("Basic ") for item in requests)
        )

    async def test_expired_deadline_fails_before_transport(self) -> None:
        called = False

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TrinoAsyncClient(
            "https://trino:8443", "service-user", "test-password", client=http
        )
        try:
            with self.assertRaises(AdapterError) as raised:
                await client.execute("SELECT 1", deadline=monotonic() - 1)
        finally:
            await http.aclose()

        self.assertEqual(raised.exception.code, AdapterErrorCode.TIMEOUT)
        self.assertFalse(called)

    async def test_forbidden_response_is_normalized(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TrinoAsyncClient(
            "https://trino:8443", "service-user", "test-password", client=http
        )
        try:
            with self.assertRaises(AdapterError) as raised:
                await client.execute("SELECT 1")
        finally:
            await http.aclose()

        self.assertEqual(raised.exception.code, AdapterErrorCode.FORBIDDEN)

    async def test_owned_transport_requires_tls_credentials_and_ca(self) -> None:
        with self.assertRaisesRegex(ValueError, "credentials"):
            TrinoAsyncClient("https://trino:8443", "service-user", "")
        with self.assertRaisesRegex(ValueError, "endpoint"):
            TrinoAsyncClient(
                "http://trino:8080",
                "service-user",
                "test-password",
                ca_file=__file__,
            )
        with self.assertRaisesRegex(ValueError, "CA file"):
            TrinoAsyncClient(
                "https://trino:8443",
                "service-user",
                "test-password",
                ca_file=Path(__file__).with_name("missing-ca.pem"),
            )
        plain_http = httpx.AsyncClient()
        try:
            with self.assertRaisesRegex(ValueError, "MockTransport"):
                TrinoAsyncClient(
                    "https://trino:8443",
                    "service-user",
                    "test-password",
                    client=plain_http,
                )
        finally:
            await plain_http.aclose()

    async def test_owned_transport_disables_environment_proxy_trust(self) -> None:
        owned_http = AsyncMock()
        tls_context = object()
        ca_file = Path(__file__).resolve()
        with (
            patch(
                "app.adapters.trino_async.ssl.create_default_context",
                return_value=tls_context,
            ) as context_factory,
            patch(
                "app.adapters.trino_async.httpx.AsyncClient",
                return_value=owned_http,
            ) as factory,
        ):
            client = TrinoAsyncClient(
                "https://trino:8443",
                "service-user",
                "test-password",
                ca_file=ca_file,
            )
            await client.aclose()

        context_factory.assert_called_once_with(cafile=str(ca_file))
        factory.assert_called_once_with(
            verify=tls_context,
            trust_env=False,
        )
        owned_http.aclose.assert_awaited_once_with()


class GovernedAdapterAsyncBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_auxiliary_query_does_not_consume_main_lifecycle_attempt(self) -> None:
        class DataHubStub:
            async def aclose(self) -> None:
                return None

        class TrinoStub:
            def __init__(self) -> None:
                self.calls = 0

            async def execute(self, _sql: str, *, deadline: float) -> QueryPage:
                self.calls += 1
                return QueryPage(
                    f"query-{self.calls}",
                    "FINISHED",
                    ("value",),
                    ((self.calls,),),
                    None,
                )

            async def aclose(self) -> None:
                return None

        adapter = GovernedDataPlatformAdapter(
            "https://trino:8443",
            "service-user",
            datahub_client=DataHubStub(),
            trino_client=TrinoStub(),
        )
        lifecycle_events: list[dict[str, object]] = []

        async def lifecycle_sink(event: dict[str, object]) -> None:
            lifecycle_events.append(event)

        adapter.bind_query_lifecycle(lifecycle_sink)
        sql = "SELECT 1"
        token = issue_query_capability("5" * 64, sql)

        auxiliary = await adapter.execute_auxiliary_query(sql, {}, token)
        main = await adapter.execute_query(sql, {}, token)
        cached_auxiliary = await adapter.get_query_status(auxiliary["query_id"])
        await adapter.aclose()

        self.assertEqual("SUCCEEDED", auxiliary["status"])
        self.assertEqual("SUCCEEDED", cached_auxiliary["status"])
        self.assertEqual("SUCCEEDED", main["status"])
        self.assertEqual(
            [("TERMINAL", "query-2")],
            [
                (event["event_type"], event["query_id"])
                for event in lifecycle_events
            ],
        )

    async def test_pages_results_and_closes_clients(self) -> None:
        class DataHubStub:
            closed = False

            async def aclose(self) -> None:
                self.closed = True

        class TrinoStub:
            closed = False
            durable_cancellations: list[tuple[str, str]] = []

            async def execute(self, _sql: str, *, deadline: float) -> QueryPage:
                self.deadline = deadline
                return QueryPage(
                    "query-1",
                    "RUNNING",
                    ("value",),
                    ((1,),),
                    "https://trino:8443/next/query-1",
                )

            async def next_page(
                self,
                _next_uri: str,
                *,
                deadline: float,
            ) -> QueryPage:
                self.deadline = deadline
                return QueryPage(
                    "query-1",
                    "FINISHED",
                    (),
                    ((2,),),
                    None,
                )

            async def cancel(
                self,
                _next_uri: str,
                *,
                deadline: float,
            ) -> None:
                self.deadline = deadline

            async def cancel_query(
                self,
                query_id: str,
                next_uri: str,
                *,
                deadline: float,
            ) -> None:
                self.deadline = deadline
                self.durable_cancellations.append((query_id, next_uri))

            async def aclose(self) -> None:
                self.closed = True

        datahub = DataHubStub()
        trino = TrinoStub()
        adapter = GovernedDataPlatformAdapter(
            "https://trino:8443",
            "service-user",
            datahub_client=datahub,
            trino_client=trino,
        )
        lifecycle_events: list[dict[str, object]] = []

        async def lifecycle_sink(event: dict[str, object]) -> None:
            lifecycle_events.append(event)

        adapter.bind_query_lifecycle(lifecycle_sink)

        sql = "SELECT 1"
        result = await adapter.execute_query(
            sql,
            {},
            issue_query_capability("3" * 64, sql),
        )
        cached = await adapter.get_query_status("query-1")
        repeated = await adapter.get_query_status("query-1")
        durable_cancel = await adapter.cancel_query_at(
            "query-1",
            "https://trino:8443/next/query-1",
        )
        await adapter.aclose()

        self.assertEqual(result["rows"], [{"value": 1}, {"value": 2}])
        self.assertEqual(cached["status"], "SUCCEEDED")
        self.assertEqual(cached, repeated)
        self.assertEqual(durable_cancel["status"], "CANCELLED")
        self.assertEqual(
            trino.durable_cancellations,
            [("query-1", "https://trino:8443/next/query-1")],
        )
        self.assertEqual(
            [event["event_type"] for event in lifecycle_events],
            ["SUBMITTED", "HEARTBEAT", "TERMINAL"],
        )
        self.assertTrue(all("sql" not in event for event in lifecycle_events))
        self.assertTrue(datahub.closed)
        self.assertTrue(trino.closed)

    async def test_submission_evidence_failure_cancels_before_query_is_polled(self) -> None:
        class DataHubStub:
            async def aclose(self) -> None:
                return None

        class TrinoStub:
            def __init__(self) -> None:
                self.cancelled: list[str] = []
                self.polled = False

            async def execute(self, _sql: str, *, deadline: float) -> QueryPage:
                return QueryPage(
                    "query-durable-failure",
                    "RUNNING",
                    ("value",),
                    (),
                    "https://trino:8443/next/query-durable-failure",
                )

            async def next_page(self, _next_uri: str, *, deadline: float) -> QueryPage:
                self.polled = True
                raise AssertionError("query must not be polled without durable evidence")

            async def cancel(self, next_uri: str, *, deadline: float) -> None:
                self.cancelled.append(next_uri)

            async def aclose(self) -> None:
                return None

        trino = TrinoStub()
        adapter = GovernedDataPlatformAdapter(
            "https://trino:8443",
            "service-user",
            datahub_client=DataHubStub(),
            trino_client=trino,
        )

        async def rejected_lifecycle(_event: dict[str, object]) -> None:
            raise RuntimeError("durable lifecycle unavailable")

        adapter.bind_query_lifecycle(rejected_lifecycle)
        sql = "SELECT 1"
        with self.assertRaisesRegex(RuntimeError, "durable lifecycle unavailable"):
            await adapter.execute_query(sql, {}, issue_query_capability("4" * 64, sql))

        self.assertFalse(trino.polled)
        self.assertEqual(
            trino.cancelled,
            ["https://trino:8443/next/query-durable-failure"],
        )


if __name__ == "__main__":
    unittest.main()
