import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from sys import path


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import ErrorCode, Role
from app.adapters.fake_context_policy import FakeContextPolicyProvider
from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.contracts import AnalysisStatus, RequestContext, RouteType
from app.services.analysis_service import AnalysisService
from app.services.context_builder import ContextAsset, ContextPackage
from app.services.context_gate import (
    ContextGate,
    ContextGateRequest,
    G1Decision,
    G1ReasonCode,
)
from app.services.routing_service import RouteDecision


class ContextGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.asset = ContextAsset(
            urn="urn:answervice:dataset:pms.public.pms_reservations",
            fqn="pms.public.pms_reservations",
            columns=("reservation_id", "check_in_date"),
        )
        self.package = ContextPackage(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version="time-v1",
            entitlement_hash="entitlement-v1",
            assets=(self.asset,),
            dataset_count=1,
            column_count=2,
            token_count=1_000,
            token_limit=4_000,
            package_hash="a" * 64,
        )
        self.request = ContextGateRequest(
            package=self.package,
            role=Role.HOTEL_ANALYST,
            allowed_roles=frozenset({Role.HOTEL_ANALYST}),
            entitled_asset_urns=frozenset({self.asset.urn}),
            expected_entitlement_hash="entitlement-v1",
            active_context_releases=frozenset({"context-v1"}),
            active_policy_versions=frozenset({"policy-v1"}),
            active_time_versions=frozenset({"time-v1"}),
            as_of=date(2026, 7, 30),
            timezone="Asia/Seoul",
            supported_timezones=frozenset({"Asia/Seoul"}),
            calendar="gregorian",
            template_id="room-demand",
            active_template_ids=frozenset({"room-demand"}),
            normalized_question_ready=False,
            valid_columns_by_urn={
                self.asset.urn: frozenset(self.asset.columns),
            },
            metric_id="reservation_count",
            active_metric_ids=frozenset({"reservation_count"}),
            time_field="check_in_date",
            valid_time_fields_by_urn={
                self.asset.urn: frozenset({"check_in_date"}),
            },
            dimension_history_valid=True,
            join_active=True,
        )
        self.gate = ContextGate()

    def test_allows_valid_context_and_records_ordered_evidence(self) -> None:
        result = self.gate.evaluate(self.request)

        self.assertTrue(result.allowed)
        self.assertEqual(G1Decision.ALLOW, result.decision)
        self.assertEqual(
            (
                "role_entitlement",
                "context_release",
                "policy_version",
                "time_context",
                "template_or_question",
                "asset_column",
                "metric",
                "time_field",
                "dimension_history",
                "join",
                "package_limit",
            ),
            tuple(item.check for item in result.evidence),
        )

    def test_blocks_role_or_entitlement_mismatch_first(self) -> None:
        result = self.gate.evaluate(
            replace(self.request, expected_entitlement_hash="other")
        )

        self.assertEqual(G1Decision.BLOCK, result.decision)
        self.assertEqual(G1ReasonCode.ACCESS_DENIED, result.reason_code)
        self.assertEqual(ErrorCode.ACCESS_DENIED, result.error_code)
        self.assertEqual(("role_entitlement",), tuple(x.check for x in result.evidence))

    def test_blocks_inactive_context_release(self) -> None:
        result = self.gate.evaluate(
            replace(self.request, active_context_releases=frozenset())
        )

        self.assertEqual(G1ReasonCode.CONTEXT_RELEASE_INACTIVE, result.reason_code)

    def test_clarifies_when_template_and_normalized_question_are_missing(self) -> None:
        result = self.gate.evaluate(
            replace(
                self.request,
                template_id=None,
                normalized_question_ready=False,
            )
        )

        self.assertEqual(G1Decision.CLARIFY, result.decision)
        self.assertEqual(G1ReasonCode.TEMPLATE_CONTEXT_MISSING, result.reason_code)

    def test_clarifies_inactive_time_contract(self) -> None:
        result = self.gate.evaluate(
            replace(self.request, active_time_versions=frozenset())
        )

        self.assertEqual(G1Decision.CLARIFY, result.decision)
        self.assertEqual(G1ReasonCode.TIME_CONTEXT_INVALID, result.reason_code)

    def test_general_question_can_replace_template(self) -> None:
        result = self.gate.evaluate(
            replace(
                self.request,
                template_id=None,
                normalized_question_ready=True,
            )
        )

        self.assertTrue(result.allowed)

    def test_blocks_unknown_asset_or_column(self) -> None:
        no_asset = self.gate.evaluate(
            replace(self.request, valid_columns_by_urn={})
        )
        bad_columns = self.gate.evaluate(
            replace(
                self.request,
                valid_columns_by_urn={
                    self.asset.urn: frozenset({"reservation_id"})
                },
            )
        )

        self.assertEqual(G1ReasonCode.ASSET_INACTIVE, no_asset.reason_code)
        self.assertEqual(G1ReasonCode.COLUMN_INVALID, bad_columns.reason_code)

    def test_clarifies_missing_metric_and_blocks_inactive_metric(self) -> None:
        missing = self.gate.evaluate(replace(self.request, metric_id=None))
        inactive = self.gate.evaluate(
            replace(self.request, active_metric_ids=frozenset())
        )

        self.assertEqual(G1Decision.CLARIFY, missing.decision)
        self.assertEqual(G1ReasonCode.METRIC_CONTEXT_MISSING, missing.reason_code)
        self.assertEqual(G1Decision.BLOCK, inactive.decision)
        self.assertEqual(G1ReasonCode.METRIC_INACTIVE, inactive.reason_code)

    def test_blocks_invalid_dimension_history_and_join(self) -> None:
        history = self.gate.evaluate(
            replace(self.request, dimension_history_valid=False)
        )
        join = self.gate.evaluate(replace(self.request, join_active=False))

        self.assertEqual(
            G1ReasonCode.DIMENSION_HISTORY_INVALID,
            history.reason_code,
        )
        self.assertEqual(G1ReasonCode.JOIN_INACTIVE, join.reason_code)

    def test_clarifies_oversized_package(self) -> None:
        oversized = replace(
            self.package,
            token_count=4_001,
        )
        result = self.gate.evaluate(replace(self.request, package=oversized))

        self.assertEqual(G1Decision.CLARIFY, result.decision)
        self.assertEqual(G1ReasonCode.PACKAGE_LIMIT_EXCEEDED, result.reason_code)

    def test_analysis_service_cannot_bypass_g1(self) -> None:
        adapter = FakeDataPlatformAdapter()
        provider = FakeContextPolicyProvider(
            adapter,
            active_context_releases=frozenset(),
        )
        service = AnalysisService(adapter, ContextGate(), provider)
        context = RequestContext(
            role=Role.HOTEL_ANALYST,
            as_of=date(2026, 7, 30),
        )
        decision = RouteDecision(RouteType.GENERAL, None, True, True)

        response = service.analyze("예약 현황", context, decision)

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(
            (
                AnalysisStatus.RECEIVED,
                AnalysisStatus.ROUTED,
                AnalysisStatus.BLOCKED,
            ),
            response.data.transitions,
        )
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE, response.error.code)

    def test_analysis_service_records_passed_g1_contract(self) -> None:
        adapter = FakeDataPlatformAdapter()
        service = AnalysisService(
            adapter,
            ContextGate(),
            FakeContextPolicyProvider(adapter),
        )
        context = RequestContext(
            role=Role.HOTEL_ANALYST,
            as_of=date(2026, 7, 30),
        )
        decision = RouteDecision(RouteType.GENERAL, None, True, True)

        response = service.analyze("예약 현황", context, decision)

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual("context-v1", response.data.result.evidence.context_release)
        self.assertEqual("policy-v1", response.data.result.evidence.policy_version)


if __name__ == "__main__":
    unittest.main()
