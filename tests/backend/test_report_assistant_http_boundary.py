"""보고서·Assistant 실패가 실제 HTTP 경계에서 안전한 공개 계약으로 유지되는지 검증한다."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
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
    public_receipt: dict[str, object] | None = None,
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
        detail = {
            "code": code,
            "assistant_request_id": assistant_request_id,
            "provider_message": "secret=must-not-leak",
        }
        detail.update(public_receipt or {})
        raise HTTPException(
            status_code=status_code,
            detail=detail,
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


def test_page_constraint_receipt_survives_patch_approval_http_envelope() -> None:
    assistant_request_id = str(uuid4())
    with TestClient(_boundary_app(
        "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED",
        route="/reports/assistant/sessions/{assistant_request_id}/patch-approval",
        status_code=409,
        public_receipt={"exact_page_count": 3, "verified_page_count": 101},
    )) as client:
        response = client.post(
            f"/reports/assistant/sessions/{assistant_request_id}/patch-approval"
        )

    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED"
    assert body["error"]["exact_page_count"] == 3
    assert body["error"]["verified_page_count"] == 101
    assert body["error"]["required_action"] == "MODIFY_REQUEST"
    assert body["error"]["retryable"] is False
    assert assistant_request_id not in response.text
    assert "must-not-leak" not in response.text
    assert "detail" not in body


def test_page_constraint_receipt_fails_closed_for_unsafe_values_or_path() -> None:
    cases = (
        (
            _boundary_app(
                "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED",
                route="/reports/assistant/sessions/{assistant_request_id}/patch-approval",
                status_code=409,
                public_receipt={"exact_page_count": True, "verified_page_count": 2},
            ),
            f"/reports/assistant/sessions/{uuid4()}/patch-approval",
        ),
        (
            _boundary_app(
                "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED",
                route="/unrelated/{assistant_request_id}/patch-approval",
                status_code=409,
                public_receipt={"exact_page_count": 2, "verified_page_count": 3},
            ),
            "/unrelated/opaque-internal-id/patch-approval",
        ),
    )
    for boundary, path in cases:
        with TestClient(boundary) as client:
            response = client.post(path)

        body = response.json()
        assert response.status_code == 409
        assert body["error"]["code"] == "RESOURCE_CONFLICT"
        assert "exact_page_count" not in body["error"]
        assert "verified_page_count" not in body["error"]
        assert "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED" not in response.text
        assert "must-not-leak" not in response.text


def test_page_renderer_failure_is_retryable_only_on_actual_assistant_endpoints() -> None:
    for endpoint in ("messages", "approval", "patch-approval"):
        route = f"/reports/assistant/sessions/{{assistant_request_id}}/{endpoint}"
        with TestClient(_boundary_app(
            "REPORT_ASSISTANT_PAGE_RENDER_FAILED", route=route, status_code=502
        )) as client:
            response = client.post(
                f"/reports/assistant/sessions/{uuid4()}/{endpoint}"
            )

        body = response.json()
        assert response.status_code == 502
        assert body["error"]["code"] == "REPORT_ASSISTANT_PAGE_RENDER_FAILED"
        assert body["error"]["retryable"] is True
        assert body["error"]["required_action"] == "RETRY"
        assert "must-not-leak" not in response.text

    with TestClient(_boundary_app(
        "REPORT_ASSISTANT_PAGE_RENDER_FAILED",
        route="/unrelated/{assistant_request_id}/patch-approval",
        status_code=502,
    )) as client:
        response = client.post("/unrelated/opaque-internal-id/patch-approval")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "REPORT_ASSISTANT_PAGE_RENDER_FAILED" not in response.text
    assert "must-not-leak" not in response.text


def test_report_block_revision_conflict_requires_reopening_the_latest_draft() -> None:
    boundary = FastAPI()

    @boundary.middleware("http")
    async def bind_request_context(request: Request, call_next):
        request.state.request_id = uuid4()
        request.state.trace_id = "report-draft-http-boundary"
        return await call_next(request)

    boundary.add_exception_handler(StarletteHTTPException, http_error)

    @boundary.put("/reports/definitions/{definition_id}/versions/{version}/blocks")
    async def fail_save(definition_id: str, version: int):
        if version == 2:
            raise HTTPException(
                status_code=409,
                detail="Legacy Report draft has no release receipt",
            )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REPORT_REVISION_CONFLICT",
                "current_draft_revision": 4,
                "internal": f"{definition_id}:{version}:must-not-leak",
            },
        )

    with TestClient(boundary) as client:
        response = client.put(f"/reports/definitions/{uuid4()}/versions/3/blocks")
        legacy_response = client.put(
            f"/reports/definitions/{uuid4()}/versions/2/blocks"
        )

    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "REPORT_DRAFT_CONFLICT"
    assert body["error"]["retryable"] is True
    assert body["error"]["required_action"] == "RETRY"
    assert "최신 초안을 다시 연 뒤" in body["error"]["message"]
    assert "current_draft_revision" not in response.text
    assert "must-not-leak" not in response.text

    legacy_body = legacy_response.json()
    assert legacy_response.status_code == 409
    assert legacy_body["error"]["code"] == "REPORT_DRAFT_CONFLICT"
    assert legacy_body["error"]["retryable"] is False
    assert legacy_body["error"]["required_action"] == "CONTACT_ADMIN"
    assert "이전 형식 보고서의 분석 근거 버전" in legacy_body["error"]["message"]
    assert "Legacy Report draft" not in legacy_response.text


def _external_transfer_disclosure(assistant_request_id: str) -> dict[str, object]:
    """HTTP 경계에 허용된 서버 발급 공개문만 구성한다."""

    return {
        "disclosure_id": str(uuid4()),
        "assistant_request_id": assistant_request_id,
        "policy_version": "REPORT-ASSISTANT-TRANSFER-v1.0.0",
        "provider_routes": [
            {
                "node": "report_assistant_turn",
                "route_id": "primary-openai",
                "route_label": "OpenAI API",
                "provider": "openai",
                "model": "gpt-report",
                "data_boundary": "external",
                "destination_origin": "https://api.openai.com",
            }
        ],
        "data_scopes": ["user_instruction", "report_block_content"],
        "excluded_data": ["인증 토큰·비밀번호·연결 자격 증명"],
        "content_warning": (
            "전송 대상 콘텐츠에 민감정보가 있으면 함께 전송될 수 있으므로 검토해 주세요."
        ),
        "disclosure_hash": "a" * 64,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        "consent_required": True,
    }


def test_external_transfer_428_preserves_only_validated_disclosure() -> None:
    assistant_request_id = str(uuid4())
    disclosure = _external_transfer_disclosure(assistant_request_id)
    with TestClient(
        _boundary_app(
            "EXTERNAL_TRANSFER_CONSENT_REQUIRED",
            status_code=428,
            public_receipt={
                "disclosure": disclosure,
                "unsafe_internal_route": "https://token@example.invalid?api_key=secret",
            },
        )
    ) as client:
        response = client.post(
            f"/reports/assistant/sessions/{assistant_request_id}/messages"
        )

    assert response.status_code == 428
    body = response.json()
    assert body["error"]["code"] == "EXTERNAL_TRANSFER_CONSENT_REQUIRED"
    assert body["error"]["assistant_request_id"] == assistant_request_id
    assert body["error"]["required_action"] == "REVIEW_EXTERNAL_TRANSFER"
    assert body["error"]["retryable"] is False
    assert body["error"]["disclosure"]["disclosure_id"] == disclosure["disclosure_id"]
    assert body["error"]["disclosure"]["provider_routes"] == disclosure["provider_routes"]
    assert body["error"]["disclosure"]["data_scopes"] == disclosure["data_scopes"]
    assert body["error"]["disclosure"]["disclosure_hash"] == disclosure["disclosure_hash"]
    assert body["error"]["trace_id"] == body["meta"]["trace_id"]
    assert "api_key" not in response.text
    assert "must-not-leak" not in response.text
    assert "unsafe_internal_route" not in response.text


def test_external_transfer_428_fails_closed_for_mismatched_or_invalid_disclosure() -> None:
    assistant_request_id = str(uuid4())
    cases = (
        _external_transfer_disclosure(str(uuid4())),
        {
            **_external_transfer_disclosure(assistant_request_id),
            "provider_routes": [
                {
                    "node": "report_assistant_turn",
                    "route_id": "primary-openai",
                    "route_label": "OpenAI API",
                    "provider": "openai",
                    "model": "gpt-report",
                    "data_boundary": "external",
                    "destination_origin": "https://api.openai.com",
                    "credential": "must-not-be-accepted",
                }
            ],
        },
    )
    for disclosure in cases:
        with TestClient(
            _boundary_app(
                "EXTERNAL_TRANSFER_CONSENT_REQUIRED",
                status_code=428,
                public_receipt={"disclosure": disclosure},
            )
        ) as client:
            response = client.post(
                f"/reports/assistant/sessions/{assistant_request_id}/messages"
            )

        body = response.json()
        assert response.status_code == 428
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "EXTERNAL_TRANSFER_CONSENT_REQUIRED" not in response.text
        assert "credential" not in response.text
        assert "must-not-leak" not in response.text


def test_unknown_external_transfer_outcome_requires_manual_new_session_without_retry() -> None:
    assistant_request_id = str(uuid4())
    with TestClient(
        _boundary_app(
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN",
            status_code=409,
        )
    ) as client:
        response = client.post(
            f"/reports/assistant/sessions/{assistant_request_id}/messages"
        )

    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
    assert body["error"]["retryable"] is False
    assert body["error"]["required_action"] == "RETRY"
    assert "새 Assistant 세션" in body["error"]["message"]
    assert assistant_request_id not in response.text
    assert "must-not-leak" not in response.text
