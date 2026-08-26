"""DB 승인 Template과 역할 정책을 함께 읽는 routing 경계를 검증한다."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from sys import path
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import AnalysisRequest, ErrorCode, Role, RouteType  # noqa: E402
from app.services.routing_service import RoutingError, RoutingService  # noqa: E402


class _MappingResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_MappingResult":
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self._row


class _Session:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row
        self.parameters: dict[str, object] | None = None
        self.query = ""

    async def execute(self, query: object, parameters: dict[str, object]) -> _MappingResult:
        self.query = str(query)
        self.parameters = parameters
        return _MappingResult(self._row)


def _session_scope_for(row: dict[str, object] | None):
    session = _Session(row)

    @asynccontextmanager
    async def scope(_database_url: str):
        yield session

    return session, scope


def _approved_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "template_id": "runtime-template-alpha",
        "parameter_names_json": ["window_start"],
        "allowed_roles_json": [Role.ADMIN.value],
        "sql_text": "SELECT CAST(:window_start AS DATE) AS window_start LIMIT 1",
        "source_fqns_json": ["catalog_alpha.schema_beta.table_gamma"],
        "requires_g1": True,
        "requires_g2": True,
    }
    row.update(overrides)
    return row


class RoutingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_general_route_never_requires_a_static_template_registry(self) -> None:
        decision = await RoutingService().decide(AnalysisRequest(question="임의 분석 요청"))

        self.assertEqual(RouteType.GENERAL, decision.route_type)
        self.assertIsNone(decision.template_id)

    async def test_template_route_fails_closed_without_database_configuration(self) -> None:
        payload = AnalysisRequest(question="승인 템플릿 실행", template_id="runtime-template-alpha")

        with self.assertRaises(RoutingError) as raised:
            await RoutingService().decide(payload, Role.ADMIN)

        self.assertEqual(ErrorCode.ACCESS_DENIED, raised.exception.code)

    async def test_approved_template_uses_roles_and_parameters_from_the_same_row(self) -> None:
        session, scope = _session_scope_for(_approved_row())
        payload = AnalysisRequest(
            question="승인 템플릿 실행",
            template_id="runtime-template-alpha",
            parameters={"window_start": "2041-03-01"},
        )

        with patch("app.services.routing_service.session_scope", scope):
            decision = await RoutingService.from_database("postgresql+psycopg://runtime").decide(
                payload,
                Role.ADMIN,
            )

        self.assertEqual(RouteType.TEMPLATE, decision.route_type)
        self.assertEqual(frozenset({"catalog_alpha.schema_beta.table_gamma"}), decision.source_fqns)
        self.assertEqual({"template_id": "runtime-template-alpha"}, session.parameters)
        self.assertIn("status = 'APPROVED'", session.query)
        self.assertIn("allowed_roles_json", session.query)

    async def test_unknown_or_duplicate_role_metadata_is_not_repaired_in_process(self) -> None:
        for roles in (["unknown-role"], [Role.ADMIN.value, Role.ADMIN.value], []):
            _session, scope = _session_scope_for(_approved_row(allowed_roles_json=roles))
            payload = AnalysisRequest(
                question="승인 템플릿 실행",
                template_id="runtime-template-alpha",
                parameters={"window_start": "2041-03-01"},
            )

            with self.subTest(roles=roles), patch("app.services.routing_service.session_scope", scope):
                with self.assertRaises(RoutingError) as raised:
                    await RoutingService.from_database("postgresql+psycopg://runtime").decide(
                        payload,
                        Role.ADMIN,
                    )
                self.assertEqual(ErrorCode.ACCESS_DENIED, raised.exception.code)

    async def test_role_and_parameter_mismatches_are_typed_failures(self) -> None:
        payload = AnalysisRequest(
            question="승인 템플릿 실행",
            template_id="runtime-template-alpha",
            parameters={"window_start": "2041-03-01"},
        )
        for role, parameters, expected in (
            (Role.ANALYST, payload.parameters, ErrorCode.ACCESS_DENIED),
            (Role.ADMIN, {}, ErrorCode.CONTEXT_INCOMPLETE),
        ):
            _session, scope = _session_scope_for(_approved_row())
            request = payload.model_copy(update={"parameters": parameters})
            with self.subTest(role=role, parameters=parameters), patch(
                "app.services.routing_service.session_scope", scope
            ):
                with self.assertRaises(RoutingError) as raised:
                    await RoutingService.from_database("postgresql+psycopg://runtime").decide(
                        request,
                        role,
                    )
                self.assertEqual(expected, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
