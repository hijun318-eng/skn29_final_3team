"""Report Assistant 모델 실패가 실제 HTTP 경계에서 안전한 공개 계약으로 유지되는지 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.main import http_error  # noqa: E402


def _boundary_app(
    code: str,
    *,
    route: str = "/reports/assistant/sessions/{assistant_request_id}/messages",
    status_code: int = 502,
) -> FastAPI:
    boundary = FastAPI()

    @boundary.middleware("http")
    async def bind_request_context(request: Request, call_next):
        request.state.request_id = uuid4()
        request.state.trace_id = "report-assistant-http-boundary"
        return await call_next(request)

    boundary.add_exception_handler(StarletteHTTPException, http_error)

    @boundary.post(route)
    async def fail_message(assistant_request_id: str):
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": code,
                "assistant_request_id": assistant_request_id,
                "provider_message": "secret=must-not-leak",
            },
        )

    return boundary


def test_retryable_report_assistant_model_error_survives_actual_http_envelope() -> None:
    assistant_request_id = str(uuid4())
    with TestClient(_boundary_app("REPORT_ASSISTANT_MODEL_TIMEOUT")) as client:
        response = client.post(
            f"/reports/assistant/sessions/{assistant_request_id}/messages"
        )

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "REPORT_ASSISTANT_MODEL_TIMEOUT"
    assert body["error"]["retryable"] is True
    assert body["error"]["required_action"] == "RETRY"
    assert body["error"]["trace_id"] == body["meta"]["trace_id"]
    assert assistant_request_id not in response.text
    assert "must-not-leak" not in response.text
    assert "detail" not in body


def test_non_retryable_report_assistant_model_error_requires_admin_without_detail() -> None:
    with TestClient(
        _boundary_app("REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED")
    ) as client:
        response = client.post(
            f"/reports/assistant/sessions/{uuid4()}/messages"
        )

    body = response.json()
    assert response.status_code == 502
    assert body["error"]["code"] == "REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED"
    assert body["error"]["retryable"] is False
    assert body["error"]["required_action"] == "CONTACT_ADMIN"
    assert "must-not-leak" not in response.text


def test_unapproved_502_detail_fails_closed_to_generic_error() -> None:
    with TestClient(_boundary_app("UNAPPROVED_INTERNAL_CODE")) as client:
        response = client.post(
            f"/reports/assistant/sessions/{uuid4()}/messages"
        )

    body = response.json()
    assert response.status_code == 502
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["retryable"] is False
    assert body["error"]["required_action"] == "CONTACT_SUPPORT"
    assert "UNAPPROVED_INTERNAL_CODE" not in response.text
    assert "must-not-leak" not in response.text


def test_approved_code_requires_exact_assistant_path_and_502_status() -> None:
    cases = (
        (
            _boundary_app(
                "REPORT_ASSISTANT_MODEL_TIMEOUT",
                route="/unrelated/{assistant_request_id}/messages",
            ),
            "/unrelated/opaque-internal-id/messages",
            502,
        ),
        (
            _boundary_app("REPORT_ASSISTANT_MODEL_TIMEOUT", status_code=500),
            f"/reports/assistant/sessions/{uuid4()}/messages",
            500,
        ),
        (
            _boundary_app(
                "REPORT_ASSISTANT_MODEL_TIMEOUT",
                route="/reports/assistant/sessions/{assistant_request_id}/messages/",
            ),
            f"/reports/assistant/sessions/{uuid4()}/messages/",
            502,
        ),
    )
    for boundary, path, expected_status in cases:
        with TestClient(boundary) as client:
            response = client.post(path)

        body = response.json()
        assert response.status_code == expected_status
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "REPORT_ASSISTANT_MODEL_TIMEOUT" not in response.text
        assert "must-not-leak" not in response.text
