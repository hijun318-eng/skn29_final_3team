"""폐기된 단발성 Report Assistant API가 외부 전송 전에 닫히는지 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.api import report_router as report_api  # noqa: E402
from app.main import app  # noqa: E402


def _retired_route_app() -> FastAPI:
    boundary = FastAPI()
    boundary.include_router(report_api.report_router)
    boundary.dependency_overrides[report_api.report_admin_context] = lambda: object()
    return boundary


def test_legacy_draft_rejects_every_body_before_repository_or_model_access() -> None:
    """valid·malformed body 모두 repository와 외부 model보다 먼저 410으로 종료한다."""

    request_bodies = (
        ({"artifact_id": str(uuid4()), "instruction": "보고서를 수정해 줘"}, None),
        ({"artifact": {"evidence": {"sensitive": "must-not-transmit"}}}, None),
        (None, b"{malformed-json"),
    )
    boundary = _retired_route_app()
    for json_body, raw_body in request_bodies:
        router = Mock(side_effect=AssertionError("repository must not be constructed"))
        model = AsyncMock(side_effect=AssertionError("model must not be called"))
        with (
            patch.object(report_api, "_router", router),
            patch("app.adapters.report_assistant.generate_report_draft", model),
            TestClient(boundary) as client,
        ):
            if raw_body is None:
                response = client.post("/reports/assistant/drafts", json=json_body)
            else:
                response = client.post(
                    "/reports/assistant/drafts",
                    content=raw_body,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 410
        router.assert_not_called()
        model.assert_not_awaited()


def test_legacy_draft_openapi_is_bodyless_deprecated_and_gone_only() -> None:
    operation = app.openapi()["paths"]["/reports/assistant/drafts"]["post"]

    assert operation["deprecated"] is True
    assert "requestBody" not in operation
    assert "200" not in operation["responses"]
    assert operation["responses"]["410"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "세션 기반" in operation["responses"]["410"]["description"]


def test_legacy_draft_uses_production_gone_error_envelope() -> None:
    router = Mock(side_effect=AssertionError("repository must not be constructed"))
    model = AsyncMock(side_effect=AssertionError("model must not be called"))
    app.dependency_overrides[report_api.report_admin_context] = lambda: object()
    client = TestClient(app)
    try:
        with (
            patch.object(report_api, "_router", router),
            patch("app.adapters.report_assistant.generate_report_draft", model),
        ):
            response = client.post(
                "/reports/assistant/drafts",
                json={"artifact_id": str(uuid4()), "instruction": "legacy"},
            )
    finally:
        client.close()
        app.dependency_overrides.pop(report_api.report_admin_context, None)

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert response.json()["error"]["retryable"] is False
    router.assert_not_called()
    model.assert_not_awaited()
