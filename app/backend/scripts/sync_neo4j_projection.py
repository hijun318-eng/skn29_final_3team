"""활성 RuntimeCatalogProjection을 Neo4j에 한 번 동기화하는 실행 진입점이다."""

from __future__ import annotations

import asyncio

from app.adapters.neo4j_graph import Neo4jGraphAdapter
from app.adapters.neo4j_graph_settings import Neo4jGraphSettings
from app.adapters.runtime_catalog_repository import (
    PostgresRuntimeCatalogProjectionRepository,
)
from app.database import dispose_database, get_sessionmaker
from app.services.neo4j_projection_loader import ActiveNeo4jProjectionLoader


class Neo4jProjectionSyncCommand:
    """환경 기반 DB·Graph 자원의 생성, 실행과 정리를 소유한다."""

    async def run(self) -> None:
        """동기화 성공 receipt를 출력하고 모든 connection pool을 닫는다."""

        adapter: Neo4jGraphAdapter | None = None
        try:
            repository = PostgresRuntimeCatalogProjectionRepository(get_sessionmaker())
            adapter = Neo4jGraphAdapter.from_settings(Neo4jGraphSettings.from_env())
            projection = await ActiveNeo4jProjectionLoader(
                repository,
                adapter,
            ).run()
        finally:
            try:
                if adapter is not None:
                    await adapter.aclose()
            finally:
                await dispose_database()
        print("NEO4J_PROJECTION_SYNC=PASS")
        print(f"PRODUCT_RELEASE_ID={projection.product_release_id}")
        print(f"SOURCE_PROJECTION_SHA256={projection.source_projection_checksum}")
        print(f"GRAPH_PROJECTION_SHA256={projection.projection_checksum}")
        print(f"ENTITY_COUNT={len(projection.entities)}")
        print(f"RELATION_COUNT={len(projection.relations)}")


if __name__ == "__main__":
    asyncio.run(Neo4jProjectionSyncCommand().run())
