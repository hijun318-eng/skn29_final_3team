"""Dependency-free production client contract and reproducible model trace."""

from __future__ import annotations

import json
import logging
from time import perf_counter
from hashlib import sha256
from typing import Any, Callable

from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, validate_payload


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


logger = logging.getLogger("uvicorn.error")


class ProductionModelClient:
    """Bound retries and circuit state while keeping transport injectable for tests."""

    def __init__(
        self,
        transport: Transport,
        *,
        timeout_seconds: float = 15.0,
        failure_threshold: int = 2,
    ) -> None:
        if timeout_seconds <= 0 or failure_threshold < 1:
            raise ValueError("timeout and failure threshold must be positive")
        self._transport = transport
        self._timeout = timeout_seconds
        self._threshold = failure_threshold
        self._failures = 0
        self.last_trace: dict[str, Any] = {}

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        try:
            validate_payload(f"{node}_request", payload)
        except (ContractError, TypeError, ValueError) as error:
            logger.warning(
                "production model request rejected: node=%s detail=%s",
                node,
                error,
            )
            raise
        if self._failures >= self._threshold:
            self._fail(node, "CIRCUIT_OPEN", 0)

        for attempt in (1, 2):
            try:
                response = self._transport(node, payload, self._timeout)
                validate_payload(f"{node}_response", response)
                self._failures = 0
                self.last_trace = {
                    "node": node,
                    "status": "SUCCESS",
                    "attempts": attempt,
                    "fallback": False,
                    "circuit_failures": 0,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                }
                return response
            except TimeoutError as error:
                reason = "TIMEOUT"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
            except (ContractError, TypeError, ValueError) as error:
                reason = "SCHEMA_INVALID"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
            except OSError as error:
                reason = "ENDPOINT_UNAVAILABLE"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
        self._failures += 1
        self._fail(node, reason, 2)

    def _fail(self, node: str, reason: str, attempts: int) -> None:
        self.last_trace = {
            "node": node,
            "status": reason,
            "attempts": attempts,
            "fallback": False,
            "circuit_failures": self._failures,
            "duration_ms": None,
        }
        raise TimeoutError(f"production model unavailable: {reason}")


def build_trace(
    *,
    trace_id: str,
    node: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    latency_ms: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """Record observed values only; unknown token and cost values stay null."""
    if not trace_id or latency_ms < 0:
        raise ValueError("trace id and non-negative latency are required")
    prompt_id = {
        "node1": "node1.normalize",
        "node2": "node2.sql",
        "node2_repair": "node2.repair",
        "node3": "node3.explain",
    }[node]
    model = output_payload.get("model", {})
    material = json.dumps(
        {"input": input_payload, "output": output_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    prompt = get_prompt(prompt_id)
    return {
        "trace_id": trace_id,
        "node": node,
        "model_version": model.get("model_version", prompt.model_version),
        "prompt_version": prompt.version,
        "prompt_hash": prompt.metadata()["hash"],
        "fixture_version": model.get("fixture_version"),
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "payload_hash": sha256(material).hexdigest(),
    }
