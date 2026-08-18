import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
from sys import path


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextMetric,
    ContextMetricTerm,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)


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
        return ContextBuildRequest(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version="time-v1",
            entitlement_hash="entitlement-hash",
            assets=assets if assets is not None else (self.pms, self.crm),
            token_count=token_count,
            model_context_tokens=model_context_tokens,
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

    def test_entitled_metric_and_required_filters_change_package_hash(self) -> None:
        base_filter = ContextRequiredFilter("is_forecast", "eq", False)
        metric = ContextMetric(
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
        changed_metric = ContextMetric(
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
        metric = ContextMetric(
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
        metric = ContextMetric(
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
        metric = ContextMetric(
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
