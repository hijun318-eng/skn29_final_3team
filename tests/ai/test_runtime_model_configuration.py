"""모델 route manifest와 운영 가이드가 동일한 일반 설정 계약을 유지하는지 검증한다."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.ai.model_contracts import model_release_manifest
from src.modelops.runtime_config import (
    active_route_for_node,
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
    "NODE2_MODEL": "answervice-sql",
}


def test_unconfigured_optional_route_covers_every_active_node_with_primary() -> None:
    routes = resolve_active_model_routes(PRIMARY)

    assert len(routes) == 1
    assert set(routes[0].nodes) == set(model_release_manifest()["nodes"])
    assert routes[0].model == "gpt-5.4-mini"


def test_dedicated_sql_route_resolves_served_alias_and_exact_capacity() -> None:
    routes = resolve_active_model_routes(PRIMARY | NODE2)
    sql_route = active_route_for_node(routes, "node2")

    assert sql_route.nodes == ("node2", "node2_repair")
    assert sql_route.provider == "qwen"
    assert sql_route.model == "answervice-sql"
    assert sql_route.capacity.base_model == "Qwen/Qwen3.5-4B"
    assert sql_route.capacity.context_window_tokens == 5120
    assert sql_route.capacity.runtime_max_output_tokens == 1280
    assert (
        "src/modelops/releases/node2_pilot800_20260824.json"
        in sql_route.capacity.sources
    )


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
