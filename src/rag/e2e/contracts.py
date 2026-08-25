from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class E2EConfigurationError(ValueError):
    """Raised when a required real runtime configuration value is unavailable."""


class E2EStage(str, Enum):
    INITIALIZED = "INITIALIZED"
    ANALYSIS = "ANALYSIS"
    RAG_SEARCH = "RAG_SEARCH"
    RAG_ANSWER = "RAG_ANSWER"
    ML_HEALTH = "ML_HEALTH"
    ML_PREDICTION = "ML_PREDICTION"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RuntimeEndpoint:
    name: str
    base_url: str
    health_path: str

    @property
    def health_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.health_path}"


@dataclass(frozen=True)
class DynamicE2EConfig:
    analysis: RuntimeEndpoint
    rag: RuntimeEndpoint
    ml: RuntimeEndpoint
    rag_search_path: str
    rag_answer_path: str
    analysis_path: str
    ml_predict_path: str
    rag_gateway_secret: str
    request_id: str
    trace_id: str
    analysis_auth_token: str
    analysis_as_of: str
    analysis_contract_version: str
    user_id: str
    role: str
    timezone_name: str
    analysis_question: str
    rag_query: str
    ml_metric: str
    ml_hotel_scope: str
    ml_horizon: int
    top_k: int
    output_dir: Path
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "DynamicE2EConfig":
        def required(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                raise E2EConfigurationError(f"Missing required environment variable: {name}")
            return value

        def positive_int(name: str, default: int) -> int:
            raw = os.getenv(name, str(default)).strip()
            try:
                value = int(raw)
            except ValueError as error:
                raise E2EConfigurationError(f"{name} must be an integer") from error
            if value < 1:
                raise E2EConfigurationError(f"{name} must be greater than zero")
            return value

        def positive_float(name: str, default: float) -> float:
            raw = os.getenv(name, str(default)).strip()
            try:
                value = float(raw)
            except ValueError as error:
                raise E2EConfigurationError(f"{name} must be numeric") from error
            if value <= 0:
                raise E2EConfigurationError(f"{name} must be greater than zero")
            return value

        def required_positive_int(name: str) -> int:
            raw = required(name)
            try:
                value = int(raw)
            except ValueError as error:
                raise E2EConfigurationError(f"{name} must be an integer") from error
            if value < 1:
                raise E2EConfigurationError(f"{name} must be greater than zero")
            return value

        output_dir = Path(os.getenv("DYNAMIC_E2E_OUTPUT_DIR", "evals/runs/rag/e2e")).expanduser().resolve()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise E2EConfigurationError(f"DYNAMIC_E2E_OUTPUT_DIR is not writable: {output_dir}") from error
        request_id = os.getenv("DYNAMIC_E2E_REQUEST_ID", str(uuid4())).strip()
        trace_id = os.getenv("DYNAMIC_E2E_TRACE_ID", request_id).strip()
        return cls(
            analysis=RuntimeEndpoint(
                name="analysis-core",
                base_url=required("ANALYSIS_E2E_BASE_URL"),
                health_path=os.getenv("ANALYSIS_E2E_HEALTH_PATH", "/health"),
            ),
            rag=RuntimeEndpoint(
                name="rag",
                base_url=required("RAG_E2E_BASE_URL"),
                health_path=os.getenv("RAG_E2E_HEALTH_PATH", "/health/ready"),
            ),
            ml=RuntimeEndpoint(
                name="ml",
                base_url=required("ML_E2E_BASE_URL"),
                health_path=os.getenv("ML_E2E_HEALTH_PATH", "/health"),
            ),
            rag_search_path=os.getenv("RAG_E2E_SEARCH_PATH", "/v1/tools/internal-manual-search"),
            rag_answer_path=os.getenv("RAG_E2E_ANSWER_PATH", "/v1/tools/internal-manual-answer"),
            analysis_path=os.getenv("ANALYSIS_E2E_PATH", "/analysis"),
            ml_predict_path=os.getenv("ML_E2E_PREDICT_PATH", "/v1/predictions"),
            rag_gateway_secret=required("RAG_GATEWAY_HMAC_SECRET"),
            request_id=request_id,
            trace_id=trace_id,
            analysis_auth_token=os.getenv("DYNAMIC_E2E_AUTH_TOKEN", "e2e-token").strip(),
            analysis_as_of=os.getenv("DYNAMIC_E2E_AS_OF", date.today().isoformat()).strip(),
            analysis_contract_version=os.getenv("DYNAMIC_E2E_CONTRACT_VERSION", "OPENAPI-v1.0.0").strip(),
            user_id=required("DYNAMIC_E2E_USER_ID"),
            role=required("DYNAMIC_E2E_ROLE"),
            timezone_name=os.getenv("DYNAMIC_E2E_TIMEZONE", "Asia/Seoul"),
            analysis_question=required("DYNAMIC_E2E_ANALYSIS_QUESTION"),
            rag_query=required("DYNAMIC_E2E_RAG_QUERY"),
            ml_metric=required("DYNAMIC_E2E_ML_METRIC"),
            ml_hotel_scope=required("DYNAMIC_E2E_ML_HOTEL_SCOPE"),
            ml_horizon=required_positive_int("DYNAMIC_E2E_ML_HORIZON"),
            top_k=positive_int("DYNAMIC_E2E_TOP_K", 5),
            output_dir=output_dir,
            timeout_seconds=positive_float("DYNAMIC_E2E_TIMEOUT_SECONDS", 20.0),
        )


@dataclass(frozen=True)
class StageEvidence:
    stage: E2EStage
    status: str
    latency_ms: float
    details: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class DynamicE2EReport:
    request_id: str
    trace_id: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    final_stage: E2EStage = E2EStage.INITIALIZED
    stages: list[StageEvidence] = field(default_factory=list)

    def record(self, evidence: StageEvidence) -> None:
        self.stages.append(evidence)
        self.final_stage = evidence.stage

    def finish(self, stage: E2EStage) -> None:
        self.final_stage = stage
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "final_stage": self.final_stage.value,
            "stages": [
                {
                    "stage": item.stage.value,
                    "status": item.status,
                    "latency_ms": item.latency_ms,
                    "details": item.details,
                    "error_code": item.error_code,
                    "error_message": item.error_message,
                }
                for item in self.stages
            ],
        }
