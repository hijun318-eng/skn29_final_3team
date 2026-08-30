"""ANSWERVICE 비즈니스 서비스의 side-effect 없는 namespace 패키지다.

분석·대화·컨텍스트·보고서·SQL Guard는 서로의 구체 구현을 package import 시점에
조립하지 않는다. 호출자는 필요한 하위 모듈에서 명시적으로 import해야 하며, 실제
애플리케이션 조립은 API runtime과 controller 경계가 담당한다. 이 원칙은 adapter가
가벼운 도메인 계약을 읽을 때 Report 실행기까지 역으로 불러오는 순환 import를 막는다.
"""

_PUBLIC_EXPORTS: dict[str, str] = {
    # conversation
    "ConversationOrchestrator": "app.services.conversation",
    "ConversationSlotResolver": "app.services.conversation",
    "SlotResolver": "app.services.conversation",
    "TimeAlgebraEngine": "app.services.conversation",
    "AnalysisChangeSet": "app.services.conversation",
    "ChangeOperation": "app.services.conversation",
    "SlotChange": "app.services.conversation",
    "derive_metric_change": "app.services.conversation",
    "apply_metric_change": "app.services.conversation",
    "derive_dimension_changes": "app.services.conversation",
    "apply_dimension_changes": "app.services.conversation",
    "execute_report_action": "app.services.conversation",
    # sql_guard
    "validate_plan": "app.services.sql_guard",
    "validate_parsed_semantics": "app.services.sql_guard",
    "GuardDecision": "app.services.sql_guard",
    "SemanticDecision": "app.services.sql_guard",
    # context
    "ContextPackageBuilder": "app.services.context",
    "ContextPackage": "app.services.context",
    "ContextAsset": "app.services.context",
    "ContextMetric": "app.services.context",
    "GovernedJoin": "app.services.context",
    "RuntimeContextPackage": "app.services.context",
    "PipelineContextService": "app.services.context",
    "ContextRegistryService": "app.services.context",
    # analysis
    "AnalysisPipeline": "app.services.analysis",
    "AnalysisService": "app.services.analysis",
    "analysis_progress": "app.services.analysis",
    # report
    "RenderedReportDocument": "app.services.report",
    "ReportDocumentRenderError": "app.services.report",
    "build_report_html": "app.services.report",
    "render_report_document": "app.services.report",
    "approve_report_document": "app.services.report",
    "AnalysisDefinitionReplay": "app.services.report",
    "ReportExecutionService": "app.services.report",
    "ReportScheduler": "app.services.report",
    "report_scheduler": "app.services.report",
}

__all__ = tuple(_PUBLIC_EXPORTS)


def __getattr__(name: str) -> object:
    """기존 공개 계약을 보존하되 요청된 하위 도메인만 지연 로딩한다."""

    module_name = _PUBLIC_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = __import__(module_name, fromlist=(name,))
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
