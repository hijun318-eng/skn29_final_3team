"""보고서(Report) 생성, 렌더링 및 스케줄링 실행 도메인 패키지.

[주요 구성 모듈]
- document.py: HTML 조립, WeasyPrint PDF/A-3u 렌더링 및 승인 영속화
- chart.py: 순수 SVG 벡터 차트 렌더러
- layout.py: 12열 그리드 레이아웃 및 페이지 분할(Pagination)
- types.py: RenderedReportDocument 및 체크섬 무결성 타입
- values.py: 수치 포맷팅, 통화 스케일링 및 마크다운 변환기
- execution.py: 분석 정의 재생(AnalysisDefinitionReplay) 및 실행 오케스트레이터
- scheduler.py: 백그라운드 예약 실행 워커(ReportScheduler)
"""

from app.services.report.chart import _chart_svg
from app.services.report.document import (
    approve_report_document,
    build_report_html,
    render_report_document,
)
from app.services.report.execution import (
    AnalysisDefinitionReplay,
    ExecutionGate,
    ReplayOutcome,
    ReportExecutionService,
)
from app.services.report.layout import (
    _artifact_html,
    _artifact_is_synthetic,
    _artifact_settings,
    _block_chart_type,
    _block_html,
    _layout_page_html,
    _paginate_layout,
    _report_is_synthetic,
)
from app.services.report.scheduler import ReportScheduler, report_scheduler
from app.services.report.types import (
    RenderedReportDocument,
    ReportDocumentRenderError,
    canonical_source_checksum,
)
from app.services.report.values import (
    ARTIFACT_PRESENTATION_MODES,
    ARTIFACT_VIEWS,
    CHART_COLORS,
    CHART_POINT_LIMIT,
    CURRENCY_DISPLAY_UNITS,
    CURRENCY_UNITS,
    LAYOUT_PAGE_ROWS,
    NUMERIC_TEXT,
    SYNTHETIC_WARNING,
    TABLE_ROW_LIMIT,
    _column_label,
    _currency_values,
    _evenly_sample,
    _finite_number,
    _format_currency,
    _format_value,
    _is_krw_unit,
    _is_numeric,
    _label_without_unit,
    _markdown_text,
    _metric_labels,
    _metric_units,
    _metrics_html,
    _resolve_currency_display_unit,
    _table_html,
    _unit_label,
)

__all__ = [
    "RenderedReportDocument",
    "ReportDocumentRenderError",
    "canonical_source_checksum",
    "build_report_html",
    "render_report_document",
    "approve_report_document",
    "AnalysisDefinitionReplay",
    "ExecutionGate",
    "ReplayOutcome",
    "ReportExecutionService",
    "ReportScheduler",
    "report_scheduler",
]
