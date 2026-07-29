"""Connection 테이블 — Answervice 데이터테이블 명세서 v1.1 C01 기준.

- DataSource: 데이터 소스 연결 정보 (C01 data_sources)
  논리 source·DataHub recipe·Trino catalog 연결 1건.
  기획서 5개 사일로·4종 엔진에 대응한다.
"""

from __future__ import annotations

import uuid

from django.db import models

from .enums import (
    DataSourceStatusCode,
    EngineTypeCode,
    HealthStatusCode,
)


class DataSource(models.Model):
    """데이터 소스 연결 정보 (C01 data_sources).

    grain: data_source_id (PK)
    기획서 5개 논리 사일로(PMS/POS/CRM/FACILITY/BANQUET)의
    DataHub recipe와 Trino catalog 연결을 관리한다.
    """

    data_source_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="데이터 소스 ID",
    )
    source_code = models.CharField(
        max_length=32,
        help_text="소스 코드 (PMS/POS/CRM/FACILITY/BANQUET)",
    )
    source_name = models.CharField(
        max_length=120,
        help_text="관리자 표시명",
    )
    engine_type = models.CharField(
        max_length=24,
        choices=EngineTypeCode.CHOICES,
        help_text="엔진 (POSTGRESQL/MYSQL/SQLSERVER/CLICKHOUSE)",
    )
    platform_instance = models.CharField(
        max_length=128,
        help_text="DataHub platform instance",
    )
    trino_catalog = models.CharField(
        max_length=128,
        help_text="Trino catalog",
    )
    datahub_recipe_ref = models.CharField(
        max_length=255,
        help_text="버전 고정 recipe 경로",
    )
    connection_ref = models.CharField(
        max_length=255,
        help_text="credential 참조 (env 또는 Secret Manager)",
    )
    owner_team = models.CharField(
        max_length=100,
        help_text="담당 조직",
    )
    status = models.CharField(
        max_length=16,
        choices=DataSourceStatusCode.CHOICES,
        default=DataSourceStatusCode.ACTIVE,
        help_text="연결 상태 (DRAFT/ACTIVE/ERROR/DISABLED)",
    )
    last_health_status = models.CharField(
        max_length=16,
        choices=HealthStatusCode.CHOICES,
        default=HealthStatusCode.UNKNOWN,
        blank=True,
        help_text="최근 health (HEALTHY/DEGRADED/DOWN/UNKNOWN)",
    )
    last_health_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="최근 점검 시각 (UTC)",
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
        db_table = "data_sources"
        verbose_name = "Data Source"
        verbose_name_plural = "Data Sources"

    def __str__(self) -> str:
        return f"{self.source_code} ({self.source_name})"
