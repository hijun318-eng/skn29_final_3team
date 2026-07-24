"""SensePlace DSG v2.0 모델 패키지.

16 table 전체를 한 곳에서 import할 수 있도록 재내보낸다.

Usage::

    from senseplace.models import FactVoc, Report
    from senseplace.models import *  # noqa: F401, F403
"""

from .enums import (  # noqa: F401
    DecisionCode,
    EvidenceTypeCode,
    JobStatusCode,
    ReportStatusCode,
    ResourceTypeCode,
    RoleCode,
    SentimentLabelCode,
    SeverityCode,
    ShiftCode,
    VerificationStatusCode,
    VocCategoryCode,
)
from .fact import (  # noqa: F401
    FactBreakfast15m,
    FactBreakfastDaily,
    FactRoomsDaily,
    FactStaffShift,
    FactVoc,
)
from .metadata import (  # noqa: F401
    DatasetManifest,
    DimDate,
    DimServiceArea,
)
from .platform import (  # noqa: F401
    AnalysisRun,
    Evidence,
    FieldNote,
    MetricCatalog,
    QueryRun,
    Report,
    ReportDecision,
    RoleScope,
)

__all__ = [
    # Metadata (3)
    "DatasetManifest",
    "DimDate",
    "DimServiceArea",
    # Fact (5)
    "FactRoomsDaily",
    "FactBreakfast15m",
    "FactBreakfastDaily",
    "FactStaffShift",
    "FactVoc",
    # Platform (8)
    "MetricCatalog",
    "RoleScope",
    "QueryRun",
    "AnalysisRun",
    "Evidence",
    "Report",
    "ReportDecision",
    "FieldNote",
    # Enums
    "RoleCode",
    "JobStatusCode",
    "SeverityCode",
    "SentimentLabelCode",
    "VocCategoryCode",
    "EvidenceTypeCode",
    "ReportStatusCode",
    "VerificationStatusCode",
    "DecisionCode",
    "ShiftCode",
    "ResourceTypeCode",
]
