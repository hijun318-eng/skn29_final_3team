"""Registry 승인·역할·rate limit·JSON Schema를 적용해 transport 중립 도구 목록과 호출을 제공한다."""

from __future__ import annotations

import re
from dataclasses import asdict, replace
from typing import Any, Protocol

from .contracts import IntegrationContext, ToolRegistration
from .coordinator import DocumentEvidencePort, SqlEvidencePort, ToolCallError
from .rate_limit import ProcessToolRateLimiter


class ToolRegistryPort(Protocol):
    """도구 코드 조회와 역할별 호출 가능 목록을 제공하는 Registry 저장소 규약이다."""

    def load(self, tool_codes: tuple[str, ...]) -> dict[str, ToolRegistration]:
        """지정 코드들의 등록 레코드를 코드 키 사전으로 반환한다."""

        ...

    def list_callable(self, role: str) -> tuple[ToolRegistration, ...]:
        """해당 역할이 현재 호출할 수 있는 승인·정상 도구 등록 목록을 반환한다."""

        ...


class ToolHandler(Protocol):
    """스키마 검증을 마친 도구 인자와 호출 문맥을 실행하는 handler 규약이다."""

    def call(self, arguments: dict[str, Any], context: IntegrationContext) -> Any:
        """도구별 인자를 실행해 등록된 출력 스키마로 검증할 결과를 반환한다."""

        ...


class RegistryToolService:
    """MCP와 무관하게 도구 alias·Registry 정책·rate limit·입출력 스키마를 일관되게 집행한다."""

    # Canonical tool names used by v3.4 boundary contracts.
    # Kept aliasable for legacy deployments that still store legacy names.
    _LEGACY_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
        "analysis.run": ("answervice-sql",),
        "rag.search": ("internal-manual-search",),
    }

    @classmethod
    def _legacy_codes(cls, tool_code: str) -> tuple[str, ...]:
        canonical = cls._canonical_tool_code(tool_code)
        legacy = cls._LEGACY_TOOL_ALIASES.get(canonical)
        if legacy is None:
            return ()
        return legacy

    @classmethod
    def _all_known_codes(cls, tool_code: str) -> tuple[str, ...]:
        canonical = cls._canonical_tool_code(tool_code)
        aliases = cls._legacy_codes(canonical)
        unique = (canonical, *aliases)
        return tuple(dict.fromkeys(unique).keys())

    @classmethod
    def _canonical_tool_code(cls, tool_code: str) -> str:
        for canonical, legacy_codes in cls._LEGACY_TOOL_ALIASES.items():
            if tool_code == canonical or tool_code in legacy_codes:
                return canonical
        return tool_code

    def __init__(
        self,
        registry: ToolRegistryPort,
        handlers: dict[str, ToolHandler],
        rate_limiter: ProcessToolRateLimiter | None = None,
    ) -> None:
        self._registry = registry
        self._handlers = dict(handlers)
        self._rate_limiter = rate_limiter or ProcessToolRateLimiter()

    def list_tools(self, role: str) -> tuple[dict[str, Any], ...]:
        """역할에 허용된 도구를 canonical 코드로 중복 제거해 직렬화 가능한 등록 목록으로 반환한다."""

        expanded: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tool in self._registry.list_callable(role):
            code = self._canonical_tool_code(tool.tool_code)
            if code in seen:
                continue
            expanded.append(asdict(replace(tool, tool_code=code)))
            seen.add(code)
        return tuple(expanded)

    def call_tool(
        self,
        tool_code: str,
        arguments: dict[str, Any],
        context: IntegrationContext,
    ) -> Any:
        """문맥·등록·권한·호출량·입출력 스키마를 검증해 canonical 또는 legacy handler를 실행한다."""

        self._validate_context(context)
        registry_codes = self._all_known_codes(tool_code)
        loaded = self._registry.load(registry_codes)

        canonical_code = self._canonical_tool_code(tool_code)
        registration = loaded.get(tool_code)
        if registration is None:
            registration = loaded.get(canonical_code)
        if registration is None:
            for legacy_code in self._legacy_codes(canonical_code):
                registration = loaded.get(legacy_code)
                if registration is not None:
                    break
        if registration is None:
            raise ToolCallError("TOOL_NOT_REGISTERED")
        if not registration.callable_by(context.role):
            raise ToolCallError("TOOL_NOT_APPROVED_OR_ACCESS_DENIED")
        if not self._rate_limiter.allow(context.actor_id, canonical_code):
            raise ToolCallError("TOOL_RATE_LIMITED")
        self._validate_schema(arguments, registration.input_schema_json)
        handler = self._handlers.get(tool_code)
        if handler is None:
            handler = self._handlers.get(canonical_code)
        if handler is None and self._legacy_codes(canonical_code):
            for legacy_code in self._legacy_codes(canonical_code):
                handler = self._handlers.get(legacy_code)
                if handler is not None:
                    break
        if handler is None:
            raise ToolCallError("TOOL_HANDLER_NOT_CONFIGURED")
        try:
            result = handler.call(arguments, context)
        except ToolCallError:
            raise
        except Exception as error:
            raise ToolCallError("TOOL_INTERNAL_ERROR") from error
        self._validate_schema(result, registration.output_schema_json, output=True)
        return result

    @staticmethod
    def _validate_context(context: IntegrationContext) -> None:
        required = (
            context.request_id,
            context.trace_id,
            context.actor_id,
            context.role,
            context.as_of,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ToolCallError("TOOL_CONTEXT_INVALID")

    @classmethod
    def _validate_schema(
        cls, value: Any, schema: dict[str, Any], *, output: bool = False
    ) -> None:
        if not schema:
            return
        error_code = "TOOL_OUTPUT_SCHEMA_INVALID" if output else "TOOL_INPUT_SCHEMA_INVALID"
        try:
            cls._assert_schema(value, schema)
        except (KeyError, TypeError, ValueError) as error:
            raise ToolCallError(error_code) from error

    @classmethod
    def _assert_schema(cls, value: Any, schema: dict[str, Any]) -> None:
        if "const" in schema and value != schema["const"]:
            raise ValueError("const mismatch")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError("enum mismatch")
        expected_type = schema.get("type")
        type_matches = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, (list, tuple)),
            "string": lambda item: isinstance(item, str),
            "boolean": lambda item: isinstance(item, bool),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "null": lambda item: item is None,
        }
        accepted_types = (
            tuple(expected_type) if isinstance(expected_type, list) else (expected_type,)
        )
        if expected_type and not any(
            name in type_matches and type_matches[name](value) for name in accepted_types
        ):
            raise TypeError("type mismatch")
        if value is None:
            return
        if expected_type == "object":
            required = schema.get("required", ())
            if any(key not in value for key in required):
                raise KeyError("required property missing")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False and not set(value).issubset(
                properties
            ):
                raise ValueError("additional property")
            for key, child in properties.items():
                if key in value:
                    cls._assert_schema(value[key], child)
        elif expected_type == "array":
            if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
                "maxItems", float("inf")
            ):
                raise ValueError("array length")
            child = schema.get("items")
            if child:
                for item in value:
                    cls._assert_schema(item, child)
        elif expected_type == "string":
            if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
                "maxLength", float("inf")
            ):
                raise ValueError("string length")
            if "pattern" in schema and re.fullmatch(str(schema["pattern"]), value) is None:
                raise ValueError("string pattern")
        elif expected_type in {"integer", "number"}:
            if value < schema.get("minimum", float("-inf")) or value > schema.get(
                "maximum", float("inf")
            ):
                raise ValueError("number range")


class DocumentSearchToolHandler:
    """MCP 문서 검색 인자를 제한하고 대화·선택 문서를 문맥에 결합해 RAG 근거를 반환한다."""

    def __init__(self, port: DocumentEvidencePort) -> None:
        self._port = port

    def call(
        self, arguments: dict[str, Any], context: IntegrationContext
    ) -> dict[str, Any]:
        """2~500자 query와 제한된 문맥 목록만 허용해 문서 근거·추적 ID 응답을 만든다."""

        allowed = {"query", "recent_utterances", "selected_document_ids"}
        if not set(arguments).issubset(allowed) or "query" not in arguments:
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        if (
            not isinstance(arguments["query"], str)
            or not 2 <= len(arguments["query"].strip()) <= 500
        ):
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        recent = self._string_tuple(
            arguments.get("recent_utterances", ()), maximum_items=3, maximum_length=500
        )
        selected = self._string_tuple(
            arguments.get("selected_document_ids", ()), maximum_items=10, maximum_length=100
        )
        routed_context = replace(
            context,
            recent_utterances=recent,
            selected_document_ids=selected,
        )
        items = self._port.search(arguments["query"], routed_context)
        evidence = [asdict(item) for item in items]
        return {
            "evidence_type": "DOCUMENT_EVIDENCE",
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "document_evidence": evidence,
            "warnings": [],
        }

    @staticmethod
    def _string_tuple(
        value: object, maximum_items: int, maximum_length: int
    ) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        result = tuple(value)
        if len(result) > maximum_items or any(
            not isinstance(item, str)
            or not item.strip()
            or len(item.strip()) > maximum_length
            for item in result
        ):
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        return result


class SqlEvidenceToolHandler:
    """단일 query 인자만 받아 승인 SQL 포트 결과를 MCP SQL 근거 payload로 감싼다."""

    def __init__(self, port: SqlEvidencePort) -> None:
        self._port = port

    def call(
        self, arguments: dict[str, Any], context: IntegrationContext
    ) -> dict[str, Any]:
        """정확한 query 문자열 스키마를 검증하고 SQL 근거와 request·trace ID를 반환한다."""

        if set(arguments) != {"query"} or not isinstance(arguments["query"], str):
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        item = self._port.query(arguments["query"], context)
        return {
            "evidence_type": "SQL_EVIDENCE",
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "item": asdict(item),
        }
