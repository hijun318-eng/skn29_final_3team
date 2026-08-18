"""versioned 노드 JSON Schema bundle을 읽어 subset 검증·definition 추출·checksum을 제공한다.

Small JSON Schema subset used by the runtime node contracts.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """모델 payload가 선택된 versioned JSON Schema 또는 도메인 불변식을 위반했음을 알린다."""


_SCHEMA_PATHS = {
    "v1": Path(__file__).with_name("contracts") / "node_io.v0.1.json",
}


def schema_version(contract: str = "v1") -> str:
    """지원되는 계약 bundle이 선언한 schema version을 반환한다."""
    return schema_bundle(contract)["version"]


def schema_definition(definition: str, contract: str = "v1") -> dict[str, Any]:
    """한 definition과 그 참조가 의존하는 공용 ``$defs``를 독립 검증 schema로 반환한다."""
    bundle = schema_bundle(contract)
    definitions = bundle["$defs"]
    if definition not in definitions:
        raise ContractError(f"unknown schema definition: {definition}")
    return {"$defs": definitions, **definitions[definition]}


def schema_sha256(contract: str = "v1") -> str:
    """canonical JSON으로 직렬화한 전체 schema bundle의 재현 가능한 SHA-256을 반환한다."""
    return sha256(
        json.dumps(
            schema_bundle(contract),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def validate_payload(definition: str, payload: Any, *, contract: str = "v1") -> None:
    """payload 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다."""
    bundle = schema_bundle(contract)
    definitions = bundle["$defs"]
    if definition not in definitions:
        raise ContractError(f"unknown schema definition: {definition}")
    _validate(definitions[definition], payload, definition, bundle)


@lru_cache(maxsize=1)
def schema_bundle(contract: str = "v1") -> dict[str, Any]:
    """등록된 versioned JSON Schema 파일만 읽고 알 수 없는 계약은 명시적으로 거부한다."""
    try:
        path = _SCHEMA_PATHS[contract]
    except KeyError as error:
        raise ContractError(f"unknown schema contract: {contract}") from error
    with path.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _validate(
    schema: dict[str, Any],
    value: Any,
    path: str,
    bundle: dict[str, Any],
) -> None:
    if "$ref" in schema:
        definition = schema["$ref"].rsplit("/", 1)[-1]
        _validate(bundle["$defs"][definition], value, path, bundle)
        return

    for item in schema.get("allOf", ()):
        _validate(item, value, path, bundle)
    if "oneOf" in schema:
        matches = 0
        for item in schema["oneOf"]:
            try:
                _validate(item, value, path, bundle)
            except ContractError:
                continue
            matches += 1
        if matches != 1:
            raise ContractError(f"{path}: expected exactly one schema variant")
    if "if" in schema:
        try:
            _validate(schema["if"], value, path, bundle)
        except ContractError:
            branch = schema.get("else")
        else:
            branch = schema.get("then")
        if branch is not None:
            _validate(branch, value, path, bundle)

    expected = schema.get("type")
    if expected is not None and not _matches_type(expected, value):
        raise ContractError(f"{path}: expected {expected}")

    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: expected one of {schema['enum']!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ContractError(f"{path}: value is too short")
        if len(value) > schema.get("maxLength", float("inf")):
            raise ContractError(f"{path}: value is too long")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            raise ContractError(f"{path}: value does not match {pattern!r}")
        if schema.get("format") == "date-time":
            _validate_datetime(value, path)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            raise ContractError(f"{path}: value is below minimum")
        if value > schema.get("maximum", float("inf")):
            raise ContractError(f"{path}: value is above maximum")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            readable = [key.replace("_", " ") for key in missing]
            raise ContractError(f"{path}: missing fields {readable}")

        properties = schema.get("properties", {})
        extras = [key for key in value if key not in properties]
        additional = schema.get("additionalProperties", True)
        if extras and additional is False:
            raise ContractError(f"{path}: unexpected fields {extras}")

        for key, item in value.items():
            if key in properties:
                _validate(properties[key], item, f"{path}.{key}", bundle)
            elif isinstance(additional, dict):
                _validate(additional, item, f"{path}.{key}", bundle)

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: expected at least {schema['minItems']} items")
        if len(value) > schema.get("maxItems", float("inf")):
            raise ContractError(f"{path}: expected at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            canonical = [
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(canonical) != len(set(canonical)):
                raise ContractError(f"{path}: items must be unique")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(schema["items"], item, f"{path}[{index}]", bundle)


def _validate_datetime(value: str, path: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ContractError(f"{path}: invalid date-time") from error
    if parsed.utcoffset() is None:
        raise ContractError(f"{path}: date-time must include a UTC offset")


def _matches_type(expected: str | list[str], value: Any) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(item, value) for item in expected)
    checks = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "boolean": lambda: isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": lambda: value is None,
    }
    return checks[expected]()
