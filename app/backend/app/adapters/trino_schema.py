"""DataHub release의 schema fingerprint를 live Trino ``information_schema`` point lookup과 대조한다."""

from __future__ import annotations

import hashlib
import json
from time import monotonic

from sqlglot import exp

from app.adapters.datahub_metadata import GovernedDataset
from app.adapters.trino_async import AdapterError, QueryPage, TrinoAsyncClient


class TrinoSchemaDriftError(ValueError):
    """DataHub governed schema와 현재 Trino relation의 유형·column·checksum이 일치하지 않음을 알린다."""


class TrinoSchemaInspector:
    """SQLGlot AST로 만든 한정 조회를 사용해 선택 relation만 검사하고 schema drift를 fail-closed로 차단한다."""
    def __init__(
        self,
        client: TrinoAsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Trino schema timeout must be positive")
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def verify(self, datasets: tuple[GovernedDataset, ...]) -> None:
        """각 dataset의 table type·정렬된 column·SHA-256을 live Trino 값과 비교하고 하나라도 다르면 거부한다."""
        if not datasets:
            raise TrinoSchemaDriftError("no selected DataHub datasets to verify")
        for dataset in datasets:
            actual_type, actual_columns = await self.relation(dataset.fqn)
            expected_columns = tuple(dataset.trino_schema_columns)
            if (
                actual_type != dataset.table_type
                or actual_columns != expected_columns
                or _schema_hash(dataset.fqn, actual_type, actual_columns)
                != dataset.trino_schema_checksum
            ):
                raise TrinoSchemaDriftError(
                    f"Trino information_schema differs from DataHub for {dataset.fqn}"
                )

    async def relation(
        self,
        fqn: str,
    ) -> tuple[str, tuple[dict[str, object], ...]]:
        """3부분 FQN의 table·column metadata를 동일 deadline 안에 조회해 canonical relation identity로 반환한다."""
        catalog, schema, table = _fqn_parts(fqn)
        deadline = monotonic() + self._timeout_seconds
        # catalog 이름은 AST identifier로, schema·table은 literal로 구성해 metadata 조회 자체의 SQL 주입을 막는다.
        try:
            table_page = await self._client.execute(
                _table_query(catalog, schema, table),
                deadline=deadline,
            )
            table_columns, table_rows = await self._collect(table_page, deadline)
            column_page = await self._client.execute(
                _column_query(catalog, schema, table),
                deadline=deadline,
            )
            column_columns, column_rows = await self._collect(column_page, deadline)
        except AdapterError as error:
            raise TrinoSchemaDriftError(
                f"Trino information_schema lookup failed for {fqn}"
            ) from error
        if table_columns != ("table_type",) or len(table_rows) != 1:
            raise TrinoSchemaDriftError(f"Trino relation is unavailable: {fqn}")
        table_type = str(table_rows[0][0])
        if column_columns != (
            "ordinal_position", "column_name", "data_type", "is_nullable"
        ):
            raise TrinoSchemaDriftError("Trino information_schema shape is invalid")
        columns = []
        for expected_ordinal, row in enumerate(column_rows, start=1):
            if len(row) != 4:
                raise TrinoSchemaDriftError("Trino information_schema row is invalid")
            ordinal, name, native_type, nullable = row
            if (
                not isinstance(ordinal, int)
                or isinstance(ordinal, bool)
                or ordinal != expected_ordinal
                or not isinstance(name, str)
                or not name
                or not isinstance(native_type, str)
                or not native_type
                or nullable not in {"YES", "NO"}
            ):
                raise TrinoSchemaDriftError("Trino information_schema value is invalid")
            columns.append(
                {
                    "ordinal_position": ordinal,
                    "name": name,
                    "native_type": native_type,
                    "nullable": nullable == "YES",
                }
            )
        if not columns:
            raise TrinoSchemaDriftError(f"Trino relation has no columns: {fqn}")
        return table_type, tuple(columns)

    async def _collect(
        self,
        first: QueryPage,
        deadline: float,
    ) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
        page = first
        columns = page.columns
        rows = list(page.rows)
        while page.next_uri:
            page = await self._client.next_page(page.next_uri, deadline=deadline)
            columns = page.columns or columns
            rows.extend(page.rows)
        if page.state != "FINISHED":
            raise TrinoSchemaDriftError("Trino information_schema query did not finish")
        return columns, tuple(rows)


def _table_query(catalog: str, schema: str, table: str) -> str:
    return (
        exp.select("table_type")
        .from_(_information_schema_table(catalog, "tables"))
        .where(_relation_predicate(schema, table))
        .sql(dialect="trino", identify=True)
    )


def _column_query(catalog: str, schema: str, table: str) -> str:
    return (
        exp.select("ordinal_position", "column_name", "data_type", "is_nullable")
        .from_(_information_schema_table(catalog, "columns"))
        .where(_relation_predicate(schema, table))
        .order_by("ordinal_position")
        .sql(dialect="trino", identify=True)
    )


def _information_schema_table(catalog: str, name: str) -> exp.Table:
    return exp.Table(
        this=exp.Identifier(this=name, quoted=True),
        db=exp.Identifier(this="information_schema", quoted=True),
        catalog=exp.Identifier(this=catalog, quoted=True),
    )


def _relation_predicate(schema: str, table: str) -> exp.Expression:
    return exp.and_(
        exp.column("table_schema").eq(exp.Literal.string(schema)),
        exp.column("table_name").eq(exp.Literal.string(table)),
    )


def _fqn_parts(fqn: str) -> tuple[str, str, str]:
    parts = fqn.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise TrinoSchemaDriftError("DataHub Trino FQN must have three parts")
    return parts[0], parts[1], parts[2]


def _schema_hash(
    fqn: str,
    table_type: str,
    columns: tuple[dict[str, object], ...],
) -> str:
    canonical = json.dumps(
        {"fqn": fqn, "table_type": table_type, "columns": list(columns)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
