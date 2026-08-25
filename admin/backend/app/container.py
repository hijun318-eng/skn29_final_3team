from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db import Database
from app.repositories import AuditRepository
from app.services import AuthService, ConnectionService, UserService


@dataclass(frozen=True)
class Container:
    settings: Settings
    db: Database
    auth: AuthService
    users: UserService
    connections: ConnectionService
    audit: AuditRepository

    @classmethod
    def build(cls, settings: Settings, db: Database) -> "Container":
        auth = AuthService(db, settings)
        return cls(
            settings=settings,
            db=db,
            auth=auth,
            users=UserService(db, auth.passwords),
            connections=ConnectionService(db, settings),
            audit=AuditRepository(),
        )
