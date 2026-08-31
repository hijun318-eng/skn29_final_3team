"""Backend와 ML runtime 사이의 bounded HMAC wire 계약이다."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any


ML_RUNTIME_HMAC_SECRET_ENV = "ML_RUNTIME_HMAC_SECRET"
ML_RUNTIME_AUTH_VERSION = "v1"
ML_RUNTIME_AUTH_MAX_SKEW_SECONDS = 30
ML_RUNTIME_AUTH_MAX_BODY_BYTES = 1024 * 1024
ML_RUNTIME_TIMESTAMP_HEADER = "X-Answervice-ML-Timestamp"
ML_RUNTIME_NONCE_HEADER = "X-Answervice-ML-Nonce"
ML_RUNTIME_SIGNATURE_HEADER = "X-Answervice-ML-Signature"
ML_RUNTIME_RESPONSE_NONCE_HEADER = "X-Answervice-ML-Request-Nonce"
ML_RUNTIME_RESPONSE_SIGNATURE_HEADER = "X-Answervice-ML-Response-Signature"
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")


class MLRuntimeTrustError(RuntimeError):
    """ML runtime wire 인증이 없거나 현재 요청에 결속되지 않은 경우다."""


class MLRuntimeNonceGuard:
    """단일 runtime process에서 짧은 인증 창의 nonce 재사용을 거부한다."""

    def __init__(self, *, max_entries: int = 8192) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._seen_at: dict[str, int] = {}

    def consume(self, nonce: str, *, now: int | None = None) -> None:
        if not _NONCE.fullmatch(nonce):
            raise MLRuntimeTrustError("ML runtime request nonce is invalid")
        current = int(time.time()) if now is None else now
        cutoff = current - ML_RUNTIME_AUTH_MAX_SKEW_SECONDS
        expired = [value for value, seen_at in self._seen_at.items() if seen_at < cutoff]
        for value in expired:
            del self._seen_at[value]
        if nonce in self._seen_at:
            raise MLRuntimeTrustError("ML runtime request nonce was already used")
        if len(self._seen_at) >= self._max_entries:
            raise MLRuntimeTrustError("ML runtime request nonce capacity is exhausted")
        self._seen_at[nonce] = current


def runtime_hmac_secret() -> bytes:
    """외부 배포 secret만 허용하고 비어 있거나 과대한 값은 fail-closed한다."""

    value = os.getenv(ML_RUNTIME_HMAC_SECRET_ENV, "")
    encoded = value.encode("utf-8")
    if value != value.strip() or not 32 <= len(encoded) <= 4096:
        raise MLRuntimeTrustError(f"{ML_RUNTIME_HMAC_SECRET_ENV} is invalid")
    return encoded


def canonical_json_bytes(payload: Any) -> bytes:
    """Backend가 전송하고 runtime이 그대로 검증할 canonical JSON을 만든다."""

    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    _bounded_digest(body)
    return body


def _bounded_digest(body: bytes) -> str:
    if len(body) > ML_RUNTIME_AUTH_MAX_BODY_BYTES:
        raise MLRuntimeTrustError("ML runtime authenticated body is too large")
    return hashlib.sha256(body).hexdigest()


def _header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    raise MLRuntimeTrustError(f"missing ML runtime authentication header: {name}")


def _signature(secret: bytes, message: str) -> str:
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


def request_auth_headers(
    secret: bytes,
    method: str,
    path: str,
    body: bytes,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """30초 timestamp와 요청별 nonce에 method/path/body를 결속한다."""

    issued_at = int(time.time()) if timestamp is None else timestamp
    request_nonce = secrets.token_hex(16) if nonce is None else nonce
    if not _NONCE.fullmatch(request_nonce):
        raise MLRuntimeTrustError("ML runtime request nonce is invalid")
    message = "\n".join(
        (
            "REQUEST",
            ML_RUNTIME_AUTH_VERSION,
            str(issued_at),
            request_nonce,
            method.upper(),
            path,
            _bounded_digest(body),
        )
    )
    return {
        ML_RUNTIME_TIMESTAMP_HEADER: str(issued_at),
        ML_RUNTIME_NONCE_HEADER: request_nonce,
        ML_RUNTIME_SIGNATURE_HEADER: _signature(secret, message),
    }


def verify_request_auth(
    secret: bytes,
    headers: Mapping[str, str],
    method: str,
    path: str,
    body: bytes,
    *,
    now: int | None = None,
) -> str:
    """서명과 clock window를 검증하고 응답 결속에 쓸 nonce를 반환한다."""

    timestamp_text = _header(headers, ML_RUNTIME_TIMESTAMP_HEADER)
    nonce = _header(headers, ML_RUNTIME_NONCE_HEADER)
    supplied = _header(headers, ML_RUNTIME_SIGNATURE_HEADER)
    if not timestamp_text.isdigit() or len(timestamp_text) > 12:
        raise MLRuntimeTrustError("ML runtime request timestamp is invalid")
    timestamp = int(timestamp_text)
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > ML_RUNTIME_AUTH_MAX_SKEW_SECONDS:
        raise MLRuntimeTrustError("ML runtime request timestamp is outside the allowed window")
    expected_headers = request_auth_headers(
        secret,
        method,
        path,
        body,
        timestamp=timestamp,
        nonce=nonce,
    )
    expected = expected_headers[ML_RUNTIME_SIGNATURE_HEADER]
    if not _SIGNATURE.fullmatch(supplied) or not hmac.compare_digest(supplied, expected):
        raise MLRuntimeTrustError("ML runtime request signature is invalid")
    return nonce


def response_auth_headers(
    secret: bytes,
    path: str,
    status_code: int,
    request_nonce: str,
    body: bytes,
) -> dict[str, str]:
    """응답 status/path/body를 원 요청 nonce에 결속한다."""

    if not _NONCE.fullmatch(request_nonce):
        raise MLRuntimeTrustError("ML runtime response nonce is invalid")
    message = "\n".join(
        (
            "RESPONSE",
            ML_RUNTIME_AUTH_VERSION,
            request_nonce,
            str(status_code),
            path,
            _bounded_digest(body),
        )
    )
    return {
        ML_RUNTIME_RESPONSE_NONCE_HEADER: request_nonce,
        ML_RUNTIME_RESPONSE_SIGNATURE_HEADER: _signature(secret, message),
    }


def verify_response_auth(
    secret: bytes,
    headers: Mapping[str, str],
    path: str,
    status_code: int,
    request_nonce: str,
    body: bytes,
) -> None:
    """서명 없는 응답이나 다른 요청에서 재사용된 응답을 거부한다."""

    bound_nonce = _header(headers, ML_RUNTIME_RESPONSE_NONCE_HEADER)
    supplied = _header(headers, ML_RUNTIME_RESPONSE_SIGNATURE_HEADER)
    if bound_nonce != request_nonce:
        raise MLRuntimeTrustError("ML runtime response is bound to another request")
    expected = response_auth_headers(
        secret,
        path,
        status_code,
        request_nonce,
        body,
    )[ML_RUNTIME_RESPONSE_SIGNATURE_HEADER]
    if not _SIGNATURE.fullmatch(supplied) or not hmac.compare_digest(supplied, expected):
        raise MLRuntimeTrustError("ML runtime response signature is invalid")
