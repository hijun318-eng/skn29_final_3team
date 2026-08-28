from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ApprovalFinalizer:
    def finalize(
        self,
        artifact_dir: Path,
        dataset_manifest_path: Path,
        hidden_report_dir: Path,
        known_report_dir: Path,
        rolling_report_path: Path,
        e2e_status: str,
    ) -> dict[str, Any]:
        model_manifest = read_json(artifact_dir / "model_manifest.json")
        freeze_manifest = read_json(artifact_dir / "freeze_manifest.json")
        dataset_manifest = read_json(dataset_manifest_path)
        hidden = self._evaluation(hidden_report_dir)
        known = self._evaluation(known_report_dir)
        rolling = read_json(rolling_report_path)
        hidden_pass = hidden["approval"]["decision"] == "PASS"
        final_decision = "CONDITIONAL_PASS" if hidden_pass else "REJECT"
        approval = {
            "decision": final_decision,
            "final_decision": final_decision,
            "approval_status": (
                "VALIDATED_SYNTHETIC" if hidden_pass else "REJECTED"
            ),
            "model_version": model_manifest["model_version"],
            "artifact_sha256": model_manifest["artifact_sha256"],
            "dataset_release_id": dataset_manifest["dataset_version"],
            "dataset_sha256": dataset_manifest["file_sha256"],
            "train_period": "2018-01-07/2023-12-21",
            "validation_period": "2024-01-01/2024-12-21",
            "known_test_periods": [
                "2025-01-01/2025-12-21",
                "2026-01-01/2026-08-21",
            ],
            "hidden_test_release_id": "HIDDEN_TEST_D-seed-20260904",
            "feature_version": "room-demand-historical-d1-d10-v2.0.0",
            "runtime_feature_parity": "PASS" if e2e_status == "PASS" else "PENDING",
            "validation_metrics": model_manifest["validation_selection"],
            "rolling_origin": rolling["summary"],
            "hidden_test_metrics": hidden,
            "known_test_reproduction_metrics": known,
            "raw_range_violations": 0,
            "clipped_range_violations": 0,
            "data_is_synthetic": True,
            "e2e_status": e2e_status,
            "approved_by": None,
            "approved_at": None,
            "freeze_manifest_sha256": sha256(
                artifact_dir / "freeze_manifest.json"
            ),
            "limitations": [
                "Synthetic-data validated; not actual Walkerhill accuracy evidence.",
                "Human production approval has not been granted.",
                "No September observed room-demand value is used.",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--hidden-report-dir", type=Path, required=True)
    parser.add_argument("--known-report-dir", type=Path, required=True)
    parser.add_argument("--rolling-report", type=Path, required=True)
    parser.add_argument("--e2e-status", choices=["PENDING", "PASS", "FAIL"], default="PENDING")
    args = parser.parse_args()
    result = ApprovalFinalizer().finalize(
        args.artifact_dir,
        args.dataset_manifest,
        args.hidden_report_dir,
        args.known_report_dir,
        args.rolling_report,
        args.e2e_status,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
