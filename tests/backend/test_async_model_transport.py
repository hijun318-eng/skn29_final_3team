from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.adapters.async_model_client import AsyncProductionModelClient
from app.adapters.async_model_client import (
    ModelAuthenticationError,
    ModelCircuitOpenError,
    ModelContractInvalidError,
    ModelEndpointUnavailableError,
)
from app.adapters.model_transport import OpenAITransport, openai_transport
from app.adapters.report_assistant import generate_report_draft
from tests.ai.test_contracts import VALID_PAYLOADS
from src.modelops.runtime import _TRANSPORT_META_KEY
from src.ai.schema import validate_payload


class AsyncModelTransportTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _report_request() -> dict[str, object]:
        return {
            "instruction": "Prepare a governed operations summary.",
            "artifact": {
                "artifact_id": "artifact-arbitrary-1",
                "query_id": "query-arbitrary-1",
                "title": "Governed result",
                "narrative": "The governed result was recorded.",
                "evidence": {"source": "runtime"},
                "chart_spec": None,
                "checksum": "a" * 64,
            },
        }

    async def test_insecure_or_ambiguous_endpoint_is_rejected_before_io(self) -> None:
        called = False

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500)

        invalid_endpoints = {
            "http://model.internal": "must use HTTPS",
            "https://model-user:model-secret@model.invalid": "URL credentials",
            "https://model.invalid/base?tenant=runtime": "query",
            "https://model.invalid/base#provider": "fragment",
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            for endpoint, error_message in invalid_endpoints.items():
                with self.subTest(endpoint=endpoint):
                    with self.assertRaisesRegex(ValueError, error_message):
                        await openai_transport(
                            endpoint,
                            "bearer-token",
                            "node3",
                            VALID_PAYLOADS["node3_request"],
                            1,
                            model="model-snapshot",
                            provider="openai",
                            client=http,
                        )

        self.assertFalse(called)

    async def test_owned_transport_rejects_invalid_endpoint_before_client_creation(self) -> None:
        invalid_endpoints = (
            "http://model.internal",
            "https://model-user@model.invalid",
            "https://model.invalid?tenant=runtime",
            "https://model.invalid#provider",
        )
        with patch("app.adapters.model_transport.httpx.AsyncClient") as client_factory:
            for endpoint in invalid_endpoints:
                with self.subTest(endpoint=endpoint):
                    with self.assertRaises(ValueError):
                        OpenAITransport(
                            endpoint,
                            "bearer-token",
                            model="model-snapshot",
                            provider="openai",
                        )

        client_factory.assert_not_called()

    async def test_owned_transport_ignores_environment_proxy_and_closes_client(self) -> None:
        http = AsyncMock(spec=httpx.AsyncClient)
        with patch(
            "app.adapters.model_transport.httpx.AsyncClient",
            return_value=http,
        ) as client_factory:
            transport = OpenAITransport(
                "https://model.invalid",
                "bearer-token",
                model="model-snapshot",
                provider="openai",
            )

        client_factory.assert_called_once_with(trust_env=False)
        await transport.aclose()
        http.aclose.assert_awaited_once_with()

    async def test_unapproved_model_or_provider_is_rejected_before_io(self) -> None:
        called = False

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            for model, provider in (
                ("unregistered-model", "openai"),
                ("gpt-5.4-mini", "unregistered-provider"),
            ):
                with self.subTest(model=model, provider=provider):
                    with self.assertRaises(ValueError):
                        await openai_transport(
                            "https://model.invalid",
                            "bearer-token",
                            "node3",
                            VALID_PAYLOADS["node3_request"],
                            1,
                            model=model,
                            provider=provider,
                            client=http,
                        )

        self.assertFalse(called)

    async def test_public_transport_rejects_injected_network_client(self) -> None:
        network_client = httpx.AsyncClient(trust_env=False)
        try:
            with self.assertRaisesRegex(ValueError, "Only httpx.MockTransport"):
                await openai_transport(
                    "https://model.invalid",
                    "bearer-token",
                    "node3",
                    VALID_PAYLOADS["node3_request"],
                    1,
                    model="gpt-5.4-mini",
                    provider="openai",
                    client=network_client,
                )
        finally:
            await network_client.aclose()

    async def test_http_wait_does_not_block_the_event_loop(self) -> None:
        request_started = asyncio.Event()
        release_response = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            request_started.set()
            await release_response.wait()
            return httpx.Response(
                200,
                json={
                    "model": "model-snapshot",
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "explanation": "result",
                                        "conditions": [],
                                        "sources": [],
                                        "limitations": [],
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        task = asyncio.create_task(
            openai_transport(
                "https://model.internal",
                "token",
                "node3",
                VALID_PAYLOADS["node3_request"],
                2,
                model="gpt-5.4-mini",
                provider="openai",
                client=http,
            )
        )
        try:
            await asyncio.wait_for(request_started.wait(), timeout=1)
            heartbeat_ran = False

            async def heartbeat() -> None:
                nonlocal heartbeat_ran
                await asyncio.sleep(0)
                heartbeat_ran = True

            await asyncio.wait_for(heartbeat(), timeout=1)
            self.assertTrue(heartbeat_ran)
            release_response.set()
            result = await asyncio.wait_for(task, timeout=1)
        finally:
            release_response.set()
            if not task.done():
                task.cancel()
            await http.aclose()

        self.assertEqual("result", result["explanation"])
        self.assertNotIn("model", result)
        self.assertEqual(
            "gpt-5.4-mini",
            result[_TRANSPORT_META_KEY]["model_version"],
        )

    async def test_async_runtime_preserves_contract_trace(self) -> None:
        async def transport(
            _node: str,
            _payload: dict[str, object],
            _timeout: float,
        ) -> dict[str, object]:
            return dict(VALID_PAYLOADS["node3_response"])

        client = AsyncProductionModelClient(transport)
        response = await client.generate(
            "node3",
            VALID_PAYLOADS["node3_request"],
        )

        self.assertEqual("fixture", response["explanation"])
        self.assertEqual("SUCCESS", client.last_trace["status"])
        self.assertEqual(1, client.last_trace["attempts"])

    async def test_provider_body_cannot_smuggle_server_model_metadata(self) -> None:
        async def transport(
            _node: str,
            _payload: dict[str, object],
            _timeout: float,
        ) -> dict[str, object]:
            return {
                **VALID_PAYLOADS["node3_response"],
                "model": {"model_version": "provider-controlled"},
            }

        client = AsyncProductionModelClient(transport, max_attempts=1)
        with self.assertRaises(ModelContractInvalidError):
            await client.generate("node3", VALID_PAYLOADS["node3_request"])

    async def test_circuit_allows_one_probe_after_cooldown(self) -> None:
        calls = 0

        async def transport(
            _node: str,
            _payload: dict[str, object],
            _timeout: float,
        ) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("offline")
            return dict(VALID_PAYLOADS["node3_response"])

        client = AsyncProductionModelClient(
            transport,
            failure_threshold=1,
            max_attempts=1,
            circuit_cooldown_seconds=0.01,
        )
        with self.assertRaises(ModelEndpointUnavailableError):
            await client.generate("node3", VALID_PAYLOADS["node3_request"])
        with self.assertRaises(ModelCircuitOpenError):
            await client.generate("node3", VALID_PAYLOADS["node3_request"])

        await asyncio.sleep(0.02)
        response = await client.generate(
            "node3",
            VALID_PAYLOADS["node3_request"],
        )

        self.assertEqual("fixture", response["explanation"])
        self.assertEqual(2, calls)

    async def test_authentication_failure_is_not_retried(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(401, json={"error": "invalid token"})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(ModelAuthenticationError):
                await openai_transport(
                    "https://model.internal",
                    "bad-token",
                    "node3",
                    VALID_PAYLOADS["node3_request"],
                    1,
                    model="gpt-5.4-mini",
                    provider="openai",
                    client=http,
                )
        finally:
            await http.aclose()

        self.assertEqual(1, calls)

    async def test_malformed_choice_is_a_contract_error(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": ["not-an-object"]})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaisesRegex(ValueError, "choice must be an object"):
                await openai_transport(
                    "https://model.internal",
                    "token",
                    "node3",
                    VALID_PAYLOADS["node3_request"],
                    1,
                    model="gpt-5.4-mini",
                    provider="openai",
                    client=http,
                )
        finally:
            await http.aclose()

    async def test_total_deadline_cancels_slow_transport(self) -> None:
        cancelled = asyncio.Event()

        async def transport(
            _node: str,
            _payload: dict[str, object],
            _timeout: float,
        ) -> dict[str, object]:
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.set()
            return dict(VALID_PAYLOADS["node3_response"])

        client = AsyncProductionModelClient(
            transport,
            timeout_seconds=0.02,
            max_attempts=2,
        )
        with self.assertRaises(Exception) as raised:
            await client.generate("node3", VALID_PAYLOADS["node3_request"])

        self.assertEqual("MODEL_TIMEOUT", getattr(raised.exception, "code", None))
        self.assertTrue(cancelled.is_set())

    async def test_report_assistant_uses_strict_http_contract_and_trace_metadata(self) -> None:
        seen_wire: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            provider_payload = json.loads(request.content)
            wire_request = json.loads(provider_payload["messages"][1]["content"])
            validate_payload("report_assistant_request", wire_request)
            seen_wire.append(wire_request)
            return httpx.Response(
                200,
                json={
                    "model": "report-model-snapshot",
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": "Operations report",
                                        "executive_summary": "The governed result remained stable.",
                                        "table_title": "Governed detail",
                                        "chart_title": "Governed trend",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 13, "completion_tokens": 8},
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_ENDPOINT": "https://report-model.invalid",
                    "OPENAI_API_KEY": "report-token",
                    "OPENAI_MODEL": "gpt-5.4-mini",
                },
            ),
            patch(
                "app.adapters.model_transport.httpx.AsyncClient",
                return_value=http,
            ) as client_factory,
        ):
            proposal, trace = await generate_report_draft(self._report_request())

        client_factory.assert_called_once_with(trust_env=False)
        self.assertTrue(http.is_closed)
        self.assertEqual(1, len(seen_wire))
        self.assertNotIn("model", proposal)
        self.assertEqual("gpt-5.4-mini", trace["model_version"])
        self.assertEqual("report-model-snapshot", trace["model_snapshot"])


if __name__ == "__main__":
    unittest.main()
