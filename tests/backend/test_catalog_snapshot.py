from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.adapters.catalog_snapshot import CatalogSnapshotLoader  # noqa: E402
from app.adapters.datahub_catalog import DataHubCatalogError  # noqa: E402


class CatalogSnapshotFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_fetch_failure_cancels_and_reaps_inflight_siblings(self) -> None:
        loader = CatalogSnapshotLoader(object(), max_concurrency=2, ttl_seconds=1)
        slow_started = asyncio.Event()
        slow_cancelled = asyncio.Event()

        async def fetch(urn: str) -> dict[str, str]:
            if urn == "slow":
                slow_started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    slow_cancelled.set()
                    raise
            await slow_started.wait()
            raise DataHubCatalogError("bounded test failure", category="transport")

        with self.assertRaises(DataHubCatalogError):
            await loader._fetch_all(("slow", "failure"), fetch)

        self.assertTrue(slow_cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
