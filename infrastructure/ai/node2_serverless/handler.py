"""Restricted RunPod proxy for the Node2 Qwen3.5-2B vLLM server.

The RunPod platform authenticates the public endpoint. This module talks only
to a vLLM process bound to loopback and deliberately exposes a small route
allowlist. Model selection is fixed so a request cannot silently reach a 4B or
another model.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, AsyncGenerator

import aiohttp


MODEL_ALIAS = "node2-qwen35-2b-full3000-20260825"
VLLM_BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = float(os.getenv("NODE2_REQUEST_TIMEOUT_SECONDS", "600"))

CHAT_ROUTE = "/v1/chat/completions"
MODELS_ROUTE = "/v1/models"
HEALTH_ROUTE = "/health"
ALLOWED_ROUTES = frozenset({CHAT_ROUTE, MODELS_ROUTE, HEALTH_ROUTE})

# Set by main.py after the subprocess has started. Leaving this as None makes
# normalization unit-testable without a live process.
vllm_process = None


class InvalidJobInput(ValueError):
    """The job cannot be safely mapped to the fixed Node2 API contract."""


def _contains_legacy_guided_json(body: dict[str, Any]) -> bool:
    if "guided_json" in body:
        return True
    extra_body = body.get("extra_body")
    return isinstance(extra_body, dict) and "guided_json" in extra_body


def normalize_job_input(job_input: Any) -> tuple[str, str, dict[str, Any] | None]:
    """Map RunPod OpenAI passthrough or direct queue input to one safe route."""
    if not isinstance(job_input, dict):
        raise InvalidJobInput("job.input must be a JSON object")

    if "openai_route" in job_input:
        route = job_input["openai_route"]
        if not isinstance(route, str) or route not in ALLOWED_ROUTES:
            raise InvalidJobInput(f"route is not allowed: {route!r}")
        if "openai_input" in job_input:
            body = job_input["openai_input"]
            if not isinstance(body, dict):
                raise InvalidJobInput("openai_input must be a JSON object")
            method = "POST"
        else:
            body = None
            method = "GET"
    elif "messages" in job_input:
        route = CHAT_ROUTE
        method = "POST"
        body = dict(job_input)
    else:
        raise InvalidJobInput(
            "job.input must contain OpenAI passthrough fields or chat messages"
        )

    if route in {MODELS_ROUTE, HEALTH_ROUTE}:
        if body is not None:
            raise InvalidJobInput(f"{route} only supports GET")
        return route, "GET", None

    if route != CHAT_ROUTE or method != "POST" or body is None:
        raise InvalidJobInput("only POST /v1/chat/completions is accepted")
    if not isinstance(body.get("messages"), list):
        raise InvalidJobInput("chat messages must be a JSON array")
    if _contains_legacy_guided_json(body):
        raise InvalidJobInput(
            "guided_json is disabled; use response_format with json_schema"
        )

    requested_model = body.get("model")
    if requested_model not in (None, MODEL_ALIAS):
        raise InvalidJobInput(
            f"model must be the fixed Node2 alias: {MODEL_ALIAS}"
        )
    normalized_body = dict(body)
    normalized_body["model"] = MODEL_ALIAS
    return CHAT_ROUTE, "POST", normalized_body


def _error(message: str, code: str) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": "node2_worker_error",
            "code": code,
        }
    }


def _is_vllm_alive() -> bool:
    return vllm_process is not None and vllm_process.poll() is None


async def handler(job: dict[str, Any]) -> AsyncGenerator[Any, None]:
    """Proxy one RunPod job to the fixed local vLLM instance."""
    try:
        route, method, body = normalize_job_input(job.get("input"))
    except InvalidJobInput as error:
        yield _error(str(error), "INVALID_INPUT")
        return

    if not _is_vllm_alive():
        yield _error("local vLLM process is not healthy", "VLLM_UNAVAILABLE")
        return

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                f"{VLLM_BASE_URL}{route}",
                json=body,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status >= 400:
                    detail = (await response.text())[:2000]
                    yield _error(
                        f"vLLM returned HTTP {response.status}: {detail}",
                        "VLLM_HTTP_ERROR",
                    )
                    return

                if route == HEALTH_ROUTE:
                    yield {"status": "healthy"}
                    return

                wants_stream = body is not None and body.get("stream") is True
                if wants_stream:
                    async for chunk in response.content.iter_any():
                        yield chunk.decode("utf-8", errors="replace")
                else:
                    yield await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        yield _error(f"request to local vLLM failed: {error}", "VLLM_REQUEST_FAILED")
