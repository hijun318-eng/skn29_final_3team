"""Fact 테이블 — DSG v2.0 §6 기준.

- FactRoomsDaily: 객실 일별 운영
- FactBreakfast15m: 조식 15분 단위 집계
- FactBreakfastDaily: 조식 일별 집계
- FactStaffShift: 인력 시프트별 집계
- FactVoc: VOC 원본
"""

from __future__ import annotations

import uuid

from django.db import models

from .enums import SentimentLabelCode, ShiftCode, VocCategoryCode


class FactRoomsDaily(models.Model):
    """객실 일별 운영 (DB-010).

    grain: (dataset_version, service_date)
    rooms_available = room_inventory - rooms_out_of_order
    rooms_sold <= rooms_available
    rooms_unsold = rooms_available - rooms_sold (derived)
    """

    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전 FK",
    )
    service_date = models.DateField(
        help_text="서비스(영업)일",
    )
    room_inventory = models.PositiveIntegerField(
        help_text="객실 재고 수",
    )
    rooms_out_of_order = models.PositiveIntegerField(
        default=0,
        help_text="점검/고장 객실 수",
    )
    rooms_available = models.PositiveIntegerField(
        help_text="판매 가능 객실 수",
    )
    rooms_sold = models.PositiveIntegerField(
        default=0,
        help_text="판매된 객실 수",
    )
    inhouse_guests = models.PositiveIntegerField(
        default=0,
        help_text="투숙 인원",
    )
    breakfast_entitled_guests = models.PositiveIntegerField(
        default=0,
        help_text="조식 권리 인원",
    )

    class Meta:
        db_table = "fact_rooms_daily"
        verbose_name = "Fact Rooms Daily"
        verbose_name_plural = "Fact Rooms Daily"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_version", "service_date"],
                name="uq_fact_rooms_daily_dataset_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dataset_version} / {self.service_date}"


class FactBreakfast15m(models.Model):
    """조식 15분 단위 집계 (DB-011).

    grain: (dataset_version, service_area_id, bucket_start)
    bucket_start은 UTC timezone-aware.
    """

    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전 FK",
    )
    service_area_id = models.CharField(
        max_length=64,
        help_text="서비스 구역 ID FK",
    )
    bucket_start = models.DateTimeField(
        help_text="15분 버킷 시작 시각 (UTC)",
    )
    expected_arrivals = models.PositiveIntegerField(
        default=0,
        help_text="예상 도착 인원",
    )
    actual_arrivals = models.PositiveIntegerField(
        default=0,
        help_text="실제 도착 인원",
    )
    service_capacity = models.PositiveIntegerField(
        default=0,
        help_text="서비스 처리 용량",
    )
    seated_guests = models.PositiveIntegerField(
        default=0,
        help_text="좌석 배치 인원",
    )
    avg_wait_min = models.FloatField(
        default=0.0,
        help_text="평균 대기 시간 (분)",
    )
    p90_wait_min = models.FloatField(
        default=0.0,
        help_text="90분위 대기 시간 (분)",
    )
    max_queue_length = models.PositiveIntegerField(
        default=0,
        help_text="최대 대기열 길이",
    )

    class Meta:
        db_table = "fact_breakfast_15m"
        verbose_name = "Fact Breakfast 15m"
        verbose_name_plural = "Fact Breakfast 15m"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_version", "service_area_id", "bucket_start"],
                name="uq_fact_breakfast_15m",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dataset_version} / {self.service_area_id} / {self.bucket_start}"


class FactBreakfastDaily(models.Model):
    """조식 일별 집계 (DB-012).

    grain: (dataset_version, service_area_id, service_date)
    p90은 내부 시뮬레이션에서 직접 산출.
    """

    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전 FK",
    )
    service_area_id = models.CharField(
        max_length=64,
        help_text="서비스 구역 ID FK",
    )
    service_date = models.DateField(
        help_text="서비스(영업)일",
    )
    arrivals_total = models.PositiveIntegerField(
        default=0,
        help_text="일별 도착 합계",
    )
    capacity_total = models.PositiveIntegerField(
        default=0,
        help_text="일별 처리 용량 합계",
    )
    avg_wait_min = models.FloatField(
        default=0.0,
        help_text="일별 평균 대기 시간 (분)",
    )
    p90_wait_min = models.FloatField(
        default=0.0,
        help_text="일별 90분위 대기 시간 (분)",
    )
    voc_negative_count = models.PositiveIntegerField(
        default=0,
        help_text="부정 VOC 건수",
    )

    class Meta:
        db_table = "fact_breakfast_daily"
        verbose_name = "Fact Breakfast Daily"
        verbose_name_plural = "Fact Breakfast Daily"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_version", "service_area_id", "service_date"],
                name="uq_fact_breakfast_daily",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dataset_version} / {self.service_area_id} / {self.service_date}"


class FactStaffShift(models.Model):
    """인력 시프트별 집계 (DB-013).

    grain: (dataset_version, service_date, service_area_id, shift_code)
    직원 identity·사유는 금지.
    """

    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전 FK",
    )
    service_date = models.DateField(
        help_text="서비스(영업)일",
    )
    service_area_id = models.CharField(
        max_length=64,
        help_text="서비스 구역 ID FK",
    )
    shift_code = models.CharField(
        max_length=8,
        choices=ShiftCode.CHOICES,
        help_text="시프트 코드 (AM/PM/FULL)",
    )
    planned_headcount = models.PositiveIntegerField(
        default=0,
        help_text="계획 인원",
    )
    actual_headcount = models.PositiveIntegerField(
        default=0,
        help_text="실제 인원",
    )
    absence_count = models.PositiveIntegerField(
        default=0,
        help_text="결근 인원",
    )
    labor_minutes = models.PositiveIntegerField(
        default=0,
        help_text="총 노동 시간 (분)",
    )

    class Meta:
        db_table = "fact_staff_shift"
        verbose_name = "Fact Staff Shift"
        verbose_name_plural = "Fact Staff Shifts"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_version", "service_date", "service_area_id", "shift_code"],
                name="uq_fact_staff_shift",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dataset_version} / {self.service_date} / {self.shift_code}"


class FactVoc(models.Model):
    """VOC 원본 (DB-014).

    grain: voc_id (PK)
    review_text는 합성·비식별 텍스트. PII 금지.
    occurred_at <= received_at
    """

    voc_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="VOC 고유 ID",
    )
    dataset_version = models.CharField(
        max_length=128,
        help_text="데이터셋 버전 FK",
    )
    received_at = models.DateTimeField(
        help_text="VOC 접수 시각 (UTC)",
    )
    occurred_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="실제 경험 시각 (UTC), 없으면 received_at만 표시",
    )
    service_area_id = models.CharField(
        max_length=64,
        help_text="서비스 구역 ID FK",
    )
    topic_code = models.CharField(
        max_length=32,
        choices=VocCategoryCode.CHOICES,
        help_text="VOC 주제 코드",
    )
    sentiment_label = models.CharField(
        max_length=16,
        choices=SentimentLabelCode.CHOICES,
        help_text="고객 감성 레이블",
    )
    review_text = models.TextField(
        help_text="합성·비식별 리뷰 텍스트",
    )
    is_synthetic = models.BooleanField(
        default=True,
        help_text="합성 데이터 여부",
    )

    class Meta:
        db_table = "fact_voc"
        verbose_name = "Fact VOC"
        verbose_name_plural = "Fact VOCs"

    def __str__(self) -> str:
        return str(self.voc_id)
