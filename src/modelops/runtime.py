"""런타임 운영 모델 호출의 timeout, 실패 격리, 추적 정책을 구현한다.

Dependency-free production client contract and reproducible model trace.
"""

from __future__ import annotations

import json
import logging
from math import ceil
from time import perf_counter
from hashlib import sha256
from typing import Any, Callable

from src.ai.model_contracts import model_node_contract
from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, schema_definition, validate_payload
from src.modelops.runtime_config import (
    ModelRuntimeManifest,
    load_model_runtime_manifest,
)


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]
TokenCounter = Callable[[str], int]


logger = logging.getLogger("uvicorn.error")


class ModelTimeoutError(TimeoutError):
    """모델 transport가 요청 deadline을 넘겨 제한된 재시도 대상이 됐음을 나타낸다."""
    code = "MODEL_TIMEOUT"
    retryable = True


class ModelEndpointUnavailableError(OSError):
    """모델 endpoint 연결이나 upstream 처리 실패로 일시 재시도가 가능함을 나타낸다."""
    code = "MODEL_ENDPOINT_UNAVAILABLE"
    retryable = True


class ModelContractInvalidError(ValueError):
    """요청 또는 응답이 active JSON Schema를 위반해 같은 payload 재시도가 금지됨을 나타낸다."""
    code = "MODEL_CONTRACT_INVALID"
    retryable = False


class ModelCircuitOpenError(OSError):
    """연속 transport 실패가 임계치를 넘어 새 provider 호출을 일시 차단했음을 나타낸다."""
    code = "CIRCUIT_OPEN"
    retryable = True


class ModelContextLimitError(ValueError):
    """canonical 입력 token 추정치가 노드 manifest 한도를 넘어 호출 전에 거부됐음을 나타낸다."""
    code = "INSUFFICIENT_CONTEXT"
    retryable = False


_TRANSPORT_META_KEY = "__answervice_transport_meta__"


def estimate_token_count(text: str) -> int:
    """Provider tokenizer가 없을 때 Unicode 문자를 UTF-8 byte로 오인하지 않는다.

    ASCII는 일반적인 BPE의 보수적 4자/token 비율을 사용하고, 한국어를 포함한
    비ASCII code point는 각각 한 token으로 잡는다. 실제 provider tokenizer를
    사용할 수 있는 배포에서는 ``ProductionModelClient.token_counter``로 교체한다.
    """

    ascii_count = sum(character.isascii() for character in text)
    non_ascii_count = len(text) - ascii_count
    return non_ascii_count + ceil(ascii_count / 4)


# Backwards-compatible import for existing offline evaluation code.
_estimated_token_count = estimate_token_count


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


def model_runtime_manifest() -> ModelRuntimeManifest:
    """별칭·provider·capacity·active-node route가 검증된 typed manifest를 반환한다."""

    return load_model_runtime_manifest()


def _schema_hash(definition: str) -> str:
    return _canonical_hash(schema_definition(definition))


class ProductionModelClient:
    """동기 transport 앞에서 active node schema와 model capacity budget을 강제한다.

    평가·단위 실행용 transport에 호출별 timeout을 전달하고 bounded retry와 연속 실패
    circuit을 적용한다. 성공·실패 trace에는 schema hash와 승인 model snapshot만 남기며
    timeout·endpoint·contract·circuit 실패는 각 typed 예외로 호출자에게 전달한다.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        timeout_seconds: float = 15.0,
        failure_threshold: int = 2,
        max_attempts: int = 2,
        model_name: str | None = None,
        token_counter: TokenCounter = estimate_token_count,
    ) -> None:
        if timeout_seconds <= 0 or failure_threshold < 1 or max_attempts < 1:
            raise ValueError("timeout and failure threshold must be positive")
        self._transport = transport
        self._timeout = timeout_seconds
        self._threshold = failure_threshold
        self._max_attempts = max_attempts
        self._model_name = model_name
        self._token_counter = token_counter
        self._failures = 0
        self.last_trace: dict[str, Any] = {}

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        """active schema·context budget을 확인한 뒤 동기 모델 transport를 제한 횟수 호출한다.

        성공 trace에는 prompt/schema/model hash를 남기고, timeout·endpoint·계약 실패를 분리해
        circuit state와 retryable 정책이 호출자에게 보존되게 한다.
        """
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
        try:
            return model_runtime_manifest().capacity_for(
                self._model_name
            ).runtime_values()
        except ValueError as error:
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
        prompt_id = str(model_node_contract(node)["prompt_id"])
        serialized = json.dumps(
            {
                "system": get_prompt(prompt_id).text,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        token_upper_bound = self._token_counter(serialized)
        if not isinstance(token_upper_bound, int) or token_upper_bound < 0:
            raise ValueError("token counter must return a non-negative integer")
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
        schema_context = (
            payload.get("schema_context")
            if node in {"node2", "node2_repair"} and isinstance(payload, dict)
            else None
        )
        schema_context = schema_context if isinstance(schema_context, dict) else {}
        query_policy = (
            payload.get("query_policy")
            if node in {"node2", "node2_repair"} and isinstance(payload, dict)
            else None
        )
        policy_hash = (
            sha256(
                json.dumps(
                    query_policy,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if isinstance(query_policy, dict)
            else None
        )
        contract = model_node_contract(node)
        return {
            "input_schema_hash": _schema_hash(str(contract["request_definition"])),
            "output_schema_hash": _schema_hash(str(contract["response_definition"])),
            "context_release": schema_context.get("version"),
            "policy_version": policy_hash,
            "data_release": None,
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
    """실행 node의 prompt·model version과 입출력 payload SHA-256을 trace 증거로 묶는다.

    빈 trace ID와 음수 latency는 거부한다. token·비용은 실제 관측값만 기록하고 미관측 값은
    ``None``으로 보존하며, 등록되지 않은 node/prompt는 registry의 ``KeyError``로 실패한다.
    """
    if not trace_id or latency_ms < 0:
        raise ValueError("trace id and non-negative latency are required")
    prompt_id = str(model_node_contract(node)["prompt_id"])
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
