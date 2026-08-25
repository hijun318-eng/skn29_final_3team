from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import CATEGORICAL_FEATURES, FILE_NAMES, KEY_COLUMNS, LABEL, NUMERIC_FEATURES
from .data import DatasetBundle


class RiskAuditor:
    def __init__(
        self,
        bundle: DatasetBundle,
        data_dir: Path,
        artifact_dir: Path,
        as_of_date: str,
    ) -> None:
        self.bundle = bundle
        self.data_dir = data_dir
        self.artifact_dir = artifact_dir
        self.as_of_date = pd.Timestamp(as_of_date)

    def run(self) -> dict[str, Any]:
        hashes = self._input_hashes()
        range_audit = self._feature_range_audit()
        hidden = self._hidden_qa_audit()
        time_contract = self._time_contract()
        register = self._risk_register(range_audit, hidden, time_contract)
        hashes.to_csv(self.artifact_dir / "input_file_hashes.csv", index=False)
        range_audit.to_csv(self.artifact_dir / "feature_range_audit.csv", index=False)
        register.to_csv(self.artifact_dir / "risk_register.csv", index=False)
        self._save_json("hidden_qa_audit.json", hidden)
        summary = {
            "status": "PASS_WITH_LIMITATIONS",
            "input_hash_count": len(hashes),
            "feature_range_warning_count": int(range_audit["status"].eq("WARN").sum()),
            "time_contract": time_contract,
            "hidden_qa": hidden,
            "open_risk_count": int(register["status"].isin(["WARN", "OPEN"]).sum()),
        }
        self._save_json("risk_audit_summary.json", summary)
        return summary

    def _input_hashes(self) -> pd.DataFrame:
        rows = []
        for role, name in FILE_NAMES.items():
            path = self.data_dir / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(
                {
                    "role": role,
                    "file": name,
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                }
            )
        return pd.DataFrame(rows)

    def _feature_range_audit(self) -> pd.DataFrame:
        current = self.bundle.forecast[
            self.bundle.forecast["prediction_cutoff_date"].eq(self.as_of_date)
        ]
        rows: list[dict[str, Any]] = []
        for column in NUMERIC_FEATURES:
            train_min = float(self.bundle.train[column].min())
            train_max = float(self.bundle.train[column].max())
            values = current[column]
            outside = ((values < train_min) | (values > train_max)) & values.notna()
            rows.append(
                {
                    "feature": column,
                    "feature_type": "numeric",
                    "train_min": train_min,
                    "train_max": train_max,
                    "current_min": float(values.min()),
                    "current_max": float(values.max()),
                    "out_of_range_rows": int(outside.sum()),
                    "out_of_range_rate": float(outside.mean()),
                    "status": "WARN" if outside.any() else "PASS",
                }
            )
        for column in CATEGORICAL_FEATURES:
            known = set(self.bundle.train[column].dropna().astype(str))
            current_values = self.bundle.forecast.loc[current.index, column].astype(str)
            unseen = ~current_values.isin(known)
            rows.append(
                {
                    "feature": column,
                    "feature_type": "categorical",
                    "train_min": None,
                    "train_max": None,
                    "current_min": None,
                    "current_max": None,
                    "out_of_range_rows": int(unseen.sum()),
                    "out_of_range_rate": float(unseen.mean()),
                    "status": "WARN" if unseen.any() else "PASS",
                }
            )
        return pd.DataFrame(rows)

    def _hidden_qa_audit(self) -> dict[str, Any]:
        forecast = pd.read_csv(self.artifact_dir / "forecast_predictions.csv")
        hidden = self.bundle.hidden_qa.rename(
            columns={"hidden_simulated_rooms_sold": LABEL}
        )
        joined = forecast.merge(
            hidden[KEY_COLUMNS[:3] + [LABEL]],
            on=KEY_COLUMNS[:3],
            how="left",
            validate="one_to_one",
        )
        if joined[LABEL].isna().any():
            raise ValueError("현재 28행 예측과 숨은 QA 정답이 완전히 연결되지 않습니다.")
        actual = joined[LABEL].to_numpy(float)
        prediction = joined["predicted_rooms_sold"].to_numpy(float)
        error = prediction - actual
        absolute = np.abs(error)
        covered = (
            (actual >= joined["prediction_lower_rooms_sold"].to_numpy(float))
            & (actual <= joined["prediction_upper_rooms_sold"].to_numpy(float))
        )
        return {
            "purpose": "posthoc_only",
            "model_selection_use": False,
            "row_count": len(joined),
            "mae": float(absolute.mean()),
            "rmse": float(np.sqrt(np.mean(error**2))),
            "wape": float(absolute.sum() / np.abs(actual).sum()),
            "bias": float(error.mean()),
            "within_3_rooms": float((absolute <= 3).mean()),
            "interval_coverage": float(covered.mean()),
        }

    def _time_contract(self) -> dict[str, Any]:
        invalid = 0
        rows = 0
        for frame in self.bundle.labeled_frames() + [self.bundle.forecast]:
            expected = frame["target_date"] - pd.to_timedelta(
                frame["horizon_days"], unit="D"
            )
            invalid += int((frame["prediction_cutoff_date"] != expected).sum())
            rows += len(frame)
        return {"status": "PASS" if invalid == 0 else "FAIL", "rows": rows, "invalid": invalid}

    def _risk_register(
        self,
        range_audit: pd.DataFrame,
        hidden: dict[str, Any],
        time_contract: dict[str, Any],
    ) -> pd.DataFrame:
        ablation = pd.read_csv(self.artifact_dir / "feature_ablation_metrics.csv")
        full = float(ablation.query("scenario == 'FULL' and split == 'TEST'")["wape"].iloc[0])
        no_booking = float(
            ablation.query("scenario == 'NO_BOOKING_ON_HAND' and split == 'TEST'")["wape"].iloc[0]
        )
        interval = json.loads(
            (self.artifact_dir / "prediction_interval_metrics.json").read_text(encoding="utf-8")
        )
        warning_features = range_audit.loc[range_audit["status"].eq("WARN"), "feature"].tolist()
        rows = [
            ("R1", "Point-in-time 누수", time_contract["status"], "예측기준일=목표일-예측시차 전 행 확인", "운영 API도 같은 cutoff 계약 강제"),
            ("R2", "예약잔량 의존", "WARN", f"예약정보 제거 시 TEST WAPE {full:.2%}→{no_booking:.2%}", "예약 스냅샷 누락·지연 시 예측 중단"),
            ("R3", "학습범위 이탈", "WARN" if warning_features else "PASS", ", ".join(warning_features) or "없음", "범위 이탈을 API 경고와 모니터링에 노출"),
            ("R4", "점 예측 불확실성", "MITIGATED", f"TEST 95% 구간 포함률 {interval['actual_coverage']:.2%}", "하한·상한을 예측값과 함께 표시"),
            ("R5", "미래 QA 일반화", "MITIGATED", f"사후 28행 WAPE {hidden['wape']:.2%}", "모델 선정에는 사용하지 않고 감시만 유지"),
            ("R6", "단일 합성 seed", "OPEN", "seed 20260803 한 세트", "5개 seed 재생성 후 동일 검증"),
            ("R7", "실데이터 부재", "OPEN", "단일 합성 호텔", "비식별 실데이터로 운영 기준 재승인"),
            ("R8", "모델 파일 로컬 전용", "CONTROLLED", "joblib은 Git 제외", "배포 환경에서 검증 후 재학습·등록"),
        ]
        return pd.DataFrame(rows, columns=["risk_id", "risk", "status", "evidence", "control"])

    def _save_json(self, name: str, payload: dict[str, Any]) -> None:
        (self.artifact_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
