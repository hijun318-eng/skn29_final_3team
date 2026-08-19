"""Trino 결과 행을 canonical 직렬화해 column 유형·행 수·checksum evidence를 결정론적으로 계산한다."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def result_metadata(
    rows: list[dict[str, Any]],
    columns: tuple[str, ...],
) -> dict[str, Any]:
    """행별 scalar 유형을 column 단위로 축약하고 canonical row JSON의 SHA-256을 결과 변조 검증값으로 반환한다."""
    typed_columns = []
    for name in columns:
        kinds = {
            _value_type(row.get(name))
            for row in rows
            if row.get(name) is not None
        }
        if kinds <= {"integer", "number"} and "number" in kinds:
            kinds = {"number"}
        value_type = next(iter(kinds)) if len(kinds) == 1 else (
            "null" if not kinds else "mixed"
        )
        typed_columns.append({"name": name, "type": value_type})
    canonical = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "columns": typed_columns,
        "row_count": len(rows),
        "checksum": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "unsupported"
