"""Backend 모델 조립이 typed active route와 동일한 credential 경계를 사용하는지 검증한다."""

from __future__ import annotations

from pathlib import Path
from sys import path
from unittest.mock import patch

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api.analysis_router_runtime import model


PRIMARY = {
    "OPENAI_ENDPOINT": "https://primary.model.invalid",
    "OPENAI_API_KEY": "primary-token",
    "OPENAI_MODEL": "gpt-5.4-mini",
    "MODEL_TIMEOUT_SECONDS": "30",
}
NODE2 = {
    "NODE2_MODEL_PROVIDER": "qwen",
    "NODE2_MODEL_ENDPOINT": "https://node2.model.invalid/openai",
    "NODE2_MODEL_API_TOKEN": "node2-token",
    "NODE2_MODEL": "answervice-sql",
}


def test_primary_route_is_shared_only_when_node2_configuration_is_empty() -> None:
    expected = object()
    with patch.dict("os.environ", PRIMARY, clear=True), patch(
        "app.adapters.contract_model.ContractModelAdapter.from_openai",
        return_value=expected,
    ) as factory:
        result = model()

    assert result is expected
    factory.assert_called_once_with(
        endpoint="https://primary.model.invalid",
        token="primary-token",
        model="gpt-5.4-mini",
        timeout_seconds=30.0,
    )


def test_dedicated_node2_route_never_substitutes_primary_credentials() -> None:
    expected = object()
    with patch.dict("os.environ", PRIMARY | NODE2, clear=True), patch(
        "app.adapters.contract_model.ContractModelAdapter.from_endpoints",
        return_value=expected,
    ) as factory:
        result = model()

    assert result is expected
    factory.assert_called_once_with(
        openai_endpoint="https://primary.model.invalid",
        openai_token="primary-token",
        openai_model="gpt-5.4-mini",
        node2_endpoint="https://node2.model.invalid/openai",
        node2_token="node2-token",
        node2_model="answervice-sql",
        node2_provider="qwen",
        timeout_seconds=30.0,
    )


def test_partial_node2_route_is_rejected_before_adapter_construction() -> None:
    with patch.dict(
        "os.environ",
        PRIMARY | {"NODE2_MODEL": "answervice-sql"},
        clear=True,
    ), patch(
        "app.adapters.contract_model.ContractModelAdapter.from_openai"
    ) as primary_factory, patch(
        "app.adapters.contract_model.ContractModelAdapter.from_endpoints"
    ) as routed_factory:
        with pytest.raises(ValueError, match="partially configured"):
            model()

    primary_factory.assert_not_called()
    routed_factory.assert_not_called()
