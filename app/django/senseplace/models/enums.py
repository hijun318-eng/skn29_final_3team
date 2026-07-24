"""Django choices — src/common/enums.py의 표준 값을 Django model에서 사용한다.

References:
    - src/common/enums.py (Role, Severity, JobStatus, SentimentLabel, VocCategory)
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Role codes (CPS v2.0 §7, 3역할 RBAC)
# ---------------------------------------------------------------------------
class RoleCode:
    OPERATIONS_MANAGER = "OPERATIONS_MANAGER"
    FACILITY_MANAGER = "FACILITY_MANAGER"
    EXTERNAL_REVIEWER = "EXTERNAL_REVIEWER"

    CHOICES = [
        (OPERATIONS_MANAGER, "Operations Manager"),
        (FACILITY_MANAGER, "Facility Manager"),
        (EXTERNAL_REVIEWER, "External Reviewer"),
    ]


# ---------------------------------------------------------------------------
# Job status (CPS v2.0 §8)
# PENDING → RUNNING → SUCCEEDED | PARTIAL | NEEDS_DATA | FAILED
# ---------------------------------------------------------------------------
class JobStatusCode:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    NEEDS_DATA = "NEEDS_DATA"
    FAILED = "FAILED"

    CHOICES = [
        (PENDING, "Pending"),
        (RUNNING, "Running"),
        (SUCCEEDED, "Succeeded"),
        (PARTIAL, "Partial"),
        (NEEDS_DATA, "Needs Data"),
        (FAILED, "Failed"),
    ]


# ---------------------------------------------------------------------------
# Severity / Sentiment
# ---------------------------------------------------------------------------
class SeverityCode:
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"

    CHOICES = [
        (NEGATIVE, "Negative"),
        (NEUTRAL, "Neutral"),
        (POSITIVE, "Positive"),
    ]


class SentimentLabelCode:
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"

    CHOICES = [
        (NEGATIVE, "Negative"),
        (NEUTRAL, "Neutral"),
        (POSITIVE, "Positive"),
    ]


# ---------------------------------------------------------------------------
# Data source (DSG v2.0 §5)
# ---------------------------------------------------------------------------
class DataSourceCode:
    PMS = "PMS"
    POS = "POS"
    CRM = "CRM"
    IOT = "IoT"
    VOC = "VOC"
    REVIEW = "REVIEW"
    WEATHER = "WEATHER"

    CHOICES = [
        (PMS, "PMS"),
        (POS, "POS"),
        (CRM, "CRM"),
        (IOT, "IoT"),
        (VOC, "VOC"),
        (REVIEW, "Review"),
        (WEATHER, "Weather"),
    ]


# ---------------------------------------------------------------------------
# VOC category / topic code (DSG v2.0 fact_voc)
# ---------------------------------------------------------------------------
class VocCategoryCode:
    GUEST_ROOM = "guest_room"
    FACILITY = "facility"
    SERVICE = "service"
    FOOD_BEVERAGE = "food_beverage"
    ETC = "etc"

    CHOICES = [
        (GUEST_ROOM, "객실"),
        (FACILITY, "시설"),
        (SERVICE, "서비스"),
        (FOOD_BEVERAGE, "식음료"),
        (ETC, "기타"),
    ]


# ---------------------------------------------------------------------------
# Evidence type
# ---------------------------------------------------------------------------
class EvidenceTypeCode:
    METRIC_COMPARISON = "METRIC_COMPARISON"
    VOC_CORRELATION = "VOC_CORRELATION"
    TREND_ANALYSIS = "TREND_ANALYSIS"
    THRESHOLD_BREACH = "THRESHOLD_BREACH"

    CHOICES = [
        (METRIC_COMPARISON, "Metric Comparison"),
        (VOC_CORRELATION, "VOC Correlation"),
        (TREND_ANALYSIS, "Trend Analysis"),
        (THRESHOLD_BREACH, "Threshold Breach"),
    ]


# ---------------------------------------------------------------------------
# Report status
# ---------------------------------------------------------------------------
class ReportStatusCode:
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    CHOICES = [
        (DRAFT, "Draft"),
        (READY_FOR_REVIEW, "Ready for Review"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]


# ---------------------------------------------------------------------------
# Verification status (field_note)
# ---------------------------------------------------------------------------
class VerificationStatusCode:
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"

    CHOICES = [
        (PENDING, "Pending"),
        (CONFIRMED, "Confirmed"),
        (DISPUTED, "Disputed"),
    ]


# ---------------------------------------------------------------------------
# Decision type (report_decision)
# ---------------------------------------------------------------------------
class DecisionCode:
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"

    CHOICES = [
        (APPROVE, "Approve"),
        (REQUEST_CHANGES, "Request Changes"),
        (REJECT, "Reject"),
    ]


# ---------------------------------------------------------------------------
# Shift code (fact_staff_shift)
# ---------------------------------------------------------------------------
class ShiftCode:
    AM = "AM"
    PM = "PM"
    FULL = "FULL"

    CHOICES = [
        (AM, "Morning"),
        (PM, "Afternoon"),
        (FULL, "Full Day"),
    ]


# ---------------------------------------------------------------------------
# Resource type (role_scope)
# ---------------------------------------------------------------------------
class ResourceTypeCode:
    TABLE = "TABLE"
    VIEW = "VIEW"
    METRIC = "METRIC"

    CHOICES = [
        (TABLE, "Table"),
        (VIEW, "View"),
        (METRIC, "Metric"),
    ]
