from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .config import (
    BOOLEAN_FEATURES,
    CATEGORICAL_FEATURES,
    EXPECTED_SPLITS,
    FEATURES,
    FILE_NAMES,
    KEY_COLUMNS,
    LABEL,
    NUMERIC_FEATURES,
    SEED,
)


@dataclass(frozen=True)
class QualityCheck:
    check: str
    status: str
    evidence: str
    severity: str = "Critical"


@dataclass
class DatasetBundle:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    forecast: pd.DataFrame
    hidden_qa: pd.DataFrame
    manifest: pd.DataFrame

    def labeled_frames(self) -> list[pd.DataFrame]:
        return [self.train, self.validation, self.test]


class DatasetRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def load(self) -> DatasetBundle:
        missing = [name for name in FILE_NAMES.values() if not (self.data_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"필수 CSV 누락: {missing}")
        frames = {
            name: pd.read_csv(self.data_dir / filename, low_memory=False)
            for name, filename in FILE_NAMES.items()
        }
        for name in ("train", "validation", "test", "forecast"):
            frames[name] = self._prepare_types(frames[name])
        return DatasetBundle(**frames)

    @staticmethod
    def _prepare_types(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        for column in ("target_date", "prediction_cutoff_date"):
            if column in result:
                result[column] = pd.to_datetime(result[column], errors="raise")
        if "prediction_cutoff_at_utc" in result:
            result["prediction_cutoff_at_utc"] = pd.to_datetime(
                result["prediction_cutoff_at_utc"], errors="raise", utc=True
            )
        mapping = {
            "true": 1, "t": 1, "1": 1, "yes": 1, "y": 1,
            "false": 0, "f": 0, "0": 0, "no": 0, "n": 0,
        }
        for column in BOOLEAN_FEATURES:
            if column in result:
                normalized = result[column].astype("string").str.strip().str.lower()
                result[column] = pd.to_numeric(normalized.map(mapping), errors="coerce")
        for column in CATEGORICAL_FEATURES:
            if column in result:
                result[column] = result[column].astype("string")
        for column in NUMERIC_FEATURES + [LABEL]:
            if column in result and column not in BOOLEAN_FEATURES:
                result[column] = pd.to_numeric(result[column], errors="coerce")
        return result


class DataContractValidator:
    def validate(self, bundle: DatasetBundle) -> list[QualityCheck]:
        checks: list[QualityCheck] = []
        required = set(KEY_COLUMNS + FEATURES + [LABEL, "dataset_split"])
        for name in EXPECTED_SPLITS:
            frame = getattr(bundle, name)
            missing = sorted(required - set(frame.columns))
            self._add(checks, f"{name}.required_columns", not missing, f"missing={missing}")
            if missing:
                continue
            duplicate_count = int(frame.duplicated(KEY_COLUMNS).sum())
            self._add(checks, f"{name}.grain_unique", duplicate_count == 0, f"duplicates={duplicate_count}")
            invalid_horizon = int((~frame["horizon_days"].between(1, 7)).sum())
            self._add(checks, f"{name}.horizon", invalid_horizon == 0, f"invalid={invalid_horizon}")
            self._validate_split(name, frame, checks)
            self._validate_dates(name, frame, checks)
            self._validate_features(name, frame, checks)
        self._validate_labels(bundle, checks)
        self._validate_synthetic_seed(bundle, checks)
        self._validate_manifest(bundle, checks)
        self._validate_hidden_qa(bundle, checks)
        return checks

    @staticmethod
    def _add(checks: list[QualityCheck], name: str, passed: bool, evidence: str, severity: str = "Critical") -> None:
        checks.append(QualityCheck(name, "PASS" if passed else "FAIL", evidence, severity))

    def _validate_split(self, name: str, frame: pd.DataFrame, checks: list[QualityCheck]) -> None:
        expected = EXPECTED_SPLITS[name][0]
        actual = sorted(frame["dataset_split"].dropna().astype(str).str.upper().unique())
        self._add(checks, f"{name}.split", actual == [expected], f"expected={expected}; actual={actual}")

    def _validate_dates(self, name: str, frame: pd.DataFrame, checks: list[QualityCheck]) -> None:
        expected_start, expected_end = EXPECTED_SPLITS[name][1:]
        actual_start = frame["target_date"].min().strftime("%Y-%m-%d")
        actual_end = frame["target_date"].max().strftime("%Y-%m-%d")
        self._add(
            checks,
            f"{name}.date_range",
            (actual_start, actual_end) == (expected_start, expected_end),
            f"expected={expected_start}..{expected_end}; actual={actual_start}..{actual_end}",
        )
        if "prediction_cutoff_date" in frame:
            delta = (frame["target_date"] - frame["prediction_cutoff_date"]).dt.days
            invalid = int((delta != frame["horizon_days"]).sum())
            self._add(checks, f"{name}.point_in_time", invalid == 0, f"invalid={invalid}")

    def _validate_features(self, name: str, frame: pd.DataFrame, checks: list[QualityCheck]) -> None:
        null_all = sorted(column for column in FEATURES if frame[column].isna().all())
        self._add(checks, f"{name}.feature_population", not null_all, f"all_null={null_all}", "High")
        numeric = frame[NUMERIC_FEATURES].apply(pd.to_numeric, errors="coerce")
        infinite = int(np.isinf(numeric.to_numpy(dtype=float)).sum())
        self._add(checks, f"{name}.finite_numeric", infinite == 0, f"infinite={infinite}", "High")

    def _validate_labels(self, bundle: DatasetBundle, checks: list[QualityCheck]) -> None:
        for name, frame in zip(("train", "validation", "test"), bundle.labeled_frames()):
            nulls = int(frame[LABEL].isna().sum())
            negative = int((frame[LABEL] < 0).sum())
            over_capacity = int((frame[LABEL] > frame["available_room_nights"]).sum())
            fractional = int((frame[LABEL].dropna() % 1 != 0).sum())
            self._add(checks, f"{name}.label_valid", not (nulls or negative or over_capacity or fractional), f"null={nulls}; negative={negative}; over_capacity={over_capacity}; fractional={fractional}")
        forecast_labels = int(bundle.forecast[LABEL].notna().sum())
        self._add(checks, "forecast.label_hidden", forecast_labels == 0, f"non_null={forecast_labels}")

    def _validate_synthetic_seed(self, bundle: DatasetBundle, checks: list[QualityCheck]) -> None:
        for name in EXPECTED_SPLITS:
            frame = getattr(bundle, name)
            if "is_synthetic" in frame:
                values = set(frame["is_synthetic"].astype(str).str.lower())
                self._add(checks, f"{name}.synthetic", values <= {"true", "1", "t"}, f"values={sorted(values)}")
            if "generation_seed" in frame:
                seeds = set(pd.to_numeric(frame["generation_seed"], errors="coerce").dropna())
                self._add(checks, f"{name}.seed", seeds == {SEED}, f"values={sorted(seeds)}")
        seed_columns = [column for column in ("generation_seed", "ml_generation_seed", "seed") if column in bundle.manifest]
        values = set()
        for column in seed_columns:
            values.update(pd.to_numeric(bundle.manifest[column], errors="coerce").dropna())
        self._add(checks, "manifest.seed", values == {SEED}, f"columns={seed_columns}; values={sorted(values)}")

    def _validate_hidden_qa(self, bundle: DatasetBundle, checks: list[QualityCheck]) -> None:
        label_column = "hidden_simulated_rooms_sold"
        label_present = label_column in bundle.hidden_qa and bundle.hidden_qa[label_column].notna().all()
        purpose_valid = (
            "purpose" in bundle.hidden_qa
            and set(bundle.hidden_qa["purpose"].dropna().astype(str))
            == {"SIMULATED_FUTURE_GROUND_TRUTH_FOR_QA_ONLY"}
        )
        evidence = f"rows={len(bundle.hidden_qa)}; label_column={label_column}; qa_purpose={purpose_valid}"
        self._add(checks, "hidden_qa.separate_file", bool(label_present and purpose_valid), evidence, "High")

    def _validate_manifest(self, bundle: DatasetBundle, checks: list[QualityCheck]) -> None:
        manifest = bundle.manifest.copy()
        required = {"object_name", "row_count", "min_business_date", "max_business_date", "checksum"}
        missing = sorted(required - set(manifest.columns))
        self._add(checks, "manifest.required_columns", not missing, f"missing={missing}")
        if missing:
            return
        for name in ("train", "validation", "test", "forecast", "hidden_qa"):
            frame = getattr(bundle, name)
            object_name = Path(FILE_NAMES[name]).stem
            rows = manifest[manifest["object_name"].eq(object_name)]
            expected_dates = (
                frame["target_date"].astype(str).min()[:10],
                frame["target_date"].astype(str).max()[:10],
            )
            valid = (
                len(rows) == 1
                and int(rows.iloc[0]["row_count"]) == len(frame)
                and str(rows.iloc[0]["min_business_date"])[:10] == expected_dates[0]
                and str(rows.iloc[0]["max_business_date"])[:10] == expected_dates[1]
            )
            evidence = f"object={object_name}; manifest_rows={len(rows)}; csv_rows={len(frame)}; dates={expected_dates[0]}..{expected_dates[1]}"
            self._add(checks, f"manifest.{name}", bool(valid), evidence)
        checksum_valid = manifest["checksum"].astype(str).map(lambda value: bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))).all()
        self._add(checks, "manifest.checksum_format", bool(checksum_valid), f"rows={len(manifest)}", "High")
        for column in ("schema_version", "scenario_version", "fixture_version"):
            values = sorted(manifest[column].dropna().astype(str).unique()) if column in manifest else []
            self._add(checks, f"manifest.{column}", len(values) == 1, f"values={values}", "High")

    @staticmethod
    def to_frame(checks: list[QualityCheck]) -> pd.DataFrame:
        return pd.DataFrame([asdict(check) for check in checks])

    @staticmethod
    def raise_for_failures(checks: list[QualityCheck]) -> None:
        failed = [check for check in checks if check.status == "FAIL"]
        if failed:
            names = ", ".join(check.check for check in failed)
            raise ValueError(f"CSV 계약검사 실패: {names}")
