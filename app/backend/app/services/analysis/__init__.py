"""분석(Analysis) 파이프라인 및 단계별 실행기 도메인 패키지.

[주요 구성 모듈]
- pipeline.py: 4단계(Context -> Plan -> Query -> Result) 파이프라인 오케스트레이터
- pipeline_state.py: 요청별 격리된 파이프라인 수명주기 상태(AnalysisPipelineState)
- service.py: 애플리케이션 진입 파사드 서비스(AnalysisService)
- pipeline_support.py: 각 단계별 공통 거버넌스 지원 파사드(PipelineSupport)
- responses.py: 표준 성공/실패/차단 응답 조립 팩토리(AnalysisResponseFactory)
- progress.py: 진행 상태 및 취소 제어 레지스트리(analysis_progress)
- evidence.py: 모델 호출 및 G1~G3 게이트 감사 증거 빌더
- model_support.py: 모델 에러 매핑 및 호출 추적 헬퍼
- result_validator.py: Trino 결과 스키마 및 G3 게이트 검증기
- stages/: 개별 파이프라인 단계 구현체 (ContextStage, PlanStage, QueryStage, ResultStage)
"""

from app.services.analysis.evidence import (
    _evidence_filters,
    _gate_evidence,
    _gate_history,
    _metric_term,
    _model_invocations,
    _reduce_metric_values,
)
from app.services.analysis.model_support import (
    is_numeric,
    model_failure_code,
    model_trace_detail,
)
from app.services.analysis.pipeline import AnalysisPipeline
from app.services.analysis.pipeline_state import AnalysisPipelineState
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.analysis.progress import (
    AmbiguousTraceError,
    AnalysisProgressRegistry,
    analysis_progress,
)
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.analysis.result_validator import PipelineResultValidator
from app.services.analysis.service import AnalysisService

__all__ = [
    "AnalysisPipeline",
    "AnalysisPipelineState",
    "AnalysisService",
    "PipelineSupport",
    "AnalysisResponseFactory",
    "PipelineResultValidator",
    "AnalysisProgressRegistry",
    "analysis_progress",
    "AmbiguousTraceError",
    "model_failure_code",
    "model_trace_detail",
    "is_numeric",
]
