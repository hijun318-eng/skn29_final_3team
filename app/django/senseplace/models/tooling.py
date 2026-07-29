"""Tooling 테이블 — Answervice 데이터테이블 명세서 v1.1 T01 기준.

- Tool: MCP Tool 도구 등록 (T01 tool_registry)
  SQL·DataHub·RAG·ML Tool 계약 버전을 관리한다. 기획서 P2 범위.
"""

from __future__ import annotations

import uuid

from django.db import models

from .enums import (
    HealthStatusCode,
    ToolTransportCode,
    ToolTypeCode,
)


class Tool(models.Model):
    """MCP Tool 도구 등록 (T01 tool_registry).

    grain: tool_id (PK)
    SQL·DataHub·RAG·ML Tool의 버전·권한·상태를 관리한다.
    """

    tool_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Tool ID",
    )
    tool_code = models.CharField(
        max_length=96,
        help_text="안정 호출 키",
    )
    tool_type = models.CharField(
        max_length=16,
        choices=ToolTypeCode.CHOICES,
        help_text="Tool 유형 (SQL/DATAHUB/RAG/ML)",
    )
    semantic_version = models.CharField(
        max_length=32,
        help_text="semantic version",
    )
    name = models.CharField(
        max_length=160,
        help_text="Tool 명",
    )
    description = models.TextField(
        default="",
        blank=True,
        help_text="설명",
    )
    input_schema_json = models.JSONField(
        default=dict,
        help_text="입력 schema",
    )
    output_schema_json = models.JSONField(
        default=dict,
        help_text="출력 schema",
    )
    transport = models.CharField(
        max_length=24,
        choices=ToolTransportCode.CHOICES,
        default=ToolTransportCode.INTERNAL,
        help_text="transport (INTERNAL/HTTP/MCP_STDIO/MCP_SSE)",
    )
    endpoint_ref = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="endpoint 참조 (secret 원문 금지)",
    )
    timeout_seconds = models.PositiveIntegerField(
        default=30,
        help_text="timeout",
    )
    required_roles_json = models.JSONField(
        default=list,
        help_text="필수 역할",
    )
    tool_hints_json = models.JSONField(
        default=dict,
        help_text="Tool hints (readOnly/destructive/idempotent)",
    )
    is_enabled = models.BooleanField(
        default=False,
        help_text="활성 여부 (P2 전 false)",
    )
    health_status = models.CharField(
        max_length=16,
        choices=HealthStatusCode.CHOICES,
        default=HealthStatusCode.HEALTHY,
        help_text="health (HEALTHY/DEGRADED/DOWN/UNKNOWN)",
    )
    success_rate = models.FloatField(
        null=True,
        blank=True,
        help_text="최근 성공률 (예: 98.7)",
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="최근 실행 시각 (UTC)",
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
        db_table = "tool_registry"
        verbose_name = "Tool"
        verbose_name_plural = "Tools"

    def __str__(self) -> str:
        return f"{self.name} ({self.semantic_version})"
