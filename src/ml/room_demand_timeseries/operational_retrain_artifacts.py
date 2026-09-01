"""V4 재학습 모델과 제출 평가 파일을 checksum으로 묶는다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .operational_submission_evaluation import IDENTITY_COLUMNS


def sha256(path: Path) -> str:
    """파일 내용을 SHA-256으로 식별한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    """한글을 보존한 재현 가능한 JSON을 기록한다."""

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class RetrainArtifactWriter:
    """평가 JSON·상세 CSV·잔차표·전체 checksum을 저장한다."""

    @staticmethod
    def write_evaluation(
        output: Path,
        report: dict[str, Any],
        prediction_frames: dict[str, pd.DataFrame],
    ) -> None:
        """제출용 평가 JSON과 사람이 확인할 상세 CSV를 함께 기록한다."""

        write_json(output / "submission_evaluation.json", report)
        pd.json_normalize(report["learning_curve"]).to_csv(
            output / "learning_curve.csv", index=False
        )
        test_report = report["split_reports"]["TEST"]
        for name, rows in test_report["group_metrics"].items():
            pd.json_normalize(rows).to_csv(output / f"test_by_{name}.csv", index=False)
        identity = [
            column
            for column in IDENTITY_COLUMNS
            if column in prediction_frames["TEST"]
        ]
        columns = [
            *identity,
            "target_rooms_sold",
            "predicted_rooms",
            "baseline_predicted_rooms",
            "residual_rooms",
            "absolute_error_rooms",
        ]
        prediction_frames["TEST"][columns].to_csv(
            output / "test_residuals.csv.gz", index=False, compression="gzip"
        )

    @staticmethod
    def write_checksums(output_dir: Path) -> None:
        """산출물별 SHA-256을 계산해 무결성 목록으로 기록한다."""

        files = sorted(
            path
            for path in output_dir.rglob("*")
            if path.is_file() and path.name != "checksums.sha256.json"
        )
        write_json(
            output_dir / "checksums.sha256.json",
            {path.relative_to(output_dir).as_posix(): sha256(path) for path in files},
        )
