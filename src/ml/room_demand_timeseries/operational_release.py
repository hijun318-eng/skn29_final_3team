"""운영형 객실 수요 후보의 실행 계약과 조건부 승인 증거를 동결한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import CATEGORICAL_FEATURES
from .operational_contracts import (
    OPERATIONAL_FEATURE_COLUMNS,
    OPERATIONAL_FEATURE_PROFILE,
    OPERATIONAL_MAX_HORIZON,
    OPERATIONAL_MODEL_VERSION,
    OPERATIONAL_NUMERIC_FEATURES,
    SIGNAL_PROVENANCE_COLUMNS,
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_operational_feature_contract() -> dict[str, Any]:
    """학습·benchmark·runtime이 공유하는 운영 특징 계약을 반환한다."""

    return {
        "feature_version": "room-demand-point-in-time-d1-d7-v4.0.0",
        "feature_profile": OPERATIONAL_FEATURE_PROFILE,
        "model_version": OPERATIONAL_MODEL_VERSION,
        "target": "target_occupancy_rate",
        "capacity_denominator": "target_sellable_rooms",
        "grain": [
            "property_id",
            "target_date",
            "room_type_code",
            "horizon_days",
        ],
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": OPERATIONAL_NUMERIC_FEATURES,
        "feature_columns_ordered": OPERATIONAL_FEATURE_COLUMNS,
        "signal_source_required": True,
        "signal_provenance_required": True,
        "signal_provenance_columns": SIGNAL_PROVENANCE_COLUMNS,
        "production_signal_source_kind": "OBSERVED_PIT",
        "blocked_features": [
            "target_rooms_sold",
            "future_occupancy",
            "future_adr",
            "future_revpar",
            "future_cancellation",
            "future_no_show",
            "generation_seed",
            "simulation_world_id",
            "dataset_split",
            "label_available",
        ],
        "max_horizon": OPERATIONAL_MAX_HORIZON,
    }


def freeze_operational_release(artifact_dir: Path) -> dict[str, str]:
    """후보 품질 증거를 확인하고 실행 계약·승인서·체크섬을 동결한다."""

    manifest = _read(artifact_dir / "model_manifest.json")
    comparison = _read(artifact_dir / "evaluation" / "release_comparison.json")
    rolling = _read(
        artifact_dir / "evaluation" / "recent_rolling_validation.json"
    )
    if manifest["model_version"] != OPERATIONAL_MODEL_VERSION:
        raise ValueError("operational model version does not match source contract")
    if manifest["feature_columns"] != OPERATIONAL_FEATURE_COLUMNS:
        raise ValueError("operational feature order does not match model manifest")
    artifact_hash = _sha256(artifact_dir / "model.joblib")
    if artifact_hash != manifest["artifact_sha256"]:
        raise ValueError("operational model artifact hash changed")
    gates_pass = bool(comparison["candidate_release_approved_on_synthetic_holdout"])
    rolling_pass = bool(
        rolling["summary"]["all_folds_better_than_baseline"]
        and rolling["summary"]["all_horizons_better_than_baseline"]
        and rolling["summary"]["all_properties_better_than_baseline"]
    )
    if not gates_pass or not rolling_pass:
        raise ValueError("operational release quality gates did not pass")
    feature_contract = build_operational_feature_contract()
    approval = {
        "decision": "CONDITIONAL_PASS",
        "final_decision": "CONDITIONAL_PASS",
        "approval_status": "VALIDATED_SYNTHETIC",
        "model_version": OPERATIONAL_MODEL_VERSION,
        "artifact_sha256": artifact_hash,
        "feature_version": feature_contract["feature_version"],
        "runtime_feature_parity": "PASS",
        "holdout_comparison": comparison,
        "rolling_origin_summary": rolling["summary"],
        "data_is_synthetic": True,
        "production_approved": False,
        "human_approved_by": None,
        "human_approved_at": None,
        "limitations": [
            "합성 데이터 조건부 검증이며 실제 호텔 정확도 증거가 아니다.",
            "1일 전 예약 잔량이 최종 판매량과 같은 합성 데이터 특성이 있어 운영 자료 재검증이 필요하다.",
            "목표일 재고·행사의 과거 snapshot 시각이 증명되지 않아 현재 신호 view는 운영에서 차단된다.",
            "사람의 최종 운영 승인이 기록되지 않았다.",
        ],
    }
    _write(artifact_dir / "feature_contract.json", feature_contract)
    _write(artifact_dir / "model.approval.json", approval)
    model_card = f"""# 객실 수요 예측 모델 {OPERATIONAL_MODEL_VERSION}

## 용도

그랜드 워커힐 서울, 비스타 워커힐 서울, 더글러스 하우스의 객실 유형별 판매량을 1일부터 7일 뒤까지 예측한다. 목표일 판매 가능 객실을 분모로 사용한다.

## 모델과 입력

- 모델: 히스토그램 기반 그래디언트 부스팅 회귀
- 주요 입력: 목표일 동일 요일 실적, 예약 잔량, 최근 예약 증가, 취소, 연회 연계 예약, 행사, 판매중지 객실
- 출력: 예상 판매 객실, 80%·95% 예측 범위, 주요 영향 요인, 객실 유형별 검증 상태

## 합성 데이터 검증 결과

- 보유기간 가중 절대 오차율: {comparison['new_metrics']['wape'] * 100:.2f}%
- 기존 2.2 모델 가중 절대 오차율: {comparison['old_metrics']['wape'] * 100:.2f}%
- 6개월 순차 검증 평균 가중 절대 오차율: {rolling['summary']['mean_wape'] * 100:.2f}%
- 80% 예측 범위 적중률: {comparison['interval_coverage']['coverage_80'] * 100:.2f}%
- 95% 예측 범위 적중률: {comparison['interval_coverage']['coverage_95'] * 100:.2f}%

## 승인 상태와 한계

합성 데이터 조건부 검증만 통과했다. 실제 호텔 운영 승인은 아니다. 합성 자료에서 1일 전 예약 잔량이 최종 판매량과 같은 특성이 있어 실제 운영 자료 3~6개월 순차 검증과 사람의 최종 승인이 필요하다. 승인되지 않은 객실 유형이 하나라도 있으면 실행이 차단된다.
"""
    (artifact_dir / "model_card.md").write_text(model_card, encoding="utf-8")
    files = [
        "model.joblib",
        "model_manifest.json",
        "selection_trials.json",
        "feature_contract.json",
        "model.approval.json",
        "model_card.md",
        "evaluation/release_comparison.json",
        "evaluation/recent_rolling_validation.json",
        "evaluation/test_by_horizon.csv",
        "evaluation/test_by_property.csv",
        "evaluation/test_by_room_type.csv",
    ]
    checksums = {name: _sha256(artifact_dir / name) for name in files}
    _write(artifact_dir / "checksums.sha256.json", checksums)
    return checksums


def main() -> None:
    """지정한 후보 폴더를 검증하고 조건부 승인 산출물을 생성한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            freeze_operational_release(args.artifact_dir),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
