"""Neo4j를 선택형 metadata read model로 사용하는 비동기 adapter다."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from app.adapters.neo4j_graph_queries import (
    AWAIT_INDEXES,
    READBACK_COUNTS,
    SCHEMA_STATEMENTS,
    SEED_COUNT,
    UPSERT_ENTITIES,
    UPSERT_RELATIONS,
    candidate_query,
)
from app.adapters.neo4j_graph_settings import Neo4jGraphSettings

from app.ports.graph_candidates import (
    GraphCandidateRequest,
    GraphCandidateSet,
    GraphEntity,
    GraphEntityKind,
    GraphProjection,
    GraphProjectionMismatchError,
    GraphSecurityError,
    GraphUnavailableError,
)


class Neo4jGraphAdapter:
    """고정 Cypher와 bounded parameter만 실행하는 projection·candidate adapter다."""

    def __init__(
        self,
        driver: Any,
        *,
        database: str,
        timeout_seconds: float,
        read_access: Any = "READ",
        write_access: Any = "WRITE",
        driver_error_types: tuple[type[BaseException], ...] = (),
        security_error_types: tuple[type[BaseException], ...] = (),
        transient_error_types: tuple[type[BaseException], ...] = (),
    ) -> None:
        if not database or not 0.1 <= timeout_seconds <= 30:
            raise ValueError("Neo4j adapter database or timeout is invalid")
        self._driver = driver
        self._database = database
        self._timeout_seconds = timeout_seconds
        self._read_access = read_access
        self._write_access = write_access
        self._driver_error_types = driver_error_types
        self._security_error_types = security_error_types
        self._transient_error_types = transient_error_types

    @classmethod
    def from_settings(cls, settings: Neo4jGraphSettings) -> "Neo4jGraphAdapter":
        """활성 설정일 때만 선택형 driver를 import하고 connection pool을 만든다."""

        settings.validate()
        if not settings.enabled:
            raise ValueError("Neo4j graph is disabled")
        try:
            neo4j = importlib.import_module("neo4j")
            errors = importlib.import_module("neo4j.exceptions")
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Neo4j graph requires app/backend/requirements-neo4j.txt"
            ) from error
        driver = neo4j.AsyncGraphDatabase.driver(
            settings.uri,
            auth=(settings.username, settings.password),
            connection_timeout=settings.timeout_seconds,
            max_connection_pool_size=settings.pool_size,
            max_transaction_retry_time=settings.timeout_seconds,
        )
        return cls(
            driver,
            database=settings.database,
            timeout_seconds=settings.timeout_seconds,
            read_access=neo4j.READ_ACCESS,
            write_access=neo4j.WRITE_ACCESS,
            driver_error_types=_exception_types(errors, "DriverError"),
            security_error_types=_exception_types(errors, "AuthError", "TokenExpired"),
            transient_error_types=_exception_types(
                errors,
                "ServiceUnavailable",
                "SessionExpired",
            ),
        )

    async def verify_connectivity(self) -> None:
        """실제 Bolt 연결을 확인하고 driver 오류를 typed 경계로 변환한다."""

        try:
            await self._driver.verify_connectivity()
        except self._driver_error_types as error:
            self._raise_translated(error)

    async def ensure_schema(self) -> None:
        """projection identity 제약과 조회 인덱스를 멱등 생성하고 ONLINE까지 기다린다."""

        try:
            async with self._driver.session(
                database=self._database,
                default_access_mode=self._write_access,
            ) as session:
                async with await session.begin_transaction(
                    timeout=self._timeout_seconds
                ) as transaction:
                    for statement in SCHEMA_STATEMENTS:
                        result = await transaction.run(statement, {})
                        await result.consume()
                async with await session.begin_transaction(
                    timeout=self._timeout_seconds
                ) as transaction:
                    result = await transaction.run(
                        AWAIT_INDEXES,
                        {"timeout_seconds": max(1, int(self._timeout_seconds))},
                    )
                    await result.consume()
        except self._driver_error_types as error:
            self._raise_translated(error)

    async def project(self, projection: GraphProjection) -> str:
        """immutable receipt namespace에 node·edge를 MERGE하고 membership을 exact read-back한다."""

        parameters = {
            "product_release_id": projection.product_release_id,
            "source_projection_checksum": projection.source_projection_checksum,
            "graph_projection_checksum": projection.projection_checksum,
            "entities": projection.entity_records(),
            "relations": projection.relation_records(),
        }
        try:
            async with self._driver.session(
                database=self._database,
                default_access_mode=self._write_access,
            ) as session:
                async with await session.begin_transaction(
                    timeout=self._timeout_seconds
                ) as transaction:
                    await self._write_projection(
                        transaction,
                        parameters,
                        len(projection.entities),
                        len(projection.relations),
                    )
        except self._driver_error_types as error:
            self._raise_translated(error)
        return projection.projection_checksum

    async def resolve_candidates(self, request: GraphCandidateRequest) -> GraphCandidateSet:
        """receipt가 정확히 일치하는 seed에서만 1~2 hop 후보를 조회한다."""

        parameters = {
            "seed_keys": list(request.seed_keys),
            "product_release_id": request.product_release_id,
            "source_projection_checksum": request.source_projection_checksum,
            "graph_projection_checksum": request.graph_projection_checksum,
            "relation_kinds": [item.value for item in request.relation_kinds],
            "limit": request.limit,
        }
        try:
            async with self._driver.session(
                database=self._database,
                default_access_mode=self._read_access,
            ) as session:
                async with await session.begin_transaction(
                    timeout=self._timeout_seconds
                ) as transaction:
                    candidates = await self._read_candidates(
                        transaction,
                        parameters,
                        request.max_hops,
                        len(request.seed_keys),
                    )
        except self._driver_error_types as error:
            self._raise_translated(error)
        return GraphCandidateSet(
            candidates=tuple(sorted(set(candidates))),
            product_release_id=request.product_release_id,
            source_projection_checksum=request.source_projection_checksum,
            graph_projection_checksum=request.graph_projection_checksum,
        )

    async def aclose(self) -> None:
        """Neo4j connection pool을 닫는다."""

        await self._driver.close()

    async def _write_projection(
        self,
        transaction: Any,
        parameters: dict[str, Any],
        expected_entities: int,
        expected_relations: int,
    ) -> None:
        entity_result = await transaction.run(UPSERT_ENTITIES, parameters)
        entity_record = await entity_result.single(strict=True)
        relation_result = await transaction.run(UPSERT_RELATIONS, parameters)
        relation_record = await relation_result.single(strict=True)
        readback = await transaction.run(READBACK_COUNTS, parameters)
        counts = await readback.single(strict=True)
        observed = (
            int(entity_record["processed"]),
            int(relation_record["processed"]),
            int(counts["entity_count"]),
            int(counts["relation_count"]),
        )
        if observed != (
            expected_entities,
            expected_relations,
            expected_entities,
            expected_relations,
        ):
            raise GraphProjectionMismatchError(
                "Neo4j projection write and exact read-back membership differ"
            )

    async def _read_candidates(
        self,
        transaction: Any,
        parameters: dict[str, Any],
        max_hops: int,
        expected_seeds: int,
    ) -> tuple[GraphEntity, ...]:
        seed_result = await transaction.run(SEED_COUNT, parameters)
        seed_record = await seed_result.single(strict=True)
        if int(seed_record["seed_count"]) != expected_seeds:
            raise GraphProjectionMismatchError(
                "Neo4j seed membership differs from the requested projection receipt"
            )
        result = await transaction.run(candidate_query(max_hops), parameters)
        try:
            return tuple(
                [
                    GraphEntity(GraphEntityKind(record["entity_kind"]), record["entity_id"])
                    async for record in result
                ]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise GraphProjectionMismatchError(
                "Neo4j candidate record is outside the graph contract"
            ) from error

    def _raise_translated(self, error: BaseException) -> None:
        code = str(getattr(error, "code", ""))
        if isinstance(error, self._security_error_types) or code.startswith(
            "Neo.ClientError.Security."
        ):
            raise GraphSecurityError("Neo4j authentication or authorization failed") from error
        if isinstance(error, self._transient_error_types):
            raise GraphUnavailableError("Neo4j connection or session is unavailable") from error
        raise error


def _exception_types(module: ModuleType, *names: str) -> tuple[type[BaseException], ...]:
    return tuple(
        value
        for name in names
        if isinstance((value := getattr(module, name, None)), type)
        and issubclass(value, BaseException)
    )
