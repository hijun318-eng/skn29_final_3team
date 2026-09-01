"""실제 RAG·Analysis·ML HTTP 런타임 호출을 JSON·서명·준비 상태 계약으로 감싼다."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from .contracts import DynamicE2EConfig, RuntimeEndpoint
from ..request_auth import (
    GatewayRequestAuthenticator,
    canonical_answer_request,
    canonical_search_request,
)


class RuntimeRequestError(RuntimeError):
    """실런타임의 연결·시간 초과·HTTP·응답 계약 위반을 안정된 코드와 함께 전달한다."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.response = response or {}


@dataclass(frozen=True)
class JsonResponse:
    """성공한 JSON 객체 응답의 HTTP 상태, 본문, 측정 지연 시간을 묶는다."""

    status_code: int
    payload: dict[str, Any]
    latency_ms: float


class JsonHttpClient:
    """리다이렉트와 환경 프록시를 허용하지 않고 실런타임 JSON 요청만 수행한다."""

    def __init__(self, timeout_seconds: float) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0.1 <= float(timeout_seconds) <= 300.0
        ):
            raise ValueError("E2E HTTP timeout must be between 0.1 and 300 seconds")
        self._timeout_seconds = timeout_seconds

    def get(self, url: str, headers: dict[str, str] | None = None) -> JsonResponse:
        """지정 URL에 GET을 보내고 유효한 JSON 객체 응답 또는 분류된 요청 오류를 돌려준다."""

        return self._request("GET", url, None, headers or {})

    def post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> JsonResponse:
        """사전 payload를 UTF-8 JSON으로 POST하고 상태·본문·지연 시간 영수증을 반환한다."""

        return self._request("POST", url, payload, headers or {})

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> JsonResponse:
        request_headers = {"Accept": "application/json", **headers}
        encoded: bytes | None = None
        if payload is not None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        try:
            with httpx.Client(
                timeout=httpx.Timeout(float(self._timeout_seconds)),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.request(
                    method,
                    url,
                    content=encoded,
                    headers=request_headers,
                )
            if response.is_redirect:
                raise RuntimeRequestError(
                    code="REDIRECT_BLOCKED",
                    message=f"{method} {url} returned a disallowed redirect",
                    status_code=response.status_code,
                )
            if response.status_code >= 400:
                parsed = self._try_parse_json(response.text)
                raise RuntimeRequestError(
                    code="HTTP_ERROR",
                    message=f"{method} {url} returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    response=parsed,
                )
            parsed = self._parse_json(response.text, response.status_code, url)
            return JsonResponse(
                status_code=response.status_code,
                payload=parsed,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except RuntimeRequestError:
            raise
        except httpx.TimeoutException as error:
            raise RuntimeRequestError(
                code="RUNTIME_TIMEOUT",
                message=f"{method} {url} exceeded {self._timeout_seconds} seconds",
            ) from error
        except httpx.RequestError as error:
            raise RuntimeRequestError(
                code="RUNTIME_UNREACHABLE",
                message=f"{method} {url} could not reach the configured runtime",
            ) from error

    @staticmethod
    def _parse_json(body: str, status_code: int, url: str) -> dict[str, Any]:
        parsed = JsonHttpClient._try_parse_json(body)
        if not parsed:
            raise RuntimeRequestError(
                code="INVALID_RUNTIME_RESPONSE",
                message=f"HTTP {status_code} from {url} did not contain a JSON object",
            )
        return parsed

    @staticmethod
    def _try_parse_json(body: str) -> dict[str, Any]:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


class RuntimeHealthClient:
    """런타임 준비 상태 URL의 JSON 상태가 허용된 정상 값인지 fail-closed로 판정한다."""

    def __init__(self, endpoint: RuntimeEndpoint, http: JsonHttpClient) -> None:
        self._endpoint = endpoint
        self._http = http

    def check(self) -> JsonResponse:
        """준비 상태를 조회해 명시적 정상 상태만 통과시키고 그 밖에는 RUNTIME_NOT_READY로 실패한다."""

        response = self._http.get(self._endpoint.health_url)
        if not self._is_healthy(response.payload):
            raise RuntimeRequestError(
                code="RUNTIME_NOT_READY",
                message=f"{self._endpoint.name} health endpoint did not report ready state",
                status_code=response.status_code,
                response=response.payload,
            )
        return response

    @staticmethod
    def _is_healthy(payload: dict[str, Any]) -> bool:
        status_candidates = []

        direct_status = payload.get("status")
        if direct_status is not None:
            status_candidates.append(direct_status)

        direct_state = payload.get("state")
        if direct_state is not None:
            status_candidates.append(direct_state)

        data = payload.get("data")
        if isinstance(data, dict):
            nested_status = data.get("status")
            if nested_status is not None:
                status_candidates.append(nested_status)
            nested_state = data.get("state")
            if nested_state is not None:
                status_candidates.append(nested_state)

        for status in status_candidates:
            normalized = str(status).strip().upper()
            if normalized in {"READY", "HEALTHY", "ALIVE", "OK", "UP", "LIVE", "SUCCEEDED"}:
                return True
            if normalized == "NOT_READY":
                return False
        return False


class RagGatewayClient:
    """E2E 주체와 trace를 HMAC 서명해 RAG 검색·근거 제한 답변 엔드포인트를 호출한다."""

    def __init__(self, config: DynamicE2EConfig, http: JsonHttpClient) -> None:
        self._config = config
        self._http = http

    def search(self) -> JsonResponse:
        """설정된 질의와 top-k를 서명된 검색 요청으로 보내 원본 Gateway 응답을 반환한다."""

        actor_hash = hashlib.sha256(
            self._config.user_id.encode("utf-8")
        ).hexdigest()
        payload = {
            "query": self._config.rag_query,
            "top_k": self._config.top_k,
            "recent_utterances": [],
            "selected_document_ids": [],
            "trace_id": self._config.trace_id,
            "actor_hash": actor_hash,
        }
        headers = self._headers(
            canonical_search_request(
                payload["query"],
                payload["top_k"],
                tuple(payload["recent_utterances"]),
                tuple(payload["selected_document_ids"]),
                trace_id=self._config.trace_id,
                actor_hash=actor_hash,
            )
        )
        return self._http.post(self._url(self._config.rag_search_path), payload, headers)

    def answer(
        self,
        evidence_blocks: list[dict[str, Any]],
        retrieval_request_id: str,
        answer_query: str,
    ) -> JsonResponse:
        """검색 영수증과 비어 있지 않은 근거만 답변 요청에 서명하며 근거 부재는 호출 전에 거부한다."""

        if not evidence_blocks:
            raise RuntimeRequestError(
                code="RAG_EVIDENCE_EMPTY",
                message="RAG answer call requires evidence returned by the real search runtime",
            )
        payload = {
            "query": answer_query,
            "evidence_blocks": evidence_blocks,
            "intent": "REGULATION_CHECK",
            "retrieval_request_id": retrieval_request_id,
            "trace_id": self._config.trace_id,
            "actor_hash": hashlib.sha256(
                self._config.user_id.encode("utf-8")
            ).hexdigest(),
        }
        headers = self._headers(
            canonical_answer_request(
                payload["query"],
                tuple(evidence_blocks),
                payload["intent"],
                retrieval_request_id,
                trace_id=self._config.trace_id,
                actor_hash=str(payload["actor_hash"]),
            )
        )
        return self._http.post(self._url(self._config.rag_answer_path), payload, headers)

    def _headers(self, signed_payload: str) -> dict[str, str]:
        timestamp = str(int(time.time()))
        request_id = str(uuid4())
        signature = GatewayRequestAuthenticator.build_signature(
            self._config.rag_gateway_secret,
            timestamp,
            request_id,
            self._config.role,
            signed_payload,
        )
        return {
            "X-Verified-Role": self._config.role,
            "X-Request-Id": request_id,
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature,
        }

    def _url(self, path: str) -> str:
        return f"{self._config.rag.base_url.rstrip('/')}{path}"


class AnalysisCoreClient:
    """사용자·역할·기준일·계약 버전을 헤더에 고정해 Analysis Core 질문을 제출한다."""

    def __init__(self, config: DynamicE2EConfig, http: JsonHttpClient) -> None:
        self._config = config
        self._http = http

    def analyze(self) -> JsonResponse:
        """설정된 분석 질문을 인증·추적 헤더와 함께 보내 실제 분석 JSON 응답을 받는다."""

        payload = {"question": self._config.analysis_question}
        headers = {
            "Authorization": f"Bearer {self._config.analysis_auth_token}",
            "X-As-Of": self._config.analysis_as_of,
            "X-Request-Id": self._config.request_id,
            "X-Trace-Id": self._config.trace_id,
            "X-User-Id": self._config.user_id,
            "X-Role": self._config.role,
            "X-Timezone": self._config.timezone_name,
            "X-Contract-Version": self._config.analysis_contract_version,
        }
        return self._http.post(
            f"{self._config.analysis.base_url.rstrip('/')}{self._config.analysis_path}",
            payload,
            headers,
        )


class MlRuntimeClient:
    """ML 준비 상태를 조회하고 활성 승인 모델이 증명된 경우에만 예측을 요청한다."""

    def __init__(self, config: DynamicE2EConfig, http: JsonHttpClient) -> None:
        self._config = config
        self._http = http

    def health(self) -> JsonResponse:
        """설정된 ML 준비 상태 URL을 조회해 승인 판정에 사용할 원본 JSON 영수증을 반환한다."""

        return self._http.get(self._config.ml.health_url)

    def prediction(self, analysis_payload: dict[str, Any]) -> JsonResponse:
        """활성 승인 모델을 재확인한 뒤 분석 결과와 예측 범위를 ML 런타임에 전달한다."""

        runtime_health = self.health()
        self._ensure_prediction_is_approved(runtime_health.payload)
        payload = {
            "request_id": self._config.request_id,
            "trace_id": self._config.trace_id,
            "role": self._config.role,
            "metric": self._config.ml_metric,
            "hotel_scope": self._config.ml_hotel_scope,
            "horizon": self._config.ml_horizon,
            "as_of": self._config.analysis_as_of,
            "analysis": analysis_payload,
        }
        return self._http.post(
            f"{self._config.ml.base_url.rstrip('/')}{self._config.ml_predict_path}",
            payload,
            {"X-Request-Id": self._config.request_id, "X-Trace-Id": self._config.trace_id},
        )

    @staticmethod
    def _ensure_prediction_is_approved(payload: dict[str, Any]) -> None:
        approval = str(payload.get("approval_status", payload.get("status", ""))).upper()
        active = payload.get("active")
        if active is not True or approval not in {"APPROVED", "HEALTHY", "READY"}:
            raise RuntimeRequestError(
                code="ML_MODEL_BLOCKED",
                message="ML runtime did not prove that a prediction model is active and approved",
                response=payload,
            )
