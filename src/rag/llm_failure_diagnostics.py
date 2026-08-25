from __future__ import annotations

import json
import socket
import urllib.error
from dataclasses import dataclass


@dataclass(frozen=True)
class LlmFailureDiagnostic:
    code: str
    retryable: bool


class LlmFailureDiagnostics:
    """Classify OpenAI-compatible LLM failures without preserving sensitive data."""

    @staticmethod
    def from_exception(error: Exception) -> LlmFailureDiagnostic:
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
