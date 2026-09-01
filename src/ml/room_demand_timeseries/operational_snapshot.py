"""운영 D+1~D+7 신호 snapshot batch를 검증하고 적재용 파일로 봉인한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .operational_contracts import (
    OBSERVED_SIGNAL_SOURCE_KIND,
    OPERATIONAL_MAX_HORIZON,
    SIGNAL_IDENTITY_COLUMNS,
    SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS,
    SIGNAL_REQUIRED_COLUMNS,
    SYNTHETIC_SIGNAL_SOURCE_KIND,
)
from .operational_features import OperationalFeatureBuilder


SNAPSHOT_METADATA_COLUMNS = ["captured_at", "source_batch_id"]
SNAPSHOT_STORAGE_COLUMNS = (
    SIGNAL_REQUIRED_COLUMNS
    + SNAPSHOT_METADATA_COLUMNS
    + ["source_payload_sha256"]
)
BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


@dataclass(frozen=True)
class SnapshotBatchReceipt:
    """검증된 snapshot batch의 적재 전 재현성 영수증이다."""

    source_batch_id: str
    source_payload_sha256: str
    signal_source_kind: str
    signal_is_synthetic: bool
    cutoff_date: str
    captured_at: str
    rows: int
    properties: list[str]
    series_count: int
    horizons: list[int]
    completeness_passed: bool


class SnapshotBatchValidator:
    """과거 최종값 backfill과 불완전 horizon batch를 적재 전에 차단한다."""

    _TIMEZONE = "Asia/Seoul"

    def __init__(self, *, max_capture_delay_hours: int = 6) -> None:
        if not 1 <= max_capture_delay_hours <= 24:
            raise ValueError("max_capture_delay_hours must be between 1 and 24")
        self.max_capture_delay = pd.Timedelta(max_capture_delay_hours, unit="h")

    def validate(
        self,
        frame: pd.DataFrame,
        *,
        expected_source_kind: str,
        source_payload_sha256: str,
    ) -> tuple[pd.DataFrame, SnapshotBatchReceipt]:
        """신호·capture 시각·batch 완전성을 검증하고 정규화된 행을 반환한다."""

        if expected_source_kind not in {
            OBSERVED_SIGNAL_SOURCE_KIND,
            SYNTHETIC_SIGNAL_SOURCE_KIND,
        }:
            raise ValueError("expected_source_kind is unsupported")
        if not re.fullmatch(r"[0-9a-f]{64}", source_payload_sha256):
            raise ValueError("source_payload_sha256 must be lowercase SHA-256")
        missing = sorted(
            set(SIGNAL_REQUIRED_COLUMNS + SNAPSHOT_METADATA_COLUMNS)
            - set(frame.columns)
        )
        if missing:
            raise ValueError(f"snapshot batch missing columns: {missing}")
        normalized_signals = OperationalFeatureBuilder.validate_signals(frame)
        metadata = frame[SIGNAL_IDENTITY_COLUMNS + SNAPSHOT_METADATA_COLUMNS].copy()
        metadata["property_id"] = metadata["property_id"].astype(str).str.upper()
        metadata["room_type_code"] = metadata["room_type_code"].astype(str)
        for column in ("cutoff_date", "target_date"):
            metadata[column] = pd.to_datetime(metadata[column])
        metadata["horizon_days"] = pd.to_numeric(
            metadata["horizon_days"], errors="raise"
        )
        metadata["captured_at"] = pd.to_datetime(
            metadata["captured_at"], utc=True, errors="coerce"
        )
        if metadata["captured_at"].isna().any():
            raise ValueError("snapshot captured_at is missing or invalid")
        batch_ids = metadata["source_batch_id"].astype(str).str.strip().unique()
        if len(batch_ids) != 1 or not BATCH_ID_PATTERN.fullmatch(batch_ids[0]):
            raise ValueError("snapshot source_batch_id is invalid or mixed")
        cutoff_values = normalized_signals["cutoff_date"].dt.normalize().unique()
        captured_values = metadata["captured_at"].unique()
        if len(cutoff_values) != 1 or len(captured_values) != 1:
            raise ValueError("one snapshot batch must contain one cutoff and capture time")
        cutoff = pd.Timestamp(cutoff_values[0])
        cutoff_end = (
            cutoff.tz_localize(self._TIMEZONE).tz_convert("UTC")
            + pd.Timedelta(1, unit="D")
        )
        captured_at = pd.Timestamp(captured_values[0])
        if not cutoff_end <= captured_at <= cutoff_end + self.max_capture_delay:
            raise ValueError("snapshot capture time is outside the cutoff grace window")
        if any(
            (normalized_signals[column] > captured_at).any()
            for column in SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS
        ):
            raise ValueError("snapshot provenance timestamp is later than captured_at")
        if not (
            normalized_signals["signal_source_kind"] == expected_source_kind
        ).all():
            raise ValueError("snapshot source kind does not match the expected mode")
        synthetic = expected_source_kind == SYNTHETIC_SIGNAL_SOURCE_KIND
        if not (normalized_signals["signal_is_synthetic"] == synthetic).all():
            raise ValueError("snapshot synthetic mode does not match the expected mode")
        self._validate_complete_horizons(normalized_signals)
        normalized = normalized_signals.merge(
            metadata,
            on=SIGNAL_IDENTITY_COLUMNS,
            how="left",
            validate="one_to_one",
        )
        normalized["captured_at"] = captured_at
        normalized["source_batch_id"] = batch_ids[0]
        normalized["source_payload_sha256"] = source_payload_sha256
        normalized = normalized[SNAPSHOT_STORAGE_COLUMNS]
        receipt = SnapshotBatchReceipt(
            source_batch_id=batch_ids[0],
            source_payload_sha256=source_payload_sha256,
            signal_source_kind=expected_source_kind,
            signal_is_synthetic=synthetic,
            cutoff_date=cutoff.date().isoformat(),
            captured_at=captured_at.isoformat(),
            rows=int(len(normalized)),
            properties=sorted(normalized["property_id"].unique().tolist()),
            series_count=int(
                normalized[["property_id", "room_type_code"]]
                .drop_duplicates()
                .shape[0]
            ),
            horizons=list(range(1, OPERATIONAL_MAX_HORIZON + 1)),
            completeness_passed=True,
        )
        return normalized, receipt

    @staticmethod
    def _validate_complete_horizons(frame: pd.DataFrame) -> None:
        expected = tuple(range(1, OPERATIONAL_MAX_HORIZON + 1))
        grouped = frame.groupby(
            ["cutoff_date", "property_id", "room_type_code"], sort=True
        )["horizon_days"]
        incomplete = [
            "|".join(str(value) for value in keys)
            for keys, values in grouped
            if tuple(sorted(values.astype(int).tolist())) != expected
        ]
        if incomplete:
            raise ValueError(
                "snapshot batch has incomplete D+1..D+7 groups: "
                + ", ".join(incomplete[:10])
            )


def sha256_file(path: Path) -> str:
    """snapshot 원본 파일의 SHA-256을 스트리밍 방식으로 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_outputs(
    normalized: pd.DataFrame,
    receipt: SnapshotBatchReceipt,
    normalized_output: Path,
    receipt_output: Path,
) -> None:
    if normalized_output.exists() or receipt_output.exists():
        raise FileExistsError("snapshot output already exists")
    normalized_output.parent.mkdir(parents=True, exist_ok=True)
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    normalized_temp = normalized_output.with_suffix(normalized_output.suffix + ".tmp")
    receipt_temp = receipt_output.with_suffix(receipt_output.suffix + ".tmp")
    normalized.to_csv(normalized_temp, index=False)
    receipt_temp.write_text(
        json.dumps(asdict(receipt), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    normalized_temp.replace(normalized_output)
    receipt_temp.replace(receipt_output)


def main() -> None:
    """원본 snapshot CSV를 정규화하고 검증 영수증과 함께 저장한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--normalized-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    parser.add_argument(
        "--expected-source-kind",
        choices=[OBSERVED_SIGNAL_SOURCE_KIND, SYNTHETIC_SIGNAL_SOURCE_KIND],
        required=True,
    )
    args = parser.parse_args()
    source_hash = sha256_file(args.input)
    frame = pd.read_csv(args.input)
    normalized, receipt = SnapshotBatchValidator().validate(
        frame,
        expected_source_kind=args.expected_source_kind,
        source_payload_sha256=source_hash,
    )
    _write_outputs(
        normalized,
        receipt,
        args.normalized_output,
        args.receipt_output,
    )
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
