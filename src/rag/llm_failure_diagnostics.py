"""LLM HTTP·network·JSON·계약 실패를 비민감 retry 분류로 축약한다."""

from __future__ import annotations

import json
import socket
import urllib.error
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class LlmFailureDiagnostic:
    """외부 호출 실패 코드와 안전한 재시도 가능 여부를 표현한다."""

    code: str
    retryable: bool


class LlmFailureDiagnostics:
    """OpenAI-compatible 실패를 원문 비밀 없이 안정된 진단 코드로 분류한다."""

    @staticmethod
    def from_exception(error: Exception) -> LlmFailureDiagnostic:
        """httpx·legacy URL·timeout·decode 예외를 retry 정책이 있는 진단으로 변환한다."""

        if isinstance(error, httpx.HTTPStatusError):
            return LlmFailureDiagnostics._from_http_status(
                error.response.status_code
            )
        if isinstance(error, httpx.TimeoutException):
            return LlmFailureDiagnostic("CONNECT_TIMEOUT", True)
        if isinstance(error, httpx.RequestError):
            return LlmFailureDiagnostics._from_url_reason(error)
        if isinstance(error, urllib.error.HTTPError):
            return LlmFailureDiagnostics._from_http_status(error.code)
        if isinstance(error, (TimeoutError, socket.timeout)):
            return LlmFailureDiagnostic("CONNECT_TIMEOUT", True)
        if isinstance(error, urllib.error.URLError):
            return LlmFailureDiagnostics._from_url_reason(error.reason)
        if isinstance(error, json.JSONDecodeError):
            return LlmFailureDiagnostic("INVALID_LLM_JSON", False)
        if isinstance(error, (KeyError, TypeError)):
            return LlmFailureDiagnostic("INVALID_PROVIDER_RESPONSE", False)
        if isinstance(error, ValueError):
            return LlmFailureDiagnostic("INVALID_ANSWER_CONTRACT", False)
        return LlmFailureDiagnostic("UNEXPECTED_ERROR", False)

    @staticmethod
    def _from_http_status(status_code: int) -> LlmFailureDiagnostic:
        if status_code in {401, 403}:
            return LlmFailureDiagnostic(f"HTTP_{status_code}", False)
        if status_code == 429:
            return LlmFailureDiagnostic("HTTP_429", True)
        if 500 <= status_code <= 599:
            return LlmFailureDiagnostic("HTTP_5XX", True)
        return LlmFailureDiagnostic(f"HTTP_{status_code}", False)

    @staticmethod
    def _from_url_reason(reason: object) -> LlmFailureDiagnostic:
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return LlmFailureDiagnostic("CONNECT_TIMEOUT", True)
        normalized = str(reason).lower()
        if any(marker in normalized for marker in ("timed out", "timeout")):
            return LlmFailureDiagnostic("CONNECT_TIMEOUT", True)
        if any(marker in normalized for marker in ("name or service not known", "temporary failure in name resolution", "nodename nor servname")):
            return LlmFailureDiagnostic("DNS_ERROR", False)
        if any(marker in normalized for marker in ("certificate", "ssl", "tls")):
            return LlmFailureDiagnostic("TLS_ERROR", False)
        if "connection refused" in normalized:
            return LlmFailureDiagnostic("CONNECTION_REFUSED", True)
        return LlmFailureDiagnostic("NETWORK_ERROR", True)
