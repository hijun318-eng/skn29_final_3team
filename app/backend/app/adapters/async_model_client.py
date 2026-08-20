"""FastAPI event loop에서 모델 schema 검증·deadline·재시도·circuit breaker를 비동기로 적용한다.

Async model runtime used by the FastAPI control plane.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from time import monotonic, perf_counter
from typing import Any, cast

from app.adapters.model_schemas import (
    canonical_model_input,
    request_definition,
    response_definition,
)
from src.ai.schema import ContractError, validate_payload
from src.modelops.runtime import (
    ModelCircuitOpenError,
    ModelContractInvalidError,
    ModelEndpointUnavailableError,
    ModelTimeoutError,
    ProductionModelClient,
    TokenCounter,
    _TRANSPORT_META_KEY,
    estimate_token_count,
)


AsyncTransport = Callable[
    [str, dict[str, Any], float],
    Awaitable[dict[str, Any]],
]

logger = logging.getLogger("uvicorn.error")


class ModelAuthenticationError(PermissionError):
    """provider가 API 자격 증명을 거부했으며 동일 credential 재시도가 무의미함을 나타낸다."""
    code = "MODEL_AUTHENTICATION_FAILED"
    retryable = False


class ModelRateLimitError(OSError):
    """provider 호출량 제한으로 요청이 일시 거부되어 backoff 후 재시도할 수 있음을 나타낸다."""
    code = "MODEL_RATE_LIMITED"
    retryable = True


class AsyncProductionModelClient(ProductionModelClient):
    """비동기 transport에 schema·전체 deadline·retry·circuit 계약을 적용한다.

    호출 전에 canonical request와 context budget을 검증하고 전체 deadline 안에서 jitter
    backoff를 수행한다. 인증 실패는 재시도하지 않고 rate limit·일시 transport 실패만 제한
    횟수 재시도하며, cooldown 뒤에는 한 coroutine만 half-open probe를 수행하게 한다.
    """

    def __init__(
        self,
        transport: AsyncTransport,
        *,
        timeout_seconds: float = 15.0,
        failure_threshold: int = 2,
        max_attempts: int = 2,
        model_name: str | None = None,
        token_counter: TokenCounter = estimate_token_count,
        circuit_cooldown_seconds: float = 30.0,
    ) -> None:
        if circuit_cooldown_seconds <= 0:
            raise ValueError("circuit cooldown must be positive")
        super().__init__(
            cast(Any, transport),
            timeout_seconds=timeout_seconds,
            failure_threshold=failure_threshold,
            max_attempts=max_attempts,
            model_name=model_name,
            token_counter=token_counter,
        )
        self._circuit_cooldown_seconds = circuit_cooldown_seconds
        self._circuit_opened_at: float | None = None
        self._half_open_probe = False
        self._circuit_lock = asyncio.Lock()

    async def _enter_circuit(self, node: str, started: float) -> None:
        async with self._circuit_lock:
            if self._failures < self._threshold:
                return
            elapsed = (
                0.0
                if self._circuit_opened_at is None
                else monotonic() - self._circuit_opened_at
            )
            if elapsed < self._circuit_cooldown_seconds or self._half_open_probe:
                self._fail(node, "CIRCUIT_OPEN", 0, started)
            self._half_open_probe = True

    async def _record_success(self) -> None:
        async with self._circuit_lock:
            self._failures = 0
            self._circuit_opened_at = None
            self._half_open_probe = False

    async def _record_transport_failure(self) -> None:
        async with self._circuit_lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._circuit_opened_at = monotonic()
            self._half_open_probe = False

    async def generate(
        self,
        node: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """노드 입력·출력 schema와 token budget을 검증하며 모델을 비동기로 호출한다.

        전체 deadline 안에서 제한된 재시도와 circuit breaker를 적용하고, 인증·rate limit·
        timeout·계약 위반을 서로 다른 예외로 보존한다.
        """
        started = perf_counter()
        try:
            wire_payload = canonical_model_input(node, payload)
            validate_payload(request_definition(node), wire_payload)
        except (ContractError, TypeError, ValueError) as error:
            logger.warning(
                "production model request rejected: node=%s detail=%s",
                node,
                error,
            )
            self._record_failure(node, "MODEL_CONTRACT_INVALID", 0, started)
            raise ModelContractInvalidError("MODEL_CONTRACT_INVALID") from error
        self._enforce_context_budget(node, wire_payload, started)
        await self._enter_circuit(node, started)

        reason = "MODEL_ENDPOINT_UNAVAILABLE"
        attempt = 0
        deadline = monotonic() + self._timeout
        for attempt in range(1, self._max_attempts + 1):
            try:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("model request deadline exceeded")
                async with asyncio.timeout(remaining):
                    response = await self._transport(node, wire_payload, remaining)
                transport_meta = response.pop(_TRANSPORT_META_KEY, {})
                if node == "node1" and isinstance(response, dict):
                    if response.get("filter_candidates") is None:
                        response["filter_candidates"] = []
                validate_payload(response_definition(node), response)
                await self._record_success()
                self.last_trace = {
                    "node": node,
                    "status": "SUCCESS",
                    "attempts": attempt,
                    "fallback": False,
                    "circuit_failures": 0,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    **self._trace_contract(node, wire_payload),
                    "model_version": transport_meta.get("model_version")
                    or self._model_name,
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
            except ModelAuthenticationError as error:
                reason = "MODEL_AUTHENTICATION_FAILED"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
                break
            except ModelRateLimitError as error:
                reason = "MODEL_RATE_LIMITED"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
            except OSError as error:
                reason = "MODEL_ENDPOINT_UNAVAILABLE"
                logger.warning(
                    "production model call rejected: node=%s attempt=%s reason=%s detail=%s",
                    node,
                    attempt,
                    reason,
                    error,
                )
            if attempt < self._max_attempts:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    reason = "MODEL_TIMEOUT"
                    break
                backoff = min(0.1 * (2 ** (attempt - 1)), 1.0)
                delay = min(remaining, backoff + random.uniform(0.0, backoff / 2))
                await asyncio.sleep(delay)
        await self._record_transport_failure()
        errors = {
            "MODEL_TIMEOUT": ModelTimeoutError,
            "MODEL_ENDPOINT_UNAVAILABLE": ModelEndpointUnavailableError,
            "MODEL_CONTRACT_INVALID": ModelContractInvalidError,
            "MODEL_AUTHENTICATION_FAILED": ModelAuthenticationError,
            "MODEL_RATE_LIMITED": ModelRateLimitError,
        }
        self._record_failure(node, reason, attempt, started)
        raise errors[reason](reason)

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다."""
        close = getattr(self._transport, "aclose", None)
        if callable(close):
            await close()


__all__ = [
    "AsyncProductionModelClient",
    "ModelCircuitOpenError",
    "ModelAuthenticationError",
    "ModelContractInvalidError",
    "ModelEndpointUnavailableError",
    "ModelRateLimitError",
    "ModelTimeoutError",
]
