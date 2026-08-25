from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, Request, Response

from app.container import Container
from app.dependencies import SESSION_COOKIE, container, current_admin
from app.schemas import LoginRequest, UserOut


router = APIRouter(prefix="/admin-api/auth", tags=["admin-auth"])


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or uuid4().hex


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    services: Annotated[Container, Depends(container)],
) -> dict[str, Any]:
    user, token = await services.auth.login(payload.email, payload.password, _request_id(request))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=services.settings.session_ttl_seconds,
        httponly=True,
        secure=services.settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return user


@router.get("/me", response_model=UserOut)
async def me(admin: Annotated[dict[str, Any], Depends(current_admin)]) -> dict[str, Any]:
    return admin


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    services: Annotated[Container, Depends(container)],
    admin: Annotated[dict[str, Any], Depends(current_admin)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if token:
        await services.auth.logout(token, admin, _request_id(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
