"""runtime DataHub ingestion recipe에서 release discovery scope를 해석한다."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ReleaseScopeError(ValueError):
    """runtime recipe가 모호하지 않은 physical discovery scope를 정의하지 못했음을 나타낸다."""


@dataclass(frozen=True, order=True)
class ReleaseScope:
    """DataHub platform-instance namespace 하나와 Trino schema 하나의 매핑이다."""

    catalog: str
    schema: str
    platform_instance: str
    datahub_namespace: str
    origin: str


def load_release_scopes(
    recipe_paths: Sequence[Path],
    environment: Mapping[str, str],
) -> tuple[ReleaseScope, ...]:
    """환경변수로 해석된 scope만 읽고 정적 scenario 값은 거부한다."""

    if not recipe_paths:
        raise ReleaseScopeError("at least one runtime ingestion recipe is required")
    scopes = [
        _scope_from_recipe(path.resolve(), environment)
        for path in sorted(recipe_paths, key=lambda item: str(item.resolve()))
    ]
    return _validated_scopes(scopes)


def load_release_scopes_with_serving(
    recipe_paths: Sequence[Path],
    environment: Mapping[str, str],
    serving_schema: str,
    *,
    serving_recipe_name: str = "serving.runtime.yml",
) -> tuple[ReleaseScope, ...]:
    """동적 serving ingestion과 별개로 승인할 단일 serving schema를 결합한다.

    ingestion recipe는 새 schema를 자동 수집하므로 allow-list를 갖지 않는다. 반면
    governance approval은 한 번에 정확히 한 physical release에 결박되어야 하므로,
    호출자가 선택한 schema를 해당 Trino recipe의 catalog·instance 계약과 조합한다.
    """

    if not recipe_paths:
        raise ReleaseScopeError("at least one runtime ingestion recipe is required")
    resolved = tuple(
        sorted((path.resolve() for path in recipe_paths), key=lambda item: str(item))
    )
    serving_paths = tuple(path for path in resolved if path.name == serving_recipe_name)
    if len(serving_paths) != 1:
        raise ReleaseScopeError("exactly one serving runtime recipe is required")
    scopes = [
        _scope_from_recipe(path, environment)
        for path in resolved
        if path != serving_paths[0]
    ]
    scopes.append(
        _scope_from_recipe(
            serving_paths[0],
            environment,
            schema_override=_identifier(serving_schema.strip(), "serving schema"),
        )
    )
    return _validated_scopes(scopes)


def _validated_scopes(scopes: Sequence[ReleaseScope]) -> tuple[ReleaseScope, ...]:
    """catalog/schema와 DataHub namespace가 중복되지 않은 정렬 scope를 반환한다."""

    identities = {(scope.catalog, scope.schema) for scope in scopes}
    instances = {(scope.platform_instance, scope.datahub_namespace) for scope in scopes}
    if len(identities) != len(scopes) or len(instances) != len(scopes):
        raise ReleaseScopeError("runtime recipes contain duplicate discovery scopes")
    return tuple(sorted(scopes))


def _scope_from_recipe(
    path: Path,
    environment: Mapping[str, str],
    *,
    schema_override: str | None = None,
) -> ReleaseScope:
    if not path.name.endswith(".runtime.yml"):
        raise ReleaseScopeError(f"not a runtime ingestion recipe: {path.name}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ReleaseScopeError(f"runtime ingestion recipe is unreadable: {path.name}") from error
    root = _mapping(document, path.name)
    source = _mapping(root.get("source"), f"{path.name}.source")
    config = _mapping(source.get("config"), f"{path.name}.source.config")
    source_type = _text(source.get("type"), f"{path.name}.source.type")
    platform_instance = _runtime_value(
        config.get("platform_instance"), environment, f"{path.name}.platform_instance"
    )
    origin = _runtime_value(config.get("env"), environment, f"{path.name}.env")
    database = _optional_runtime_value(
        config.get("database"), environment, f"{path.name}.database"
    )
    if schema_override is not None and source_type != "trino":
        raise ReleaseScopeError("serving schema override requires one Trino recipe")
    schema = (
        schema_override
        if schema_override is not None
        else _schema_value(config, environment, path.name, database)
    )
    catalog = database if source_type == "trino" else path.name.removesuffix(".runtime.yml")
    catalog = _identifier(catalog, f"{path.name}.catalog")
    namespace_parts = [database] if database else []
    if not namespace_parts or namespace_parts[-1] != schema:
        namespace_parts.append(schema)
    namespace = ".".join(namespace_parts)
    return ReleaseScope(
        catalog=catalog,
        schema=_identifier(schema, f"{path.name}.schema"),
        platform_instance=_identifier(
            platform_instance, f"{path.name}.platform_instance"
        ),
        datahub_namespace=_namespace(namespace, f"{path.name}.namespace"),
        origin=_identifier(origin, f"{path.name}.env"),
    )


def _schema_value(
    config: Mapping[str, Any],
    environment: Mapping[str, str],
    recipe_name: str,
    database: str | None,
) -> str:
    pattern = config.get("schema_pattern")
    if pattern is None:
        if database is None:
            raise ReleaseScopeError(f"{recipe_name} has no runtime schema or database")
        return database
    allow = _mapping(pattern, f"{recipe_name}.schema_pattern").get("allow")
    if not isinstance(allow, list) or len(allow) != 1:
        raise ReleaseScopeError(f"{recipe_name} must allow exactly one runtime schema")
    return _runtime_value(allow[0], environment, f"{recipe_name}.schema_pattern.allow")


def _optional_runtime_value(
    value: object,
    environment: Mapping[str, str],
    context: str,
) -> str | None:
    if value is None:
        return None
    return _runtime_value(value, environment, context)


def _runtime_value(
    value: object,
    environment: Mapping[str, str],
    context: str,
) -> str:
    text = _text(value, context)
    if not text.startswith("${") or not text.endswith("}") or text.count("${") != 1:
        raise ReleaseScopeError(f"{context} must be supplied by one runtime environment variable")
    variable = text[2:-1]
    if not variable or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
        for character in variable
    ):
        raise ReleaseScopeError(f"{context} has an invalid environment reference")
    resolved = environment.get(variable)
    if not isinstance(resolved, str) or not resolved.strip():
        raise ReleaseScopeError(f"runtime environment variable is missing: {variable}")
    return resolved.strip()


def _identifier(value: str, context: str) -> str:
    if not value or any(ord(character) < 32 for character in value) or "." in value:
        raise ReleaseScopeError(f"{context} must be one non-empty identifier")
    return value


def _namespace(value: str, context: str) -> str:
    parts = value.split(".")
    if any(not part or any(ord(character) < 32 for character in part) for part in parts):
        raise ReleaseScopeError(f"{context} is invalid")
    return value


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseScopeError(f"{context} must be an object")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseScopeError(f"{context} must be non-empty text")
    return value.strip()
