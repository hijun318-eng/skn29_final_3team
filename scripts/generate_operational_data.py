"""SensePlace 운영 더미 데이터 생성 스크립트.

DSG v2.0 스키마 기반 결정론적 합성 데이터를 생성하여:
1. data/raw/ 에 CSV 원본 저장
2. SQLite DB에 INSERT

Usage:
    cd app/django
    .venv\Scripts\python.exe ..\..\scripts\generate_operational_data.py
"""

from __future__ import annotations

import csv
import json
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

SEED = 42
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "app" / "django" / "db.sqlite3"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATASET_VERSION = "2.0.0-synthetic"

# 목업 v1.2 ZONES 기반 서비스 구역
SERVICE_AREAS = [
    ("SA-RM-001", "그랜드 워커힐 (객실동)"),
    ("SA-RM-002", "비스타 워커힐 (객실동)"),
    ("SA-RM-003", "더글라스 하우스 (객실동)"),
    ("SA-RM-004", "애스톤 하우스 (객실동)"),
    ("SA-DN-001", "피자힐 (다이닝)"),
    ("SA-DN-002", "명월관 (다이닝)"),
    ("SA-LW-001", "리버파크 (레저·웰니스)"),
    ("SA-LW-002", "테네즈 파크 (레저·웰니스)"),
    ("SA-LW-003", "포레스트 파크 (레저·웰니스)"),
    ("SA-ME-001", "컨벤션 센터 (MICE·엔터)"),
    ("SA-IF-001", "주차타워 (인프라)"),
]

VOC_TOPICS = ["청결·위생", "안전", "대기·혼잡", "직원 서비스", "시설 고장", "소음", "온도·환경", "가격·결제", "예약·안내"]
VOC_TEMPLATES_NEG = [
    "객실 청소 상태가 불량했습니다. {area}",
    "체크인 대기 시간이 너무 깁니다. {area}",
    "직원 응대가 불친절했습니다. {area}",
    "에어컨 소음이 심해 수면에 지장이 있었습니다. {area}",
    "조식 대기 시간이 30분 이상이었습니다. {area}",
    "시설 고장 신고 후 처리가 늦었습니다. {area}",
]
VOC_TEMPLATES_POS = [
    "직원이 매우 친절했습니다. {area}",
    "시설이 깨끗하고 쾌적했습니다. {area}",
    "조식 품질이 우수했습니다. {area}",
    "전반적으로 만족스러운 숙박이었습니다. {area}",
]
VOC_TEMPLATES_NEU = [
    "보통이었습니다. 특별한 문제는 없습니다. {area}",
    "평범한 이용이었습니다. {area}",
]

# ---------------------------------------------------------------------------
# 데이터 생성 함수 (결정론적)
# ---------------------------------------------------------------------------

def generate_dim_date(start: datetime, weeks: int = 8) -> list[dict]:
    """날짜 차원 테이블."""
    rows = []
    day_names = ["월", "화", "수", "목", "금", "토", "일"]
    for i in range(weeks * 7):
        d = start + timedelta(days=i)
        dow = d.weekday()
        rows.append({
            "service_date": d.strftime("%Y-%m-%d"),
            "day_of_week": day_names[dow],
            "is_weekend": 1 if dow >= 5 else 0,
            "virtual_week_id": f"VW-{d.isocalendar().week:02d}",
        })
    return rows


def generate_dim_service_area() -> list[dict]:
    """서비스 구역 차원."""
    return [
        {"service_area_id": sid, "display_name": name, "is_synthetic": 1}
        for sid, name in SERVICE_AREAS
    ]


def generate_fact_voc(rnd: random.Random, dates: list[dict], areas: list[dict]) -> list[dict]:
    """VOC 팩트 — 일평균 5~15건, 시나리오 비율 적용."""
    rows = []
    voc_seq = 1
    for d in dates:
        daily_count = rnd.randint(5, 15)
        # 주말은 VOC 증가
        if d["is_weekend"]:
            daily_count = int(daily_count * 1.3)
        for _ in range(daily_count):
            area = rnd.choice(areas)
            rnd_val = rnd.random()
            if rnd_val < 0.35:
                template = rnd.choice(VOC_TEMPLATES_NEG)
                sentiment = "NEGATIVE"
            elif rnd_val < 0.65:
                template = rnd.choice(VOC_TEMPLATES_POS)
                sentiment = "POSITIVE"
            else:
                template = rnd.choice(VOC_TEMPLATES_NEU)
                sentiment = "NEUTRAL"

            received = d["service_date"] + f" {rnd.randint(6,23):02d}:{rnd.randint(0,59):02d}:00"
            occurred = d["service_date"] + f" {rnd.randint(6,23):02d}:{rnd.randint(0,59):02d}:00"
            rows.append({
                "voc_id": f"VOC-2026-{voc_seq:05d}",
                "dataset_version": DATASET_VERSION,
                "received_at": received,
                "occurred_at": occurred,
                "service_area_id": area["service_area_id"],
                "topic_code": rnd.choice(VOC_TOPICS),
                "sentiment_label": sentiment,
                "review_text": template.format(area=area["display_name"]),
                "is_synthetic": 1,
            })
            voc_seq += 1
    return rows


def generate_fact_rooms_daily(rnd: random.Random, dates: list[dict]) -> list[dict]:
    """일일 객실 팩트."""
    rows = []
    seq = 1
    for d in dates:
        inventory = 800 + rnd.randint(-10, 10)
        ooo = rnd.randint(5, 25)
        available = inventory - ooo
        occupancy = rnd.uniform(0.65, 0.95)
        if d["is_weekend"]:
            occupancy = min(0.98, occupancy + 0.05)
        sold = int(available * occupancy)
        inhouse = sold + rnd.randint(-5, 5)
        breakfast = int(inhouse * rnd.uniform(0.75, 0.90))
        rows.append({
            "id": seq,
            "dataset_version": DATASET_VERSION,
            "service_date": d["service_date"],
            "room_inventory": inventory,
            "rooms_out_of_order": ooo,
            "rooms_available": available,
            "rooms_sold": sold,
            "inhouse_guests": max(0, inhouse),
            "breakfast_entitled_guests": max(0, breakfast),
        })
        seq += 1
    return rows


def generate_fact_breakfast_daily(rnd: random.Random, dates: list[dict], areas: list[dict]) -> list[dict]:
    """일일 조식 팩트 (다이닝 구역만)."""
    dining_areas = [a for a in areas if a["service_area_id"].startswith("SA-DN")]
    rows = []
    seq = 1
    for d in dates:
        for area in dining_areas:
            arrivals = rnd.randint(150, 400)
            if d["is_weekend"]:
                arrivals = int(arrivals * 1.2)
            capacity = rnd.randint(200, 350)
            avg_wait = rnd.uniform(3, 25)
            p90_wait = avg_wait * rnd.uniform(1.3, 2.0)
            neg_count = max(0, int((avg_wait - 10) * rnd.uniform(0.5, 2.0))) if avg_wait > 10 else rnd.randint(0, 2)
            rows.append({
                "id": seq,
                "dataset_version": DATASET_VERSION,
                "service_area_id": area["service_area_id"],
                "service_date": d["service_date"],
                "arrivals_total": arrivals,
                "capacity_total": capacity,
                "avg_wait_min": round(avg_wait, 1),
                "p90_wait_min": round(p90_wait, 1),
                "voc_negative_count": neg_count,
            })
            seq += 1
    return rows


def generate_fact_breakfast_15m(rnd: random.Random, dates: list[dict], areas: list[dict]) -> list[dict]:
    """15분 단위 조식 팩트 (피크 시간 06:00~10:00)."""
    dining_areas = [a for a in areas if a["service_area_id"].startswith("SA-DN")]
    rows = []
    seq = 1
    for d in dates:
        for area in dining_areas:
            for hour in range(6, 10):
                for minute in [0, 15, 30, 45]:
                    bucket = f"{d['service_date']} {hour:02d}:{minute:02d}:00"
                    expected = rnd.randint(10, 60)
                    if hour in (7, 8):
                        expected = int(expected * 1.5)
                    actual = expected + rnd.randint(-5, 5)
                    capacity = rnd.randint(30, 50)
                    seated = min(actual, capacity) + rnd.randint(-3, 3)
                    avg_wait = rnd.uniform(1, 20)
                    p90_wait = avg_wait * rnd.uniform(1.2, 1.8)
                    rows.append({
                        "id": seq,
                        "dataset_version": DATASET_VERSION,
                        "service_area_id": area["service_area_id"],
                        "bucket_start": bucket,
                        "expected_arrivals": max(0, expected),
                        "actual_arrivals": max(0, actual),
                        "service_capacity": capacity,
                        "seated_guests": max(0, seated),
                        "avg_wait_min": round(avg_wait, 1),
                        "p90_wait_min": round(p90_wait, 1),
                        "max_queue_length": max(0, rnd.randint(0, 15)),
                    })
                    seq += 1
    return rows


def generate_fact_staff_shift(rnd: random.Random, dates: list[dict], areas: list[dict]) -> list[dict]:
    """직원 교대 팩트."""
    shifts = [("S1", "조식"), ("S2", "런치"), ("S3", "디너"), ("S4", "야간")]
    rows = []
    seq = 1
    for d in dates:
        for area in areas:
            for shift_code, _ in shifts:
                planned = rnd.randint(5, 20)
                actual = planned - rnd.randint(0, 3)
                absence = planned - actual
                labor = actual * rnd.randint(4, 8) * 60
                rows.append({
                    "id": seq,
                    "dataset_version": DATASET_VERSION,
                    "service_date": d["service_date"],
                    "service_area_id": area["service_area_id"],
                    "shift_code": shift_code,
                    "planned_headcount": planned,
                    "actual_headcount": actual,
                    "absence_count": absence,
                    "labor_minutes": labor,
                })
                seq += 1
    return rows


def _to_json_list(s: str) -> str:
    """쉼표 구분 문자열을 JSON 배열 문자열로 변환."""
    return json.dumps([x.strip() for x in s.split(",")])


def generate_metric_catalog() -> list[dict]:
    """지표 카탈로그."""
    metrics = [
        ("M-VOC-NEG-RATIO", "VOC 부정 비율", "전체 VOC 중 NEGATIVE 감성 비율", "%", False, "daily,weekly", "service_area,topic", "voc부정률,부정VOC", "fact_voc", "2.0"),
        ("M-OCCUPANCY", "객실 가동률", "판매 객실 / 가용 객실", "%", False, "daily,weekly", "hotel", "가동률,occ", "fact_rooms_daily", "2.0"),
        ("M-BF-AVG-WAIT", "조식 평균 대기시간", "조식 식당 평균 대기시간", "min", False, "daily,15m", "service_area", "대기시간,wait", "fact_breakfast_daily", "2.0"),
        ("M-BF-P90-WAIT", "조식 P90 대기시간", "조식 식당 90백분위 대기시간", "min", False, "daily,15m", "service_area", "p90,퍼센타일", "fact_breakfast_daily", "2.0"),
        ("M-STAFF-ABSENCE", "직원 결근률", "결근 인원 / 계획 인원", "%", False, "daily", "service_area,shift", "결근,absence", "fact_staff_shift", "2.0"),
        ("M-VOC-VOLUME", "VOC 건수", "접수된 VOC 총 건수", "count", True, "daily,weekly", "service_area,topic,sentiment", "voc건수,volume", "fact_voc", "2.0"),
    ]
    return [
        {"metric_code": m[0], "display_name": m[1], "definition": m[2], "unit": m[3],
         "additive": 1 if m[4] else 0, "allowed_grains": _to_json_list(m[5]),
         "allowed_dimensions": _to_json_list(m[6]),
         "synonyms": _to_json_list(m[7]), "source_view": m[8], "version": m[9]}
        for m in metrics
    ]


def generate_role_scope() -> list[dict]:
    """역할별 권한 스코프."""
    rows = []
    seq = 1
    roles = [
        ("OPERATIONS_MANAGER", ["fact_voc", "fact_rooms_daily", "fact_breakfast_daily", "report", "evidence"]),
        ("FACILITY_MANAGER", ["fact_voc", "fact_rooms_daily", "fact_breakfast_daily"]),
        ("EXTERNAL_REVIEWER", ["report"]),
    ]
    for role, resources in roles:
        for res in resources:
            rows.append({
                "id": seq,
                "role_code": role,
                "resource_type": "table",
                "resource_code": res,
                "allowed": 1,
                "scope_version": "1.0",
            })
            seq += 1
    return rows


def generate_dataset_manifest(start: datetime, end: datetime) -> list[dict]:
    """데이터셋 메타데이터."""
    return [{
        "dataset_version": DATASET_VERSION,
        "schema_version": "2.0",
        "generator_version": "0.1.0",
        "seed": SEED,
        "scenario_id": "operational-baseline",
        "virtual_period_start": start.strftime("%Y-%m-%d"),
        "virtual_period_end": end.strftime("%Y-%m-%d"),
        "virtual_as_of_date": end.strftime("%Y-%m-%d"),
        "data_cutoff": end.strftime("%Y-%m-%d"),
        "is_synthetic": 1,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }]


# ---------------------------------------------------------------------------
# CSV 저장
# ---------------------------------------------------------------------------

def save_csv(filename: str, rows: list[dict]) -> None:
    if not rows:
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    filepath = RAW_DIR / filename
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [CSV] {filepath.name}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# DB INSERT
# ---------------------------------------------------------------------------

def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cursor = conn.cursor()
    cols = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})"
    data = [tuple(r[c] for c in cols) for r in rows]
    cursor.executemany(sql, data)
    conn.commit()
    print(f"  [DB]  {table}: {len(rows)} rows inserted")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"=== SensePlace 운영 더미 데이터 생성 (seed={SEED}) ===\n")

    rnd = random.Random(SEED)
    start = datetime(2026, 6, 1)
    end = start + timedelta(days=8 * 7 - 1)  # 8주

    # 1. 데이터 생성
    print("[1/3] 데이터 생성 중...")
    dates = generate_dim_date(start, 8)
    areas = generate_dim_service_area()
    vocs = generate_fact_voc(rnd, dates, areas)
    rooms = generate_fact_rooms_daily(rnd, dates)
    bf_daily = generate_fact_breakfast_daily(rnd, dates, areas)
    bf_15m = generate_fact_breakfast_15m(rnd, dates, areas)
    staff = generate_fact_staff_shift(rnd, dates, areas)
    metrics = generate_metric_catalog()
    role_scope = generate_role_scope()
    manifest = generate_dataset_manifest(start, end)

    datasets = {
        "dim_date": dates,
        "dim_service_area": areas,
        "fact_voc": vocs,
        "fact_rooms_daily": rooms,
        "fact_breakfast_daily": bf_daily,
        "fact_breakfast_15m": bf_15m,
        "fact_staff_shift": staff,
        "metric_catalog": metrics,
        "role_scope": role_scope,
        "dataset_manifest": manifest,
    }

    print(f"  dim_date: {len(dates)} rows")
    print(f"  dim_service_area: {len(areas)} rows")
    print(f"  fact_voc: {len(vocs)} rows")
    print(f"  fact_rooms_daily: {len(rooms)} rows")
    print(f"  fact_breakfast_daily: {len(bf_daily)} rows")
    print(f"  fact_breakfast_15m: {len(bf_15m)} rows")
    print(f"  fact_staff_shift: {len(staff)} rows")
    print(f"  metric_catalog: {len(metrics)} rows")
    print(f"  role_scope: {len(role_scope)} rows")
    print(f"  dataset_manifest: {len(manifest)} rows")

    # 2. CSV 저장
    print(f"\n[2/3] CSV 저장 → {RAW_DIR}")
    for name, rows in datasets.items():
        save_csv(f"{name}.csv", rows)

    # 3. DB INSERT
    print(f"\n[3/3] DB INSERT → {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        for table, rows in datasets.items():
            insert_rows(conn, table, rows)
    finally:
        conn.close()

    print(f"\n=== 완료: {sum(len(r) for r in datasets.values())} rows 총 생성 ===")
    print(f"Raw 데이터: {RAW_DIR}")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    sys.exit(main())
