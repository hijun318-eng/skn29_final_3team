"""실데이터 검증 증거가 모두 일치할 때만 운영 승인서를 원자적으로 발급한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .operational_contracts import OPERATIONAL_MODEL_VERSION
from .operational_governance import ProductionApprovalGate
from .operational_shadow_contracts import HASH_PATTERN, SHADOW_SCHEMA_VERSION
from .operational_shadow_validation import ObservedShadowValidator


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object is required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class OperationalPromoter:
    """모델·데이터·비교·shadow 영수증을 연결해 수동 운영 승인을 확정한다."""

    def promote(
        self,
        artifact_dir: Path,
        dataset_manifest_path: Path,
        benchmark_path: Path,
        shadow_report_path: Path,
        shadow_source_path: Path,
        *,
        approved_by: str,
        approved_at: str,
    ) -> dict[str, Any]:
        """원본 증거를 재검증하고 모두 일치할 때만 운영 승인서를 발급한다."""

        manifest_path = artifact_dir / "model_manifest.json"
        feature_contract_path = artifact_dir / "feature_contract.json"
        artifact_path = artifact_dir / "model.joblib"
        manifest = _read(manifest_path)
        feature_contract = _read(feature_contract_path)
        dataset = _read(dataset_manifest_path)
        benchmark = _read(benchmark_path)
        shadow = _read(shadow_report_path)
        artifact_hash = _sha256(artifact_path)
        feature_contract_hash = _sha256(feature_contract_path)
        blockers = self._integrity_blockers(
            manifest,
            feature_contract,
            dataset,
            benchmark,
            shadow,
            artifact_hash,
            feature_contract_hash,
            dataset_manifest_path,
        )
        blockers.extend(
            self._shadow_source_blockers(
                shadow,
                shadow_source_path,
                artifact_hash,
                feature_contract_hash,
            )
        )
        gate = ProductionApprovalGate.evaluate(
            dataset,
            benchmark,
            shadow,
            approved_by=approved_by,
            approved_at=approved_at,
        )
        blockers.extend(gate["blockers"])
        if blockers:
            raise ValueError(
                "production approval blocked: " + ", ".join(sorted(set(blockers)))
            )
        approval = {
            "decision": "APPROVED",
            "final_decision": "APPROVED",
            "approval_status": "APPROVED",
            "production_approved": True,
            "model_version": OPERATIONAL_MODEL_VERSION,
            "artifact_sha256": artifact_hash,
            "feature_version": feature_contract["feature_version"],
            "data_is_synthetic": False,
            "runtime_feature_parity": "PASS",
            "dataset_manifest_sha256": _sha256(dataset_manifest_path),
            "aligned_benchmark_sha256": _sha256(benchmark_path),
            "shadow_report_sha256": _sha256(shadow_report_path),
            "shadow_source_sha256": _sha256(shadow_source_path),
            "human_approved_by": approved_by.strip(),
            "human_approved_at": approved_at,
            "limitations": shadow.get("limitations", []),
        }
        approval_path = artifact_dir / "model.approval.json"
        _write_atomic(approval_path, approval)
        checksums_path = artifact_dir / "checksums.sha256.json"
        checksums = _read(checksums_path) if checksums_path.exists() else {}
        checksums[approval_path.name] = _sha256(approval_path)
        _write_atomic(checksums_path, checksums)
        return approval

    @staticmethod
    def _integrity_blockers(
        manifest: dict[str, Any],
        feature_contract: dict[str, Any],
        dataset: dict[str, Any],
        benchmark: dict[str, Any],
        shadow: dict[str, Any],
        artifact_hash: str,
        feature_contract_hash: str,
        dataset_manifest_path: Path,
    ) -> list[str]:
        blockers = []
        if manifest.get("model_version") != OPERATIONAL_MODEL_VERSION:
            blockers.append("model_version_mismatch")
        if feature_contract.get("model_version") != OPERATIONAL_MODEL_VERSION:
            blockers.append("feature_contract_model_version_mismatch")
        if manifest.get("artifact_sha256") != artifact_hash:
            blockers.append("artifact_hash_mismatch")
        if manifest.get("synthetic_training_data") is not False:
            blockers.append("model_was_not_trained_on_observed_data")
        if feature_contract.get("signal_provenance_required") is not True:
            blockers.append("feature_contract_does_not_require_signal_provenance")
        if manifest.get("source_dataset_sha256") != dataset.get("source_sha256"):
            blockers.append("daily_fact_dataset_hash_mismatch")
        if manifest.get("signal_dataset_sha256") != dataset.get("signal_sha256"):
            blockers.append("signal_dataset_hash_mismatch")
        if benchmark.get("dataset_manifest_sha256") != _sha256(dataset_manifest_path):
            blockers.append("benchmark_dataset_manifest_hash_mismatch")
        benchmark_hashes = benchmark.get("model_artifact_sha256") or {}
        if benchmark_hashes.get("operational_ablation") != artifact_hash:
            blockers.append("approved_benchmark_candidate_hash_mismatch")
        if shadow.get("model_version") != OPERATIONAL_MODEL_VERSION:
            blockers.append("shadow_model_version_mismatch")
        if shadow.get("artifact_sha256") != artifact_hash:
            blockers.append("shadow_artifact_hash_mismatch")
        if shadow.get("runtime_feature_parity") != "PASS":
            blockers.append("runtime_feature_parity_did_not_pass")
        if shadow.get("schema_version") != SHADOW_SCHEMA_VERSION:
            blockers.append("shadow_schema_version_mismatch")
        if shadow.get("feature_contract_sha256") != feature_contract_hash:
            blockers.append("shadow_feature_contract_hash_mismatch")
        if not HASH_PATTERN.fullmatch(str(shadow.get("source_sha256") or "")):
            blockers.append("shadow_source_hash_is_invalid")
        return blockers

    @staticmethod
    def _shadow_source_blockers(
        shadow: dict[str, Any],
        source_path: Path,
        artifact_hash: str,
        feature_contract_hash: str,
    ) -> list[str]:
        if not source_path.is_file():
            return ["shadow_source_is_missing"]
        source_hash = _sha256(source_path)
        if shadow.get("source_sha256") != source_hash:
            return ["shadow_source_hash_mismatch"]
        try:
            recomputed = ObservedShadowValidator().validate(
                pd.read_csv(source_path),
                expected_artifact_sha256=artifact_hash,
                expected_feature_contract_sha256=feature_contract_hash,
                source_sha256=source_hash,
            )
        except (OSError, TypeError, ValueError):
            return ["shadow_source_validation_failed"]
        return [] if recomputed == shadow else ["shadow_report_is_not_reproducible"]


def main() -> None:
    """명령행 인자로 운영 승인 증거를 받아 승격 절차를 실행한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--aligned-benchmark", type=Path, required=True)
    parser.add_argument("--shadow-report", type=Path, required=True)
    parser.add_argument("--shadow-source", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approved-at", required=True)
    args = parser.parse_args()
    result = OperationalPromoter().promote(
        args.artifact_dir,
        args.dataset_manifest,
        args.aligned_benchmark,
        args.shadow_report,
        args.shadow_source,
        approved_by=args.approved_by,
        approved_at=args.approved_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
