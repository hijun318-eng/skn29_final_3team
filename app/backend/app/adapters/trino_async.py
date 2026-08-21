"""이벤트 루프를 막지 않고 Trino HTTP statement protocol의 실행·page·cancel을 처리한다."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any

import httpx


class AdapterErrorCode(str, Enum):
    """호출자가 권한·timeout·cancel·upstream·query 실패를 분기할 수 있는 안정된 오류 분류다."""
    FORBIDDEN = "FORBIDDEN"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    UPSTREAM = "UPSTREAM"
    QUERY = "QUERY"


class AdapterError(RuntimeError):
    """Trino transport 또는 statement 실패를 ``AdapterErrorCode``와 메시지로 전달한다."""
    def __init__(self, code: AdapterErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QueryPage:
    """한 Trino statement page의 query id·상태·column·row·next URI·warning을 불변으로 보존한다."""
    query_id: str
    state: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    next_uri: str | None
    warnings: tuple[str, ...] = ()


class TrinoAsyncClient:
    """``httpx.AsyncClient``로 Trino statement를 실행하고 same-origin page 이동·취소만 허용한다."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        ca_file: str | Path | None = None,
        client: httpx.AsyncClient | None = None,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        endpoint = httpx.URL(base_url)
        if (
            endpoint.scheme != "https"
            or not endpoint.host
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or request_timeout_seconds <= 0
            or not isinstance(user, str)
            or not user.strip()
            or user != user.strip()
            or not isinstance(password, str)
            or not password
        ):
            raise ValueError("Trino endpoint, credentials, and timeout are invalid")
        # 운영 client는 HTTPS와 명시적 trust anchor가 모두 있어야 생성한다. 시스템 CA나
        # HTTP로 자동 강등하면 내부 DNS/프록시 장악 시 SQL과 Basic credential이 노출된다.
        if client is None:
            if ca_file is None:
                raise ValueError("Trino TLS and a CA file are required")
            ca_path = Path(ca_file)
            try:
                resolved_ca_path = ca_path.resolve(strict=True)
            except OSError as error:
                raise ValueError("Trino CA file is unavailable") from error
            if not ca_path.is_absolute() or not resolved_ca_path.is_file():
                raise ValueError("Trino CA file is unavailable")
            transport = httpx.AsyncClient(
                verify=ssl.create_default_context(cafile=str(resolved_ca_path)),
                trust_env=False,
            )
        else:
            # 임의 AsyncClient를 받으면 verify=False나 custom network transport로 운영 TLS를
            # 우회할 수 있다. 따라서 실제 socket을 열지 않는 httpx.MockTransport만 명시적
            # 테스트 seam으로 허용하고 모든 network client는 위 CA 검증 경로로 생성한다.
            if not isinstance(getattr(client, "_transport", None), httpx.MockTransport):
                raise ValueError("Only httpx.MockTransport may be injected")
            transport = client
        self._base_url = str(endpoint).rstrip("/")
        self._origin = _origin(endpoint)
        self._user = user
        self._auth = httpx.BasicAuth(user, password)
        self._request_timeout_seconds = request_timeout_seconds
        self._owns_client = client is None
        self._client = transport

    async def _request(
        self,
        method: str,
        url: str,
        body: str | None,
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        timeout = self._request_timeout_seconds
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AdapterError(
                    AdapterErrorCode.TIMEOUT,
                    "query total deadline exceeded",
                )
            timeout = min(timeout, remaining)
        try:
            response = await self._client.request(
                method,
                url,
                content=body.encode("utf-8") if body is not None else None,
                headers={
                    "Content-Type": (
                        "text/plain; charset=utf-8"
                        if body is not None
                        else "application/json"
                    ),
                    "X-Trino-User": self._user,
                },
                timeout=timeout,
                auth=self._auth,
            )
            response.raise_for_status()
            if not response.content:
                return {}
            payload = response.json()
        except httpx.TimeoutException as error:
            raise AdapterError(
                AdapterErrorCode.TIMEOUT,
                "upstream request timed out",
            ) from error
        except httpx.HTTPStatusError as error:
            code = (
                AdapterErrorCode.FORBIDDEN
                if error.response.status_code in {401, 403}
                else AdapterErrorCode.UPSTREAM
            )
            raise AdapterError(
                code,
                f"upstream HTTP {error.response.status_code}",
            ) from error
        except (httpx.RequestError, ValueError) as error:
            raise AdapterError(
                AdapterErrorCode.UPSTREAM,
                "upstream request failed",
            ) from error
        if not isinstance(payload, dict):
            raise AdapterError(
                AdapterErrorCode.UPSTREAM,
                "upstream returned an invalid response",
            )
        return payload

    @staticmethod
    def _page(payload: dict[str, Any]) -> QueryPage:
        error = payload.get("error")
        if isinstance(error, dict):
            # Trino는 DELETE 취소 후 stats.state보다 error payload를 먼저 반환하며,
            # errorName=USER_CANCELED이 권위 있는 typed 분류다. 메시지 문자열 비교로
            # 취소를 판정하면 locale/version에 따라 일반 QUERY 오류로 퇴행한다.
            error_name = str(error.get("errorName") or "")
            raise AdapterError(
                (
                    AdapterErrorCode.CANCELLED
                    if error_name == "USER_CANCELED"
                    else AdapterErrorCode.QUERY
                ),
                str(error.get("message") or "query failed"),
            )
        stats = payload.get("stats") or {}
        state = str(stats.get("state") or "QUEUED")
        if state == "CANCELED":
            raise AdapterError(AdapterErrorCode.CANCELLED, "query was cancelled")
        if state == "FAILED":
            raise AdapterError(AdapterErrorCode.QUERY, "query failed")
        try:
            return QueryPage(
                query_id=str(payload["id"]),
                state=state,
                columns=tuple(item["name"] for item in payload.get("columns") or ()),
                rows=tuple(tuple(row) for row in payload.get("data") or ()),
                next_uri=payload.get("nextUri"),
                warnings=tuple(
                    str(item.get("message") or "")
                    for item in payload.get("warnings") or ()
                ),
            )
        except (KeyError, TypeError) as error:
            raise AdapterError(
                AdapterErrorCode.UPSTREAM,
                "Trino returned an invalid query page",
            ) from error

    async def execute(self, sql: str, *, deadline: float | None = None) -> QueryPage:
        """SQL 원문을 coordinator statement endpoint에 POST하고 첫 응답을 typed ``QueryPage``로 변환한다."""
        payload = await self._request(
            "POST",
            f"{self._base_url}/v1/statement",
            sql,
            deadline=deadline,
        )
        return self._page(payload)

    async def next_page(
        self,
        next_uri: str,
        *,
        deadline: float | None = None,
    ) -> QueryPage:
        """coordinator와 same-origin인 ``nextUri``만 GET해 deadline 안의 다음 ``QueryPage``를 반환한다."""
        self._validate_next_uri(next_uri)
        return self._page(
            await self._request("GET", next_uri, None, deadline=deadline)
        )

    async def cancel(
        self,
        next_uri: str,
        *,
        deadline: float | None = None,
    ) -> None:
        """검증된 same-origin ``nextUri``에 DELETE를 보내 진행 중인 Trino statement를 취소한다."""
        self._validate_next_uri(next_uri)
        await self._request("DELETE", next_uri, None, deadline=deadline)

    def _validate_next_uri(self, value: str) -> None:
        try:
            uri = httpx.URL(value)
        except (TypeError, ValueError) as error:
            raise AdapterError(AdapterErrorCode.UPSTREAM, "Trino nextUri is invalid") from error
        # upstream nextUri를 그대로 따르면 credential이 임의 host로 전달될 수 있어 scheme·host·port를 고정한다.
        if (
            uri.scheme not in {"http", "https"}
            or not uri.host
            or uri.username
            or uri.password
            or uri.fragment
            or _origin(uri) != self._origin
        ):
            raise AdapterError(
                AdapterErrorCode.UPSTREAM,
                "Trino nextUri is outside the configured coordinator origin",
            )

    async def health(self) -> bool:
        """Trino info endpoint의 객체 응답 여부를 probe하고 adapter 실패는 readiness용 ``False``로 축약한다."""
        try:
            return bool(
                await self._request("GET", f"{self._base_url}/v1/info", None)
            )
        except AdapterError:
            return False

    async def statement_ready(self, *, deadline: float) -> bool:
        """runtime principal로 ``SELECT 1``을 terminal 성공까지 실행해 statement 권한을 증명한다.

        공개 `/v1/info` liveness와 달리 Basic 인증·사용자 일치·query 실행 권한을 실제
        statement protocol로 확인한다. same-origin ``nextUri``만 최대 100 page까지 따르고,
        정확히 한 행의 숫자 1을 반환하지 않거나 deadline·HTTP·query 오류가 나면 닫는다.
        """

        try:
            page = await self.execute("SELECT 1", deadline=deadline)
            rows = list(page.rows)
            for _ in range(100):
                if page.next_uri is None:
                    value = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else None
                    return (
                        page.state == "FINISHED"
                        and not isinstance(value, bool)
                        and value == 1
                    )
                page = await self.next_page(page.next_uri, deadline=deadline)
                rows.extend(page.rows)
            return False
        except AdapterError:
            return False

    async def aclose(self) -> None:
        """내부에서 생성한 ``httpx.AsyncClient``만 닫아 주입된 shared client의 소유권을 지킨다."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> TrinoAsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


def _origin(value: httpx.URL) -> tuple[str, str, int]:
    port = value.port or (443 if value.scheme == "https" else 80)
    return value.scheme, str(value.host).casefold(), port
