"""검증된 실제 시점 snapshot batch를 최소 권한으로 PostgreSQL에 적재한다."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from .operational_contracts import (
    OBSERVED_SIGNAL_SOURCE_KIND,
    SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS,
)
from .operational_snapshot import (
    SNAPSHOT_STORAGE_COLUMNS,
    SnapshotBatchValidator,
    sha256_file,
)


_TABLE = "ml_evaluation.room_demand_signal_snapshot"
_DATE_COLUMNS = {"cutoff_date", "target_date"}
_INTEGER_COLUMNS = {"horizon_days"}
_BOOLEAN_COLUMNS = {"signal_is_synthetic"}
_TEXT_COLUMNS = {
    "property_id",
    "room_type_code",
    "signal_source_kind",
    "source_batch_id",
    "source_payload_sha256",
}
_TIMESTAMP_COLUMNS = set(SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS) | {"captured_at"}


class ObservedSnapshotRepository:
    """관리자 권한을 거부하고 observed snapshot을 append-only 원장에 적재한다."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url is required")
        self._database_url = database_url

    def load(self, source: Path) -> dict[str, Any]:
        """원본 CSV를 메모리에서 다시 검증한 뒤 한 transaction으로 적재한다."""

        source_hash = sha256_file(source)
        raw = pd.read_csv(source)
        normalized, receipt = SnapshotBatchValidator().validate(
            raw,
            expected_source_kind=OBSERVED_SIGNAL_SOURCE_KIND,
            source_payload_sha256=source_hash,
        )
        captured_at = pd.Timestamp(receipt.captured_at)
        application_now = pd.Timestamp.now(tz="UTC")
        if not (
            application_now - pd.Timedelta(10, unit="min")
            <= captured_at
            <= application_now + pd.Timedelta(2, unit="min")
        ):
            raise ValueError("historical snapshot backfill is forbidden")
        rows = [self._database_row(row) for row in normalized.itertuples(index=False)]
        columns = ", ".join(SNAPSHOT_STORAGE_COLUMNS)
        with psycopg.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                self._assert_least_privilege(cursor)
                with cursor.copy(f"COPY {_TABLE} ({columns}) FROM STDIN") as copy:
                    for row in rows:
                        copy.write_row(row)
                cursor.execute(
                    f"SELECT count(*) FROM {_TABLE} "
                    "WHERE source_batch_id = %s AND source_payload_sha256 = %s",
                    (receipt.source_batch_id, receipt.source_payload_sha256),
                )
                stored_rows = int(cursor.fetchone()[0])
                if stored_rows != receipt.rows:
                    raise RuntimeError("stored snapshot row count does not match receipt")
            connection.commit()
        return {
            **asdict(receipt),
            "status": "LOADED",
            "storage_table": _TABLE,
            "stored_rows": stored_rows,
        }

    @staticmethod
    def _assert_least_privilege(cursor: psycopg.Cursor[Any]) -> None:
        cursor.execute(
            "SELECT current_user, r.rolsuper, "
            "has_table_privilege(current_user, %s, 'INSERT'), "
            "has_table_privilege(current_user, %s, 'SELECT'), "
            "has_table_privilege(current_user, %s, 'UPDATE'), "
            "has_table_privilege(current_user, %s, 'DELETE'), "
            "has_table_privilege(current_user, %s, 'TRUNCATE') "
            "FROM pg_roles r WHERE r.rolname = current_user",
            (_TABLE, _TABLE, _TABLE, _TABLE, _TABLE),
        )
        role, superuser, can_insert, can_select, can_update, can_delete, can_truncate = (
            cursor.fetchone()
        )
        if superuser or not can_insert or not can_select:
            raise RuntimeError(f"snapshot writer role has unsafe or missing grants: {role}")
        if can_update or can_delete or can_truncate:
            raise RuntimeError(f"snapshot writer role can mutate immutable rows: {role}")

    @staticmethod
    def _database_row(row: Any) -> tuple[Any, ...]:
        values: list[Any] = []
        for column in SNAPSHOT_STORAGE_COLUMNS:
            value = getattr(row, column)
            if column in _DATE_COLUMNS:
                values.append(pd.Timestamp(value).date())
            elif column in _TIMESTAMP_COLUMNS:
                values.append(pd.Timestamp(value).to_pydatetime())
            elif column in _INTEGER_COLUMNS:
                values.append(int(value))
            elif column in _BOOLEAN_COLUMNS:
                values.append(bool(value))
            elif column in _TEXT_COLUMNS:
                values.append(str(value))
            else:
                values.append(float(value))
        return tuple(values)


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError("snapshot load receipt already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    """검증된 관측 snapshot CSV를 append-only 저장소에 적재한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    args = parser.parse_args()
    database_url = os.getenv("ML_SNAPSHOT_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("ML_SNAPSHOT_DATABASE_URL is required")
    result = ObservedSnapshotRepository(database_url).load(args.input)
    _write_receipt(args.receipt_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
