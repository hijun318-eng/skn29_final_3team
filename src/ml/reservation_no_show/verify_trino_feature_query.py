from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path

from no_show_ml.config import FEATURES


PROJECT_DIR = Path(__file__).resolve().parent
RESERVATION_ID = "RES-02eedc3f21116d08e72ff9909dbb28ed"
FEATURE_AS_OF = "2026-07-28T18:00:00+09:00"
CONTAINER_ENV = "ANSWERVICE_TRINO_CONTAINER"


def main() -> None:
    container = os.environ.get(CONTAINER_ENV, "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
        raise ValueError(f"{CONTAINER_ENV} must name one running Trino container")
    if not re.fullmatch(r"RES-[a-f0-9]{32}", RESERVATION_ID):
        raise ValueError("invalid fixture reservation_id")
    sql = (PROJECT_DIR / "sql" / "reservation_no_show_feature_set_trino_v1.sql").read_text(
        encoding="utf-8"
    )
    sql = sql.replace("${RESERVATION_ID}", RESERVATION_ID).replace(
        "${FEATURE_AS_OF}", FEATURE_AS_OF
    )
    completed = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "trino",
            "--output-format",
            "CSV_HEADER",
            "--execute",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    expected_columns = {
        "reservation_id",
        "feature_as_of",
        "is_synthetic",
        *FEATURES,
    }
    if len(rows) != 1 or not expected_columns.issubset(rows[0]):
        raise ValueError("Trino feature fixture must return one contract row")
    missing_values = [column for column in expected_columns if rows[0][column] == ""]
    if missing_values:
        raise ValueError(f"Trino feature fixture contains null values: {missing_values}")
    result = {
        "status": "LOCAL_REAL_DB_PASS",
        "production_status": "NOT_VERIFIED",
        "container": container,
        "catalog": "pms",
        "schema": "public",
        "row_count": len(rows),
        "feature_column_count": len(rows[0]),
        "reservation_id": rows[0]["reservation_id"],
        "feature_as_of": rows[0]["feature_as_of"],
        "is_synthetic": rows[0]["is_synthetic"].lower() == "true",
        "service_adapter_connected": False,
    }
    artifact_path = PROJECT_DIR / "artifacts" / "rdb_feature_query_fixture.json"
    artifact_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    readiness_path = PROJECT_DIR / "artifacts" / "readiness_gate.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    for check in readiness["checks"]:
        if check["gate"] == "live_rdb_feature_query":
            check["status"] = "LOCAL_REAL_DB_PASS"
            check["reason"] = "Running Trino/PMS query PASS; production service adapter not connected"
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
