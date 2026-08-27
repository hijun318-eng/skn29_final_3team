"""조건부 Graph read model이 교환하는 최소 projection·후보 계약을 정의한다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class GraphPortError(RuntimeError):
    """Graph 경계가 요청을 안전하게 완료하지 못했음을 나타낸다."""


class GraphUnavailableError(GraphPortError):
    """일시적인 연결·세션 장애로 Graph 후보를 읽을 수 없음을 나타낸다."""


class GraphSecurityError(GraphPortError):
    """인증·인가 실패를 일반 가용성 오류와 구분해 fail-closed하게 전달한다."""


class GraphProjectionMismatchError(GraphPortError):
    """요청 receipt와 Neo4j에 저장된 projection membership이 다름을 나타낸다."""


class GraphEntityKind(StrEnum):
    """Graph에 저장할 수 있는 승인 metadata 식별자 종류다."""

    DATASET = "DATASET"
    METRIC = "METRIC"
    DIMENSION = "DIMENSION"


class GraphRelationKind(StrEnum):
    """고정 ``RELATED_TO`` edge의 허용된 의미 종류다."""

    SOURCE_ASSET = "SOURCE_ASSET"
    DIMENSION_ASSET = "DIMENSION_ASSET"
    JOIN = "JOIN"


def _required_text(value: str, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} is invalid")
    return value


def _checksum(value: str, name: str) -> str:
    _required_text(value, name, maximum=64)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 checksum")
    return value


@dataclass(frozen=True, order=True)
class GraphEntity:
    """Graph에 저장하는 설명·원문 없는 metadata 식별자다."""

    kind: GraphEntityKind
    entity_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GraphEntityKind):
            raise ValueError("graph entity kind is invalid")
        _required_text(self.entity_id, "graph entity id")

    @property
    def key(self) -> str:
        """서로 다른 entity kind 사이의 ID 충돌을 막는 결정적 key를 반환한다."""

        return f"{self.kind.value}:{self.entity_id}"


@dataclass(frozen=True, order=True)
class GraphRelation:
    """두 승인 metadata entity 사이의 allowlist 관계다."""

    source_key: str
    target_key: str
    kind: GraphRelationKind

    def __post_init__(self) -> None:
        _required_text(self.source_key, "graph relation source")
        _required_text(self.target_key, "graph relation target")
        if self.source_key == self.target_key or not isinstance(self.kind, GraphRelationKind):
            raise ValueError("graph relation is invalid")


@dataclass(frozen=True)
class GraphProjection:
    """RuntimeCatalogProjection에서 단방향으로 만든 bounded Graph 문서다."""

    product_release_id: str
    source_projection_checksum: str
    entities: tuple[GraphEntity, ...]
    relations: tuple[GraphRelation, ...]
    projection_checksum: str = field(init=False)

    # ponytail: 첫 도입의 단일 transaction 상한이다. 실제 release가 넘을 때만 batch receipt를 추가한다.
    MAX_ENTITIES = 10_000
    MAX_RELATIONS = 50_000

    def __post_init__(self) -> None:
        _required_text(self.product_release_id, "product release id", maximum=160)
        _checksum(self.source_projection_checksum, "source projection checksum")
        if (
            not self.entities
            or len(self.entities) > self.MAX_ENTITIES
            or len(self.relations) > self.MAX_RELATIONS
            or self.entities != tuple(sorted(set(self.entities)))
            or self.relations != tuple(sorted(set(self.relations)))
        ):
            raise ValueError("graph projection membership is not canonical or bounded")
        entity_keys = {entity.key for entity in self.entities}
        if any(
            relation.source_key not in entity_keys or relation.target_key not in entity_keys
            for relation in self.relations
        ):
            raise ValueError("graph relation references an unknown entity")
        payload = {
            "product_release_id": self.product_release_id,
            "source_projection_checksum": self.source_projection_checksum,
            "entities": [
                {"key": item.key, "kind": item.kind.value, "entity_id": item.entity_id}
                for item in self.entities
            ],
            "relations": [
                {
                    "source_key": item.source_key,
                    "target_key": item.target_key,
                    "kind": item.kind.value,
                }
                for item in self.relations
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "projection_checksum", hashlib.sha256(encoded).hexdigest())

    def entity_records(self) -> list[dict[str, str]]:
        """Neo4j parameter로 넘길 최소 node record를 새 목록으로 반환한다."""

        return [
            {"key": item.key, "kind": item.kind.value, "entity_id": item.entity_id}
            for item in self.entities
        ]

    def relation_records(self) -> list[dict[str, str]]:
        """Neo4j parameter로 넘길 최소 edge record를 새 목록으로 반환한다."""

        return [
            {
                "source_key": item.source_key,
                "target_key": item.target_key,
                "kind": item.kind.value,
            }
            for item in self.relations
        ]


@dataclass(frozen=True)
class GraphCandidateRequest:
    """allowlist traversal에 필요한 seed·receipt·budget만 묶은 입력이다."""

    seed_keys: tuple[str, ...]
    product_release_id: str
    source_projection_checksum: str
    graph_projection_checksum: str
    relation_kinds: tuple[GraphRelationKind, ...] = ()
    max_hops: int = 2
    limit: int = 20

    def __post_init__(self) -> None:
        if (
            not 1 <= len(self.seed_keys) <= 4
            or self.seed_keys != tuple(sorted(set(self.seed_keys)))
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 640
                for item in self.seed_keys
            )
            or self.relation_kinds != tuple(sorted(set(self.relation_kinds)))
            or any(not isinstance(item, GraphRelationKind) for item in self.relation_kinds)
            or self.max_hops not in (1, 2)
            or not 1 <= self.limit <= 20
        ):
            raise ValueError("graph candidate request is not canonical or bounded")
        _required_text(self.product_release_id, "product release id", maximum=160)
        _checksum(self.source_projection_checksum, "source projection checksum")
        _checksum(self.graph_projection_checksum, "graph projection checksum")


@dataclass(frozen=True)
class GraphCandidateSet:
    """Graph 후보와 후보가 속한 immutable receipt를 함께 반환한다."""

    candidates: tuple[GraphEntity, ...]
    product_release_id: str
    source_projection_checksum: str
    graph_projection_checksum: str

    def __post_init__(self) -> None:
        if self.candidates != tuple(sorted(set(self.candidates))):
            raise ValueError("graph candidates must be sorted and unique")
        _required_text(self.product_release_id, "product release id", maximum=160)
        _checksum(self.source_projection_checksum, "source projection checksum")
        _checksum(self.graph_projection_checksum, "graph projection checksum")


class GraphCandidateResolver(Protocol):
    """서비스가 구현 기술 없이 선택형 Graph 후보를 요청하는 계약이다."""

    async def resolve_candidates(self, request: GraphCandidateRequest) -> GraphCandidateSet:
        """고정 traversal로 찾은 후보와 동일 release receipt를 반환한다."""
        ...

    async def aclose(self) -> None:
        """외부 Graph driver resource를 닫는다."""
        ...


class GraphProjectionSink(Protocol):
    """out-of-band compiler가 immutable Graph projection을 쓰는 계약이다."""

    async def project(self, projection: GraphProjection) -> str:
        """projection을 idempotent하게 저장하고 exact checksum을 반환한다."""
        ...
