from __future__ import annotations

from typing import Annotated, Any

from fastapi import Cookie, Depends, HTTPException, Request

from app.container import Container


SESSION_COOKIE = "answervice_admin_session"


def container(request: Request) -> Container:
    return request.app.state.container


async def current_admin(
    services: Annotated[Container, Depends(container)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=401, detail="관리자 로그인이 필요합니다.")
    admin = await services.auth.current(token)
    if not admin:
        raise HTTPException(status_code=401, detail="관리자 세션이 만료되었습니다.")
    return admin


async def require_admin(admin: Annotated[dict[str, Any], Depends(current_admin)]) -> dict[str, Any]:
    if admin["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="ADMIN 권한이 필요합니다.")
    return admin
