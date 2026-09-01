"""일별 실적과 시점 보존 미래 신호를 운영형 학습·평가 묶음으로 만든다."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .contracts import SPLIT_WINDOWS
from .features import TimeSeriesFeatureBuilder
from .operational_contracts import OPERATIONAL_FEATURE_COLUMNS
from .operational_features import OperationalFeatureBuilder
from .operational_governance import OperationalDataGate


WINDOWS = SPLIT_WINDOWS


def sha256(path: Path) -> str:
    """입력·산출 파일의 재현성 검증용 SHA-256을 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    """일별 실적과 시점 신호를 검증해 학습·평가 자료를 생성한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-facts", type=Path, required=True)
    parser.add_argument("--point-in-time-signals", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    historical = TimeSeriesFeatureBuilder()
    facts, audit = historical.load_daily_facts(args.daily_facts)
    signals = pd.read_csv(
        args.point_in_time_signals,
        parse_dates=["cutoff_date", "target_date"],
    )
    builder = OperationalFeatureBuilder()
    signals = builder.validate_signals(signals)
    signal_synthetic_values = signals["signal_is_synthetic"].unique().tolist()
    if len(signal_synthetic_values) != 1:
        raise ValueError("mixed observed and synthetic signals are not allowed")
    if bool(signal_synthetic_values[0]) != audit.synthetic_only:
        raise ValueError("daily facts and point-in-time signal source modes do not match")
    datasets = {
        window.name: builder.build_labeled(facts, signals, window)
        for window in WINDOWS
    }
    aligned_contract = OperationalDataGate.validate_aligned_splits(datasets)
    label_proxy_audits = {
        name: OperationalDataGate.audit_label_proxy(frame)
        for name, frame in datasets.items()
    }
    blocked = {
        name: report["blocked_horizons"]
        for name, report in label_proxy_audits.items()
        if not report["passed"]
    }
    if blocked:
        raise ValueError(f"booking_on_hand label-proxy risk detected: {blocked}")
    last_fact_date = pd.Timestamp(facts["business_date"].max())
    complete_signals = signals.loc[signals["target_date"] <= last_fact_date]
    inference_cutoff = complete_signals["cutoff_date"].max().date().isoformat()
    inference = builder.build_inference(
        facts,
        signals.loc[signals["cutoff_date"] == pd.Timestamp(inference_cutoff)],
        cutoff_date=inference_cutoff,
        forecast_start=(
            pd.Timestamp(inference_cutoff) + pd.Timedelta(1, unit="D")
        ).date().isoformat(),
        forecast_end=(
            pd.Timestamp(inference_cutoff) + pd.Timedelta(7, unit="D")
        ).date().isoformat(),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, frame in {**datasets, "INFERENCE": inference}.items():
        path = args.output_dir / f"{name.lower()}.csv.gz"
        frame.to_csv(path, index=False, compression="gzip")
        paths[name.lower()] = path
    development = pd.concat(datasets.values(), ignore_index=True)
    development_path = args.output_dir / "development.csv.gz"
    development.to_csv(development_path, index=False, compression="gzip")
    paths["development"] = development_path
    manifest = {
        "dataset_version": "room-demand-operational-point-in-time-v1",
        "source_sha256": sha256(args.daily_facts),
        "signal_sha256": sha256(args.point_in_time_signals),
        "synthetic_only": audit.synthetic_only,
        "source_audit": asdict(audit),
        "signal_provenance": signals.attrs["signal_provenance"],
        "aligned_comparison_contract": aligned_contract,
        "label_proxy_audits": label_proxy_audits,
        "windows": [asdict(window) for window in WINDOWS],
        "rows": {name: int(len(frame)) for name, frame in datasets.items()},
        "inference_rows": int(len(inference)),
        "feature_columns": OPERATIONAL_FEATURE_COLUMNS,
        "file_sha256": {name: sha256(path) for name, path in paths.items()},
    }
    (args.output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
