"""모델 route manifest와 운영 가이드가 동일한 일반 설정 계약을 유지하는지 검증한다."""

from __future__ import annotations

from dataclasses import replace
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ai.model_contracts import model_release_manifest
from src.modelops.runtime_config import (
    active_route_for_node,
    load_model_runtime_manifest,
    resolve_active_model_routes,
)


ROOT = Path(__file__).resolve().parents[2]
PRIMARY = {
    "OPENAI_ENDPOINT": "https://primary.model.invalid",
    "OPENAI_API_KEY": "primary-token",
    "OPENAI_MODEL": "gpt-5.4-mini",
}
NODE2 = {
    "NODE2_MODEL_PROVIDER": "qwen",
    "NODE2_MODEL_ENDPOINT": "https://node2.model.invalid/openai",
    "NODE2_MODEL_API_TOKEN": "node2-token",
    "NODE2_MODEL": "node2-qwen35-2b-full3000-20260825",
}


@pytest.fixture(autouse=True)
def approved_test_model_origins():
    """격리 test endpoint만 typed manifest fixture에서 명시적으로 승인한다."""

    manifest = load_model_runtime_manifest()
    test_manifest = replace(
        manifest,
        route_profiles=tuple(
            replace(
                route,
                approved_endpoint_origins=(
                    "https://primary.model.invalid",
                ) if route.route_id == "primary" else (
                    "https://node2.model.invalid",
                ),
            )
            for route in manifest.route_profiles
        ),
    )
    with patch(
        "src.modelops.runtime_config.load_model_runtime_manifest",
        return_value=test_manifest,
    ):
        yield


def test_unconfigured_optional_route_covers_every_active_node_with_primary() -> None:
    routes = resolve_active_model_routes(PRIMARY)

    assert len(routes) == 1
    assert set(routes[0].nodes) == set(model_release_manifest()["nodes"])
    assert routes[0].model == "gpt-5.4-mini"
    assert routes[0].capacity.runtime_max_output_tokens == 4096


def test_dedicated_sql_route_resolves_served_alias_and_exact_capacity() -> None:
    routes = resolve_active_model_routes(PRIMARY | NODE2)
    sql_route = active_route_for_node(routes, "node2")

    assert sql_route.nodes == ("node2", "node2_repair")
    assert sql_route.provider == "qwen"
    assert sql_route.model == "node2-qwen35-2b-full3000-20260825"
    assert sql_route.capacity.base_model == "Qwen/Qwen3.5-2B"
    assert sql_route.capacity.snapshot == (
        "yoondaesung/answerviceqwen352b@28e9974a42163c5ca97137622669d40cfc14d73b"
    )
    assert sql_route.capacity.context_window_tokens == 5120
    assert sql_route.capacity.runtime_max_output_tokens == 1024


def test_cp135_capacity_and_runpod_origin_are_explicitly_registered() -> None:
    manifest = load_model_runtime_manifest()
    capacity = manifest.capacity_for("node2-qwen35-2b-cp135-20260901")
    sql_route = next(
        route for route in manifest.route_profiles if route.route_id == "sql"
    )

    assert capacity.base_model == "Qwen/Qwen3.5-2B"
    assert capacity.snapshot == (
        "yoondaesung/answervice-node2-qwen35-2b-cp135"
        "@3cea09dcb30b19f7ee584d2de299fb7f2e5c49a8"
    )
    assert capacity.context_window_tokens == 8192
    assert capacity.runtime_max_output_tokens == 1536
    assert sql_route.data_boundary == "external"
    assert sql_route.approved_endpoint_origins == ("https://api.runpod.ai",)


@pytest.mark.parametrize("missing", tuple(NODE2))
def test_partially_configured_sql_route_fails_closed(missing: str) -> None:
    environment = PRIMARY | NODE2
    environment.pop(missing)

    with pytest.raises(ValueError, match="partially configured"):
        resolve_active_model_routes(environment)


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"NODE2_MODEL_PROVIDER": "openai"}, "provider does not match"),
        ({"NODE2_MODEL": "unregistered-model"}, "not registered"),
        ({"NODE2_MODEL_ENDPOINT": "http://node2.invalid"}, "is invalid"),
        ({"NODE2_MODEL_API_TOKEN": " node2-token"}, "outer whitespace"),
    ),
)
def test_provider_alias_and_https_must_match_manifest(
    override: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_active_model_routes(PRIMARY | NODE2 | override)


def test_repository_example_leaves_optional_node2_route_fully_inactive() -> None:
    source = (ROOT / "infrastructure/database/.env.example").read_text(
        encoding="utf-8"
    )

    for name in NODE2:
        assert f"{name}=" in source
        assert re.search(rf"(?m)^{name}=$", source)
