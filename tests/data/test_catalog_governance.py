"""V4.3 이름에 의존하지 않는 catalog governance 계획과 wire 계약을 검증한다."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))

from catalog_governance import (  # noqa: E402
    CatalogDataset,
    CatalogField,
    build_plan,
)
from metadata_wire import metadata_change_proposals  # noqa: E402
from release_scope import ReleaseScope  # noqa: E402


OWNER = "urn:li:corpuser:service_12345678"
SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:postgres,alpha.raw.orders,PROD)"
VIEW_URN = "urn:li:dataset:(urn:li:dataPlatform:trino,serving.analytics.order_daily,PROD)"


class CatalogGovernancePlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = ReleaseScope("alpha", "raw", "alpha", "raw", "PROD")
        self.serving = ReleaseScope(
            "serving", "analytics", "serving", "serving.analytics", "PROD"
        )
        self.datasets = (
            CatalogDataset(
                SOURCE_URN,
                "alpha.raw.orders",
                "orders",
                "임의 주문 원천",
                self.source,
                (CatalogField("amount", "임의 주문 금액"),),
            ),
            CatalogDataset(
                VIEW_URN,
                "serving.analytics.order_daily",
                "order_daily",
                "임의 일별 주문 집계",
                self.serving,
                (CatalogField("amount", "임의 일별 주문 금액"),),
            ),
        )

    def test_plan_scopes_terms_and_lineage_come_from_runtime_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            serving_dir = Path(temporary) / "06_trino_serving"
            serving_dir.mkdir()
            (serving_dir / "20_views.sql").write_text(
                "CREATE OR REPLACE VIEW serving.analytics.order_daily AS "
                "SELECT amount FROM alpha.raw.orders",
                encoding="utf-8",
            )
            plan = build_plan(
                self.datasets,
                (self.source, self.serving),
                "R9.2",
                OWNER,
                Path(temporary),
            )
        self.assertEqual(2, len(plan.domains))
        self.assertEqual(4, len(plan.tags))
        self.assertEqual(2, len(plan.dataset_terms))
        self.assertEqual(2, len(plan.field_terms))
        self.assertEqual(((VIEW_URN, SOURCE_URN),), plan.lineage_edges)
        self.assertNotEqual(
            plan.field_terms[(SOURCE_URN, "amount")],
            plan.field_terms[(VIEW_URN, "amount")],
        )

    def test_plan_fails_when_a_serving_view_has_no_ast_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            serving_dir = Path(temporary) / "06_trino_serving"
            serving_dir.mkdir()
            (serving_dir / "20_views.sql").write_text(
                "SELECT 1",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "no governed views"):
                build_plan(
                    self.datasets,
                    (self.source, self.serving),
                    "R9.2",
                    OWNER,
                    Path(temporary),
                )

    def test_tag_wire_uses_v1_7_typed_aspects(self) -> None:
        proposals = metadata_change_proposals(
            "tag",
            "urn:li:tag:answervice_release_r9_2",
            {
                "tagKey": {"name": "answervice_release_r9_2"},
                "tagProperties": {
                    "name": "R9.2",
                    "description": "임의 릴리스 태그",
                },
            },
            {"actor": OWNER, "time": 1},
        )
        request = {
            item["aspectName"]: json.loads(item["aspect"]["value"])
            for item in proposals
        }
        self.assertEqual("answervice_release_r9_2", request["tagKey"]["name"])
        self.assertEqual("R9.2", request["tagProperties"]["name"])
        self.assertEqual(
            OWNER,
            request["tagProperties"]["created"]["actor"],
        )


if __name__ == "__main__":
    unittest.main()
