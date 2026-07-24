"""Platform 테이블 — DSG v2.0 §7 기준.

- MetricCatalog: 지표 카탈로그
- RoleScope: 역할별 접근 범위
- QueryRun: Text-to-SQL 실행 이력
- AnalysisRun: 이상 감지 분석 실행
- Evidence: 분석 근거
- Report: 보고서 버전
- ReportDecision: 보고서 결정
- FieldNote: 현장 확인 메모
"""

from __future__ import annotations

import uuid

from django.db import models

from .enums import (
    DecisionCode,
    EvidenceTypeCode,
    JobStatusCode,
    ReportStatusCode,
    ResourceTypeCode,
    RoleCode,
    VerificationStatusCode,
)


class MetricCatalog(models.Model):
    """지표 카탈로그 (DB-020).

    grain: metric_code (PK)
    additive=false인 지표는 bucket 값의 합·평균 재집계 금지.
    """

    metric_code = models.CharField(
        max_length=64,
        primary_key=True,
        help_text="지표 코드",
    )
    display_name = models.CharField(
        max_length=128,
        help_text="지표 표시 이름",
    )
    definition = models.TextField(
        help_text="지표 정의",
    )
    unit = models.CharField(
        max_length=32,
        help_text="단위 (min, count, rate 등)",
    )
    additive = models.BooleanField(
        default=True,
        help_text="가산성 여부 (합산 가능 여부)",
    )
    allowed_grains = models.JSONField(
        default=list,
        help_text="허용 grain 목록",
    )
    allowed_dimensions = models.JSONField(
        default=list,
        help_text="허용 차원 목록",
    )
    synonyms = models.JSONField(
        default=list,
        help_text="동의어 목록",
    )
    source_view = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="원본 view 이름",
    )
    version = models.CharField(
        max_length=32,
        help_text="카탈로그 버전",
    )

    class Meta:
        db_table = "metric_catalog"
        verbose_name = "Metric Catalog"
        verbose_name_plural = "Metric Catalog"

    def __str__(self) -> str:
        return self.metric_code


class RoleScope(models.Model):
    """역할별 접근 범위 (DB-021).

    grain: (role_code, resource_code, scope_version)
    """

    role_code = models.CharField(
        max_length=32,
        choices=RoleCode.CHOICES,
        help_text="역할 코드",
    )
    resource_type = models.CharField(
        max_length=16,
        choices=ResourceTypeCode.CHOICES,
        help_text="리소스 유형 (TABLE/VIEW/METRIC)",
    )
    resource_code = models.CharField(
        max_length=64,
        help_text="리소스 코드",
    )
    allowed = models.BooleanField(
        default=True,
        help_text="접근 허용 여부",
    )
    scope_version = models.CharField(
        max_length=16,
        help_text="범위 버전",
    )

    class Meta:
        db_table = "role_scope"
        verbose_name = "Role Scope"
        verbose_name_plural = "Role Scopes"
        constraints = [
            models.UniqueConstraint(
                fields=["role_code", "resource_code", "scope_version"],
                name="uq_role_scope",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role_code} / {self.resource_code}"


class QueryRun(models.Model):
    """Text-to-SQL 실행 이력 (DB-022).

    grain: query_run_id (PK)
    """

    query_run_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="쿼리 실행 ID",
    )
    job_id = models.UUIDField(
        help_text="관련 작업 ID",
    )
    actor_id = models.CharField(
        max_length=64,
        help_text="실행자 ID",
    )
    role_code = models.CharField(
        max_length=32,
        choices=RoleCode.CHOICES,
        help_text="실행자 역할",
    )
    scope_snapshot = models.JSONField(
        default=dict,
        help_text="실행 시점 권한 스냅샷",
    )
    question_redacted = models.TextField(
        help_text="원본 질문 (비식별화)",
    )
    query_plan = models.JSONField(
        default=dict,
        blank=True,
        help_text="쿼리 실행 계획",
    )
    sql_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SQL 해시",
    )
    row_count = models.PositiveIntegerField(
        default=0,
        help_text="반환 행 수",
    )
    status = models.CharField(
        max_length=16,
        choices=JobStatusCode.CHOICES,
        default=JobStatusCode.PENDING,
        help_text="실행 상태",
    )
    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="생성 시각 (UTC)",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="완료 시각 (UTC)",
    )

    class Meta:
        db_table = "query_run"
        verbose_name = "Query Run"
        verbose_name_plural = "Query Runs"

    def __str__(self) -> str:
        return str(self.query_run_id)


class AnalysisRun(models.Model):
    """이상 감지 분석 실행 (DB-023).

    grain: analysis_run_id (PK)
    idempotency_key로 중복 실행 방지.
    """

    analysis_run_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="분석 실행 ID",
    )
    job_id = models.UUIDField(
        help_text="관련 작업 ID",
    )
    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전",
    )
    scenario_id = models.CharField(
        max_length=64,
        help_text="시나리오 ID",
    )
    rule_id = models.CharField(
        max_length=64,
        help_text="감지 규칙 ID",
    )
    rule_version = models.CharField(
        max_length=32,
        help_text="감지 규칙 버전",
    )
    status = models.CharField(
        max_length=16,
        choices=JobStatusCode.CHOICES,
        default=JobStatusCode.PENDING,
        help_text="실행 상태",
    )
    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        help_text="멱등키 (중복 실행 방지)",
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="시작 시각 (UTC)",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="완료 시각 (UTC)",
    )

    class Meta:
        db_table = "analysis_run"
        verbose_name = "Analysis Run"
        verbose_name_plural = "Analysis Runs"

    def __str__(self) -> str:
        return str(self.analysis_run_id)


class Evidence(models.Model):
    """분석 근거 (DB-024).

    grain: evidence_id (PK)
    is_counter_evidence로 반대 근표시 가능.
    """

    evidence_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="근거 ID",
    )
    analysis_run_id = models.UUIDField(
        help_text="분석 실행 ID FK",
    )
    evidence_type = models.CharField(
        max_length=32,
        choices=EvidenceTypeCode.CHOICES,
        help_text="근거 유형",
    )
    source_table = models.CharField(
        max_length=64,
        help_text="원본 테이블",
    )
    source_key = models.CharField(
        max_length=128,
        help_text="원본 레코드 키",
    )
    metric_code = models.CharField(
        max_length=64,
        help_text="관련 지표 코드 FK",
    )
    observed_window = models.JSONField(
        default=dict,
        help_text="관측 윈도우 (start, end)",
    )
    comparison_window = models.JSONField(
        default=dict,
        blank=True,
        help_text="비교 윈도우 (start, end)",
    )
    value = models.FloatField(
        help_text="관측 값",
    )
    unit = models.CharField(
        max_length=32,
        help_text="값 단위",
    )
    sample_size = models.PositiveIntegerField(
        default=0,
        help_text="표본 크기",
    )
    is_counter_evidence = models.BooleanField(
        default=False,
        help_text="반대 근거 여부",
    )
    limitations = models.TextField(
        blank=True,
        default="",
        help_text="한계 사항",
    )

    class Meta:
        db_table = "evidence"
        verbose_name = "Evidence"
        verbose_name_plural = "Evidence"

    def __str__(self) -> str:
        return str(self.evidence_id)


class Report(models.Model):
    """보고서 버전 (DB-025).

    grain: (report_id, report_version)
    is_synthetic=true.
    """

    report_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        help_text="보고서 ID",
    )
    report_version = models.PositiveIntegerField(
        help_text="보고서 버전 번호",
    )
    analysis_run_id = models.UUIDField(
        help_text="분석 실행 ID FK",
    )
    virtual_week_id = models.CharField(
        max_length=16,
        help_text="가상 주차 ID",
    )
    status = models.CharField(
        max_length=24,
        choices=ReportStatusCode.CHOICES,
        default=ReportStatusCode.DRAFT,
        help_text="보고서 상태",
    )
    sections = models.JSONField(
        default=list,
        help_text="섹션 목록",
    )
    evidence_ids = models.JSONField(
        default=list,
        help_text="포함된 근거 ID 목록",
    )
    is_synthetic = models.BooleanField(
        default=True,
        help_text="합성 데이터 여부",
    )
    template_version = models.CharField(
        max_length=32,
        help_text="보고서 템플릿 버전",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="생성 시각 (UTC)",
    )

    class Meta:
        db_table = "report"
        verbose_name = "Report"
        verbose_name_plural = "Reports"
        constraints = [
            models.UniqueConstraint(
                fields=["report_id", "report_version"],
                name="uq_report_id_version",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.report_id} v{self.report_version}"


class ReportDecision(models.Model):
    """보고서 결정 (DB-026).

    grain: decision_id (PK)
    """

    decision_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="결정 ID",
    )
    report_id = models.UUIDField(
        help_text="보고서 ID FK",
    )
    report_version = models.PositiveIntegerField(
        help_text="보고서 버전 FK",
    )
    actor_id = models.CharField(
        max_length=64,
        help_text="결정자 ID",
    )
    decision = models.CharField(
        max_length=24,
        choices=DecisionCode.CHOICES,
        help_text="결정 유형",
    )
    comment_redacted = models.TextField(
        blank=True,
        default="",
        help_text="의견 (비식별화)",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="생성 시각 (UTC)",
    )

    class Meta:
        db_table = "report_decision"
        verbose_name = "Report Decision"
        verbose_name_plural = "Report Decisions"

    def __str__(self) -> str:
        return str(self.decision_id)


class FieldNote(models.Model):
    """현장 확인 메모 (DB-027).

    grain: field_note_id (PK)
    Django가 소유. FastAPI는 redacted note만 읽음.
    """

    field_note_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="현장 메모 ID",
    )
    analysis_run_id = models.UUIDField(
        help_text="분석 실행 ID FK",
    )
    actor_id = models.CharField(
        max_length=64,
        help_text="작성자 ID",
    )
    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatusCode.CHOICES,
        default=VerificationStatusCode.PENDING,
        help_text="확인 상태",
    )
    note_redacted = models.TextField(
        help_text="메모 내용 (비식별화)",
    )
    note_version = models.PositiveIntegerField(
        default=1,
        help_text="메모 버전",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="생성 시각 (UTC)",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="수정 시각 (UTC)",
    )

    class Meta:
        db_table = "field_note"
        verbose_name = "Field Note"
        verbose_name_plural = "Field Notes"

    def __str__(self) -> str:
        return str(self.field_note_id)
