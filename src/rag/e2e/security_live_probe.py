"""배포 RAG Gateway가 정상 서명만 허용하고 재사용·미등록 역할·만료 요청을 거부하는지 확인한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass

import httpx

from src.rag.request_auth import GatewayRequestAuthenticator, canonical_search_request


@dataclass(frozen=True)
class SecurityCheckResult:
    """하나의 실보안 시나리오 이름, 통과 여부, HTTP 상태와 비민감 진단을 기록한다."""

    name: str
    passed: bool
    status_code: int
    detail: str


class LiveSecurityContractVerifier:
    """동일 검색 payload에 정상·재사용·미등록 역할·만료 서명을 적용해 Gateway 경계를 검증한다."""

    def __init__(self, base_url: str, secret: str, query: str, role: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        self._query = query
        self._role = role

    def verify(self) -> list[SecurityCheckResult]:
        """네 가지 서명 시나리오를 실제 호출하고 각각의 허용·거부 결과 영수증을 반환한다."""

        payload = {
            "query": self._query,
            "top_k": 3,
            "trace_id": str(uuid.uuid4()),
            "actor_hash": hashlib.sha256(b"RAG_SECURITY_LIVE_PROBE").hexdigest(),
        }
        normal_headers = self._signed_headers(payload, self._role, int(time.time()))
        normal_status, normal_body = self._post(payload, normal_headers)
        results = [
            SecurityCheckResult(
                "authorized_signed_search",
                normal_status == 200,
                normal_status,
                f"evidence_count={len(normal_body.get('results', []))}",
            )
        ]
        replay_status, _ = self._post(payload, normal_headers)
        results.append(SecurityCheckResult("replayed_request_denied", replay_status in {401, 403, 409}, replay_status, "reused signed request"))
        unknown_headers = self._signed_headers(payload, "UNREGISTERED_ROLE", int(time.time()))
        unknown_status, _ = self._post(payload, unknown_headers)
        results.append(SecurityCheckResult("unregistered_role_denied", unknown_status in {401, 403}, unknown_status, "unregistered verified role"))
        expired_headers = self._signed_headers(payload, self._role, int(time.time()) - 120)
        expired_status, _ = self._post(payload, expired_headers)
        results.append(SecurityCheckResult("expired_timestamp_denied", expired_status in {401, 403}, expired_status, "expired signed timestamp"))
        return results

    def _signed_headers(self, payload: dict[str, object], role: str, epoch_seconds: int) -> dict[str, str]:
        request_id = str(uuid.uuid4())
        timestamp = str(epoch_seconds)
        canonical_request = canonical_search_request(
            self._query,
            int(payload["top_k"]),
            trace_id=str(payload["trace_id"]),
            actor_hash=str(payload["actor_hash"]),
        )
        signature = GatewayRequestAuthenticator.build_signature(self._secret, timestamp, request_id, role, canonical_request)
        return {
            "Content-Type": "application/json",
            "X-Verified-Role": role,
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Request-Signature": signature,
        }

    def _post(self, payload: dict[str, object], headers: dict[str, str]) -> tuple[int, dict[str, object]]:
        endpoint = f"{self._base_url}/v1/tools/internal-manual-search"
        try:
            with httpx.Client(
                timeout=httpx.Timeout(45.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    endpoint,
                    content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                )
        except httpx.RequestError:
            return 0, {}
        if response.is_redirect:
            return response.status_code, {}
        try:
            parsed = response.json()
        except json.JSONDecodeError:
            parsed = {}
        return response.status_code, parsed if isinstance(parsed, dict) else {}


def main() -> int:
    """명령행·환경 설정으로 실보안 검증을 실행하고 모든 검사 통과 여부를 종료 코드로 노출한다."""

    parser = argparse.ArgumentParser(description="Verify live Manual/Policy RAG security contracts")
    parser.add_argument("--base-url", default=os.getenv("RAG_E2E_BASE_URL", "http://127.0.0.1:18082"))
    parser.add_argument("--query", default=os.getenv("RAG_E2E_QUERY", "?關釉?癰귣떯????됯컧"))
    parser.add_argument("--role", default=os.getenv("RAG_E2E_ROLE", "MANAGER"))
    arguments = parser.parse_args()
    secret = os.getenv("RAG_E2E_GATEWAY_HMAC_SECRET", "")
    if not secret:
        raise SystemExit("RAG_E2E_GATEWAY_HMAC_SECRET is required")
    results = LiveSecurityContractVerifier(arguments.base_url, secret, arguments.query, arguments.role).verify()
    print(json.dumps({"checks": [asdict(result) for result in results]}, ensure_ascii=False, indent=2))
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
