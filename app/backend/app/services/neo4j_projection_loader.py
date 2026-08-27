"""활성 RuntimeCatalogProjection을 선택형 Neo4j read model로 적재한다."""

from __future__ import annotations

from app.adapters.neo4j_graph import Neo4jGraphAdapter
from app.adapters.neo4j_projection import compile_neo4j_projection
from app.adapters.runtime_catalog_repository import (
    PostgresRuntimeCatalogProjectionRepository,
)
from app.ports.graph_candidates import GraphProjection, GraphProjectionMismatchError


class ActiveNeo4jProjectionLoader:
    """활성 release 하나를 스키마 보장·투영·receipt 확인 순서로 동기화한다."""

    def __init__(
        self,
        repository: PostgresRuntimeCatalogProjectionRepository,
        adapter: Neo4jGraphAdapter,
    ) -> None:
        self._repository = repository
        self._adapter = adapter

    async def run(self) -> GraphProjection:
        """활성 projection을 적재하고 정확한 Graph receipt가 아니면 실패한다."""

        active = await self._repository.load_active()
        projection = compile_neo4j_projection(
            active.projection,
            product_release_id=active.product_release_id,
        )
        await self._adapter.verify_connectivity()
        await self._adapter.ensure_schema()
        receipt = await self._adapter.project(projection)
        if receipt != projection.projection_checksum:
            raise GraphProjectionMismatchError(
                "Neo4j automatic projection receipt differs"
            )
        return projection
