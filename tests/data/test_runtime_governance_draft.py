"""임의 schema SQL로 runtime governance DRAFT의 fail-closed 구조 분류를 검증한다."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(DATAHUB))

from runtime_governance_draft import build_draft, render_markdown  # noqa: E402


ARBITRARY_SQL = """
CREATE OR REPLACE VIEW serving.metrics.alpha_daily AS
SELECT day_key, region_key, SUM(amount_value) AS amount_sum,
       CAST(SUM(amount_value) AS DOUBLE) / NULLIF(COUNT(*), 0) AS amount_mean
FROM source_alpha.raw.fact_alpha
GROUP BY 1, 2;
COMMENT ON VIEW serving.metrics.alpha_daily IS '임의 일별 집계';
COMMENT ON COLUMN serving.metrics.alpha_daily.day_key IS '임의 기준일';
COMMENT ON COLUMN serving.metrics.alpha_daily.region_key IS '임의 지역';
COMMENT ON COLUMN serving.metrics.alpha_daily.amount_sum IS '임의 금액 합계';
COMMENT ON COLUMN serving.metrics.alpha_daily.amount_mean IS '임의 금액 평균';

CREATE OR REPLACE VIEW serving.metrics.alpha_signal AS
SELECT day_key, amount_sum, amount_mean, amount_sum + 1 AS adjusted_amount
FROM serving.metrics.alpha_daily;
COMMENT ON VIEW serving.metrics.alpha_signal IS '임의 전달 뷰';
COMMENT ON COLUMN serving.metrics.alpha_signal.day_key IS '전달 기준일';
COMMENT ON COLUMN serving.metrics.alpha_signal.amount_sum IS '전달 합계';
COMMENT ON COLUMN serving.metrics.alpha_signal.amount_mean IS '전달 평균';
COMMENT ON COLUMN serving.metrics.alpha_signal.adjusted_amount IS '임의 파생값';
""".strip()


class RuntimeGovernanceDraftTest(unittest.TestCase):
    def test_ast_roles_and_upstream_are_derived_without_business_name_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "views.sql").write_text(ARBITRARY_SQL, encoding="utf-8")
            draft = build_draft(directory, "serving.metrics", "R7")
        aggregate = draft.views[0]
        signal = draft.views[1]
        self.assertEqual(("day_key", "region_key"), aggregate.grain_candidates)
        self.assertEqual("AGGREGATE", aggregate.fields[2].structural_role)
        self.assertEqual("AGGREGATED_DERIVATION", aggregate.fields[3].structural_role)
        self.assertIn("DENOMINATOR_AND_ZERO_POLICY_REQUIRED", aggregate.fields[3].review_flags)
        self.assertEqual(("serving.metrics.alpha_daily",), signal.source_relations)
        self.assertEqual("PASS_THROUGH", signal.fields[1].structural_role)
        self.assertIn("PREAGGREGATED_SOURCE_REVIEW_REQUIRED", signal.fields[1].review_flags)
        self.assertEqual("DERIVED_EXPRESSION", signal.fields[3].structural_role)

    def test_rendered_document_never_claims_runtime_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "views.sql").write_text(ARBITRARY_SQL, encoding="utf-8")
            rendered = render_markdown(build_draft(directory, "serving.metrics", "R7"))
        self.assertIn("DRAFT / DATAHUB 발행 금지", rendered)
        self.assertIn("모든 항목 `REVIEW_REQUIRED`", rendered)
        self.assertIn("통합 매출의 세금·봉사료·인식 기준", rendered)
        self.assertNotIn("APPROVED", rendered)

    def test_missing_field_description_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            incomplete = ARBITRARY_SQL.replace(
                "COMMENT ON COLUMN serving.metrics.alpha_daily.amount_sum IS '임의 금액 합계';",
                "",
            )
            (directory / "views.sql").write_text(incomplete, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "field description is missing"):
                build_draft(directory, "serving.metrics", "R7")

    def test_invalid_serving_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "catalog.schema"):
                build_draft(Path(temporary), "serving.metrics.extra", "R7")

    def test_v43_business_approval_is_bound_to_current_sql_evidence(self) -> None:
        release = (
            ROOT
            / "infrastructure"
            / "database"
            / "releases"
            / "walkerhill_v4_3_20260815_derived_1"
        )
        sql_directory = release / "01_V4.3_생성_및_서빙_SQL" / "06_trino_serving"
        draft = build_draft(sql_directory, "serving.analytics_v4_3", "V4.3")
        approval = (
            ROOT / "docs" / "reference" / "Runtime_governance_V4.3_업무승인.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"SQL source SHA-256: `{draft.source_sha256}`", approval)
        for metric_id in (
            "total_operating_revenue_krw",
            "realized_uplift_rate",
            "voc_review_count",
            "voc_low_rating_reviews",
            "voc_negative_reviews",
            "voc_positive_reviews",
            "voc_followup_reviews",
            "banquet_cancelled_events",
        ):
            self.assertIn(f"`{metric_id}`", approval)
        self.assertIn("multi-column weighted reduction 지원 전까지 보류", approval)
        self.assertIn("존재하지 않는 metric", approval)

        fields = {
            (view.fqn, field.name): field
            for view in draft.views
            for field in view.fields
        }
        integrated = fields[
            (
                "serving.analytics_v4_3.hotel_operations_daily",
                "total_operating_revenue_krw",
            )
        ]
        self.assertEqual(
            (
                "b.recognized_revenue_krw",
                "f.net_revenue_krw",
                "r.room_revenue_krw",
                "x.facility_revenue_krw",
            ),
            integrated.source_columns,
        )
        self.assertIn(
            "DENOMINATOR_AND_ZERO_POLICY_REQUIRED",
            fields[
                (
                    "serving.analytics_v4_3.event_counterfactual_daily",
                    "realized_uplift_rate",
                )
            ].review_flags,
        )
        self.assertIn(
            "WEIGHTING_POLICY_REQUIRED",
            fields[("serving.analytics_v4_3.voc_daily", "average_rating")].review_flags,
        )

        banquet_seed = (
            release
            / "01_V4.3_생성_및_서빙_SQL"
            / "02_postgresql_banquet"
            / "32_postgresql_banquet_revenue_block_seed.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("FROM walkerhill_v4_3.banquet_bookings b WHERE b.booking_status='COMPLETED'", banquet_seed)
        self.assertIn("gross,discount,0,gross-discount", banquet_seed)


if __name__ == "__main__":
    unittest.main()
