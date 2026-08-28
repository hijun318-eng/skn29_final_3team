import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
from sys import path


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.context.builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextDimensionMemberReceipt,
    ContextMetric,
    ContextMetricTerm,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


def _v2_metric(*args, **kwargs) -> ContextMetric:
    """실행 가능한 fixture Metric을 운영과 같은 v2 권한 계약으로 만든다."""

    asset_fqn = str(kwargs.get("asset_fqn", args[1] if len(args) > 1 else ""))
    kwargs.setdefault("governance_version", RUNTIME_GOVERNANCE_VERSION_V2)
    kwargs.setdefault("allowed_roles", ("analyst",))
    kwargs.setdefault("contains_pii", False)
    kwargs.setdefault("allowed_join_ids", ())
    kwargs.setdefault("join_required", False)
    kwargs.setdefault(
        "query_strategies",
        ("VIEW_REUSE",) if asset_fqn.startswith("serving.") else ("RAW_APPROVED_DETAIL",),
    )
    return ContextMetric(*args, **kwargs)


class ContextPackageBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ContextPackageBuilder()
        self.pms = ContextAsset(
            urn="urn:answervice:dataset:pms.public.reservations",
            fqn="pms.public.reservations",
            columns=("reservation_id", "check_in_date"),
        )
        self.crm = ContextAsset(
            urn="urn:answervice:dataset:crm.dbo.members",
            fqn="crm.dbo.members",
            columns=("member_id", "grade"),
        )

    def request(
        self,
        *,
        assets: tuple[ContextAsset, ...] | None = None,
        token_count: int = 1_000,
        model_context_tokens: int = 16_000,
    ) -> ContextBuildRequest:
        selected_assets = assets if assets is not None else (self.pms, self.crm)
        metric_terms = tuple(
            ContextMetricTerm(
                id=metric.id,
                urn=f"urn:li:glossaryTerm:{metric.id}",
                label=metric.id,
                aliases=(metric.id,),
                definition=f"Test fixture definition for {metric.id}.",
                unit=metric.unit or "test_unit",
                version="fixture-v2",
                checksum=f"fixture-{metric.id}",
            )
            for asset in selected_assets
            for metric in asset.metrics
            if metric.visibility == "BUSINESS"
        )
        return ContextBuildRequest(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version="time-v1",
            entitlement_hash="entitlement-hash",
            assets=selected_assets,
            token_count=token_count,
            model_context_tokens=model_context_tokens,
            metric_terms=metric_terms,
        )

    def test_filters_unauthorized_assets_before_package_creation(self) -> None:
        package = self.builder.build(
            self.request(),
            entitled_asset_urns=frozenset({self.pms.urn}),
        )

        self.assertEqual((self.pms,), package.assets)
        self.assertEqual(1, package.dataset_count)
        self.assertEqual(2, package.column_count)

    def test_rejects_context_without_entitled_assets(self) -> None:
        with self.assertRaisesRegex(ContextBuildError, "하나 이상의 권한 있는 승인 asset"):
            self.builder.build(
                self.request(assets=()),
                entitled_asset_urns=frozenset(),
            )

    def test_hash_is_deterministic_regardless_of_candidate_order(self) -> None:
        entitled = frozenset({self.pms.urn, self.crm.urn})
        first = self.builder.build(self.request(), entitled)
        second = self.builder.build(
            self.request(assets=(self.crm, self.pms)),
            entitled,
        )

        self.assertEqual(first.package_hash, second.package_hash)
        self.assertEqual(64, len(first.package_hash))

    def test_product_release_and_cutoff_are_preserved_in_package_hash(self) -> None:
        entitled = frozenset({self.pms.urn, self.crm.urn})
        legacy = self.builder.build(self.request(), entitled)
        shadow_request = replace(
            self.request(),
            product_release_id="walkerhill-v4.3-sql-20260815-derived.1",
            evidence_cutoff=date(2026, 8, 15),
        )
        shadow = self.builder.build(shadow_request, entitled)
        changed_release = self.builder.build(
            replace(shadow_request, product_release_id="walkerhill-v4.3-next"),
            entitled,
        )

        self.assertIsNone(legacy.product_release_id)
        self.assertIsNone(legacy.evidence_cutoff)
        self.assertEqual(shadow_request.product_release_id, shadow.product_release_id)
        self.assertEqual(shadow_request.evidence_cutoff, shadow.evidence_cutoff)
        self.assertNotEqual(legacy.package_hash, shadow.package_hash)
        self.assertNotEqual(shadow.package_hash, changed_release.package_hash)

    def test_dimension_member_receipt_is_preserved_and_changes_package_hash(self) -> None:
        entitled = frozenset({self.pms.urn, self.crm.urn})
        receipt = ContextDimensionMemberReceipt(
            dimension_id="membership_tier",
            member_id="premier",
            term_urn="urn:li:glossaryTerm:membership_tier_premier",
            canonical_value="PREMIER",
            version="glossary-r4",
            semantic_sha256="a" * 64,
            asset_fqn="crm.dbo.members",
            column="grade",
        )

        baseline = self.builder.build(self.request(), entitled)
        governed = self.builder.build(
            replace(self.request(), dimension_member_receipts=(receipt,)),
            entitled,
        )

        self.assertEqual((receipt,), governed.dimension_member_receipts)
        self.assertNotEqual(baseline.package_hash, governed.package_hash)

    def test_glossary_checksum_is_preserved_and_changes_package_hash(self) -> None:
        term = ContextMetricTerm(
            id="recognized_room_revenue",
            urn="urn:li:glossaryTerm:recognized_room_revenue",
            label="인식 객실 매출",
            aliases=("인식 객실 매출",),
            definition="체크아웃 날짜에 전액 인식한 객실 매출입니다.",
            unit="KRW",
            version="METRIC-GLOSSARY-release",
            checksum="a" * 64,
        )
        entitled = frozenset({self.pms.urn, self.crm.urn})
        first = self.builder.build(
            replace(self.request(), metric_terms=(term,)),
            entitled,
        )
        changed = self.builder.build(
            replace(self.request(), metric_terms=(replace(term, checksum="b" * 64),)),
            entitled,
        )

        self.assertEqual("a" * 64, first.metric_terms[0].checksum)
        self.assertNotEqual(first.package_hash, changed.package_hash)

    def test_metric_term_accepts_verified_datahub_namespace_suffix(self) -> None:
        """DataHub release namespace가 metric ID suffix를 보존하면 유효한 Term URN이다."""

        term = ContextMetricTerm(
            id="total_operating_revenue_krw",
            urn=(
                "urn:li:glossaryTerm:"
                "answervice_runtime_v4_3_total_operating_revenue_krw"
            ),
            label="합성 통합 운영매출",
            aliases=("합성 통합 운영매출",),
            definition="검증된 합성 운영매출 지표입니다.",
            unit="KRW",
            version="v2",
            checksum="a" * 64,
        )

        self.assertTrue(term.urn.endswith(f"_{term.id}"))
        with self.assertRaises(ContextBuildError):
            ContextMetricTerm(
                id=term.id,
                urn="urn:li:glossaryTerm:answervice_runtime_v4_3_other_metric",
                label=term.label,
                aliases=term.aliases,
                definition=term.definition,
                unit=term.unit,
                version=term.version,
                checksum=term.checksum,
            )

    def test_entitled_metric_and_required_filters_change_package_hash(self) -> None:
        base_filter = ContextRequiredFilter("is_forecast", "eq", False)
        metric = _v2_metric(
            "recognized_room_revenue",
            "serving.analytics.hotel_daily_metrics",
            "room_revenue",
            "sum",
            "business_date",
            (base_filter,),
        )
        asset = ContextAsset(
            urn="urn:li:dataset:hotel_daily_metrics",
            fqn="serving.analytics.hotel_daily_metrics",
            columns=("room_revenue", "business_date", "is_forecast"),
            metrics=(metric,),
            metric_registry_required=True,
        )
        first = self.builder.build(
            self.request(assets=(asset,)), frozenset({asset.urn})
        )
        changed_metric = _v2_metric(
            metric.id,
            metric.asset_fqn,
            metric.field,
            metric.aggregation,
            metric.time_field,
            (ContextRequiredFilter("is_forecast", "eq", True),),
        )
        changed_asset = ContextAsset(
            asset.urn,
            asset.fqn,
            asset.columns,
            metrics=(changed_metric,),
            metric_registry_required=True,
        )
        second = self.builder.build(
            self.request(assets=(changed_asset,)), frozenset({asset.urn})
        )

        self.assertEqual((metric,), first.metrics)
        self.assertNotEqual(first.package_hash, second.package_hash)

    def test_duplicate_metric_id_fails_closed(self) -> None:
        metric = _v2_metric(
            "duplicate",
            self.pms.fqn,
            "reservation_id",
            "count",
            "check_in_date",
            (ContextRequiredFilter("reservation_id", "eq", "synthetic"),),
        )
        duplicated = ContextAsset(
            self.pms.urn,
            self.pms.fqn,
            self.pms.columns,
            metrics=(metric, metric),
            metric_registry_required=True,
        )

        with self.assertRaisesRegex(ContextBuildError, "중복"):
            self.builder.build(
                self.request(assets=(duplicated,)), frozenset({duplicated.urn})
            )

    def test_metric_without_required_filter_is_valid_for_curated_serving_view(self) -> None:
        metric = _v2_metric(
            "recognized_room_revenue",
            "serving.analytics.v4_hotel_daily_metrics",
            "recognized_room_revenue",
            "sum",
            "business_date",
            (),
        )
        asset = ContextAsset(
            urn="urn:li:dataset:v4-hotel-daily",
            fqn=metric.asset_fqn,
            columns=(metric.field, metric.time_field),
            metrics=(metric,),
            metric_registry_required=True,
        )

        package = self.builder.build(
            self.request(assets=(asset,)), frozenset({asset.urn})
        )

        self.assertEqual((metric,), package.metrics)
        self.assertEqual((), package.metrics[0].required_filters)

    def test_metric_result_unit_and_reduction_are_typed_and_hashed(self) -> None:
        metric = _v2_metric(
            "governed_amount",
            "serving.analytics.hotel_daily_metrics",
            "amount",
            "sum",
            "business_date",
            (),
            result_field="governed_total",
            unit="credits",
            reduction="sum",
        )
        asset = ContextAsset(
            urn="urn:li:dataset:hotel-daily",
            fqn=metric.asset_fqn,
            columns=(metric.field, metric.time_field),
            metrics=(metric,),
            metric_registry_required=True,
        )

        package = self.builder.build(
            self.request(assets=(asset,)), frozenset({asset.urn})
        )
        changed = self.builder.build(
            self.request(
                assets=(
                    replace(
                        asset,
                        metrics=(replace(metric, unit="alternate_credits"),),
                    ),
                )
            ),
            frozenset({asset.urn}),
        )

        self.assertEqual("governed_total", package.metrics[0].result_field)
        self.assertEqual("credits", package.metrics[0].unit)
        self.assertNotEqual(package.package_hash, changed.package_hash)

    def test_metric_result_contract_fails_closed(self) -> None:
        with self.assertRaises(ContextBuildError):
            ContextMetric(
                "metric",
                self.pms.fqn,
                "reservation_id",
                "sum",
                "check_in_date",
                (),
                result_field="bad.field",
            )
        with self.assertRaises(ContextBuildError):
            ContextMetric(
                "metric",
                self.pms.fqn,
                "reservation_id",
                "sum",
                "check_in_date",
                (),
                reduction="unsupported",
            )

    def test_ratio_metric_has_no_physical_field_and_governed_zero_policy(self) -> None:
        with self.assertRaises(ContextBuildError):
            ContextMetric(
                "adr", "", "", "ratio", "", (),
                numerator_metric_id="room_revenue",
                denominator_metric_id="room_nights",
                zero_policy="unsupported_policy",
            )
        with self.assertRaises(ContextBuildError):
            ContextMetric(
                "adr", self.pms.fqn, "", "ratio", "", (),
                numerator_metric_id="room_revenue",
                denominator_metric_id="room_nights",
                zero_policy="null_on_zero_denominator",
            )
        with self.assertRaises(ContextBuildError):
            ContextMetric(
                "adr", "", "", "ratio", "", (),
                numerator_metric_id="room_revenue",
                denominator_metric_id="room_revenue",
                zero_policy="null_on_zero_denominator",
            )
        metric = ContextMetric(
            "adr", "", "", "ratio", "", (),
            numerator_metric_id="room_revenue",
            denominator_metric_id="room_nights",
            zero_policy="null_on_zero_denominator",
        )
        self.assertEqual("ratio", metric.reduction)

    def test_exists_metric_requires_a_physical_field_and_defaults_to_scalar_reduction(self) -> None:
        metric = ContextMetric(
            "has_flagged_event",
            self.pms.fqn,
            "flagged_at",
            "exists",
            "check_in_date",
            (),
            result_field="resolved_exists",
            unit="boolean",
        )
        self.assertEqual("scalar", metric.reduction)

    def test_ratio_metric_numerator_and_denominator_must_be_sibling_single_metrics(self) -> None:
        numerator = _v2_metric(
            "room_revenue", self.pms.fqn, "reservation_id", "sum", "check_in_date", (),
        )
        ratio_referencing_missing_denominator = _v2_metric(
            "adr", "", "", "ratio", "", (),
            numerator_metric_id="room_revenue",
            denominator_metric_id="room_nights",
            zero_policy="null_on_zero_denominator",
        )
        asset = ContextAsset(
            urn=self.pms.urn,
            fqn=self.pms.fqn,
            columns=self.pms.columns,
            metrics=(numerator, ratio_referencing_missing_denominator),
            metric_registry_required=True,
        )
        with self.assertRaisesRegex(ContextBuildError, "분자·분모"):
            self.builder.build(
                self.request(assets=(asset,)), frozenset({asset.urn})
            )

        denominator = _v2_metric(
            "room_nights", self.pms.fqn, "reservation_id", "count", "check_in_date", (),
        )
        ratio = _v2_metric(
            "adr", "", "", "ratio", "", (),
            numerator_metric_id="room_revenue",
            denominator_metric_id="room_nights",
            zero_policy="null_on_zero_denominator",
        )
        complete_asset = ContextAsset(
            urn=self.pms.urn,
            fqn=self.pms.fqn,
            columns=self.pms.columns,
            metrics=(numerator, denominator, ratio),
            metric_registry_required=True,
        )
        package = self.builder.build(
            self.request(assets=(complete_asset,)), frozenset({complete_asset.urn})
        )
        self.assertEqual(3, len(package.metrics))

    def test_package_is_immutable(self) -> None:
        package = self.builder.build(
            self.request(),
            frozenset({self.pms.urn, self.crm.urn}),
        )

        with self.assertRaises(FrozenInstanceError):
            package.context_release = "changed"

    def test_typed_parameter_bindings_are_lossless_and_hashed(self) -> None:
        bindings = (
            ContextParameterBinding("period_start", "date", "2026-05-01"),
            ContextParameterBinding("required_filter_1", "string", "O'Brien"),
            ContextParameterBinding("required_filter_2", "boolean", False),
            ContextParameterBinding("required_filter_3", "number", 0),
            ContextParameterBinding(
                "observed_before",
                "timestamp",
                "2026-08-15T23:59:59+09:00",
            ),
        )
        package = self.builder.build(
            replace(self.request(), parameter_bindings=bindings),
            frozenset({self.pms.urn, self.crm.urn}),
        )
        changed = self.builder.build(
            replace(
                self.request(),
                parameter_bindings=(
                    *bindings[:-2],
                    ContextParameterBinding("required_filter_3", "number", 1),
                    bindings[-1],
                ),
            ),
            frozenset({self.pms.urn, self.crm.urn}),
        )

        self.assertEqual(bindings, package.parameter_bindings)
        self.assertNotEqual(package.package_hash, changed.package_hash)

    def test_typed_parameter_bindings_fail_closed(self) -> None:
        for name, value_type, value in (
            ("required_filter_1", "number", True),
            ("required_filter_1", "number", float("inf")),
            ("required_filter_1", "date", "2026-02-30"),
            ("required_filter_1", "timestamp", "2026-08-15T23:59:59"),
            ("required_filter_1", "string", ""),
        ):
            with self.subTest(value_type=value_type, value=value):
                with self.assertRaises(ContextBuildError):
                    ContextParameterBinding(name, value_type, value)

        with self.assertRaisesRegex(ContextBuildError, "중복"):
            self.builder.build(
                replace(
                    self.request(),
                    parameter_bindings=(
                        ContextParameterBinding("required_filter_1", "string", "A"),
                        ContextParameterBinding("required_filter_1", "string", "A"),
                    ),
                ),
                frozenset({self.pms.urn, self.crm.urn}),
            )

    def test_scalar_filter_operators_follow_the_live_contract(self) -> None:
        for operator in ("eq", "neq", "gt", "gte", "lt", "lte"):
            with self.subTest(operator=operator):
                item = ContextRequiredFilter("amount", operator, 1)
                self.assertEqual(operator, item.operator)
        with self.assertRaises(ContextBuildError):
            ContextRequiredFilter("amount", "in", 1)

    def test_rejects_more_than_eight_datasets(self) -> None:
        assets = tuple(
            ContextAsset(
                urn=f"urn:answervice:dataset:test.schema.table_{index}",
                fqn=f"test.schema.table_{index}",
                columns=("id",),
            )
            for index in range(9)
        )

        with self.assertRaisesRegex(ContextBuildError, "Dataset"):
            self.builder.build(
                self.request(assets=assets),
                frozenset(asset.urn for asset in assets),
            )

    def test_rejects_more_than_sixty_columns(self) -> None:
        asset = ContextAsset(
            urn="urn:answervice:dataset:test.schema.wide_table",
            fqn="test.schema.wide_table",
            columns=tuple(f"column_{index}" for index in range(61)),
        )

        with self.assertRaisesRegex(ContextBuildError, "Column"):
            self.builder.build(
                self.request(assets=(asset,)),
                frozenset({asset.urn}),
            )

    def test_uses_twenty_five_percent_model_limit(self) -> None:
        with self.assertRaises(ContextBuildError) as raised:
            self.builder.build(
                self.request(token_count=2_001, model_context_tokens=8_000),
                frozenset({self.pms.urn, self.crm.urn}),
            )

        self.assertEqual(
            ContextBuildErrorCode.TOKEN_LIMIT_EXCEEDED,
            raised.exception.code,
        )

    def test_caps_token_limit_at_six_thousand(self) -> None:
        package = self.builder.build(
            self.request(token_count=6_000, model_context_tokens=100_000),
            frozenset({self.pms.urn, self.crm.urn}),
        )

        self.assertEqual(6_000, package.token_limit)


if __name__ == "__main__":
    unittest.main()
