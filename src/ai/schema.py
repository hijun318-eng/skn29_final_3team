"""Small JSON Schema subset used by the dependency-free fake adapter."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Raised when a node payload violates the versioned contract."""


_SCHEMA_PATH = Path(__file__).with_name("contracts") / "node_io.v0.1.json"


def schema_version() -> str:
    return _bundle()["version"]


def validate_payload(definition: str, payload: Any) -> None:
    definitions = _bundle()["$defs"]
    if definition not in definitions:
        raise ContractError(f"unknown schema definition: {definition}")
    _validate(definitions[definition], payload, definition)


def _bundle() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _validate(schema: dict[str, Any], value: Any, path: str) -> None:
    if "$ref" in schema:
        definition = schema["$ref"].rsplit("/", 1)[-1]
        _validate(_bundle()["$defs"][definition], value, path)
        return

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
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            raise ContractError(f"{path}: value does not match {pattern!r}")
        if schema.get("format") == "date-time":
            _validate_datetime(value, path)

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ContractError(f"{path}: missing fields {missing}")

        properties = schema.get("properties", {})
        extras = [key for key in value if key not in properties]
        additional = schema.get("additionalProperties", True)
        if extras and additional is False:
            raise ContractError(f"{path}: unexpected fields {extras}")

        for key, item in value.items():
            if key in properties:
                _validate(properties[key], item, f"{path}.{key}")
            elif isinstance(additional, dict):
                _validate(additional, item, f"{path}.{key}")

    if isinstance(value, list) and "items" in schema:
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: expected at least {schema['minItems']} items")
        for index, item in enumerate(value):
            _validate(schema["items"], item, f"{path}[{index}]")


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
