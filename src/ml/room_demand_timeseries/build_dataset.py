"""원시 일별 실적을 시점 보존 학습·비공개 평가·추론 dataset 묶음으로 변환한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .contracts import FEATURE_COLUMNS, IDENTITY_COLUMNS, SPLIT_WINDOWS
from .features import TimeSeriesFeatureBuilder


def sha256(path: Path) -> str:
    """dataset 파일을 스트리밍해 무결성 manifest용 SHA-256을 반환한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DatasetBundleWriter:
    """분할별 label 공개 범위를 지키며 압축 CSV와 파일 hash를 기록한다."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write(self, datasets: dict[str, pd.DataFrame]) -> dict[str, str]:
        """분할 DataFrame을 용도별 경로에 쓰고 논리 이름별 SHA-256을 반환한다.

        필수 분할이나 label 열이 없거나 파일 쓰기가 실패하면 해당 예외를
        호출자에게 전달해 불완전한 bundle을 성공으로 취급하지 않는다.
        """

        trainer = self.output_dir / "trainer"
        evaluator = self.output_dir / "evaluator_private"
        inference = self.output_dir / "inference"
        for directory in (trainer, evaluator, inference):
            directory.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for name in ("TRAIN", "VALIDATION"):
            path = trainer / f"{name.lower()}.csv.gz"
            datasets[name].to_csv(path, index=False, compression="gzip")
            paths[name.lower()] = path
        for name in ("TEST_A", "TEST_B"):
            normalized = name.lower()
            frame = datasets[name]
            feature_path = evaluator / f"{normalized}_features.csv.gz"
            label_path = evaluator / f"{normalized}_labels.csv.gz"
            frame.drop(columns=["target_rooms_sold", "target_occupancy_rate"]).to_csv(
                feature_path, index=False, compression="gzip"
            )
            frame[IDENTITY_COLUMNS + [
                "target_rooms_sold",
                "target_occupancy_rate",
            ]].to_csv(label_path, index=False, compression="gzip")
            paths[f"{normalized}_features"] = feature_path
            paths[f"{normalized}_labels"] = label_path
        inference_path = inference / "cutoff_20260831_d1_d10.csv.gz"
        datasets["INFERENCE"].to_csv(
            inference_path, index=False, compression="gzip"
        )
        paths["inference"] = inference_path
        return {
            name: sha256(path)
            for name, path in paths.items()
        }


def main() -> None:
    """CLI 원본을 감사·feature화하고 dataset manifest와 hash를 출력한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-facts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    builder = TimeSeriesFeatureBuilder()
    facts, audit = builder.load_daily_facts(args.daily_facts)
    datasets = {
        window.name: builder.build_labeled(facts, window)
        for window in SPLIT_WINDOWS
    }
    datasets["INFERENCE"] = builder.build_inference(
        facts,
        cutoff_date="2026-08-31",
        forecast_start="2026-09-01",
        forecast_end="2026-09-10",
    )
    hashes = DatasetBundleWriter(args.output_dir).write(datasets)
    manifest = {
        "dataset_version": "room-demand-timeseries-d1-d10-v2.0.0",
        "source_path": str(args.daily_facts),
        "source_sha256": sha256(args.daily_facts),
        "source_audit": asdict(audit),
        "split_windows": [asdict(window) for window in SPLIT_WINDOWS],
        "rows": {name: int(len(frame)) for name, frame in datasets.items()},
        "cutoff_ranges": {
            name: {
                "min": frame["cutoff_date"].min().date().isoformat(),
                "max": frame["cutoff_date"].max().date().isoformat(),
            }
            for name, frame in datasets.items()
        },
        "target_ranges": {
            name: {
                "min": frame["target_date"].min().date().isoformat(),
                "max": frame["target_date"].max().date().isoformat(),
            }
            for name, frame in datasets.items()
        },
        "feature_columns": FEATURE_COLUMNS,
        "inference_contains_labels": False,
        "september_observed_values_used": False,
        "file_sha256": hashes,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
