"""HTTP 테스트가 명시적으로 주입하는 인증 principal dependency를 제공한다."""

from __future__ import annotations

from uuid import UUID

from app.auth import AuthenticationError, Principal
from app.contracts import Role


INJECTED_PRINCIPALS = {
    "runtime-test-token": Principal(UUID(int=1), Role.ANALYST),
    "runtime-report-admin-token": Principal(UUID(int=2), Role.REPORT_ADMIN),
    "runtime-data-admin-token": Principal(UUID(int=3), Role.DATA_ADMIN),
}


async def authenticate_injected_token(token: str | None) -> Principal:
    """test support에 등록된 token만 principal로 변환하고 나머지는 401로 거부한다."""
    principal = INJECTED_PRINCIPALS.get(token or "")
    if principal is None:
        raise AuthenticationError("인증 정보를 확인할 수 없습니다.", 401)
    return principal


def injected_token_authenticator():
    """FastAPI dependency override에 test 전용 authenticator를 명시적으로 주입한다."""
    return authenticate_injected_token
