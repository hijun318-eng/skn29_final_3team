"""Metadata 테이블 — DSG v2.0 §5 기준.

- dataset_manifest: 데이터셋 추적 메타데이터
- DimDate: 가상 영업일 달력
- DimServiceArea: 서비스 구역 차원
"""

from __future__ import annotations

import uuid

from django.db import models


class DatasetManifest(models.Model):
    """데이터셋 추적 메타데이터 (DB-001).

    is_synthetic=true가 원칙이며, overwrite 금지.
    """

    dataset_version = models.CharField(
        max_length=128,
        primary_key=True,
        help_text="데이터셋 버전 (예: gw-synthetic-1.0.0)",
    )
    schema_version = models.CharField(
        max_length=32,
        help_text="스키마 버전",
    )
    generator_version = models.CharField(
        max_length=64,
        help_text="생성기 버전",
    )
    seed = models.BigIntegerField(
        help_text="생성기 seed",
    )
    scenario_id = models.CharField(
        max_length=64,
        help_text="시나리오 ID",
    )
    virtual_period_start = models.DateField(
        help_text="가상 기간 시작일",
    )
    virtual_period_end = models.DateField(
        help_text="가상 기간 종료일",
    )
    virtual_as_of_date = models.DateField(
        help_text="가상 기준일",
    )
    data_cutoff = models.DateTimeField(
        help_text="데이터 컷오프 시각 (UTC)",
    )
    is_synthetic = models.BooleanField(
        default=True,
        help_text="합성 데이터 여부",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="레코드 생성 시각 (UTC)",
    )

    class Meta:
        db_table = "dataset_manifest"
        verbose_name = "Dataset Manifest"
        verbose_name_plural = "Dataset Manifests"

    def __str__(self) -> str:
        return self.dataset_version


class DimDate(models.Model):
    """가상 영업일 달력 (DB-002).

    Baseline 기간만 사용하며, 실제 날짜와 매핑한다.
    """

    service_date = models.DateField(
        primary_key=True,
        help_text="서비스(영업)일",
    )
    day_of_week = models.CharField(
        max_length=3,
        help_text="요일 약자 (Mon, Tue, ...)",
    )
    is_weekend = models.BooleanField(
        default=False,
        help_text="주말 여부",
    )
    virtual_week_id = models.CharField(
        max_length=16,
        help_text="가상 주차 ID (예: W01)",
    )

    class Meta:
        db_table = "dim_date"
        verbose_name = "Dim Date"
        verbose_name_plural = "Dim Dates"

    def __str__(self) -> str:
        return str(self.service_date)


class DimServiceArea(models.Model):
    """서비스 구역 차원 (DB-003).

    Baseline ID는 GW_BREAKFAST_DEMO.
    """

    service_area_id = models.CharField(
        max_length=64,
        primary_key=True,
        help_text="서비스 구역 ID (예: GW_BREAKFAST_DEMO)",
    )
    display_name = models.CharField(
        max_length=128,
        help_text="표시 이름",
    )
    is_synthetic = models.BooleanField(
        default=True,
        help_text="합성 데이터 여부",
    )

    class Meta:
        db_table = "dim_service_area"
        verbose_name = "Dim Service Area"
        verbose_name_plural = "Dim Service Areas"

    def __str__(self) -> str:
        return self.display_name
