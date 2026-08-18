"""운영 DataHub read/publish service token의 발급 주체 분리를 검증한다."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from datahub_connection import DataHubConnectionSettings


IDENTITY_QUERY = "query DataHubServiceIdentity { me { corpUser { urn } } }"


class ServiceTokenVerificationError(RuntimeError):
    """token이 인증되지 않거나 두 권한 경계가 같은 actor를 공유할 때 발생한다."""


def _identity_urn(payload: Any) -> str:
    """GraphQL identity 응답을 exact shape로 축소해 예상 밖 payload를 거부한다."""

    if not isinstance(payload, dict) or payload.get("errors"):
        raise ServiceTokenVerificationError("DataHub identity query was rejected")
    data = payload.get("data")
    if not isinstance(data, dict) or set(data) != {"me"}:
        raise ServiceTokenVerificationError("DataHub identity data is invalid")
    me = data.get("me")
    if not isinstance(me, dict) or set(me) != {"corpUser"}:
        raise ServiceTokenVerificationError("DataHub actor payload is invalid")
    corp_user = me.get("corpUser")
    if not isinstance(corp_user, dict) or set(corp_user) != {"urn"}:
        raise ServiceTokenVerificationError("DataHub corpUser payload is invalid")
    urn = corp_user.get("urn")
    if not isinstance(urn, str) or not urn.startswith("urn:li:corpuser:"):
        raise ServiceTokenVerificationError("DataHub actor URN is invalid")
    return urn


async def _query_identity(settings: DataHubConnectionSettings) -> str:
    """한 service token을 private-CA HTTPS로 보내고 인증된 actor를 확인한다."""

    async with settings.async_client(timeout_seconds=10.0) as client:
        response = await client.post(
            f"{settings.base_url}/api/graphql",
            json={"query": IDENTITY_QUERY, "variables": {}},
        )
        response.raise_for_status()
        actor_urn = _identity_urn(response.json())
        if actor_urn != settings.actor_urn:
            raise ServiceTokenVerificationError(
                "DataHub token actor does not match the deployment contract"
            )
        return actor_urn


async def verify_service_tokens() -> None:
    """read와 publish token이 서로 다른 DataHub service actor인지 검증한다."""

    read_settings = DataHubConnectionSettings.from_env()
    publish_settings = DataHubConnectionSettings.from_publish_env()
    if read_settings.token == publish_settings.token:
        raise ServiceTokenVerificationError("read and publish tokens must differ")
    if read_settings.actor_urn == publish_settings.actor_urn:
        raise ServiceTokenVerificationError("read and publish actors must differ")
    read_actor, publish_actor = await asyncio.gather(
        _query_identity(read_settings),
        _query_identity(publish_settings),
    )
    if read_actor == publish_actor:
        raise ServiceTokenVerificationError("read and publish actors must differ")


def main() -> int:
    """credential 값을 출력하지 않고 verification 결과와 종료 코드만 반환한다."""

    try:
        asyncio.run(verify_service_tokens())
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {"status": "NOT_VERIFIED", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"status": "VERIFIED"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
