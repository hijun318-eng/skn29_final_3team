"""정렬 benchmark에서 선택된 v4 모델을 운영 승인 대기 artifact로 묶는다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import joblib

from .operational_contracts import (
    OPERATIONAL_FEATURE_COLUMNS,
    OPERATIONAL_FEATURE_PROFILE,
    OPERATIONAL_MAX_HORIZON,
    OPERATIONAL_MODEL_VERSION,
)
from .operational_release import build_operational_feature_contract


class CandidateArtifactWriter:
    """모델·manifest·특징계약·benchmark를 한 폴더에 재현 가능하게 기록한다."""

    def write(
        self,
        output_dir: Path,
        report: dict[str, Any],
        models: Mapping[str, Any],
        dataset_manifest: Mapping[str, Any],
        *,
        selected_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        """선정 모델과 비교 보고서를 checksum으로 연결해 후보 폴더에 저장한다."""

        output_dir.mkdir(parents=True, exist_ok=False)
        model_hashes = {}
        for name, model in models.items():
            filename = (
                "model.joblib"
                if name == "operational_ablation"
                else f"{name}.joblib"
            )
            path = output_dir / filename
            joblib.dump(model, path)
            model_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        report["model_artifact_sha256"] = model_hashes
        candidate = models["operational_ablation"]
        manifest = {
            "model_version": OPERATIONAL_MODEL_VERSION,
            "model_type": "operational-point-in-time-hgbr",
            "feature_profile": OPERATIONAL_FEATURE_PROFILE,
            "max_horizon": OPERATIONAL_MAX_HORIZON,
            "feature_columns": OPERATIONAL_FEATURE_COLUMNS,
            "selected_config": dict(selected_config),
            "validation": report["equal_budget_feature_ablation"][
                "candidate_validation"
            ],
            "quality_scope": candidate.quality_scope,
            "interval_quantiles": candidate.interval_quantiles,
            "training_rows": int(
                report["aligned_contract"]["splits"]["TRAIN"]["rows"]
                + report["aligned_contract"]["splits"]["VALIDATION"]["rows"]
            ),
            "source_dataset_sha256": dataset_manifest["source_sha256"],
            "signal_dataset_sha256": dataset_manifest["signal_sha256"],
            "artifact_sha256": model_hashes["operational_ablation"],
            "synthetic_training_data": bool(dataset_manifest["synthetic_only"]),
            "production_approved": False,
        }
        payloads = {
            "model_manifest.json": manifest,
            "feature_contract.json": build_operational_feature_contract(),
            "aligned_benchmark.json": report,
        }
        for filename, payload in payloads.items():
            (output_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return manifest
