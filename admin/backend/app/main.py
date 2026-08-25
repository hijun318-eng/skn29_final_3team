from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import audit, auth, connections, users
from app.config import Settings
from app.container import Container
from app.db import Database
from app.services import ServiceError


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = Settings.load()
    database = Database(settings.database_url)
    await database.open()
    services = Container.build(settings, database)
    await services.auth.bootstrap()
    application.state.container = services
    yield
    await database.close()


app = FastAPI(title="Answervice Admin API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(ServiceError)
async def service_error(_: Request, error: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(connections.router)
app.include_router(audit.router)


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    healthy = await request.app.state.container.db.healthy()
    return {"status": "healthy" if healthy else "unhealthy"}


@app.on_event("startup")
async def configure_cors() -> None:
    settings = app.state.container.settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
