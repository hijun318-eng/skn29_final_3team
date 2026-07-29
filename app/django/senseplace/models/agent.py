"""Agent 테이블 — 분석 워크플로우 단계.

기획서 Guarded Text-to-SQL Pipeline의 워크플로우 단계를
결정론적 시뮬레이션으로 표현한다. LLM 없이 고정된 단계 시나리오를 제공한다.
"""

from __future__ import annotations

import uuid

from django.db import models


class AgentWorkflowStep(models.Model):
    """분석 Agent 워크플로우 단계 (시뮬레이션).

    grain: step_id (PK)
    AgentPage의 분석 근거(TRACEABILITY) 패널에 표시되는
    워크플로우 단계를 관리한다.
    """

    STEP_STATUS_CHOICES = [
        ("COMPLETED", "완료"),
        ("IN_PROGRESS", "진행 중"),
        ("PENDING", "대기"),
    ]

    step_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="단계 ID",
    )
    step_order = models.PositiveIntegerField(
        help_text="실행 순서 (1부터)",
    )
    step_name = models.CharField(
        max_length=64,
        help_text="단계명 (예: 질문 해석)",
    )
    status = models.CharField(
        max_length=16,
        choices=STEP_STATUS_CHOICES,
        default="COMPLETED",
        help_text="단계 상태",
    )
    description = models.TextField(
        default="",
        blank=True,
        help_text="단계 설명",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="생성 시각 (UTC)",
    )

    class Meta:
        db_table = "agent_workflow_step"
        verbose_name = "Agent Workflow Step"
        verbose_name_plural = "Agent Workflow Steps"
        ordering = ["step_order"]

    def __str__(self) -> str:
        return f"{self.step_order}. {self.step_name} ({self.status})"
