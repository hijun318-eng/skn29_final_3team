from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .access_policy import AccessDeniedError
from .request_auth import (
    GatewayAuthenticationError,
    GatewayRequestAuthenticator,
    canonical_search_request,
    canonical_answer_request,
)
from .vector_application import VectorRagApplication
from .e2e.dashboard import E2EDashboard
from .security_audit_repository import SecurityAuditRepository


class ManualSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    recent_utterances: list[str] = Field(default_factory=list, max_length=3)
    selected_document_ids: list[str] = Field(default_factory=list, max_length=10)
    resolved_question: str | None = Field(default=None, min_length=2, max_length=500)
    domains: list[Literal[
        "COMMON", "PRIVACY", "REPORT", "NOTIFICATION_COOPERATION",
        "INTERACTIVE_ANALYSIS", "CUSTOMER_SERVICE", "EXTERNAL_REVIEW",
        "FOOD_BEVERAGE", "RESERVATION_CHECKIN_PAYMENT", "LEISURE",
        "FACILITY", "PARKING_EVENT_LOBBY", "ROOM", "SAFETY",
        "CUSTOMER_FEEDBACK", "CANCELLATION_REFUND_COMPENSATION",
    ]] = Field(default_factory=list, max_length=3)
    intent: Literal["PROCESS", "IMMEDIATE_ACTION", "DECISION_CRITERIA", "REGULATION_CHECK", "COMPARISON", "SUMMARY"] = "REGULATION_CHECK"



class ManualAnswerRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    evidence_blocks: list[dict] = Field(default_factory=list)
    intent: Literal["PROCESS", "IMMEDIATE_ACTION", "DECISION_CRITERIA", "REGULATION_CHECK", "COMPARISON", "SUMMARY"] = "REGULATION_CHECK"
    retrieval_request_id: str | None = None

def create_app(project_root: Path | None = None) -> FastAPI:
    root = (project_root or Path.cwd()).resolve()
    service = VectorRagApplication(root)
    audit = SecurityAuditRepository(service.database_url)
    authenticator = GatewayRequestAuthenticator(os.getenv("RAG_GATEWAY_HMAC_SECRET"))
    app = FastAPI(title="Answervice Internal Manual Tool API", version="1.0.0-rc1")

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def readiness() -> dict[str, object]:
        if not authenticator.configured:
            raise HTTPException(status_code=503, detail="Gateway authentication is not configured")
        status = service.status()
        if not status.get("embedding_api_configured"):
            raise HTTPException(status_code=503, detail="Embedding provider is not configured")
        return status

    @app.post("/v1/tools/internal-manual-search")
    def search(
        request: ManualSearchRequest,
        verified_role: Annotated[str | None, Header(alias="X-Verified-Role")] = None,
        timestamp: Annotated[str | None, Header(alias="X-Request-Timestamp")] = None,
        request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
        signature: Annotated[str | None, Header(alias="X-Request-Signature")] = None,
    ) -> dict[str, object]:
        query_hash = hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        recent = tuple(request.recent_utterances)
        selected = tuple(request.selected_document_ids)
        signed_payload = canonical_search_request(
            request.query, request.top_k, recent, selected, request.resolved_question, tuple(request.domains), request.intent
        )
        try:
            role = authenticator.verify(
                verified_role, timestamp, request_id, signature, signed_payload
            )
            if not audit.reserve_request_id(str(request_id)):
                raise GatewayAuthenticationError("Replayed gateway request")
            result = service.search(
                request.query,
                role,
                request.top_k,
                request_id=str(request_id),
                recent_utterances=recent,
                selected_document_ids=selected,
                resolved_question=request.resolved_question,
                domains=tuple(request.domains),
                intent=request.intent,
            )
            audit.record(request_id, role, query_hash, "AUTHORIZED", "SIGNED_GATEWAY_REQUEST")
            return result
        except GatewayAuthenticationError as error:
            audit.record(request_id, verified_role, query_hash, "DENIED", str(error))
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except AccessDeniedError as error:
            audit.record(request_id, verified_role, query_hash, "DENIED", "UNREGISTERED_ROLE")
            raise HTTPException(status_code=403, detail=str(error)) from error
        except Exception as error:
            audit.record(request_id, verified_role, query_hash, "ERROR", type(error).__name__)
            raise HTTPException(status_code=500, detail="Internal search failure") from error

    @app.post("/v1/tools/internal-manual-answer")
    def answer(
        request: ManualAnswerRequest,
        verified_role: Annotated[str | None, Header(alias="X-Verified-Role")] = None,
        timestamp: Annotated[str | None, Header(alias="X-Request-Timestamp")] = None,
        request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
        signature: Annotated[str | None, Header(alias="X-Request-Signature")] = None,
    ) -> dict[str, object]:
        query_hash = hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        signed_payload = canonical_answer_request(
            request.query,
            tuple(request.evidence_blocks),
            request.intent,
            request.retrieval_request_id,
        )
        try:
            role = authenticator.verify(
                verified_role, timestamp, request_id, signature, signed_payload
            )
            if not audit.reserve_request_id(str(request_id)):
                raise GatewayAuthenticationError("Replayed gateway request")
            result = service.answer(
                request_id=str(request_id or "dummy-req"),
                trace_id=str(request_id or "dummy-trace"),
                query=request.query,
                evidence_blocks=request.evidence_blocks,
                intent=request.intent,
                retrieval_request_id=request.retrieval_request_id,
            )
            audit.record(
                request_id,
                role,
                query_hash,
                "AUTHORIZED",
                "SIGNED_GATEWAY_REQUEST",
            )
            return result
        except GatewayAuthenticationError as error:
            audit.record(request_id, verified_role, query_hash, "DENIED", str(error))
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except AccessDeniedError as error:
            audit.record(request_id, verified_role, query_hash, "DENIED", "UNREGISTERED_ROLE")
            raise HTTPException(status_code=403, detail=str(error)) from error
        except Exception as error:
            audit.record(request_id, verified_role, query_hash, "ERROR", type(error).__name__)
            raise HTTPException(status_code=500, detail="Internal answer failure") from error

    @app.post("/v1/tools/internal-manual-catalog")
    def catalog(
        verified_role: Annotated[str | None, Header(alias="X-Verified-Role")] = None,
        timestamp: Annotated[str | None, Header(alias="X-Request-Timestamp")] = None,
        request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
        signature: Annotated[str | None, Header(alias="X-Request-Signature")] = None,
    ) -> dict[str, object]:
        try:
            role = authenticator.verify(verified_role, timestamp, request_id, signature, "{}")
            if not audit.reserve_request_id(str(request_id)):
                raise GatewayAuthenticationError("Replayed gateway request")
            audit.record(request_id, role, hashlib.sha256(b"{}").hexdigest(), "AUTHORIZED", "SIGNED_GATEWAY_REQUEST")
            return {"documents": service.catalog(role)}
        except GatewayAuthenticationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    @app.get("/v1/documents/{manual_id}/source.pdf")
    def source_pdf(
        manual_id: str,
        verified_role: Annotated[str | None, Header(alias="X-Verified-Role")] = None,
        timestamp: Annotated[str | None, Header(alias="X-Request-Timestamp")] = None,
        request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
        signature: Annotated[str | None, Header(alias="X-Request-Signature")] = None,
    ) -> Response:
        canonical = json.dumps({"manual_id": manual_id}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            role = authenticator.verify(verified_role, timestamp, request_id, signature, canonical)
            if not audit.reserve_request_id(str(request_id)):
                raise GatewayAuthenticationError("Replayed gateway request")
            content, filename = service.source_pdf(manual_id, role)
            audit.record(request_id, role, hashlib.sha256(canonical.encode()).hexdigest(), "AUTHORIZED", "SIGNED_GATEWAY_REQUEST")
            return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}", "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
        except GatewayAuthenticationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Manual PDF not found") from error

    dashboard = E2EDashboard(service)

    @app.get("/e2e", include_in_schema=False, response_class=HTMLResponse)
    def e2e_dashboard() -> str:
        return dashboard.html()

    @app.get("/v1/e2e/runtime-status")
    def e2e_runtime_status() -> dict[str, object]:
        return dashboard.runtime_status()

    return app
