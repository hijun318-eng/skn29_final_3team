"""ANSWERVICE 핵심 비즈니스 도메인 서비스 패키지.

[5대 핵심 하위 도메인 패키지]
- conversation: 대화 턴 수명주기, 슬롯 결정, 시간 대수, CAS 오케스트레이션
- sql_guard: AST 기반 SQL 거버넌스 가드, 스키마/지표/조인/시간 검증
- context: DataHub 메타데이터 기반 컨텍스트 패키지 빌더, 3대 쿼리 전략, 지표/필터 해석기
- analysis: 4단계(Context -> Plan -> Query -> Result) 분석 파이프라인 및 실행 서비스
- report: 보고서 렌더링(HTML/PDF), A4 그리드 레이아웃, SVG 차트, 멱등 재생 및 스케줄러
"""

from app.services.analysis import AnalysisPipeline, AnalysisService, analysis_progress
from app.services.context import (
    ContextAsset,
    ContextMetric,
    ContextPackage,
    ContextPackageBuilder,
    ContextRegistryService,
    GovernedJoin,
    PipelineContextService,
    RuntimeContextPackage,
)
from app.services.conversation import (
    AnalysisChangeSet,
    ChangeOperation,
    ConversationOrchestrator,
    ConversationSlotResolver,
    SlotChange,
    SlotResolver,
    TimeAlgebraEngine,
    apply_dimension_changes,
    apply_metric_change,
    derive_dimension_changes,
    derive_metric_change,
    execute_report_action,
)
from app.services.report import (
    AnalysisDefinitionReplay,
    RenderedReportDocument,
    ReportDocumentRenderError,
    ReportExecutionService,
    ReportScheduler,
    approve_report_document,
    build_report_html,
    render_report_document,
    report_scheduler,
)
from app.services.sql_guard import (
    GuardDecision,
    SemanticDecision,
    validate_parsed_semantics,
    validate_plan,
)

__all__ = [
    # conversation
    "ConversationOrchestrator",
    "ConversationSlotResolver",
    "SlotResolver",
    "TimeAlgebraEngine",
    "AnalysisChangeSet",
    "ChangeOperation",
    "SlotChange",
    "derive_metric_change",
    "apply_metric_change",
    "derive_dimension_changes",
    "apply_dimension_changes",
    "execute_report_action",
    # sql_guard
    "validate_plan",
    "validate_parsed_semantics",
    "GuardDecision",
    "SemanticDecision",
    # context
    "ContextPackageBuilder",
    "ContextPackage",
    "ContextAsset",
    "ContextMetric",
    "GovernedJoin",
    "RuntimeContextPackage",
    "PipelineContextService",
    "ContextRegistryService",
    # analysis
    "AnalysisPipeline",
    "AnalysisService",
    "analysis_progress",
    # report
    "RenderedReportDocument",
    "ReportDocumentRenderError",
    "build_report_html",
    "render_report_document",
    "approve_report_document",
    "AnalysisDefinitionReplay",
    "ReportExecutionService",
    "ReportScheduler",
    "report_scheduler",
]
