"""DataHub 운영 호출자가 공유하는 인증·TLS 환경 계약을 정의한다."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx


class DataHubConnectionError(ValueError):
    """DataHub endpoint, bearer token 또는 CA가 운영 보안 계약을 충족하지 못했음을 알린다."""


@dataclass(frozen=True)
class DataHubConnectionSettings:
    """하나의 HTTPS GMS origin과 외부 주입 bearer/CA를 불변 설정으로 묶는다.

    token은 ``repr``에서 제외해 예외·진단 객체 출력으로 credential이 새는 경로를
    차단한다. 이 계약은 production 환경만 다루며 HTTP test transport는 각 테스트가
    명시적으로 주입해야 한다.
    """

    base_url: str
    ca_file: Path
    actor_urn: str
    token: str = field(repr=False)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> DataHubConnectionSettings:
        """조회 전용 service identity의 HTTPS·Bearer·CA 계약을 읽어 검증한다."""

        return cls._from_env(
            "DATAHUB_READ_API_TOKEN", "DATAHUB_READ_ACTOR_URN", environ
        )

    @classmethod
    def from_publish_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> DataHubConnectionSettings:
        """metadata mutation 전용 service identity의 별도 Bearer 계약을 검증한다."""

        return cls._from_env(
            "DATAHUB_PUBLISH_API_TOKEN", "DATAHUB_PUBLISH_ACTOR_URN", environ
        )

    @classmethod
    def _from_env(
        cls,
        token_name: str,
        actor_name: str,
        environ: Mapping[str, str] | None,
    ) -> DataHubConnectionSettings:
        """고정된 권한 경계가 선택한 token 이름과 공통 TLS 설정을 조립한다."""

        source = os.environ if environ is None else environ
        base_url = source.get("DATAHUB_GMS_URL", "").strip()
        token = source.get(token_name, "").strip()
        actor_urn = source.get(actor_name, "").strip()
        ca_value = (
            source.get("DATAHUB_TLS_CA_FILE", "").strip()
            or source.get("DATAHUB_TLS_CA_HOST_FILE", "").strip()
        )
        endpoint = httpx.URL(base_url) if base_url else None
        if (
            endpoint is None
            or endpoint.scheme != "https"
            or not endpoint.host
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise DataHubConnectionError(
                "DATAHUB_GMS_URL must be an uncredentialed HTTPS origin"
            )
        if not token:
            raise DataHubConnectionError(f"{token_name} is required")
        if not actor_urn.startswith("urn:li:corpuser:service_"):
            raise DataHubConnectionError(
                f"{actor_name} must identify a DataHub service account"
            )
        ca_file = Path(ca_value).expanduser() if ca_value else None
        if ca_file is None or not ca_file.is_absolute() or not ca_file.is_file():
            raise DataHubConnectionError("an absolute readable DataHub CA file is required")
        return cls(str(endpoint).rstrip("/"), ca_file.resolve(), actor_urn, token)

    @property
    def authorization_headers(self) -> dict[str, str]:
        """모든 GMS 요청에 적용할 canonical Bearer header를 새 객체로 반환한다."""

        return {"Authorization": f"Bearer {self.token}"}

    def async_client(self, *, timeout_seconds: float) -> httpx.AsyncClient:
        """proxy 환경을 무시하고 지정 CA만 신뢰하는 bounded 비동기 transport를 생성한다."""

        if timeout_seconds <= 0:
            raise DataHubConnectionError("DataHub timeout must be positive")
        return httpx.AsyncClient(
            headers=self.authorization_headers,
            verify=str(self.ca_file),
            timeout=httpx.Timeout(timeout_seconds),
            trust_env=False,
        )
