"""실제 운영 shadow 검증 입력의 열·형식·파일 hash 계약을 정의한다."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

from .operational_contracts import SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS


SHADOW_SCHEMA_VERSION = "room-demand-operational-shadow-v2"
SHADOW_IDENTITY_COLUMNS = [
    "cutoff_date",
    "property_id",
    "room_type_code",
    "target_date",
    "horizon_days",
]
SHADOW_REQUIRED_COLUMNS = SHADOW_IDENTITY_COLUMNS + [
    "target_sellable_rooms",
    "predicted_rooms",
    "baseline_predicted_rooms",
    "actual_rooms_sold",
    "lower_80",
    "upper_80",
    "lower_95",
    "upper_95",
    "inference_latency_ms",
    "model_version",
    "artifact_sha256",
    "feature_contract_sha256",
    "runtime_feature_parity",
    "signal_source_kind",
    "signal_is_synthetic",
    *SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS,
    "captured_at",
    "prediction_generated_at",
    "actual_as_of_at",
    "source_batch_id",
]
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    """대용량 shadow 증거 파일의 SHA-256을 스트리밍 방식으로 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_shadow_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    """필수 열을 고정 순서와 비교 가능한 자료형으로 정규화한다."""

    missing = sorted(set(SHADOW_REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"shadow evidence missing columns: {missing}")
    data = frame[SHADOW_REQUIRED_COLUMNS].copy()
    data["property_id"] = data["property_id"].astype(str).str.strip().str.upper()
    data["room_type_code"] = data["room_type_code"].astype(str).str.strip()
    for column in ("cutoff_date", "target_date"):
        data[column] = pd.to_datetime(data[column], errors="raise").dt.normalize()
    timestamp_columns = SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS + [
        "captured_at",
        "prediction_generated_at",
        "actual_as_of_at",
    ]
    for column in timestamp_columns:
        data[column] = pd.to_datetime(data[column], utc=True, errors="coerce")
    if data[timestamp_columns].isna().any().any():
        raise ValueError("shadow timestamp is missing or invalid")
    for column in (
        "horizon_days",
        "target_sellable_rooms",
        "predicted_rooms",
        "baseline_predicted_rooms",
        "actual_rooms_sold",
        "lower_80",
        "upper_80",
        "lower_95",
        "upper_95",
        "inference_latency_ms",
    ):
        data[column] = pd.to_numeric(data[column], errors="raise")
    boolean = data["signal_is_synthetic"].astype(str).str.strip().str.lower()
    if not boolean.isin({"true", "false"}).all():
        raise ValueError("signal_is_synthetic must be boolean")
    data["signal_is_synthetic"] = boolean.eq("true")
    return data
