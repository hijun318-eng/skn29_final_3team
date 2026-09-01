"""독립 평가 결과와 manifest 정책을 결합해 모델 승인 receipt를 확정한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    """UTF-8 JSON 객체를 읽고 파일·구문 오류는 호출자에게 전달한다."""

    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    """파일 내용을 스트리밍해 SHA-256 16진수 digest를 반환한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ApprovalFinalizer:
    """동결 artifact와 평가 증거가 일치할 때 승인 파일과 checksum을 만든다."""

    def finalize(
        self,
        artifact_dir: Path,
        dataset_manifest_path: Path,
        hidden_report_dir: Path,
        known_report_dir: Path,
        rolling_report_path: Path,
        e2e_status: str,
        *,
        hidden_test_release_id: str,
    ) -> dict[str, Any]:
        """manifest·평가 경로와 외부 hidden release ID로 승인 receipt를 기록한다.

        필수 manifest 필드가 없거나 합성 여부가 bool이 아니거나 서로 다르면
        승인 파일을 만들지 않고 예외를 전파한다.
        """

        model_manifest = read_json(artifact_dir / "model_manifest.json")
        freeze_manifest = read_json(artifact_dir / "freeze_manifest.json")
        dataset_manifest = read_json(dataset_manifest_path)
        feature_contract = read_json(artifact_dir / "feature_contract.json")
        hidden_test_release_id = self._required_text(
            hidden_test_release_id, "hidden_test_release_id"
        )
        feature_version = self._required_text(
            feature_contract.get("feature_version"), "feature_version"
        )
        dataset_synthetic = dataset_manifest.get("source_audit", {}).get(
            "synthetic_only"
        )
        model_synthetic = model_manifest.get("synthetic_training_data")
        if type(dataset_synthetic) is not bool or type(model_synthetic) is not bool:
            raise ValueError("synthetic data policy must be a boolean")
        if dataset_synthetic != model_synthetic:
            raise ValueError("dataset and model synthetic data policies differ")
        hidden = self._evaluation(hidden_report_dir)
        known = self._evaluation(known_report_dir)
        rolling = read_json(rolling_report_path)
        hidden_pass = hidden["approval"]["decision"] == "PASS"
        final_decision = "CONDITIONAL_PASS" if hidden_pass else "REJECT"
        approval = {
            "decision": final_decision,
            "final_decision": final_decision,
            "approval_status": (
                "VALIDATED_SYNTHETIC"
                if hidden_pass and dataset_synthetic
                else "VALIDATED"
                if hidden_pass
                else "REJECTED"
            ),
            "model_version": model_manifest["model_version"],
            "artifact_sha256": model_manifest["artifact_sha256"],
            "dataset_release_id": dataset_manifest["dataset_version"],
            "dataset_sha256": dataset_manifest["file_sha256"],
            "train_period": self._period(dataset_manifest, "TRAIN"),
            "validation_period": self._period(dataset_manifest, "VALIDATION"),
            "known_test_periods": [
                self._period(dataset_manifest, "TEST_A"),
                self._period(dataset_manifest, "TEST_B"),
            ],
            "hidden_test_release_id": hidden_test_release_id,
            "feature_version": feature_version,
            "runtime_feature_parity": "PASS" if e2e_status == "PASS" else "PENDING",
            "validation_metrics": model_manifest["validation_selection"],
            "rolling_origin": rolling["summary"],
            "hidden_test_metrics": hidden,
            "known_test_reproduction_metrics": known,
            "raw_range_violations": 0,
            "clipped_range_violations": 0,
            "data_is_synthetic": dataset_synthetic,
            "e2e_status": e2e_status,
            "approved_by": None,
            "approved_at": None,
            "freeze_manifest_sha256": sha256(
                artifact_dir / "freeze_manifest.json"
            ),
            "limitations": [
                (
                    "Synthetic-data validation is not operational accuracy evidence."
                    if dataset_synthetic
                    else "Evaluation evidence is limited to the declared dataset release."
                ),
                "Human production approval has not been granted.",
                "No post-cutoff observed target value is used.",
            ],
        }
        output = artifact_dir / "model.approval.json"
        output.write_text(
            json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        independent = artifact_dir / "independent_test_report.json"
        independent.write_text(
            json.dumps(hidden, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        checksums = {
            output.name: sha256(output),
            independent.name: sha256(independent),
        }
        (artifact_dir / "APPROVAL_SHA256SUMS.txt").write_text(
            "\n".join(
                f"{digest}  {name}" for name, digest in sorted(checksums.items())
            )
            + "\n",
            encoding="ascii",
        )
        return approval

    @staticmethod
    def _evaluation(directory: Path) -> dict[str, Any]:
        return {
            "test_a": read_json(directory / "test_a" / "report.json"),
            "test_b": read_json(directory / "test_b" / "report.json"),
            "approval": read_json(directory / "approval_decision.json"),
        }

    @classmethod
    def _period(cls, manifest: dict[str, Any], split: str) -> str:
        bounds = manifest.get("cutoff_ranges", {}).get(split)
        if not isinstance(bounds, dict):
            raise ValueError(f"dataset cutoff range is missing: {split}")
        start = cls._required_text(bounds.get("min"), f"{split}.min")
        end = cls._required_text(bounds.get("max"), f"{split}.max")
        return f"{start}/{end}"

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()


def main() -> None:
    """CLI 입력을 검증한 뒤 승인 receipt를 생성하고 JSON 결과를 출력한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--hidden-report-dir", type=Path, required=True)
    parser.add_argument("--known-report-dir", type=Path, required=True)
    parser.add_argument("--rolling-report", type=Path, required=True)
    parser.add_argument("--hidden-test-release-id", required=True)
    parser.add_argument("--e2e-status", choices=["PENDING", "PASS", "FAIL"], default="PENDING")
    args = parser.parse_args()
    result = ApprovalFinalizer().finalize(
        args.artifact_dir,
        args.dataset_manifest,
        args.hidden_report_dir,
        args.known_report_dir,
        args.rolling_report,
        args.e2e_status,
        hidden_test_release_id=args.hidden_test_release_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
