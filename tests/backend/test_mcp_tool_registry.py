from __future__ import annotations

import asyncio
from collections.abc import Mapping
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import UUID, uuid4

from app.contracts import Capability, Role
from app.ports.mcp_tool import (
    MCPToolDescriptor,
    MCPToolDispatchError,
    MCPToolErrorPolicy,
    MCPToolInvocation,
)
from app.services.mcp_tool_registry import MCPToolDispatcher, MCPToolRegistry


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "string", "minLength": 1},
    },
    "required": ["value"],
    "additionalProperties": False,
}
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
    },
    "required": ["ok"],
    "additionalProperties": False,
}
_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_ERROR_POLICY = MCPToolErrorPolicy(
    timeout_code="TEST_TIMEOUT",
    timeout_message="테스트 Tool 시간이 초과되었습니다.",
    output_code="TEST_OUTPUT_INVALID",
    output_message="테스트 Tool 결과 계약이 올바르지 않습니다.",
    unexpected_code="TEST_EXECUTION_FAILED",
    unexpected_message="테스트 Tool 실행에 실패했습니다.",
)


def _descriptor(
    name: str = "alpha.read",
    *,
    tool_id: UUID | None = None,
    capability: Capability = Capability.READ_ANALYSIS,
    roles: tuple[Role, ...] = (Role.ANALYST,),
    handler_output: Mapping[str, object] | None = None,
    output_adapter=None,
    input_schema: Mapping[str, object] = _INPUT_SCHEMA,
    output_schema: Mapping[str, object] = _OUTPUT_SCHEMA,
) -> MCPToolDescriptor:
    """Generic registry 검증에 사용할 최소 versioned descriptor를 만든다."""

    async def handler(_invocation: MCPToolInvocation) -> Mapping[str, object]:
        return handler_output if handler_output is not None else {"ok": True}

    return MCPToolDescriptor(
        tool_id=tool_id or uuid4(),
        name=name,
        semantic_version="1.0.0",
        title=name,
        description=f"{name} descriptor",
        input_schema=input_schema,
        output_schema=output_schema,
        handler=handler,
        input_adapter=lambda arguments: dict(arguments),
        output_adapter=output_adapter or (lambda output: dict(output)),
        audit_adapter=lambda output: {"ok": output["ok"]},
        timeout_seconds=1,
        capability=capability,
        roles=roles,
        annotations=_ANNOTATIONS,
        error_policy=_ERROR_POLICY,
    )


def _receipt(
    descriptor: MCPToolDescriptor,
    *,
    enabled: bool = True,
) -> dict[str, object]:
    """Descriptor와 exact match하는 persistence receipt를 만든다."""

    public = descriptor.public_definition()
    return {
        "tool_id": str(descriptor.tool_id),
        "tool_code": descriptor.name,
        "semantic_version": descriptor.semantic_version,
        "title": descriptor.title,
        "description": descriptor.description,
        "input_schema_json": public["inputSchema"],
        "output_schema_json": public["outputSchema"],
        "annotations_json": public["annotations"],
        "transport": descriptor.transport,
        "timeout_seconds": descriptor.timeout_seconds,
        "required_roles_json": [role.value for role in descriptor.roles],
        "is_enabled": enabled,
    }


class MCPToolRegistryTest(IsolatedAsyncioTestCase):
    async def test_role_and_capability_filter_generic_list_deterministically(self) -> None:
        """동일 registry에서 역할별 capability와 entitlement를 함께 적용한다."""

        analysis = _descriptor("z.analysis")
        report = _descriptor(
            "a.report",
            capability=Capability.MANAGE_REPORT,
            roles=(Role.REPORT_ADMIN,),
        )

        async def rows() -> tuple[dict[str, object], ...]:
            return (_receipt(analysis), _receipt(report))

        registry = MCPToolRegistry((analysis, report), rows)
        self.assertEqual(
            ("z.analysis",),
            tuple(item.name for item in await registry.list_authorized(Role.ANALYST)),
        )
        self.assertEqual(
            ("a.report",),
            tuple(item.name for item in await registry.list_authorized(Role.REPORT_ADMIN)),
        )
        self.assertEqual(
            ("a.report", "z.analysis"),
            tuple(
                item.name
                for item in await registry.list_authorized(Role.PLATFORM_ADMIN)
            ),
        )
        self.assertEqual((), await registry.list_authorized(Role.DATA_ADMIN))

    async def test_disabled_and_schema_drift_candidates_are_hidden(self) -> None:
        """Disabled와 schema drift를 목록·직접 resolve에서 똑같이 숨긴다."""

        disabled = _descriptor("a.disabled")
        drifted = _descriptor("b.drifted")
        drifted_row = _receipt(drifted)
        drifted_row["output_schema_json"] = {
            **drifted_row["output_schema_json"],  # type: ignore[dict-item]
            "additionalProperties": True,
        }

        async def rows() -> tuple[dict[str, object], ...]:
            return (_receipt(disabled, enabled=False), drifted_row)

        registry = MCPToolRegistry((disabled, drifted), rows)
        self.assertEqual((), await registry.list_authorized(Role.ANALYST))
        for name in ("a.disabled", "b.drifted", "missing.tool"):
            with self.subTest(name=name):
                access = await registry.resolve(name, Role.ANALYST)
                self.assertFalse(access.known)
                self.assertFalse(access.authorized)
                self.assertIsNone(access.descriptor)

    async def test_title_and_annotations_drift_are_hidden(self) -> None:
        descriptor = _descriptor()
        for field, value in (
            ("title", "drifted title"),
            ("annotations_json", {**_ANNOTATIONS, "readOnlyHint": False}),
        ):
            with self.subTest(field=field):
                row = {**_receipt(descriptor), field: value}

                async def rows() -> tuple[dict[str, object], ...]:
                    return (row,)

                access = await MCPToolRegistry((descriptor,), rows).resolve(
                    descriptor.name,
                    Role.ANALYST,
                )
                self.assertFalse(access.known)

    async def test_nested_object_schema_must_also_be_closed(self) -> None:
        nested_open_schema = {
            "type": "object",
            "properties": {
                "value": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            },
            "required": ["value"],
            "additionalProperties": False,
        }

        with self.assertRaisesRegex(ValueError, "must be a closed object"):
            _descriptor(input_schema=nested_open_schema)

    async def test_common_input_validation_rejects_adapter_schema_omission(self) -> None:
        """Adapter가 추가 필드를 놓쳐도 dispatcher의 공통 schema 검증이 닫는다."""

        descriptor = _descriptor()
        with self.assertRaises(MCPToolDispatchError) as raised:
            await MCPToolDispatcher().dispatch(
                descriptor,
                subject_id=uuid4(),
                role=Role.ANALYST,
                trace_id="trace-input",
                arguments={"value": "accepted", "unexpected": True},
            )
        self.assertEqual("INVALID_ARGUMENT", raised.exception.code)
        self.assertTrue(raised.exception.protocol_error)

    async def test_common_output_validation_rejects_adapter_schema_violation(self) -> None:
        """신규 adapter가 추가 결과를 노출해도 공통 output schema가 차단한다."""

        descriptor = _descriptor(
            handler_output={"ok": True, "internal": "must-not-leak"},
        )
        with self.assertRaises(MCPToolDispatchError) as raised:
            await MCPToolDispatcher().dispatch(
                descriptor,
                subject_id=uuid4(),
                role=Role.ANALYST,
                trace_id="trace-output",
                arguments={"value": "accepted"},
            )
        self.assertEqual("TEST_OUTPUT_INVALID", raised.exception.code)
        self.assertNotIn("must-not-leak", str(raised.exception))

    async def test_common_output_validation_rejects_non_json_number(self) -> None:
        """JSON Schema의 number로 보일 수 있는 NaN도 wire 출력에서는 거부한다."""

        descriptor = _descriptor(
            handler_output={"value": float("nan")},
            output_schema={
                "type": "object",
                "properties": {"value": {"type": "number"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        with self.assertRaises(MCPToolDispatchError) as raised:
            await MCPToolDispatcher().dispatch(
                descriptor,
                subject_id=uuid4(),
                role=Role.ANALYST,
                trace_id="trace-nan-output",
                arguments={"value": "accepted"},
            )
        self.assertEqual("TEST_OUTPUT_INVALID", raised.exception.code)

    async def test_dispatcher_applies_descriptor_timeout(self) -> None:
        """Handler 종류와 무관하게 descriptor deadline과 공개 오류 정책을 적용한다."""

        async def raise_timeout(awaitable, *, timeout):
            self.assertEqual(1, timeout)
            awaitable.close()
            raise TimeoutError

        with (
            patch(
                "app.services.mcp_tool_registry.asyncio.wait_for",
                side_effect=raise_timeout,
            ),
            self.assertRaises(MCPToolDispatchError) as raised,
        ):
            await MCPToolDispatcher().dispatch(
                _descriptor(),
                subject_id=uuid4(),
                role=Role.ANALYST,
                trace_id="trace-timeout",
                arguments={"value": "accepted"},
            )
        self.assertEqual("TEST_TIMEOUT", raised.exception.code)

    def test_descriptor_and_invocation_are_deeply_immutable(self) -> None:
        """외부 dict·public copy·handler 입력 변이가 versioned 계약을 바꾸지 못한다."""

        source_schema = {
            **_INPUT_SCHEMA,
            "properties": {
                "value": {
                    "type": "string",
                    "examples": ["before"],
                },
            },
        }
        descriptor = _descriptor(input_schema=source_schema)
        source_schema["properties"]["value"]["examples"].append("after")
        definition = descriptor.public_definition()
        definition["inputSchema"]["properties"]["value"]["examples"].append(
            "public-change"
        )
        self.assertEqual(
            ["before"],
            descriptor.public_definition()["inputSchema"]["properties"]["value"][
                "examples"
            ],
        )
        with self.assertRaises(TypeError):
            descriptor.input_schema["properties"] = {}  # type: ignore[index]

        original_arguments = {"value": "before", "nested": {"items": [1]}}
        invocation = MCPToolInvocation(
            subject_id=uuid4(),
            role=Role.ANALYST,
            trace_id="trace-immutable",
            arguments=original_arguments,
        )
        original_arguments["nested"]["items"].append(2)
        self.assertEqual((1,), invocation.arguments["nested"]["items"])
        with self.assertRaises(TypeError):
            invocation.arguments["value"] = "changed"  # type: ignore[index]

    def test_descriptor_rejects_invalid_draft_2020_schema(self) -> None:
        """조립 시점에 Draft 2020-12 schema 자체가 잘못되면 즉시 거부한다."""

        invalid_schema = {
            **_INPUT_SCHEMA,
            "properties": {"value": {"type": "string", "minLength": "one"}},
        }
        with self.assertRaises(ValueError):
            _descriptor(input_schema=invalid_schema)


if __name__ == "__main__":
    import unittest

    unittest.main()
