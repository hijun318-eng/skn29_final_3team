from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
import uuid
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from .config import FEATURES, ProjectConfig
from .onnx_support import OnnxExporter


@dataclass(frozen=True)
class ToolRequest:
    reservation_id: str
    feature_as_of: str
    feature_set_version: str
    input_schema_version: str


class SchemaMismatchError(ValueError):
    pass


class CsvFeatureRepository:
    source = "CSV_SNAPSHOT"

    def __init__(self, config: ProjectConfig, feature_path: Path | None = None):
        self.config = config
        self._frame = pd.read_csv(feature_path or config.inference_csv, low_memory=False)

    def get(self, reservation_id: str, feature_as_of: str) -> pd.DataFrame:
        missing_columns = sorted(set(FEATURES) - set(self._frame.columns))
        if missing_columns:
            raise ValueError(f"reservation feature columns missing: {missing_columns}")
        selected = self._frame[self._frame["reservation_id"].eq(reservation_id)]
        if selected.empty:
            raise LookupError("reservation feature not found")
        if len(selected) != 1:
            raise ValueError("reservation feature must be unique")
        expected = pd.Timestamp(selected.iloc[0]["prediction_cutoff_at"])
        requested = pd.Timestamp(feature_as_of)
        if requested.tzinfo is not None:
            requested = requested.tz_convert("Asia/Seoul").tz_localize(None)
        if requested != expected:
            raise ValueError("feature_as_of does not match stored prediction cutoff")
        feature_frame = selected[FEATURES]
        null_features = feature_frame.columns[feature_frame.isna().any()].tolist()
        if null_features:
            raise ValueError(f"reservation features contain null values: {null_features}")
        return selected


class TrinoFeatureRepository:
    source = "LIVE_TRINO"

    def __init__(
        self,
        config: ProjectConfig,
        url: str,
        user: str,
        password: str,
        ca_file: str,
    ) -> None:
        if not url.startswith("https://"):
            raise ValueError("live Trino feature lookup requires HTTPS")
        if not all((user, password, ca_file)):
            raise ValueError("live Trino credentials and CA file are required")
        self._url = url.rstrip("/")
        self._authorization = "Basic " + b64encode(
            f"{user}:{password}".encode("utf-8")
        ).decode("ascii")
        self._user = user
        self._context = ssl.create_default_context(cafile=ca_file)
        self._query = (
            config.project_dir / "sql" / "reservation_no_show_feature_set_trino_v1.sql"
        ).read_text(encoding="utf-8")

    @classmethod
    def from_environment(cls, config: ProjectConfig) -> "TrinoFeatureRepository":
        return cls(
            config,
            os.getenv("TRINO_URL", ""),
            os.getenv("TRINO_RUNTIME_USER") or os.getenv("TRINO_USER", ""),
            os.getenv("TRINO_RUNTIME_PASSWORD") or os.getenv("TRINO_PASSWORD", ""),
            os.getenv("TRINO_TLS_CA_FILE", ""),
        )

    def get(self, reservation_id: str, feature_as_of: str) -> pd.DataFrame:
        sql = self._query.replace(
            "${RESERVATION_ID}", reservation_id.replace("'", "''")
        ).replace("${FEATURE_AS_OF}", feature_as_of.replace("'", "''"))
        columns: list[str] = []
        rows: list[list[object]] = []
        payload = self._request("POST", f"{self._url}/v1/statement", sql)
        while True:
            error = payload.get("error")
            if isinstance(error, dict):
                raise RuntimeError(str(error.get("message") or "Trino query failed"))
            if payload.get("columns"):
                columns = [str(item["name"]) for item in payload["columns"]]
            rows.extend(payload.get("data") or [])
            next_uri = payload.get("nextUri")
            if not next_uri:
                break
            payload = self._request("GET", str(next_uri))
        if not columns or not rows:
            raise LookupError("reservation feature not found")
        frame = pd.DataFrame(rows, columns=columns)
        if len(frame) != 1:
            raise ValueError("reservation feature must be unique")
        missing = sorted(set(FEATURES) - set(frame.columns))
        if missing:
            raise ValueError(f"reservation feature columns missing: {missing}")
        null_features = frame[FEATURES].columns[frame[FEATURES].isna().any()].tolist()
        if null_features:
            raise ValueError(f"reservation features contain null values: {null_features}")
        return frame

    def _request(self, method: str, url: str, body: str | None = None) -> dict:
        request = Request(
            url,
            data=body.encode("utf-8") if body is not None else None,
            headers={
                "Authorization": self._authorization,
                "Content-Type": "text/plain; charset=utf-8",
                "X-Trino-User": self._user,
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=10, context=self._context) as response:
                return json.loads(response.read())
        except HTTPError as error:
            raise RuntimeError(f"Trino HTTP {error.code}") from error
        except (TimeoutError, URLError) as error:
            raise RuntimeError("Trino request failed") from error


class NoShowToolService:
    input_schema_version = "reservation-no-show-input-v1.0"

    def __init__(
        self,
        config: ProjectConfig,
        feature_path: Path | None = None,
        repository: CsvFeatureRepository | TrinoFeatureRepository | None = None,
    ):
        self.config = config
        self.repository = repository or CsvFeatureRepository(config, feature_path)
        self.metadata = json.loads(
            (config.artifacts_dir / "model_metadata.json").read_text(encoding="utf-8")
        )
        self.model_path = config.model_dir / "reservation_no_show_model.onnx"
        expected_hash = self.metadata.get("onnx_sha256")
        actual_hash = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
        if not expected_hash or actual_hash != expected_hash:
            raise RuntimeError("No-show model artifact integrity check failed")
        self.runtime = OnnxExporter()
        self.ranking = (
            pd.read_csv(
                config.artifacts_dir / "inference_predictions.csv", low_memory=False
            ).set_index("reservation_id")
            if isinstance(self.repository, CsvFeatureRepository)
            else None
        )

    def execute(self, request: ToolRequest) -> dict:
        started = time.perf_counter()
        base = {
            "reservation_id": request.reservation_id,
            "feature_as_of": request.feature_as_of,
            "model_name": self.metadata["model_name"],
            "model_version": self.config.model_version,
            "feature_set_version": self.config.feature_set_version,
            "input_schema_version": self.input_schema_version,
            "execution_id": f"mlrun-{uuid.uuid4()}",
        }
        try:
            self._validate(request)
            row = self.repository.get(request.reservation_id, request.feature_as_of)
            probability = float(
                self.runtime.predict_probability(self.model_path, row[FEATURES])[0]
            )
            threshold = float(self.metadata["threshold"])
            ranking = self.ranking.loc[request.reservation_id] if self.ranking is not None else None
            if isinstance(ranking, pd.DataFrame):
                raise ValueError("reservation ranking must be unique")
            result = {
                **base,
                "no_show_probability": probability,
                "risk_level": (
                    str(ranking["risk_level"])
                    if ranking is not None
                    else ("HIGH" if probability >= threshold else "LOW")
                ),
                "risk_rank": int(ranking["risk_rank"]) if ranking is not None else None,
                "cohort_size": int(ranking["cohort_size"]) if ranking is not None else None,
                "ranking_policy": (
                    "TOP_15_PERCENT_DAILY_COHORT"
                    if ranking is not None
                    else "SINGLE_LIVE_PREDICTION"
                ),
                "threshold": threshold,
                "prediction_status": "SUCCESS",
                "error_message": None,
                "is_synthetic": bool(row.iloc[0]["is_synthetic"]),
                "display_label": "모델 예측 · 합성 데이터 기반 예측",
                "feature_source": self.repository.source,
            }
        except LookupError as error:
            result = self._error(base, "FEATURE_NOT_FOUND", error)
        except SchemaMismatchError as error:
            result = self._error(base, "SCHEMA_MISMATCH", error)
        except ValueError as error:
            result = self._error(base, "INVALID_INPUT", error)
        except Exception as error:  # pragma: no cover - defensive service boundary
            result = self._error(base, "MODEL_ERROR", error)
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def execute_arguments(self, arguments: dict) -> dict:
        return self.execute(ToolRequest(**arguments))

    def _validate(self, request: ToolRequest) -> None:
        if not request.reservation_id.strip():
            raise ValueError("reservation_id is required")
        if request.feature_set_version != self.config.feature_set_version:
            raise SchemaMismatchError("feature_set_version mismatch")
        if request.input_schema_version != self.input_schema_version:
            raise SchemaMismatchError("input_schema_version mismatch")
        try:
            parsed = pd.Timestamp(request.feature_as_of)
        except (TypeError, ValueError) as error:
            raise ValueError("feature_as_of must be RFC3339 timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError("feature_as_of timezone is required")

    @staticmethod
    def _error(base: dict, status: str, error: Exception) -> dict:
        public_message = {
            "FEATURE_NOT_FOUND": "requested features were not found",
            "SCHEMA_MISMATCH": "input schema or feature set version is incompatible",
            "INVALID_INPUT": "request input is invalid",
            "MODEL_ERROR": "model execution failed",
        }.get(status, "model execution failed")
        return {
            **base,
            "no_show_probability": None,
            "risk_level": None,
            "risk_rank": None,
            "cohort_size": None,
            "ranking_policy": "TOP_15_PERCENT_DAILY_COHORT",
            "threshold": None,
            "prediction_status": status,
            "error_message": public_message,
            "is_synthetic": True,
            "display_label": "모델 예측 오류",
        }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
