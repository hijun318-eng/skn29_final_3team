"""검증된 RuntimeCatalogProjection을 PII 없는 Neo4j read model로 컴파일한다."""

from __future__ import annotations

from app.adapters.runtime_catalog_projection import RuntimeCatalogProjection
from app.ports.graph_candidates import (
    GraphEntity,
    GraphEntityKind,
    GraphProjection,
    GraphRelation,
    GraphRelationKind,
)


def compile_neo4j_projection(
    runtime_projection: RuntimeCatalogProjection,
    *,
    product_release_id: str,
) -> GraphProjection:
    """설명·정책·raw row 없이 canonical asset·Metric·Dimension 관계만 투영한다."""

    release = runtime_projection.release
    entities = {
        *(GraphEntity(GraphEntityKind.DATASET, item.fqn) for item in release.assets),
        *(GraphEntity(GraphEntityKind.METRIC, item.id) for item in release.metrics),
        *(GraphEntity(GraphEntityKind.DIMENSION, item.id) for item in release.dimensions),
    }
    by_key = {item.key: item for item in entities}
    relations: set[GraphRelation] = set()

    for metric in release.metrics:
        metric_key = GraphEntity(GraphEntityKind.METRIC, metric.id).key
        for source_asset in metric.source_assets:
            asset_key = GraphEntity(GraphEntityKind.DATASET, source_asset).key
            if asset_key not in by_key:
                raise ValueError("metric source asset is absent from graph projection")
            relations.add(
                GraphRelation(metric_key, asset_key, GraphRelationKind.SOURCE_ASSET)
            )

    for dimension in release.dimensions:
        dimension_key = GraphEntity(GraphEntityKind.DIMENSION, dimension.id).key
        asset_key = GraphEntity(GraphEntityKind.DATASET, dimension.asset_fqn).key
        if asset_key not in by_key:
            raise ValueError("dimension source asset is absent from graph projection")
        relations.add(
            GraphRelation(
                dimension_key,
                asset_key,
                GraphRelationKind.DIMENSION_ASSET,
            )
        )

    for join in release.joins:
        left_key = GraphEntity(GraphEntityKind.DATASET, join.left).key
        right_key = GraphEntity(GraphEntityKind.DATASET, join.right).key
        if left_key not in by_key or right_key not in by_key:
            raise ValueError("join endpoint is absent from graph projection")
        relations.add(GraphRelation(left_key, right_key, GraphRelationKind.JOIN))

    return GraphProjection(
        product_release_id=product_release_id,
        source_projection_checksum=runtime_projection.projection_sha256,
        entities=tuple(sorted(entities)),
        relations=tuple(sorted(relations)),
    )
