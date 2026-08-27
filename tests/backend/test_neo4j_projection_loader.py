from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from app.ports.graph_candidates import GraphProjectionMismatchError  # noqa: E402
from app.services.neo4j_projection_loader import (  # noqa: E402
    ActiveNeo4jProjectionLoader,
)


def _runtime_projection():
    release = SimpleNamespace(
        assets=(
            SimpleNamespace(fqn="catalog.sales"),
            SimpleNamespace(fqn="catalog.calendar"),
        ),
        metrics=(
            SimpleNamespace(id="revenue", source_assets=("catalog.sales",)),
        ),
        dimensions=(
            SimpleNamespace(id="business_date", asset_fqn="catalog.calendar"),
        ),
        joins=(
            SimpleNamespace(left="catalog.sales", right="catalog.calendar"),
        ),
    )
    return SimpleNamespace(projection_sha256="a" * 64, release=release)


class _Repository:
    async def load_active(self):
        return SimpleNamespace(
            projection=_runtime_projection(),
            product_release_id="product-release-1",
        )


class _Adapter:
    def __init__(self, receipt: str | None = None) -> None:
        self.events: list[str] = []
        self.receipt = receipt

    async def verify_connectivity(self) -> None:
        self.events.append("verify")

    async def ensure_schema(self) -> None:
        self.events.append("schema")

    async def project(self, projection) -> str:
        self.events.append("project")
        return self.receipt or projection.projection_checksum


class ActiveNeo4jProjectionLoaderTest(unittest.IsolatedAsyncioTestCase):
    async def test_active_projection_is_loaded_in_guarded_order(self) -> None:
        adapter = _Adapter()

        projection = await ActiveNeo4jProjectionLoader(
            _Repository(), adapter
        ).run()

        self.assertEqual(["verify", "schema", "project"], adapter.events)
        self.assertEqual("product-release-1", projection.product_release_id)
        self.assertEqual(4, len(projection.entities))
        self.assertEqual(3, len(projection.relations))

    async def test_receipt_mismatch_fails_closed(self) -> None:
        with self.assertRaises(GraphProjectionMismatchError):
            await ActiveNeo4jProjectionLoader(
                _Repository(), _Adapter("0" * 64)
            ).run()


if __name__ == "__main__":
    unittest.main()
