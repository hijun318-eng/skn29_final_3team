from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from app.adapters.neo4j_graph import Neo4jGraphAdapter  # noqa: E402
from app.adapters.neo4j_graph_settings import Neo4jGraphSettings  # noqa: E402
from app.ports.graph_candidates import (  # noqa: E402
    GraphCandidateRequest,
    GraphEntity,
    GraphEntityKind,
    GraphProjection,
    GraphRelation,
    GraphRelationKind,
)


@unittest.skipUnless(
    os.getenv("TEST_REAL_NEO4J") == "1",
    "opt-in disposable Neo4j integration",
)
class LiveNeo4jGraphTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """외부 환경으로 명시한 disposable Neo4j에 연결하고 최소 projection을 준비한다."""

        self.adapter = Neo4jGraphAdapter.from_settings(Neo4jGraphSettings.from_env())
        await self.adapter.verify_connectivity()
        await self.adapter.ensure_schema()
        metric = GraphEntity(GraphEntityKind.METRIC, "live_revenue")
        dataset = GraphEntity(GraphEntityKind.DATASET, "live.catalog.sales")
        self.projection = GraphProjection(
            product_release_id="neo4j-live-integration-v1",
            source_projection_checksum="b" * 64,
            entities=tuple(sorted((metric, dataset))),
            relations=(
                GraphRelation(
                    metric.key,
                    dataset.key,
                    GraphRelationKind.SOURCE_ASSET,
                ),
            ),
        )

    async def asyncTearDown(self) -> None:
        """각 live test 뒤 driver pool을 닫는다."""

        await self.adapter.aclose()

    async def test_projection_is_idempotent_and_candidate_receipt_is_exact(self) -> None:
        """같은 projection을 두 번 써도 membership이 같고 고정 traversal만 반환하는지 확인한다."""

        first = await self.adapter.project(self.projection)
        second = await self.adapter.project(self.projection)
        result = await self.adapter.resolve_candidates(
            GraphCandidateRequest(
                seed_keys=("METRIC:live_revenue",),
                product_release_id=self.projection.product_release_id,
                source_projection_checksum=self.projection.source_projection_checksum,
                graph_projection_checksum=self.projection.projection_checksum,
                relation_kinds=(GraphRelationKind.SOURCE_ASSET,),
                max_hops=1,
                limit=5,
            )
        )

        self.assertEqual(first, second)
        self.assertEqual(
            (GraphEntity(GraphEntityKind.DATASET, "live.catalog.sales"),),
            result.candidates,
        )


if __name__ == "__main__":
    unittest.main()
