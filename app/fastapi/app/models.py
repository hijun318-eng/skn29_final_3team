"""SQLAlchemy 2 ORM 모델 — 엔터프라이즈 프론트엔드 공개 API용.

7개 테이블을 정의한다. 명세서 및 Django 모델 기준과 매핑된다.
현재 SQLite data.db의 기존 스키마와 호환된다.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class DimDate(Base):
    __tablename__ = "dim_date"

    service_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    day_of_week: Mapped[str] = mapped_column(String(3))
    is_weekend: Mapped[bool] = mapped_column(Boolean, default=False)
    virtual_week_id: Mapped[str] = mapped_column(String(16))


class Report(Base):
    __tablename__ = "report"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_version: Mapped[int] = mapped_column(Integer)
    analysis_run_id: Mapped[str] = mapped_column(String(36))
    virtual_week_id: Mapped[str] = mapped_column(String(16))
    report_type: Mapped[str] = mapped_column(String(16), default="WEEKLY")
    author_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    sections: Mapped[str] = mapped_column(Text, default="[]")
    evidence_ids: Mapped[str] = mapped_column(Text, default="[]")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    template_version: Mapped[str] = mapped_column(String(32), default="v1.0")
    created_at: Mapped[str] = mapped_column(String(32))


class DataSource(Base):
    __tablename__ = "data_sources"

    data_source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(120))
    engine_type: Mapped[str] = mapped_column(String(24))
    platform_instance: Mapped[str] = mapped_column(String(128))
    trino_catalog: Mapped[str] = mapped_column(String(128))
    datahub_recipe_ref: Mapped[str] = mapped_column(String(255))
    connection_ref: Mapped[str] = mapped_column(String(255))
    owner_team: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    last_health_status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    last_health_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class DataProduct(Base):
    __tablename__ = "data_products"

    data_product_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product_name: Mapped[str] = mapped_column(String(160))
    source_name: Mapped[str] = mapped_column(String(120))
    catalog_ref: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(64))
    owner_team: Mapped[str] = mapped_column(String(100))
    freshness_label: Mapped[str] = mapped_column(String(32))
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    sensitivity: Mapped[str] = mapped_column(String(16), default="INTERNAL")
    tool_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class Tool(Base):
    __tablename__ = "tool_registry"

    tool_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tool_code: Mapped[str] = mapped_column(String(96))
    tool_type: Mapped[str] = mapped_column(String(16))
    semantic_version: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    output_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    transport: Mapped[str] = mapped_column(String(24), default="INTERNAL")
    endpoint_ref: Mapped[str] = mapped_column(String(255), default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    required_roles_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_hints_json: Mapped[str] = mapped_column(Text, default="{}")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    health_status: Mapped[str] = mapped_column(String(16), default="HEALTHY")
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_run_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class AgentWorkflowStep(Base):
    __tablename__ = "agent_workflow_step"

    step_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_order: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32))


class CustomerProfile(Base):
    __tablename__ = "customer_profile"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(32))
    member_no: Mapped[str] = mapped_column(String(36), default="")
    tier_label: Mapped[str] = mapped_column(String(32))
    stays_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_display: Mapped[str] = mapped_column(String(32))
    revisit_score: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_label: Mapped[str] = mapped_column(String(16))
    last_issue: Mapped[str] = mapped_column(String(64), default="")
    last_stay_date: Mapped[str] = mapped_column(String(16))
    preferred_room: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


# ===========================================================================
# 소스 데이터 테이블 (명세서 S01-S18, 기획서 §14 합성 데이터)
# ===========================================================================


class PmsReservation(Base):
    """S03 pms_reservations — PMS 예약 (PostgreSQL)."""
    __tablename__ = "pms_reservations"

    reservation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guest_id: Mapped[str] = mapped_column(String(36))
    stay_date: Mapped[str] = mapped_column(String(10))
    room_revenue: Mapped[int] = mapped_column(Integer, default=0)
    room_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="CONFIRMED")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class PmsStay(Base):
    """S04 pms_stays — PMS 투숙 (PostgreSQL)."""
    __tablename__ = "pms_stays"

    stay_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(36))
    guest_id: Mapped[str] = mapped_column(String(36))
    check_in: Mapped[str] = mapped_column(String(10))
    check_out: Mapped[str] = mapped_column(String(10), default="")
    room_number: Mapped[str] = mapped_column(String(8), default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class CrmMember(Base):
    """S09 crm_members — CRM 회원 (SQL Server)."""
    __tablename__ = "crm_members"

    member_no: Mapped[str] = mapped_column(String(36), primary_key=True)
    property_id: Mapped[str] = mapped_column(String(64), default="SYNTHETIC_HOTEL_001")
    membership_grade: Mapped[str] = mapped_column(String(16), default="BASIC")
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    member_status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class CrmMemberGradeHistory(Base):
    """S18 crm_member_grade_history — 등급 이력 (SQL Server).

    반개구간 [valid_from, valid_to) event-time JOIN용.
    """
    __tablename__ = "crm_member_grade_history"

    grade_history_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    member_no: Mapped[str] = mapped_column(String(36))
    grade_code: Mapped[str] = mapped_column(String(16), default="BASIC")
    valid_from: Mapped[str] = mapped_column(String(10))
    valid_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    change_reason_code: Mapped[str] = mapped_column(String(24), default="JOIN")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class CrmCustomerMap(Base):
    """S11 crm_customer_map — 교차 소스 고객 식별 bridge (SQL Server).

    member_no ↔ PMS guest_id ↔ POS customer_ref 연결.
    기획서 §14.3 공통키 관리.
    """
    __tablename__ = "crm_customer_map"

    map_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    member_no: Mapped[str] = mapped_column(String(36))
    pms_guest_id: Mapped[str] = mapped_column(String(36))
    pos_customer_ref: Mapped[str] = mapped_column(String(36), default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditEvent(Base):
    """감사 이벤트 — 기획서 §17.2 감사 항목.

    모든 /api/v1/ 요청에 대해 request_id, 사용자, 엔드포인트, 상태를 기록한다.
    """
    __tablename__ = "audit_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), default="")
    user_id: Mapped[str] = mapped_column(String(64), default="")
    endpoint: Mapped[str] = mapped_column(String(128), default="")
    method: Mapped[str] = mapped_column(String(8), default="GET")
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    timestamp: Mapped[str] = mapped_column(String(32), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
