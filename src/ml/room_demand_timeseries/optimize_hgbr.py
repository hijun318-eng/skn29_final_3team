"""HGBR 후보를 교차검증하고 독립 holdout에서 boosting 계열과 통계 비교한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from xgboost import XGBRegressor

from .hgbr_optimization_support import (
    BASELINE,
    CAPACITY,
    DATE,
    IDENTITY,
    MARGIN,
    TARGET,
    HgbrSpec,
    paired_block_bootstrap,
    restore_prediction,
    transform_target,
)


class HgbrOptimizer:
    """feature 계약, CV, 두 holdout과 bootstrap 증거로 운영 후보 family를 선택한다."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.features = self._features()
        self.output = args.output_dir
        if args.resume:
            if not self.output.is_dir():
                raise ValueError(f"resume output does not exist: {self.output}")
        else:
            self.output.mkdir(parents=True, exist_ok=False)

    def _features(self) -> list[str]:
        contract = json.loads(self.args.feature_contract.read_text(encoding="utf-8"))
        features = contract.get("feature_columns_ordered") or contract.get("feature_columns")
        if not features: raise ValueError("feature contract has no ordered features")
        return list(features)

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _read(self, path: Path) -> pd.DataFrame:
        return pd.read_csv(path, usecols=list(dict.fromkeys(self.features + [TARGET, CAPACITY, DATE])))

    @staticmethod
    def _category_maps(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
        return {
            column: {value: index for index, value in enumerate(sorted(frame[column].astype(str).unique()))}
            for column in ("property_id", "room_type_code")
        }

    def _encode(self, frame: pd.DataFrame, maps: dict[str, dict[str, int]]) -> np.ndarray:
        encoded = frame[self.features].copy()
        for column, mapping in maps.items():
            encoded[column] = encoded[column].astype(str).map(mapping).fillna(-1)
        return encoded.to_numpy(dtype=np.float32)

    def _specs(self) -> list[HgbrSpec]:
        specs = []
        for mode in ("direct", "residual_rooms", "residual_rate", "occupancy_rate"):
            specs.extend([
                HgbrSpec(f"{mode}_squared_base", mode, "squared_error", 240, 0.06, 31, 40, 0.2),
                HgbrSpec(f"{mode}_absolute_base", mode, "absolute_error", 240, 0.06, 31, 40, 0.2),
                HgbrSpec(f"{mode}_squared_wide", mode, "squared_error", 360, 0.04, 63, 50, 0.4),
            ])
        specs.extend([
            HgbrSpec("direct_poisson_base", "direct", "poisson", 240, 0.06, 31, 40, 0.2),
            HgbrSpec("direct_poisson_wide", "direct", "poisson", 360, 0.04, 63, 50, 0.4),
        ])
        return specs

    def _hgbr(self, spec: HgbrSpec) -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(
            loss=spec.loss,
            max_iter=spec.max_iter,
            learning_rate=spec.learning_rate,
            max_leaf_nodes=spec.max_leaf_nodes,
            min_samples_leaf=spec.min_samples_leaf,
            l2_regularization=spec.l2_regularization,
            early_stopping=False,
            random_state=self.args.seed,
        )

    @staticmethod
    def _metrics(actual: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
        error = prediction - actual
        denominator = np.abs(actual).sum()
        return {
            "wape": float(np.abs(error).sum() / denominator),
            "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.mean(error ** 2))),
            "bias": float(error.sum() / denominator),
            "r2": float(1 - np.sum(error ** 2) / np.sum((actual - actual.mean()) ** 2)),
        }

    def _cross_validate(self, frame: pd.DataFrame, maps: dict[str, dict[str, int]]) -> tuple[HgbrSpec, pd.DataFrame]:
        dates = pd.to_datetime(frame[DATE])
        rows = []
        for spec in self._specs():
            fold_wapes, fit_seconds = [], 0.0
            for year in (2021, 2022, 2023):
                train = frame[dates.dt.year < year]
                valid = frame[dates.dt.year == year]
                x_train, x_valid = self._encode(train, maps), self._encode(valid, maps)
                baseline_train = train[BASELINE].to_numpy(dtype=np.float64)
                baseline_valid = valid[BASELINE].to_numpy(dtype=np.float64)
                capacity_train = train[CAPACITY].to_numpy(dtype=np.float64)
                capacity_valid = valid[CAPACITY].to_numpy(dtype=np.float64)
                y_train = train[TARGET].to_numpy(dtype=np.float64)
                y_valid = valid[TARGET].to_numpy(dtype=np.float64)
                transformed = transform_target(spec.mode, y_train, baseline_train, capacity_train)
                model = self._hgbr(spec)
                started = time.perf_counter()
                model.fit(x_train, transformed)
                fit_seconds += time.perf_counter() - started
                prediction = restore_prediction(spec.mode, model.predict(x_valid), baseline_valid, capacity_valid)
                fold_wapes.append(self._metrics(y_valid, prediction)["wape"])
            rows.append({
                **asdict(spec),
                "cv_mean_wape": float(np.mean(fold_wapes)),
                "cv_worst_wape": float(np.max(fold_wapes)),
                "cv_std_wape": float(np.std(fold_wapes)),
                "fold_2021_wape": fold_wapes[0],
                "fold_2022_wape": fold_wapes[1],
                "fold_2023_wape": fold_wapes[2],
                "fit_seconds": fit_seconds,
            })
        results = pd.DataFrame(rows).sort_values(["cv_mean_wape", "cv_worst_wape"]).reset_index(drop=True)
        winner = self._spec_from_row(results.iloc[0])
        return winner, results

    @staticmethod
    def _spec_from_row(row: pd.Series) -> HgbrSpec:
        return HgbrSpec(
            name=str(row["name"]),
            mode=str(row["mode"]),
            loss=str(row["loss"]),
            max_iter=int(row["max_iter"]),
            learning_rate=float(row["learning_rate"]),
            max_leaf_nodes=int(row["max_leaf_nodes"]),
            min_samples_leaf=int(row["min_samples_leaf"]),
            l2_regularization=float(row["l2_regularization"]),
        )

    def _competitors(self) -> dict[str, Any]:
        return {
            "xgboost": XGBRegressor(
                objective="reg:absoluteerror", random_state=self.args.seed, n_jobs=-1, tree_method="hist", verbosity=0,
                n_estimators=650, learning_rate=0.03, max_depth=5, min_child_weight=8,
                subsample=0.9, colsample_bytree=0.9, reg_lambda=1.5,
            ),
            "lightgbm": LGBMRegressor(
                objective="regression_l1", random_state=self.args.seed, n_jobs=-1, deterministic=True,
                force_col_wise=True, verbosity=-1, n_estimators=420, learning_rate=0.05,
                num_leaves=63, min_child_samples=60, reg_lambda=0.5,
            ),
        }

    def _fit_models(self, train: pd.DataFrame, maps: dict[str, dict[str, int]], spec: HgbrSpec) -> dict[str, Any]:
        x = self._encode(train, maps)
        y = train[TARGET].to_numpy(dtype=np.float64)
        baseline = train[BASELINE].to_numpy(dtype=np.float64)
        capacity = train[CAPACITY].to_numpy(dtype=np.float64)
        models = self._competitors()
        models["hgbr"] = self._hgbr(spec)
        fit_seconds = {}
        for name, model in models.items():
            target = transform_target(spec.mode, y, baseline, capacity) if name == "hgbr" else y
            started = time.perf_counter()
            model.fit(x, target)
            fit_seconds[name] = time.perf_counter() - started
        return {"models": models, "fit_seconds": fit_seconds}

    def _predict(self, name: str, model: Any, frame: pd.DataFrame, maps: dict[str, dict[str, int]], mode: str) -> np.ndarray:
        x = self._encode(frame, maps)
        capacity = frame[CAPACITY].to_numpy(dtype=np.float64)
        raw = np.asarray(model.predict(x), dtype=np.float64)
        if name == "hgbr":
            baseline = frame[BASELINE].to_numpy(dtype=np.float64)
            return restore_prediction(mode, raw, baseline, capacity)
        return np.clip(raw, 0, capacity)

    def _holdout(self, directory: Path, split: str) -> pd.DataFrame:
        features = pd.read_csv(directory / f"{split}_features.csv.gz")
        labels = pd.read_csv(directory / f"{split}_labels.csv.gz", usecols=IDENTITY + [TARGET])
        merged = features.merge(labels, on=IDENTITY, validate="one_to_one")
        if len(merged) != len(features) or len(merged) != len(labels):
            raise ValueError(f"holdout identity mismatch: {directory}/{split}")
        return merged

    def run(self) -> dict[str, Any]:
        """HGBR 탐색·경쟁 모델 비교를 실행하고 후보 artifact와 selection JSON을 쓴다.

        resume 증거, feature·label join 또는 estimator 학습이 불완전하면 예외를
        전파하며 ``production_approved``는 이 최적화 단계에서 부여하지 않는다.
        """

        train, validation = self._read(self.args.train), self._read(self.args.validation)
        maps = self._category_maps(train)
        if self.args.resume:
            cv_results = pd.read_csv(self.output / "hgbr_cv_results.csv")
            winner = self._spec_from_row(cv_results.iloc[0])
        else:
            winner, cv_results = self._cross_validate(train, maps)
            cv_results.to_csv(self.output / "hgbr_cv_results.csv", index=False)
        validation_fit = self._fit_models(train, maps, winner)
        validation_metrics = {
            name: self._metrics(
                validation[TARGET].to_numpy(dtype=np.float64),
                self._predict(name, model, validation, maps, winner.mode),
            )
            for name, model in validation_fit["models"].items()
        }
        combined = pd.concat([train, validation], ignore_index=True)
        final_maps = self._category_maps(combined)
        final_fit = self._fit_models(combined, final_maps, winner)
        holdout_results, daily, pooled = {}, {}, {name: [0.0, 0.0] for name in final_fit["models"]}
        for release, directory in {"F": self.args.holdout_f, "G": self.args.holdout_g}.items():
            holdout_results[release] = {}
            for split in ("test_a", "test_b"):
                frame = self._holdout(directory, split)
                actual = frame[TARGET].to_numpy(dtype=np.float64)
                predictions = {
                    name: self._predict(name, model, frame, final_maps, winner.mode)
                    for name, model in final_fit["models"].items()
                }
                metrics = {name: self._metrics(actual, prediction) for name, prediction in predictions.items()}
                holdout_results[release][split] = {"rows": len(frame), "models": metrics}
                for name, prediction in predictions.items():
                    pooled[name][0] += float(np.abs(prediction - actual).sum())
                    pooled[name][1] += float(np.abs(actual).sum())
                temp = pd.DataFrame({"date": frame[DATE], "actual": actual, **predictions})
                grouped = temp.groupby("date", sort=True).apply(
                    lambda part: pd.Series({
                        "denominator": np.abs(part["actual"]).sum(),
                        "hgbr_error": np.abs(part["hgbr"] - part["actual"]).sum(),
                        "xgboost_error": np.abs(part["xgboost"] - part["actual"]).sum(),
                        "lightgbm_error": np.abs(part["lightgbm"] - part["actual"]).sum(),
                    }), include_groups=False,
                )
                daily[f"{release}:{split}"] = grouped.to_numpy()
        pooled_wape = {name: values[0] / values[1] for name, values in pooled.items()}
        bootstrap = {
            "xgboost": paired_block_bootstrap(daily, 2, self.args.seed),
            "lightgbm": paired_block_bootstrap(daily, 3, self.args.seed),
        }
        observed_winner = min(pooled_wape, key=pooled_wape.get)
        strict_winner = observed_winner == "hgbr" and all(result["ci_upper"] < 0 for result in bootstrap.values())
        noninferior = all(result["ci_upper"] <= MARGIN for result in bootstrap.values())
        package = {"model": final_fit["models"]["hgbr"], "feature_columns": self.features, "category_maps": final_maps, "target_mode": winner.mode, "spec": asdict(winner)}
        joblib.dump(package, self.output / "hgbr_candidate.joblib")
        result = {
            "schema_version": "RoomDemandHgbrOptimization.v1",
            "seed": self.args.seed,
            "data_hashes": {"train": self._hash(self.args.train), "validation": self._hash(self.args.validation)},
            "cv_folds": [2021, 2022, 2023],
            "selected_hgbr_spec": asdict(winner),
            "validation_metrics": validation_metrics,
            "final_fit_seconds": final_fit["fit_seconds"],
            "holdouts": holdout_results,
            "pooled_holdout_wape": pooled_wape,
            "bootstrap_hgbr_minus_competitor": bootstrap,
            "observed_accuracy_winner": observed_winner,
            "hgbr_strict_accuracy_winner": strict_winner,
            "hgbr_noninferior": noninferior,
            "selected_operational_family": "hgbr" if noninferior else observed_winner,
            "production_approved": False,
        }
        (self.output / "selection.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def parse_args() -> argparse.Namespace:
    """학습·validation·독립 holdout 경로와 seed·resume CLI 옵션을 파싱한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--holdout-f", type=Path, required=True)
    parser.add_argument("--holdout-g", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    """CLI 최적화를 실행하고 선택 근거 JSON을 표준 출력에 기록한다."""

    print(json.dumps(HgbrOptimizer(parse_args()).run(), indent=2))


if __name__ == "__main__":
    main()
