"""MCP transport와 독립된 versioned Tool descriptor·handler 계약을 정의한다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from app.contracts import Capability, Role


MCP_TOOL_DESCRIPTOR_VERSION = "MCPToolDescriptor.v1"
MCP_STREAMABLE_HTTP = "MCP_STREAMABLE_HTTP"


class MCPToolInfrastructureError(RuntimeError):
    """Registry·handler·audit 저장소 장애를 안정적인 code로 표현한다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MCPToolDispatchError(RuntimeError):
    """Tool 입력·실행·출력 실패의 공개 계약을 보존한다."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        protocol_error: bool = False,
    ) -> None:
        self.code = code
        self.protocol_error = protocol_error
        super().__init__(message)


@dataclass(frozen=True)
class MCPToolErrorPolicy:
    """Dispatcher가 만드는 공통 실패의 Tool별 공개 문구를 고정한다."""

    timeout_code: str
    timeout_message: str
    output_code: str
    output_message: str
    unexpected_code: str
    unexpected_message: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.timeout_code,
                self.timeout_message,
                self.output_code,
                self.output_message,
                self.unexpected_code,
                self.unexpected_message,
            )
        ):
            raise ValueError("MCP Tool error policy is invalid")


@dataclass(frozen=True)
class MCPToolInvocation:
    """인증 주체·trace·검증된 인자를 handler에 전달하는 immutable 봉투다."""

    subject_id: UUID
    role: Role
    trace_id: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.subject_id, UUID)
            or not isinstance(self.role, Role)
            or not isinstance(self.trace_id, str)
            or not self.trace_id.strip()
            or not isinstance(self.arguments, Mapping)
        ):
            raise ValueError("MCP Tool invocation is invalid")
        try:
            normalized = json.loads(
                json.dumps(
                    self.arguments,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError("MCP Tool invocation arguments must be JSON") from error
        object.__setattr__(self, "arguments", _deep_freeze(normalized))


MCPToolInputAdapter = Callable[[Any], Mapping[str, Any]]
MCPToolOutputAdapter = Callable[[Mapping[str, Any]], Mapping[str, Any]]
MCPToolHandler = Callable[[MCPToolInvocation], Awaitable[Mapping[str, Any]]]
MCPToolAuditAdapter = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return deepcopy(value)


def _assert_closed_object_schemas(value: Any, *, label: str) -> None:
    """중첩된 모든 명시적 object schema가 추가 속성을 닫았는지 검증한다."""

    if isinstance(value, dict):
        declared_type = value.get("type")
        is_object = declared_type == "object" or (
            isinstance(declared_type, list) and "object" in declared_type
        )
        if is_object:
            properties = value.get("properties")
            required = value.get("required")
            if (
                value.get("additionalProperties") is not False
                or not isinstance(properties, dict)
                or not isinstance(required, list)
                or len(required) != len(set(required))
                or any(
                    not isinstance(item, str) or item not in properties
                    for item in required
                )
            ):
                raise ValueError(f"MCP Tool {label} schema must be a closed object")
        for nested in value.values():
            _assert_closed_object_schemas(nested, label=label)
    elif isinstance(value, list):
        for nested in value:
            _assert_closed_object_schemas(nested, label=label)


def _closed_object_schema(schema: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    """Descriptor schema를 JSON 복사하고 재귀 closed object 계약을 검증한다."""

    try:
        normalized = json.loads(
            json.dumps(schema, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"MCP Tool {label} schema is not JSON serializable") from error
    if normalized.get("type") != "object":
        raise ValueError(f"MCP Tool {label} schema must be a closed object")
    _assert_closed_object_schemas(normalized, label=label)
    try:
        Draft202012Validator.check_schema(normalized)
    except SchemaError as error:
        raise ValueError(f"MCP Tool {label} schema is invalid") from error
    return _deep_freeze(normalized)


@dataclass(frozen=True)
class MCPToolDescriptor:
    """Code handler와 DB registry receipt가 exact match해야 하는 Tool 계약이다."""

    tool_id: UUID
    name: str
    semantic_version: str
    title: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    handler: MCPToolHandler
    input_adapter: MCPToolInputAdapter
    output_adapter: MCPToolOutputAdapter
    audit_adapter: MCPToolAuditAdapter
    timeout_seconds: int
    capability: Capability
    roles: tuple[Role, ...]
    annotations: Mapping[str, bool]
    error_policy: MCPToolErrorPolicy
    transport: Literal["MCP_STREAMABLE_HTTP"] = MCP_STREAMABLE_HTTP
    schema_version: Literal["MCPToolDescriptor.v1"] = MCP_TOOL_DESCRIPTOR_VERSION

    def __post_init__(self) -> None:
        """Descriptor identity·closed schema·handler·권한 계약을 조립 시 검증한다."""

        if (
            not isinstance(self.tool_id, UUID)
            or not isinstance(self.name, str)
            or not self.name.strip()
            or not isinstance(self.semantic_version, str)
            or not self.semantic_version.strip()
            or not isinstance(self.title, str)
            or not self.title.strip()
            or not isinstance(self.description, str)
            or not self.description.strip()
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 30
            or not isinstance(self.capability, Capability)
            or not self.roles
            or len(self.roles) != len(set(self.roles))
            or any(not isinstance(role, Role) for role in self.roles)
            or any(
                not callable(callback)
                for callback in (
                    self.handler,
                    self.input_adapter,
                    self.output_adapter,
                    self.audit_adapter,
                )
            )
        ):
            raise ValueError("MCP Tool descriptor is invalid")
        normalized_annotations = dict(self.annotations)
        if (
            set(normalized_annotations)
            != {
                "readOnlyHint",
                "destructiveHint",
                "idempotentHint",
                "openWorldHint",
            }
            or any(type(value) is not bool for value in normalized_annotations.values())
        ):
            raise ValueError("MCP Tool annotations are invalid")
        object.__setattr__(
            self,
            "input_schema",
            _closed_object_schema(self.input_schema, label="input"),
        )
        object.__setattr__(
            self,
            "output_schema",
            _closed_object_schema(self.output_schema, label="output"),
        )
        object.__setattr__(self, "roles", tuple(self.roles))
        object.__setattr__(self, "annotations", _deep_freeze(normalized_annotations))

    def validate_input(self, value: Mapping[str, Any]) -> None:
        """정규화된 인자를 선언된 Draft 2020-12 input schema로 검증한다."""

        Draft202012Validator(
            _deep_thaw(self.input_schema),
            format_checker=FormatChecker(),
        ).validate(_deep_thaw(value))

    def validate_output(self, value: Mapping[str, Any]) -> None:
        """공개 결과를 선언된 Draft 2020-12 output schema로 검증한다."""

        Draft202012Validator(
            _deep_thaw(self.output_schema),
            format_checker=FormatChecker(),
        ).validate(_deep_thaw(value))

    def public_definition(self) -> dict[str, Any]:
        """MCP tools/list에 출력할 transport-neutral 정의를 반환한다."""

        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": _deep_thaw(self.input_schema),
            "outputSchema": _deep_thaw(self.output_schema),
            "annotations": _deep_thaw(self.annotations),
        }

    def registry_contract_matches(self, row: Mapping[str, Any] | None) -> bool:
        """DB row의 전체 registry 계약이 descriptor와 exact match하는지 판정한다."""

        if row is None:
            return False
        try:
            roles = row["required_roles_json"]
            return bool(
                UUID(str(row["tool_id"])) == self.tool_id
                and row["tool_code"] == self.name
                and row["semantic_version"] == self.semantic_version
                and row["title"] == self.title
                and row["description"] == self.description
                and row["input_schema_json"] == _deep_thaw(self.input_schema)
                and row["output_schema_json"] == _deep_thaw(self.output_schema)
                and row["annotations_json"] == _deep_thaw(self.annotations)
                and row["transport"] == self.transport
                and type(row["timeout_seconds"]) is int
                and row["timeout_seconds"] == self.timeout_seconds
                and type(roles) is list
                and tuple(roles) == tuple(role.value for role in self.roles)
                and row["is_enabled"] is True
            )
        except (KeyError, TypeError, ValueError):
            return False
