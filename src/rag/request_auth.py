from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections.abc import Callable
from uuid import UUID


class GatewayAuthenticationError(ValueError):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class GatewayRequestAuthenticator:
    def __init__(
        self,
        secret: str | None,
        maximum_clock_skew_seconds: int = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._secret = secret.encode("utf-8") if secret and len(secret) >= 32 else None
        self._maximum_clock_skew = maximum_clock_skew_seconds
        self._clock = clock
        self._used_request_ids: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._secret is not None

    def verify(
        self,
        role: str | None,
        timestamp: str | None,
        request_id: str | None,
        signature: str | None,
        query: str,
    ) -> str:
        if self._secret is None:
            raise GatewayAuthenticationError("Gateway authentication is not configured", 503)
        if not all((role, timestamp, request_id, signature)):
            raise GatewayAuthenticationError("Missing signed gateway headers")
        normalized_role = str(role).strip().upper()
        parsed_timestamp = self._parse_timestamp(str(timestamp))
        normalized_request_id = self._parse_request_id(str(request_id))
        now = self._clock()
        if abs(now - parsed_timestamp) > self._maximum_clock_skew:
            raise GatewayAuthenticationError("Expired gateway signature")
        expected = self.build_signature(
            self._secret, str(timestamp), normalized_request_id, normalized_role, query
        )
        if not hmac.compare_digest(expected, str(signature).lower()):
            raise GatewayAuthenticationError("Invalid gateway signature")
        self._reject_replay(normalized_request_id, now)
        return normalized_role

    @staticmethod
    def build_signature(
        secret: str | bytes,
        timestamp: str,
        request_id: str,
        role: str,
        query: str,
    ) -> str:
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        message = f"{timestamp}\n{request_id}\n{role.strip().upper()}\n{query_hash}".encode("utf-8")
        return hmac.new(secret_bytes, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _parse_timestamp(value: str) -> int:
        try:
            return int(value)
        except ValueError as error:
            raise GatewayAuthenticationError("Invalid gateway timestamp") from error

    @staticmethod
    def _parse_request_id(value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as error:
            raise GatewayAuthenticationError("Invalid gateway request ID") from error

    def _reject_replay(self, request_id: str, now: float) -> None:
        with self._lock:
            expired = [key for key, expiry in self._used_request_ids.items() if expiry < now]
            for key in expired:
                del self._used_request_ids[key]
            if request_id in self._used_request_ids:
                raise GatewayAuthenticationError("Replayed gateway request")
            self._used_request_ids[request_id] = now + self._maximum_clock_skew


def canonical_search_request(
    query: str,
    top_k: int,
    recent_utterances: tuple[str, ...] = (),
    selected_document_ids: tuple[str, ...] = (),
    resolved_question: str | None = None,
    domains: tuple[str, ...] = (),
    intent: str = "REGULATION_CHECK",
    *,
    trace_id: str,
    actor_hash: str,
) -> str:
    return json.dumps(
        {
            "query": query,
            "resolved_question": resolved_question or query,
            "domains": list(domains),
            "intent": intent,
            "recent_utterances": list(recent_utterances),
            "selected_document_ids": list(selected_document_ids),
            "top_k": top_k,
            "trace_id": trace_id,
            "actor_hash": actor_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_answer_request(
    query: str,
    evidence_blocks: tuple[dict[str, object], ...] = (),
    intent: str = "REGULATION_CHECK",
    retrieval_request_id: str | None = None,
    *,
    trace_id: str,
    actor_hash: str,
) -> str:
    normalized = tuple(
        {key: block[key] for key in sorted(block.keys())} if isinstance(block, dict) else {}
        for block in evidence_blocks
    )
    return json.dumps(
        {
            "query": query,
            "evidence_blocks": normalized,
            "intent": intent,
            "retrieval_request_id": retrieval_request_id,
            "trace_id": trace_id,
            "actor_hash": actor_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
