"""감사된 일별 실적 CSV를 변경 불가 PostgreSQL history table로 적재한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.conninfo import make_conninfo


IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
HISTORY_COLUMNS = [
    "property_id",
    "business_date",
    "room_type_code",
    "physical_rooms",
    "available_room_nights",
    "rooms_sold",
    "daily_adr",
    "cancellation_rate",
    "is_synthetic",
]


def sha256(path: Path) -> str:
    """원본 history CSV를 스트리밍해 내용 식별용 SHA-256을 반환한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identifier(value: str) -> str:
    """SQL identifier 형식만 허용하고 안전하지 않은 schema·table·role을 거부한다."""

    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


class HistoricalFactsLoader:
    """일별 실적 무결성과 기존 DB 내용 hash를 검증한 뒤 최초 한 번만 적재한다."""

    def load(
        self,
        source: Path,
        schema: str,
        table: str,
        grant_select_to: str | None = None,
    ) -> dict[str, object]:
        """CSV를 검증·적재하거나 동일 immutable table을 재사용하고 receipt를 반환한다.

        중복·수용량 위반, DB 환경 누락, 기존 행 수·source hash 불일치는
        예외로 실패하며 기존 table을 덮어쓰지 않는다.
        """

        source_hash = sha256(source)
        frame = pd.read_csv(source, usecols=HISTORY_COLUMNS)
        frame["business_date"] = pd.to_datetime(frame["business_date"])
        key = ["property_id", "business_date", "room_type_code"]
        duplicate_count = int(frame.duplicated(key).sum())
        invalid_count = int(
            (
                (frame["rooms_sold"] < 0)
                | (frame["rooms_sold"] > frame["physical_rooms"])
            ).sum()
        )
        if duplicate_count or invalid_count:
            raise ValueError("historical daily facts failed integrity checks")
        dsn = os.getenv("ML_EVALUATION_DATABASE_URL")
        if not dsn:
            values = {
                "host": os.getenv("ML_DB_HOST"),
                "port": os.getenv("ML_DB_PORT", "5432"),
                "dbname": os.getenv("POSTGRES_DB"),
                "user": os.getenv("POSTGRES_USER"),
                "password": os.getenv("POSTGRES_PASSWORD"),
            }
            missing = [name for name, value in values.items() if not value]
            if missing:
                raise RuntimeError("missing DB environment: " + ", ".join(missing))
            dsn = make_conninfo(**values)
        status = "LOADED"
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cursor.execute(
                    f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" ('
                    "property_id text NOT NULL,"
                    "business_date date NOT NULL,"
                    "room_type_code text NOT NULL,"
                    "physical_rooms integer NOT NULL,"
                    "available_room_nights integer NOT NULL,"
                    "rooms_sold integer NOT NULL,"
                    "daily_adr double precision NOT NULL,"
                    "cancellation_rate double precision NOT NULL,"
                    "is_synthetic boolean NOT NULL,"
                    "source_dataset_sha256 text NOT NULL,"
                    "PRIMARY KEY (property_id, business_date, room_type_code)"
                    ")"
                )
                cursor.execute(
                    f'SELECT count(*), min(source_dataset_sha256), '
                    f'max(source_dataset_sha256) FROM "{schema}"."{table}"'
                )
                count, min_hash, max_hash = cursor.fetchone()
                if count:
                    if count != len(frame) or min_hash != source_hash or max_hash != source_hash:
                        raise RuntimeError("existing immutable history table differs")
                    status = "REUSED_VERIFIED"
                else:
                    values = []
                    for row in frame.itertuples(index=False):
                        values.append(
                            (
                                str(row.property_id),
                                row.business_date.date(),
                                str(row.room_type_code),
                                int(row.physical_rooms),
                                int(row.available_room_nights),
                                int(row.rooms_sold),
                                float(row.daily_adr),
                                float(row.cancellation_rate),
                                bool(row.is_synthetic),
                                source_hash,
                            )
                        )
                    cursor.executemany(
                        f'INSERT INTO "{schema}"."{table}" VALUES '
                        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        values,
                    )
                if grant_select_to:
                    role = identifier(grant_select_to)
                    cursor.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
                    cursor.execute(
                        f'GRANT SELECT ON "{schema}"."{table}" TO "{role}"'
                    )
            connection.commit()
        return {
            "status": status,
            "schema": schema,
            "table": table,
            "row_count": int(len(frame)),
            "min_date": frame["business_date"].min().date().isoformat(),
            "max_date": frame["business_date"].max().date().isoformat(),
            "properties": sorted(frame["property_id"].astype(str).unique()),
            "room_types": int(frame["room_type_code"].nunique()),
            "source_dataset_sha256": source_hash,
            "duplicate_rows": duplicate_count,
            "invalid_target_rows": invalid_count,
            "select_granted_to": grant_select_to,
        }


def main() -> None:
    """CLI 식별자를 검증해 history를 적재하고 JSON receipt 파일을 기록한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-facts", type=Path, required=True)
    parser.add_argument("--schema", default="ml_evaluation")
    parser.add_argument("--table", default="room_demand_daily_facts_20260826_v2")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--grant-select-to")
    args = parser.parse_args()
    result = HistoricalFactsLoader().load(
        args.daily_facts,
        identifier(args.schema),
        identifier(args.table),
        args.grant_select_to,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
