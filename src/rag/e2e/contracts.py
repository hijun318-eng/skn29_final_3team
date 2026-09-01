"""실런타임 E2E의 환경 설정, 단계 상태, 증거 영수증 직렬화 계약을 정의한다."""

from __future__ import annotations

import os
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class E2EConfigurationError(ValueError):
    """필수 런타임 주소·주체·질문·수치 설정이 없거나 유효하지 않을 때 발생한다."""


class E2EStage(str, Enum):
    """Analysis, RAG, ML 검증의 현재 단계와 최종 성공·차단·실패 상태를 식별한다."""

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
    """한 실런타임의 이름, 기본 URL, 준비 상태 경로를 함께 보관한다."""

    name: str
    base_url: str
    health_path: str

    @property
    def health_url(self) -> str:
        """기본 URL의 말단 슬래시를 정규화해 준비 상태 요청용 절대 URL을 만든다."""

        return f"{self.base_url.rstrip('/')}{self.health_path}"


@dataclass(frozen=True)
class DynamicE2EConfig:
    """세 런타임 호출과 서명·주체·질문·출력에 필요한 검증 완료 설정을 보관한다."""

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
        """환경 변수를 typed 설정으로 변환하며 누락·비양수·쓰기 불가 값은 즉시 거부한다."""

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
            if not math.isfinite(value) or not 0.1 <= value <= 300.0:
                raise E2EConfigurationError(
                    f"{name} must be between 0.1 and 300 seconds"
                )
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
    """한 검증 단계의 상태, 지연 시간, 응답 세부 정보와 오류 코드를 기록한다."""

    stage: E2EStage
    status: str
    latency_ms: float
    details: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class DynamicE2EReport:
    """동일 request·trace에 속한 단계별 증거와 실행 시작·완료 시각을 누적한다."""

    request_id: str
    trace_id: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    final_stage: E2EStage = E2EStage.INITIALIZED
    stages: list[StageEvidence] = field(default_factory=list)

    def record(self, evidence: StageEvidence) -> None:
        """단계 증거를 순서대로 추가하고 보고서의 현재 단계를 해당 단계로 갱신한다."""

        self.stages.append(evidence)
        self.final_stage = evidence.stage

    def finish(self, stage: E2EStage) -> None:
        """최종 단계를 확정하고 UTC 완료 시각을 기록해 실행 종료를 봉인한다."""

        self.final_stage = stage
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Enum과 단계 객체를 JSON 직렬화 가능한 증거 보고서 사전으로 변환한다."""

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
