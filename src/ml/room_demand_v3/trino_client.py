"""TLS와 origin 고정을 강제하는 최소 Trino statement protocol client를 제공한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


@dataclass(frozen=True)
class TrinoResult:
    """완료된 Trino query ID와 column 이름으로 매핑된 행 목록을 담는다."""

    query_id: str
    rows: list[dict[str, Any]]


class TrinoClient:
    """HTTPS·CA·basic auth로 Trino를 호출하고 nextUri origin 변경을 차단한다."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        ca_file: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("TRINO_URL must be an absolute HTTPS URL")
        if not ca_file:
            raise ValueError("TRINO_CA_FILE is required")
        self._base_url = base_url.rstrip("/") + "/"
        self._origin = (parsed.scheme, parsed.hostname, parsed.port)
        self._headers = {
            "X-Trino-User": user,
            "X-Trino-Source": "answervice-ml-room-demand-v3",
        }
        self._auth = httpx.BasicAuth(user, password)
        self._verify = ca_file
        self._timeout = timeout_seconds

    def _validate_next_uri(self, next_uri: str) -> str:
        absolute = urljoin(self._base_url, next_uri)
        parsed = urlparse(absolute)
        if (parsed.scheme, parsed.hostname, parsed.port) != self._origin:
            raise RuntimeError("Trino nextUri origin changed")
        return absolute

    def query(self, sql: str) -> TrinoResult:
        """SQL statement를 제출·끝까지 page 처리해 query ID와 행 mapping을 반환한다.

        HTTP 실패, Trino error payload, 외부 origin nextUri 또는 열·행 길이
        불일치는 예외로 전달해 부분 결과를 성공으로 반환하지 않는다.
        """

        rows: list[list[Any]] = []
        columns: list[str] = []
        query_id = ""
        with httpx.Client(
            auth=self._auth,
            verify=self._verify,
            timeout=self._timeout,
            headers=self._headers,
        ) as client:
            response = client.post(urljoin(self._base_url, "v1/statement"), content=sql)
            response.raise_for_status()
            payload = response.json()
            while True:
                query_id = payload.get("id", query_id)
                if payload.get("error"):
                    message = payload["error"].get("message", "unknown error")
                    raise RuntimeError(f"Trino query failed: {message}")
                if payload.get("columns"):
                    columns = [column["name"] for column in payload["columns"]]
                rows.extend(payload.get("data", []))
                next_uri = payload.get("nextUri")
                if not next_uri:
                    break
                response = client.get(self._validate_next_uri(next_uri))
                response.raise_for_status()
                payload = response.json()
        if not columns:
            return TrinoResult(query_id=query_id, rows=[])
        return TrinoResult(
            query_id=query_id,
            rows=[dict(zip(columns, row, strict=True)) for row in rows],
        )
