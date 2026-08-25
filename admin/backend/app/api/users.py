from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request

from app.container import Container
from app.dependencies import container, current_admin, require_admin
from app.schemas import UserCreate, UserOut, UserPatch


router = APIRouter(prefix="/admin-api/users", tags=["admin-users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    services: Annotated[Container, Depends(container)],
    _: Annotated[dict[str, Any], Depends(current_admin)],
) -> list[dict[str, Any]]:
    return await services.users.list()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    services: Annotated[Container, Depends(container)],
    admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    return await services.users.create(
        payload, admin, request.headers.get("X-Request-ID") or uuid4().hex
    )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserPatch,
    request: Request,
    services: Annotated[Container, Depends(container)],
    admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    return await services.users.update(
        user_id, payload, admin, request.headers.get("X-Request-ID") or uuid4().hex
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    request: Request,
    services: Annotated[Container, Depends(container)],
    admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> None:
    await services.users.delete(
        user_id, admin, request.headers.get("X-Request-ID") or uuid4().hex
    )
