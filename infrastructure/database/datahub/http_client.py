"""로컬 DataHub 관리 작업에 쓰는 제한된 비동기 HTTP transport를 제공한다."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from metadata_wire import entity_path, metadata_change_proposals


LOCAL_GMS_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "datahub-gms",
    "datahub-gms-quickstart",
}


class DataHubAdminError(RuntimeError):
    """로컬 DataHub 요청이 실패했거나 유효하지 않은 계약을 반환했음을 나타낸다."""


def validate_local_server(server: str) -> str:
    """metadata 관리 endpoint를 인증정보 없는 승인된 GMS origin으로 제한한다."""

    parsed = urlparse(server)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_GMS_HOSTS:
        raise ValueError("DataHub metadata administration is restricted to local GMS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("DataHub GMS URL must not contain credentials, query, or fragment")
    return server.rstrip("/")


class DataHubMetadataAdminClient:
    """발행 또는 검증 workflow 전체에서 ``httpx.AsyncClient`` 하나를 재사용한다."""

    def __init__(
        self,
        server: str,
        *,
        token: str | None = None,
        ca_file: str | Path | None = None,
        timeout_seconds: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """timeout을 검증하고 HTTPS·Bearer·CA owned client 또는 MockTransport만 구성한다."""

        if timeout_seconds <= 0:
            raise ValueError("DataHub timeout must be positive")
        self.server = validate_local_server(server)
        parsed = urlparse(self.server)
        if http is None:
            if parsed.scheme != "https" or not token or ca_file is None:
                raise ValueError(
                    "owned DataHub transport requires HTTPS, bearer token, and CA"
                )
            ca_path = Path(ca_file)
            try:
                resolved_ca_path = ca_path.resolve(strict=True)
            except OSError as error:
                raise ValueError("DataHub CA file is unavailable") from error
            if not ca_path.is_absolute() or not resolved_ca_path.is_file():
                raise ValueError("DataHub CA file is unavailable")
        elif not isinstance(getattr(http, "_transport", None), httpx.MockTransport):
            raise ValueError("Only httpx.MockTransport may be injected")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._owns_http = http is None
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-RestLi-Protocol-Version": "2.0.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._headers = headers
        self._http = http or httpx.AsyncClient(
            verify=str(resolved_ca_path),
            timeout=self._timeout,
            trust_env=False,
        )

    async def upsert_entity(
        self,
        entity_type: str,
        urn: str,
        aspects: Mapping[str, Mapping[str, Any]],
        audit_stamp: Mapping[str, Any],
    ) -> None:
        """동기 MCP endpoint로 entity의 검증된 aspect를 순서대로 upsert한다."""

        entity_path(entity_type)
        proposals = metadata_change_proposals(entity_type, urn, aspects, audit_stamp)
        endpoint = f"{self.server}/aspects?action=ingestProposal"
        for proposal in proposals:
            await self._request(
                "POST",
                endpoint,
                json={"proposal": proposal, "async": "false"},
                expect_json=False,
            )

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict[str, Any]:
        """정확한 URN 하나에서 요청된 aspect만 Rest.li를 통해 조회한다."""

        if not aspects:
            raise ValueError("at least one DataHub aspect is required")
        path = f"{self.server}/entitiesV2/{quote(urn, safe='')}"
        # WHY: Rest.li는 List(a,b) 문법의 쉼표를 그대로 요구한다. 쉼표를 percent-encoding하면
        # GMS가 전체 문자열을 하나의 aspect 이름으로 해석해 잘못된 readback이 된다.
        url = httpx.URL(path).copy_with(
            query=f"aspects=List({','.join(aspects)})".encode("ascii")
        )
        payload = await self._request("GET", url, expect_json=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("aspects"), dict):
            raise DataHubAdminError("DataHub entity response is missing aspects")
        return payload

    async def graphql(
        self,
        query: str,
        variables: Mapping[str, Any],
    ) -> dict[str, Any]:
        """GraphQL을 실행하고 오류 없는 객체형 data 결과만 반환한다."""

        payload = await self._request(
            "POST",
            f"{self.server}/api/graphql",
            json={"query": query, "variables": dict(variables)},
            expect_json=True,
        )
        if not isinstance(payload, dict) or payload.get("errors"):
            raise DataHubAdminError("DataHub GraphQL returned errors or an invalid payload")
        return payload

    async def _request(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        json: object | None = None,
        expect_json: bool,
    ) -> object | None:
        try:
            response = await self._http.request(
                method,
                url,
                json=json,
                headers=self._headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            if not expect_json:
                return None
            return response.json()
        except httpx.TimeoutException as error:
            raise DataHubAdminError("DataHub request timed out") from error
        except httpx.HTTPStatusError as error:
            raise DataHubAdminError(
                f"DataHub request failed with HTTP {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise DataHubAdminError("DataHub request failed") from error
        except ValueError as error:
            raise DataHubAdminError("DataHub returned malformed JSON") from error

    async def aclose(self) -> None:
        """이 adapter가 생성해 소유한 HTTP client만 안전하게 닫는다."""

        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> DataHubMetadataAdminClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()
