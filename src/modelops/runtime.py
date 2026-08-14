"""Dependency-free production client contract and reproducible model trace."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from hashlib import sha256
from typing import Any, Callable

from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, schema_definition, validate_payload


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


logger = logging.getLogger("uvicorn.error")


class ModelTimeoutError(TimeoutError):
    code = "MODEL_TIMEOUT"
    retryable = True


class ModelEndpointUnavailableError(OSError):
    code = "MODEL_ENDPOINT_UNAVAILABLE"
    retryable = True


class ModelContractInvalidError(ValueError):
    code = "MODEL_CONTRACT_INVALID"
    retryable = False


class ModelCircuitOpenError(OSError):
    code = "CIRCUIT_OPEN"
    retryable = True


class ModelContextLimitError(ValueError):
    code = "INSUFFICIENT_CONTEXT"
    retryable = False


_TRANSPORT_META_KEY = "__answervice_transport_meta__"


def _canonical_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=1)
def model_runtime_manifest() -> dict[str, Any]:
    path = Path(__file__).with_name("model_runtime_manifest.v1.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != "MODEL-RUNTIME-v1.0.0":
        raise ValueError("model runtime manifest version is invalid")
    return manifest


def _schema_hash(definition: str) -> str:
    return _canonical_hash(schema_definition(definition))


class ProductionModelClient:
    """Bound retries and circuit state while keeping transport injectable for tests."""

    def __init__(
        self,
        transport: Transport,
        *,
        timeout_seconds: float = 15.0,
        failure_threshold: int = 2,
        max_attempts: int = 2,
        model_name: str | None = None,
    ) -> None:
        if timeout_seconds <= 0 or failure_threshold < 1 or max_attempts < 1:
            raise ValueError("timeout and failure threshold must be positive")
        self._transport = transport
        self._timeout = timeout_seconds
        self._threshold = failure_threshold
        self._max_attempts = max_attempts
        self._model_name = model_name
        self._failures = 0
        self.last_trace: dict[str, Any] = {}

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        self._enforce_context_budget(node, payload, started)
        try:
            validate_payload(f"{node}_request", payload)
        except (ContractError, TypeError, ValueError) as error:
            logger.warning(
                "production model request rejected: node=%s detail=%s",
                node,
                error,
            )
            self._record_failure(node, "MODEL_CONTRACT_INVALID", 0, started)
            raise ModelContractInvalidError("MODEL_CONTRACT_INVALID") from error
        if self._failures >= self._threshold:
            self._fail(node, "CIRCUIT_OPEN", 0, started)

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._transport(node, payload, self._timeout)
                transport_meta = response.pop(_TRANSPORT_META_KEY, {})
                validate_payload(f"{node}_response", response)
                self._failures = 0
                self.last_trace = {
                    "node": node,
                    "status": "SUCCESS",
                    "attempts": attempt,
                    "fallback": False,
                    "circuit_failures": 0,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    **self._trace_contract(node, payload),
                    "model_snapshot": transport_meta.get("model_snapshot")
                    or self._manifest_model().get("snapshot"),
                    "input_tokens": transport_meta.get("input_tokens"),
                    "output_tokens": transport_meta.get("output_tokens"),
                }
                return response
            except TimeoutError as error:
                reason = "MODEL_TIMEOUT"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
            except (ContractError, TypeError, ValueError) as error:
                reason = "MODEL_CONTRACT_INVALID"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
                break
            except OSError as error:
                reason = "MODEL_ENDPOINT_UNAVAILABLE"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
        self._failures += 1
        self._fail(node, reason, attempt, started)

    def _record_failure(
        self,
        node: str,
        reason: str,
        attempts: int,
        started: float,
    ) -> None:
        self.last_trace = {
            "node": node,
            "status": reason,
            "attempts": attempts,
            "fallback": False,
            "circuit_failures": self._failures,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            **self._trace_contract(node, {}),
            "model_snapshot": self._manifest_model().get("snapshot"),
            "input_tokens": None,
            "output_tokens": None,
        }

    def _fail(self, node: str, reason: str, attempts: int, started: float) -> None:
        self._record_failure(node, reason, attempts, started)
        errors = {
            "MODEL_TIMEOUT": ModelTimeoutError,
            "MODEL_ENDPOINT_UNAVAILABLE": ModelEndpointUnavailableError,
            "MODEL_CONTRACT_INVALID": ModelContractInvalidError,
            "CIRCUIT_OPEN": ModelCircuitOpenError,
        }
        raise errors[reason](reason)

    def _manifest_model(self) -> dict[str, Any]:
        if self._model_name is None:
            return {}
        models = model_runtime_manifest().get("models", {})
        try:
            return dict(models[self._model_name])
        except KeyError as error:
            raise ModelContextLimitError("INSUFFICIENT_CONTEXT") from error

    def _enforce_context_budget(
        self,
        node: str,
        payload: dict[str, Any],
        started: float,
    ) -> None:
        model = self._manifest_model()
        if not model:
            return
        prompt_id = {
            "node1": "node1.normalize",
            "node2": "node2.sql",
            "node2_repair": "node2.repair",
            "node3": "node3.explain",
        }[node]
        serialized = json.dumps(
            {
                "system": get_prompt(prompt_id).text,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        # UTF-8 bytes are a safe upper bound for text tokens without coupling the
        # control plane to a provider-specific tokenizer.
        token_upper_bound = len(serialized)
        allowed = (
            int(model["context_window_tokens"])
            - int(model["runtime_max_output_tokens"])
            - int(model["safety_margin_tokens"])
        )
        if token_upper_bound > allowed:
            self._record_failure(node, "INSUFFICIENT_CONTEXT", 0, started)
            raise ModelContextLimitError("INSUFFICIENT_CONTEXT")

    @staticmethod
    def _trace_contract(node: str, payload: dict[str, Any]) -> dict[str, Any]:
        package = payload.get("context_package") if isinstance(payload, dict) else None
        package = package if isinstance(package, dict) else {}
        return {
            "input_schema_hash": _schema_hash(f"{node}_request"),
            "output_schema_hash": _schema_hash(f"{node}_response"),
            "context_release": package.get("context_release")
            or package.get("context_version"),
            "policy_version": package.get("policy_version"),
            "data_release": package.get("data_release"),
        }


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
