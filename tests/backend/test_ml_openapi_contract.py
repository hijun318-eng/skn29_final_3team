"""ML runtime 오류가 실제 FastAPI envelope와 같은 OpenAPI 모델인지 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


def test_ml_runtime_failures_have_typed_openapi_responses() -> None:
    """capability·prediction의 502/503을 동일한 code/reason 계약으로 공개한다."""

    schema = app.openapi()
    for path, method in (("/ml/capabilities", "get"), ("/analysis/ml", "post")):
        responses = schema["paths"][path][method]["responses"]
        for status in ("502", "503"):
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/MLRuntimeErrorResponse"
            }

    error_response = schema["components"]["schemas"]["MLRuntimeErrorResponse"]
    assert error_response["required"] == ["detail"]
    error_detail = schema["components"]["schemas"]["MLRuntimeErrorDetail"]
    assert error_detail["required"] == ["code", "reason"]


def test_ml_success_responses_publish_versioned_contracts() -> None:
    """운영 capability와 prediction 200 응답을 임의 object로 공개하지 않는다."""

    schema = app.openapi()

    assert schema["paths"]["/ml/capabilities"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MLRuntimeCapability"
    }
    assert schema["paths"]["/analysis/ml"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MLRoomDemandPrediction"
    }

    capability = schema["components"]["schemas"]["MLRuntimeCapability"]
    assert capability["properties"]["schema_version"]["const"] == (
        "MLRuntimeCapability.v2"
    )
    prediction = schema["components"]["schemas"]["MLRoomDemandPrediction"]
    assert prediction["properties"]["schema_version"]["const"] == (
        "MLRoomDemandPrediction.v1"
    )
