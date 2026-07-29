"""Customer 테이블 — 고객 360 합성 뷰.

명세서 S09 crm_members, S18 member_grade_history, S04 pms_stays,
S07 pos_orders, VOC 데이터를 합친 Customer 360 표시용 뷰 모델이다.
기획서에서 고객 360은 "선택" 범위이며, 공통키·마스킹·권한 적용 후 조회한다.
"""

from __future__ import annotations

import uuid

from django.db import models


class CustomerProfile(models.Model):
    """고객 360 프로필 (합성 뷰).

    grain: customer_id (PK, 마스킹 ID)
    여러 소스(CRM·PMS·POS·VOC)를 합성한 고객 통합 프로필이다.
    개인정보 마스킹이 적용된 표시용 데이터만 저장한다.
    """

    customer_id = models.CharField(
        max_length=32,
        primary_key=True,
        help_text="마스킹된 고객 ID (예: CUS-84••12)",
    )
    display_name = models.CharField(
        max_length=32,
        help_text="마스킹된 표시명 (예: 김*현)",
    )
    member_no = models.CharField(
        max_length=36,
        blank=True,
        default="",
        help_text="CRM 회원 번호 참조",
    )
    tier_label = models.CharField(
        max_length=32,
        help_text="등급 라벨 (예: VIP Gold)",
    )
    stays_count = models.PositiveIntegerField(
        default=0,
        help_text="총 투숙 횟수",
    )
    revenue_display = models.CharField(
        max_length=32,
        help_text="누적 매출 표시 (예: ₩5,760,000)",
    )
    revisit_score = models.PositiveIntegerField(
        default=0,
        help_text="재방문 예측 점수 (0~100)",
    )
    sentiment_label = models.CharField(
        max_length=16,
        help_text="감성 라벨 (긍정/중립/부정)",
    )
    last_issue = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="최근 이슈",
    )
    last_stay_date = models.CharField(
        max_length=16,
        help_text="최근 투숙일 (예: 2026.07.18)",
    )
    preferred_room = models.CharField(
        max_length=64,
        help_text="선호 객실",
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
        db_table = "customer_profile"
        verbose_name = "Customer Profile"
        verbose_name_plural = "Customer Profiles"

    def __str__(self) -> str:
        return f"{self.display_name} ({self.customer_id})"
