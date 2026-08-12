"""Dependency-free production client contract and reproducible model trace."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Callable, NoReturn

from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, validate_payload


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


class ModelUnavailableError(RuntimeError):
    """Raised when the configured production model cannot return a valid response."""


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
        validate_payload(f"{node}_request", payload)
        if self._failures >= self._threshold:
            self._raise_unavailable("CIRCUIT_OPEN", 0)

        for attempt in (1, 2):
            try:
                response = self._transport(node, payload, self._timeout)
                validate_payload(f"{node}_response", response)
                self._failures = 0
                self.last_trace = {
                    "status": "SUCCESS",
                    "attempts": attempt,
                    "circuit_failures": 0,
                }
                return response
            except TimeoutError:
                reason = "TIMEOUT"
            except (ContractError, TypeError, ValueError):
                reason = "SCHEMA_INVALID"
            except OSError:
                reason = "ENDPOINT_UNAVAILABLE"
        self._failures += 1
        self._raise_unavailable(reason, 2)

    def _raise_unavailable(self, reason: str, attempts: int) -> NoReturn:
        self.last_trace = {
            "status": reason,
            "attempts": attempts,
            "circuit_failures": self._failures,
        }
        raise ModelUnavailableError(f"production model unavailable: {reason}")


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
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "payload_hash": sha256(material).hexdigest(),
    }
