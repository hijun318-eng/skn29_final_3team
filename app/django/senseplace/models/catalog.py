"""Catalog 테이블 — 데이터 제품 카탈로그.

명세서에 독립 테이블이 없으나, 기획서의 "데이터 제품" 개념과
DataHub 자산(asset) 표시를 지원하기 위한 합성 테이블이다.
CTX01 context_records의 asset_binding과 간접 연관된다.
"""

from __future__ import annotations

import uuid

from django.db import models

from .enums import SensitivityCode


class DataProduct(models.Model):
    """데이터 제품 카탈로그 (합성).

    grain: data_product_id (PK)
    CatalogPage에서 데이터 제품 목록을 표시한다.
    DataHub 자산 URN과 Trino FQN을 참조한다.
    """

    data_product_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="데이터 제품 ID",
    )
    product_name = models.CharField(
        max_length=160,
        help_text="제품명 (예: Reservation Fact)",
    )
    source_name = models.CharField(
        max_length=120,
        help_text="원천 소스명",
    )
    catalog_ref = models.CharField(
        max_length=128,
        help_text="catalog 참조 (예: pms.reservation)",
    )
    domain = models.CharField(
        max_length=64,
        help_text="업무 도메인",
    )
    owner_team = models.CharField(
        max_length=100,
        help_text="담당 조직",
    )
    freshness_label = models.CharField(
        max_length=32,
        help_text="최신성 라벨 (예: 1분)",
    )
    quality_score = models.PositiveIntegerField(
        default=0,
        help_text="품질 점수 (0~100)",
    )
    sensitivity = models.CharField(
        max_length=16,
        choices=SensitivityCode.CHOICES,
        default=SensitivityCode.INTERNAL,
        help_text="민감도 (Internal/Restricted/Confidential)",
    )
    tool_name = models.CharField(
        max_length=64,
        help_text="사용 Tool명",
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
        db_table = "data_products"
        verbose_name = "Data Product"
        verbose_name_plural = "Data Products"

    def __str__(self) -> str:
        return f"{self.product_name} ({self.catalog_ref})"
