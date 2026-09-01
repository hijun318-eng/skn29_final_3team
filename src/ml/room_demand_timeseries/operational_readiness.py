"""운영형 객실 수요 모델의 남은 승인 증거를 재현 가능한 보고서로 감사한다."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .operational_contracts import OBSERVED_SIGNAL_SOURCE_KIND
from .operational_metrics import METRIC_CONTRACT_VERSION
from .operational_shadow_validation import ObservedShadowValidator, sha256_file


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object is required: {path}")
    return value


class OperationalReadinessAuditor:
    """artifact·실데이터·정렬 비교·shadow·사람 승인 상태를 fail-closed로 감사한다."""

    def audit(
        self,
        artifact_dir: Path,
        environment_example: Path,
        *,
        dataset_manifest_path: Path | None = None,
        aligned_benchmark_path: Path | None = None,
        shadow_report_path: Path | None = None,
        shadow_source_path: Path | None = None,
    ) -> dict[str, Any]:
        """운영 후보에 필요한 모든 기술·사람 승인 증거의 현재 상태를 감사한다."""

        blockers: list[str] = []
        checks = {
            "artifact_integrity": self._artifact_integrity(artifact_dir),
            "feature_provenance_contract": self._feature_contract(artifact_dir),
            "runtime_default_disabled": self._runtime_disabled(environment_example),
            "observed_aligned_dataset": self._observed_dataset(
                dataset_manifest_path
            ),
            "aligned_v22_v40_benchmark": self._aligned_benchmark(
                aligned_benchmark_path
            ),
            "observed_90_day_shadow": self._observed_shadow(
                artifact_dir,
                shadow_report_path,
                shadow_source_path,
            ),
            "human_approval_recorded": self._human_approval(artifact_dir),
        }
        blocker_names = {
            "artifact_integrity": "artifact_integrity_failed",
            "feature_provenance_contract": "feature_provenance_contract_failed",
            "runtime_default_disabled": "unsafe_runtime_default",
            "observed_aligned_dataset": "observed_aligned_dataset_missing",
            "aligned_v22_v40_benchmark": "observed_aligned_benchmark_missing",
            "observed_90_day_shadow": "observed_90_day_shadow_missing",
            "human_approval_recorded": "human_approval_missing",
        }
        blockers.extend(
            blocker_names[name] for name, passed in checks.items() if not passed
        )
        technical = all(
            checks[name]
            for name in checks
            if name != "human_approval_recorded"
        )
        return {
            "schema_version": "room-demand-operational-readiness-v1",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": _read(artifact_dir / "model_manifest.json").get(
                "model_version"
            ),
            "decision": (
                "APPROVED"
                if not blockers
                else "READY_FOR_HUMAN_APPROVAL"
                if technical
                else "BLOCKED"
            ),
            "production_approved": not blockers,
            "checks": checks,
            "blockers": blockers,
            "evidence": {
                "artifact_dir": str(artifact_dir.resolve()),
                "dataset_manifest": self._path(dataset_manifest_path),
                "aligned_benchmark": self._path(aligned_benchmark_path),
                "shadow_report": self._path(shadow_report_path),
                "shadow_source": self._path(shadow_source_path),
            },
        }

    @staticmethod
    def _path(path: Path | None) -> str | None:
        return str(path.resolve()) if path is not None and path.exists() else None

    @staticmethod
    def _artifact_integrity(artifact_dir: Path) -> bool:
        try:
            checksums = _read(artifact_dir / "checksums.sha256.json")
            return bool(checksums) and all(
                (artifact_dir / name).is_file()
                and sha256_file(artifact_dir / name) == expected
                for name, expected in checksums.items()
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _feature_contract(artifact_dir: Path) -> bool:
        try:
            contract = _read(artifact_dir / "feature_contract.json")
            columns = set(contract.get("signal_provenance_columns") or [])
            return bool(
                contract.get("signal_provenance_required") is True
                and contract.get("production_signal_source_kind")
                == OBSERVED_SIGNAL_SOURCE_KIND
                and {
                    "reservation_as_of_at",
                    "capacity_as_of_at",
                    "event_as_of_at",
                    "signal_source_kind",
                    "signal_is_synthetic",
                }.issubset(columns)
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _runtime_disabled(path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
            return "ML_FEATURE_ENABLED=0" in text and "ML_ALLOW_CONDITIONAL=false" in text
        except OSError:
            return False

    @staticmethod
    def _observed_dataset(path: Path | None) -> bool:
        if path is None or not path.is_file():
            return False
        try:
            manifest = _read(path)
            provenance = manifest.get("signal_provenance") or {}
            audits = manifest.get("label_proxy_audits") or {}
            aligned = manifest.get("aligned_comparison_contract") or {}
            return bool(
                manifest.get("synthetic_only") is False
                and provenance.get("source_kinds") == [OBSERVED_SIGNAL_SOURCE_KIND]
                and audits
                and all(report.get("passed") is True for report in audits.values())
                and aligned.get("contract")
                == "2018-2023_train__2024_validation__2025_test_a__2026_test_b"
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _aligned_benchmark(path: Path | None) -> bool:
        if path is None or not path.is_file():
            return False
        try:
            report = _read(path)
            gates = report.get("approval_gates") or {}
            self_evaluation = report.get("self_evaluation") or {}
            return bool(
                report.get("comparison_mode") == "aligned_same_rows_equal_budget"
                and report.get("metric_contract_version")
                == METRIC_CONTRACT_VERSION
                and report.get("data_is_synthetic") is False
                and self_evaluation.get("technical_validation_passed") is True
                and self_evaluation.get("production_eligible") is True
                and gates
                and all(value is True for value in gates.values())
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _observed_shadow(
        artifact_dir: Path,
        report_path: Path | None,
        source_path: Path | None,
    ) -> bool:
        if not report_path or not source_path or not report_path.is_file() or not source_path.is_file():
            return False
        try:
            report = _read(report_path)
            recomputed = ObservedShadowValidator().validate(
                pd.read_csv(source_path),
                expected_artifact_sha256=sha256_file(artifact_dir / "model.joblib"),
                expected_feature_contract_sha256=sha256_file(
                    artifact_dir / "feature_contract.json"
                ),
                source_sha256=sha256_file(source_path),
            )
            return recomputed == report
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _human_approval(artifact_dir: Path) -> bool:
        try:
            approval = _read(artifact_dir / "model.approval.json")
            return bool(
                approval.get("production_approved") is True
                and str(approval.get("human_approved_by") or "").strip()
                and str(approval.get("human_approved_at") or "").strip()
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False


def main() -> None:
    """명령행에서 운영 준비도 감사를 실행하고 JSON 보고서를 원자적으로 저장한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--environment-example", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path)
    parser.add_argument("--aligned-benchmark", type=Path)
    parser.add_argument("--shadow-report", type=Path)
    parser.add_argument("--shadow-source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = OperationalReadinessAuditor().audit(
        args.artifact_dir,
        args.environment_example,
        dataset_manifest_path=args.dataset_manifest,
        aligned_benchmark_path=args.aligned_benchmark,
        shadow_report_path=args.shadow_report,
        shadow_source_path=args.shadow_source,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
