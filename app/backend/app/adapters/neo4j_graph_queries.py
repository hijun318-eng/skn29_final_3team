"""Neo4j adapter가 실행할 allowlist Cypher template만 보존한다."""

SCHEMA_STATEMENTS = (
    """
    CREATE CONSTRAINT catalog_entity_identity IF NOT EXISTS
    FOR (entity:CatalogEntity)
    REQUIRE (
      entity.product_release_id,
      entity.graph_projection_checksum,
      entity.entity_key
    ) IS UNIQUE
    """,
    """
    CREATE INDEX catalog_entity_source_receipt IF NOT EXISTS
    FOR (entity:CatalogEntity)
    ON (
      entity.product_release_id,
      entity.graph_projection_checksum,
      entity.source_projection_checksum
    )
    """,
    """
    CREATE INDEX related_to_receipt IF NOT EXISTS
    FOR ()-[relation:RELATED_TO]-()
    ON (relation.graph_projection_checksum, relation.kind)
    """,
)

AWAIT_INDEXES = "CALL db.awaitIndexes($timeout_seconds)"

UPSERT_ENTITIES = """
UNWIND $entities AS item
MERGE (entity:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  entity_key: item.key
})
SET entity.kind = item.kind,
    entity.entity_id = item.entity_id,
    entity.source_projection_checksum = $source_projection_checksum
RETURN count(entity) AS processed
"""

UPSERT_RELATIONS = """
UNWIND $relations AS item
MATCH (source:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  entity_key: item.source_key
})
MATCH (target:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  entity_key: item.target_key
})
MERGE (source)-[relation:RELATED_TO {
  graph_projection_checksum: $graph_projection_checksum,
  kind: item.kind
}]->(target)
RETURN count(relation) AS processed
"""

READBACK_COUNTS = """
MATCH (entity:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  source_projection_checksum: $source_projection_checksum
})
WITH count(entity) AS entity_count
OPTIONAL MATCH (:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum
})-[relation:RELATED_TO {
  graph_projection_checksum: $graph_projection_checksum
}]->(:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum
})
RETURN entity_count, count(relation) AS relation_count
"""

SEED_COUNT = """
MATCH (seed:CatalogEntity {
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  source_projection_checksum: $source_projection_checksum
})
WHERE seed.entity_key IN $seed_keys
RETURN count(seed) AS seed_count
"""


def candidate_query(max_hops: int) -> str:
    """검증된 1·2 hop 값 중 하나만 Cypher 문법에 고정해 반환한다."""

    if max_hops not in (1, 2):
        raise ValueError("Neo4j traversal hop budget must be 1 or 2")
    hops = "1" if max_hops == 1 else "1..2"
    return f"""
MATCH (seed:CatalogEntity {{
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  source_projection_checksum: $source_projection_checksum
}})
WHERE seed.entity_key IN $seed_keys
MATCH path = (seed)-[:RELATED_TO*{hops}]-(candidate:CatalogEntity {{
  product_release_id: $product_release_id,
  graph_projection_checksum: $graph_projection_checksum,
  source_projection_checksum: $source_projection_checksum
}})
WHERE NOT candidate.entity_key IN $seed_keys
  AND all(relation IN relationships(path)
          WHERE relation.graph_projection_checksum = $graph_projection_checksum)
  AND (size($relation_kinds) = 0 OR
       all(relation IN relationships(path) WHERE relation.kind IN $relation_kinds))
RETURN DISTINCT candidate.kind AS entity_kind, candidate.entity_id AS entity_id
ORDER BY entity_kind, entity_id
LIMIT $limit
"""
