"""학습 artifact를 외부 release 정책 계약과 묶어 재현 가능한 동결 묶음으로 만든다."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    MAX_HORIZON,
    MODEL_VERSION,
    NUMERIC_FEATURES,
)


BLOCKED_FEATURES = [
    "rooms_sold",
    "future_occupancy",
    "future_adr",
    "future_revpar",
    "future_cancellation",
    "future_no_show",
    "booking_curve_family_qa",
    "market_regime_qa",
    "generation_seed",
    "simulation_world_id",
    "dataset_split",
    "label_available",
    "is_synthetic",
]


def sha256(path: Path) -> str:
    """artifact 파일을 스트리밍해 SHA-256 16진수 digest를 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_attestation() -> dict[str, Any]:
    """현재 ML Python 모듈별 hash와 정렬된 bundle hash를 반환한다."""

    module_dir = Path(__file__).resolve().parent
    files = {
        path.name: sha256(path)
        for path in sorted(module_dir.glob("*.py"))
    }
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "type": "python_source_bundle_sha256",
        "bundle_sha256": hashlib.sha256(payload).hexdigest(),
        "files_sha256": files,
    }


class ArtifactFreezer:
    """학습 결과와 dataset 증거를 검증하고 배포 전 동결 계약을 기록한다."""

    def freeze(
        self,
        artifact_dir: Path,
        dataset_manifest_path: Path,
        *,
        feature_version: str,
        target_column: str,
    ) -> dict[str, Any]:
        """외부 feature/target 정책을 동결 파일에 반영하고 checksum manifest를 반환한다.

        모델 버전·feature 순서·합성 및 미래 관측 계약이 잘못되면 파일 생성을
        시작하기 전에 ``ValueError``로 실패한다.
        """

        model_manifest = json.loads(
            (artifact_dir / "model_manifest.json").read_text(encoding="utf-8")
        )
        dataset_manifest = json.loads(
            dataset_manifest_path.read_text(encoding="utf-8")
        )
        if model_manifest["model_version"] != MODEL_VERSION:
            raise ValueError("model version does not match source contract")
        if model_manifest["feature_columns"] != FEATURE_COLUMNS:
            raise ValueError("model and source feature order differ")
        feature_version = self._required_text(feature_version, "feature_version")
        target_column = self._required_text(target_column, "target_column")
        synthetic_training_data = model_manifest.get("synthetic_training_data")
        observed_future_values_used = model_manifest.get(
            "september_observed_values_used"
        )
        if type(synthetic_training_data) is not bool:
            raise ValueError("synthetic_training_data must be a boolean")
        if type(observed_future_values_used) is not bool:
            raise ValueError("observed future value policy must be a boolean")
        feature_contract = {
            "feature_version": feature_version,
            "model_version": MODEL_VERSION,
            "target": target_column,
            "grain": [
                "property_id",
                "target_date",
                "room_type_code",
                "horizon_days",
            ],
            "categorical_features": CATEGORICAL_FEATURES,
            "numeric_features": NUMERIC_FEATURES,
            "feature_columns_ordered": FEATURE_COLUMNS,
            "blocked_features": BLOCKED_FEATURES,
            "max_horizon": MAX_HORIZON,
        }
        runtime_contract = {
            "status": "IMPLEMENTED_PENDING_E2E",
            "as_of_semantics": "end_of_business_day",
            "minimum_history_days": 371,
            "forecast_horizons": list(range(1, MAX_HORIZON + 1)),
            "sources": {
                "identity_and_capacity": "historical daily facts",
                "lag_and_rolling_features": "facts at or before as_of_date",
                "target_calendar": "deterministic target date calculation",
                "holiday_flags": "versioned Korean holiday calendar",
            },
            "future_observed_features": [],
            "booking_on_hand_required": False,
            "september_observed_values_used": observed_future_values_used,
            "feature_columns_ordered": FEATURE_COLUMNS,
        }
        self._write_json(artifact_dir / "feature_contract.json", feature_contract)
        self._write_json(
            artifact_dir / "runtime_feature_contract.json", runtime_contract
        )
        self._write_json(
            artifact_dir / "source_code_attestation.json", source_attestation()
        )
        model_card = f"""# {MODEL_VERSION}

## Purpose

Predict {target_column} for D+1 through D+{MAX_HORIZON} from historical daily facts available at the end of the cutoff date.

## Training and validation

- Training source: {'synthetic generated daily facts' if synthetic_training_data else 'declared operational daily facts'}
- Training rows: {model_manifest['training_rows']:,}
- Validation WAPE: {model_manifest['validation_selection']['metrics']['wape']:.4%}
- Best baseline: {model_manifest['validation_selection']['best_baseline_name']}
- Best baseline improvement: {model_manifest['validation_selection']['baseline_improvement']:.4%}
- Post-cutoff observed target values used: {'yes' if observed_future_values_used else 'no'}

## Limitations

- {'Synthetic-data validation is not operational accuracy evidence.' if synthetic_training_data else 'Accuracy evidence applies only to the declared dataset release.'}
- Runtime feature parity and dynamic service E2E must pass before service approval.
- Known TEST-A/B results are reproduction evidence only; a newly generated Hidden Test is required for independent performance evidence.
"""
        (artifact_dir / "model_card.md").write_text(model_card, encoding="utf-8")
        frozen_files = [
            "model.joblib",
            "model_manifest.json",
            "selection_trials.json",
            "feature_contract.json",
            "runtime_feature_contract.json",
            "source_code_attestation.json",
            "model_card.md",
        ]
        hashes = {name: sha256(artifact_dir / name) for name in frozen_files}
        freeze_manifest = {
            "freeze_status": "FROZEN_CANDIDATE",
            "model_version": MODEL_VERSION,
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_version": dataset_manifest["dataset_version"],
            "dataset_source_sha256": dataset_manifest["source_sha256"],
            "dataset_file_sha256": dataset_manifest["file_sha256"],
            "artifact_files_sha256": hashes,
            "test_seen_by_trainer": False,
            "hidden_test_evaluated": False,
            "code_revision": json.loads(
                (artifact_dir / "source_code_attestation.json").read_text(
                    encoding="utf-8"
                )
            ),
        }
        self._write_json(artifact_dir / "freeze_manifest.json", freeze_manifest)
        all_hashes = {
            **hashes,
            "freeze_manifest.json": sha256(artifact_dir / "freeze_manifest.json"),
        }
        lines = [f"{digest}  {name}" for name, digest in sorted(all_hashes.items())]
        (artifact_dir / "SHA256SUMS.txt").write_text(
            "\n".join(lines) + "\n", encoding="ascii"
        )
        return freeze_manifest

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()


def main() -> None:
    """필수 release 정책을 CLI에서 받아 artifact 동결 결과를 출력한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--feature-version", required=True)
    parser.add_argument("--target-column", required=True)
    args = parser.parse_args()
    result = ArtifactFreezer().freeze(
        args.artifact_dir,
        args.dataset_manifest,
        feature_version=args.feature_version,
        target_column=args.target_column,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
