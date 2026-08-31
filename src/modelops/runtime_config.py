"""활성 모델 노드의 환경 설정을 버전 고정 capacity·route manifest와 결합한다.

모델 별칭, provider, endpoint와 credential을 한 경계에서 검증하므로 새 서빙 모델을
추가할 때 질문별 분기나 코드 내 별칭 예외를 만들지 않고 manifest만 확장할 수 있다.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.ai.model_contracts import model_release_manifest


_MANIFEST_VERSION = "MODEL-RUNTIME-v1.5.0"
_MANIFEST_PATH = Path(__file__).with_name("model_runtime_manifest.v1.json")
_SUPPORTED_PROVIDERS = frozenset({"openai", "qwen"})


@dataclass(frozen=True)
class ModelCapacityProfile:
    """서빙 별칭들이 공유하는 provider·context window·출력 한도를 표현한다."""

    profile_id: str
    provider: str
    model_aliases: tuple[str, ...]
    base_model: str
    snapshot: str
    context_window_tokens: int
    runtime_max_output_tokens: int
    safety_margin_tokens: int
    sources: tuple[str, ...]

    def runtime_values(self) -> dict[str, Any]:
        """token budget과 trace가 소비할 불변 capacity 값을 새 mapping으로 반환한다."""

        return {
            "profile_id": self.profile_id,
            "provider": self.provider,
            "base_model": self.base_model,
            "snapshot": self.snapshot,
            "context_window_tokens": self.context_window_tokens,
            "runtime_max_output_tokens": self.runtime_max_output_tokens,
            "safety_margin_tokens": self.safety_margin_tokens,
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class ModelRouteProfile:
    """active release 노드 집합과 그 집합을 구성하는 환경 변수 계약을 묶는다."""

    route_id: str
    data_boundary: str
    route_label: str
    approved_endpoint_origins: tuple[str, ...]
    nodes: tuple[str, ...]
    provider_env: str | None
    default_provider: str | None
    endpoint_env: str
    token_env: str
    model_env: str
    fallback_route: str | None

    @property
    def environment_names(self) -> tuple[str, ...]:
        """부분 설정 여부를 판정할 route 소유 환경 변수 이름을 중복 없이 반환한다."""

        names = (self.endpoint_env, self.token_env, self.model_env)
        return ((self.provider_env,) + names) if self.provider_env else names


@dataclass(frozen=True)
class ModelRuntimeManifest:
    """검증된 capacity profile과 active-node route profile의 versioned 계약이다."""

    manifest_version: str
    capacity_profiles: tuple[ModelCapacityProfile, ...]
    route_profiles: tuple[ModelRouteProfile, ...]

    def capacity_for(
        self,
        model_alias: str,
        *,
        provider: str | None = None,
    ) -> ModelCapacityProfile:
        """서빙 model ID를 일반 별칭 목록에서 찾아 provider가 일치하는 profile로 해석한다."""

        matches = tuple(
            profile
            for profile in self.capacity_profiles
            if model_alias in profile.model_aliases
        )
        if len(matches) != 1:
            raise ValueError("active model alias is not registered exactly once")
        profile = matches[0]
        if provider is not None and profile.provider != provider:
            raise ValueError("active model provider does not match its capacity profile")
        return profile


@dataclass(frozen=True)
class ActiveModelRoute:
    """실행 시점에 확정된 노드·provider·endpoint·model과 capacity를 보존한다."""

    route_id: str
    manifest_version: str
    data_boundary: str
    nodes: tuple[str, ...]
    provider: str
    endpoint: str
    token: str = field(repr=False)
    model: str
    capacity: ModelCapacityProfile
    route_label: str = ""
    approved_endpoint_origins: tuple[str, ...] = ()

    @property
    def route_fingerprint(self) -> str:
        """credential을 제외한 실제 전송 route 계약의 canonical SHA-256을 반환한다."""

        payload = {
            "manifest_version": self.manifest_version,
            "route_id": self.route_id,
            "nodes": self.nodes,
            "data_boundary": self.data_boundary,
            "route_label": self.route_label,
            "approved_endpoint_origins": self.approved_endpoint_origins,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "model_snapshot": self.capacity.snapshot,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _parse_capacity(profile_id: str, raw: object) -> ModelCapacityProfile:
    expected = {
        "provider",
        "model_aliases",
        "base_model",
        "snapshot",
        "context_window_tokens",
        "runtime_max_output_tokens",
        "safety_margin_tokens",
        "sources",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError(f"capacity profile {profile_id!r} fields are invalid")
    aliases = raw["model_aliases"]
    if not isinstance(aliases, list) or not aliases:
        raise ValueError(f"capacity profile {profile_id!r} aliases are invalid")
    parsed_aliases = tuple(
        _required_text(alias, f"capacity profile {profile_id!r} alias")
        for alias in aliases
    )
    if len(parsed_aliases) != len(set(parsed_aliases)):
        raise ValueError(f"capacity profile {profile_id!r} aliases are duplicated")
    sources = raw["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"capacity profile {profile_id!r} sources are invalid")
    parsed_sources = tuple(
        _required_text(source, f"capacity profile {profile_id!r} source")
        for source in sources
    )
    if len(parsed_sources) != len(set(parsed_sources)):
        raise ValueError(f"capacity profile {profile_id!r} sources are duplicated")
    profile = ModelCapacityProfile(
        profile_id=_required_text(profile_id, "capacity profile id"),
        provider=_required_text(raw["provider"], "capacity provider"),
        model_aliases=parsed_aliases,
        base_model=_required_text(raw["base_model"], "capacity base model"),
        snapshot=_required_text(raw["snapshot"], "capacity snapshot"),
        context_window_tokens=_positive_integer(
            raw["context_window_tokens"], "context window"
        ),
        runtime_max_output_tokens=_positive_integer(
            raw["runtime_max_output_tokens"], "runtime max output"
        ),
        safety_margin_tokens=_positive_integer(
            raw["safety_margin_tokens"], "safety margin"
        ),
        sources=parsed_sources,
    )
    if (
        profile.provider not in _SUPPORTED_PROVIDERS
        or profile.runtime_max_output_tokens + profile.safety_margin_tokens
        >= profile.context_window_tokens
    ):
        raise ValueError(f"capacity profile {profile_id!r} limits are invalid")
    return profile


def _parse_route(route_id: str, raw: object) -> ModelRouteProfile:
    expected = {
        "data_boundary",
        "route_label",
        "approved_endpoint_origins",
        "nodes",
        "provider_env",
        "default_provider",
        "endpoint_env",
        "token_env",
        "model_env",
        "fallback_route",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError(f"model route {route_id!r} fields are invalid")
    nodes = raw["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise ValueError(f"model route {route_id!r} nodes are invalid")
    parsed_nodes = tuple(_required_text(node, "model route node") for node in nodes)
    if len(parsed_nodes) != len(set(parsed_nodes)):
        raise ValueError(f"model route {route_id!r} nodes are duplicated")
    approved_origins = raw["approved_endpoint_origins"]
    if (
        not isinstance(approved_origins, list)
        or any(not isinstance(origin, str) for origin in approved_origins)
        or len(approved_origins) != len(set(approved_origins))
    ):
        raise ValueError(f"model route {route_id!r} approved origins are invalid")
    route = ModelRouteProfile(
        route_id=_required_text(route_id, "model route id"),
        data_boundary=_required_text(raw["data_boundary"], "model data boundary"),
        route_label=_required_text(raw["route_label"], "model route label"),
        approved_endpoint_origins=tuple(
            _validate_origin(origin, "approved endpoint origin")
            for origin in approved_origins
        ),
        nodes=parsed_nodes,
        provider_env=_optional_text(raw["provider_env"], "provider environment"),
        default_provider=_optional_text(raw["default_provider"], "default provider"),
        endpoint_env=_required_text(raw["endpoint_env"], "endpoint environment"),
        token_env=_required_text(raw["token_env"], "token environment"),
        model_env=_required_text(raw["model_env"], "model environment"),
        fallback_route=_optional_text(raw["fallback_route"], "fallback route"),
    )
    if not route.provider_env and not route.default_provider:
        raise ValueError(f"model route {route_id!r} has no provider source")
    if route.data_boundary not in {"external", "internal"}:
        raise ValueError(f"model route {route_id!r} data boundary is invalid")
    if route.default_provider and route.default_provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"model route {route_id!r} default provider is unsupported")
    if route.data_boundary == "external" and not route.approved_endpoint_origins:
        raise ValueError(f"model route {route_id!r} has no approved endpoint origin")
    return route


def _validate_manifest(manifest: ModelRuntimeManifest) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    for profile in manifest.capacity_profiles:
        for source in profile.sources:
            if source.startswith("https://"):
                continue
            if not (repository_root / source).is_file():
                raise ValueError(
                    f"capacity profile {profile.profile_id!r} source is unavailable"
                )
    aliases = [
        alias
        for profile in manifest.capacity_profiles
        for alias in profile.model_aliases
    ]
    if len(aliases) != len(set(aliases)):
        raise ValueError("model aliases must belong to exactly one capacity profile")
    route_ids = {route.route_id for route in manifest.route_profiles}
    all_nodes = [node for route in manifest.route_profiles for node in route.nodes]
    active_nodes = set(model_release_manifest()["nodes"])
    if len(all_nodes) != len(set(all_nodes)) or set(all_nodes) != active_nodes:
        raise ValueError("model routes must cover every active release node exactly once")
    for route in manifest.route_profiles:
        if route.fallback_route and route.fallback_route not in route_ids:
            raise ValueError(f"model route {route.route_id!r} fallback is unknown")
        visited = {route.route_id}
        fallback = route.fallback_route
        while fallback:
            if fallback in visited:
                raise ValueError("model route fallback cycle is invalid")
            visited.add(fallback)
            fallback = next(
                item.fallback_route
                for item in manifest.route_profiles
                if item.route_id == fallback
            )


@lru_cache(maxsize=1)
def load_model_runtime_manifest() -> ModelRuntimeManifest:
    """JSON manifest를 typed 객체로 읽고 version·별칭·노드 완전성을 fail-closed 검증한다."""

    payload = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "manifest_version",
        "capacity_profiles",
        "route_profiles",
    }:
        raise ValueError("model runtime manifest fields are invalid")
    if payload["manifest_version"] != _MANIFEST_VERSION:
        raise ValueError("model runtime manifest version is invalid")
    capacities = payload["capacity_profiles"]
    routes = payload["route_profiles"]
    if not isinstance(capacities, dict) or not capacities:
        raise ValueError("model runtime capacity profiles are invalid")
    if not isinstance(routes, dict) or not routes:
        raise ValueError("model runtime route profiles are invalid")
    manifest = ModelRuntimeManifest(
        manifest_version=_MANIFEST_VERSION,
        capacity_profiles=tuple(
            _parse_capacity(profile_id, raw)
            for profile_id, raw in capacities.items()
        ),
        route_profiles=tuple(
            _parse_route(route_id, raw) for route_id, raw in routes.items()
        ),
    )
    _validate_manifest(manifest)
    return manifest


def _environment_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not isinstance(value, str):
        raise ValueError(f"model environment {name} must be a string")
    if value != value.strip():
        raise ValueError(f"model environment {name} must not contain outer whitespace")
    return value


def _validate_endpoint(value: str, environment_name: str) -> str:
    try:
        endpoint = urlsplit(value)
        endpoint.port
    except ValueError as error:
        raise ValueError(f"{environment_name} is invalid") from error
    if (
        any(character.isspace() for character in value)
        or endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
        or "?" in value
        or "#" in value
    ):
        raise ValueError(f"{environment_name} is invalid")
    return value.rstrip("/")


def _validate_origin(value: str, label: str) -> str:
    """manifest가 승인한 credential 없는 HTTPS origin만 canonical form으로 허용한다."""

    endpoint = _validate_endpoint(value, label)
    parsed = urlsplit(endpoint)
    if parsed.path not in {"", "/"}:
        raise ValueError(f"{label} must not contain a path")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{parsed.hostname.lower()}{port}"


def resolve_active_model_routes(
    environment: Mapping[str, str] | None = None,
) -> tuple[ActiveModelRoute, ...]:
    """환경의 완전한 route만 활성화하고 미설정 optional route는 선언된 route로 병합한다.

    optional route 변수 중 하나라도 존재하면 provider·endpoint·token·model을 모두 요구한다.
    model 별칭이 manifest에 없거나 provider가 capacity와 다르면 호출 전에 ``ValueError``로
    닫아 별도 endpoint 설정이 기본 provider 자격 증명으로 조용히 대체되지 않게 한다.
    """

    values = environment if environment is not None else os.environ
    manifest = load_model_runtime_manifest()
    active: dict[str, ActiveModelRoute] = {}
    inactive: list[ModelRouteProfile] = []
    for route in manifest.route_profiles:
        configured = {
            name: _environment_value(values, name)
            for name in route.environment_names
        }
        if route.fallback_route and not any(configured.values()):
            inactive.append(route)
            continue
        missing = tuple(name for name, value in configured.items() if not value)
        if missing:
            raise ValueError(
                f"model route {route.route_id!r} is partially configured: "
                + ", ".join(missing)
            )
        provider = (
            configured[route.provider_env]
            if route.provider_env
            else route.default_provider or ""
        )
        if provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"model route {route.route_id!r} provider is unsupported")
        model = configured[route.model_env]
        endpoint = _validate_endpoint(
            configured[route.endpoint_env], route.endpoint_env
        )
        parsed_endpoint = urlsplit(endpoint)
        endpoint_port = (
            f":{parsed_endpoint.port}" if parsed_endpoint.port is not None else ""
        )
        endpoint_origin = f"https://{parsed_endpoint.hostname.lower()}{endpoint_port}"
        # boundary label만 internal로 바꿔 외부 host에 대한 동의를 우회할 수
        # 없도록, 실제로 활성화되는 모든 route는 manifest에 목적지 origin을
        # 명시해야 한다. 아직 설정되지 않은 optional internal route는 fallback을
        # 사용하고, 추후 sLLM endpoint가 확정될 때 승인 origin을 함께 추가한다.
        if endpoint_origin not in route.approved_endpoint_origins:
            raise ValueError(
                f"model route {route.route_id!r} endpoint origin is not approved"
            )
        active[route.route_id] = ActiveModelRoute(
            route_id=route.route_id,
            manifest_version=manifest.manifest_version,
            data_boundary=route.data_boundary,
            nodes=route.nodes,
            provider=provider,
            endpoint=endpoint,
            token=configured[route.token_env],
            model=model,
            capacity=manifest.capacity_for(model, provider=provider),
            route_label=route.route_label,
            approved_endpoint_origins=route.approved_endpoint_origins,
        )
    for route in inactive:
        fallback = active.get(route.fallback_route or "")
        if fallback is None:
            raise ValueError(f"model route {route.route_id!r} fallback is inactive")
        active[fallback.route_id] = replace(
            fallback,
            nodes=fallback.nodes + route.nodes,
        )
    resolved = tuple(
        active[route.route_id]
        for route in manifest.route_profiles
        if route.route_id in active
    )
    covered_nodes = [node for route in resolved for node in route.nodes]
    if len(covered_nodes) != len(set(covered_nodes)):
        raise ValueError("active model routes contain duplicate nodes")
    return resolved


def active_route_for_node(
    routes: tuple[ActiveModelRoute, ...],
    node: str,
) -> ActiveModelRoute:
    """활성 route 중 지정 노드를 정확히 한 번 소유한 route를 반환한다."""

    matches = tuple(route for route in routes if node in route.nodes)
    if len(matches) != 1:
        raise ValueError(f"active model node {node!r} is not routed exactly once")
    return matches[0]
