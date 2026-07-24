"""SensePlace 결정론적 합성 fixture 생성기.

DSG v2.0 (데이터 표준 가이드) 16 table 스키마를 기반으로
seed=42 고정 분포를 사용하여 재현 가능한 합성 데이터를 생성한다.

Usage:
    python data/samples/generate_fixtures.py

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0)
    - docs/markdown/ai_docs/SensePlace_목업_v1.2.html (ZONES, CATS)
    - src/common/enums.py (Role, Severity, JobStatus, SentimentLabel)
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEED = 42
GENERATOR_VERSION = "0.1.0"
SCHEMA_VERSION = "2.0"
PROPERTY_ID = "GRAND_WALKERHILL_SEOUL"
SERVICE_AREA_ID = "GW_BREAKFAST_DEMO"
STORAGE_TZ = "UTC"
DISPLAY_TZ = "Asia/Seoul"
CURRENCY = "KRW"

# 목업 v1.2 ZONES 온톨로지 (SensePlace_목업_v1.2.html)
ZONES: dict[str, list[str]] = {
    "객실동": ["그랜드 워커힐", "비스타 워커힐", "더글라스 하우스", "애스톤 하우스"],
    "다이닝": ["피자힐", "명월관"],
    "레저·웰니스": [
        "리버파크",
        "테네즈 파크",
        "포레스트 파크",
        "힐링 포레스트",
        "더글라스 가든",
        "워커힐 골프클럽",
    ],
    "MICE·엔터": ["컨벤션 센터", "빛의 시어터", "Casino"],
    "인프라": ["주차타워", "South Gate", "East Gate"],
}

# 목업 v1.2 CATS 온톨로지
CATS: list[str] = [
    "청결·위생",
    "안전",
    "대기·혼잡",
    "직원 서비스",
    "시설 고장",
    "소음",
    "온도·환경",
    "가격·결제",
    "예약·안내",
]

# 시설 ID 접두사 매핑
ZONE_PREFIX: dict[str, str] = {
    "객실동": "HTL",
    "다이닝": "DIN",
    "레저·웰니스": "LWR",
    "MICE·엔터": "MCE",
    "인프라": "INF",
}

# 합성 VOC 템플릿 (PII 없음)
VOC_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "청결·위생": [
        {"text": "객실 청소 상태가 기대에 미치지 못했습니다.", "sentiment": "NEGATIVE"},
        {"text": "화장실 위생 상태가 양호했습니다.", "sentiment": "POSITIVE"},
    ],
    "안전": [
        {"text": "복도 조명이 어두워서 안전 우려가 있습니다.", "sentiment": "NEGATIVE"},
        {"text": "비상구 안내가 잘 되어 있어 안심했습니다.", "sentiment": "POSITIVE"},
    ],
    "대기·혼잡": [
        {"text": "체크인 대기가 너무 오래 걸렸습니다.", "sentiment": "NEGATIVE"},
        {"text": "레스토랑 대기 없이 바로 입장했습니다.", "sentiment": "POSITIVE"},
    ],
    "직원 서비스": [
        {"text": "직원 응대가 친절하고 전문적이었습니다.", "sentiment": "POSITIVE"},
        {"text": "직원 문의 응답이 느렸습니다.", "sentiment": "NEGATIVE"},
    ],
    "시설 고장": [
        {"text": "에어컨 온도 조절이 되지 않았습니다.", "sentiment": "NEGATIVE"},
        {"text": "시설이 모두 정상 작동했습니다.", "sentiment": "POSITIVE"},
    ],
    "소음": [
        {"text": "옆 객실 소음이 심해서 숙면을 취하기 어려웠습니다.", "sentiment": "NEGATIVE"},
        {"text": "방음 상태가 좋아 편안했습니다.", "sentiment": "POSITIVE"},
    ],
    "온도·환경": [
        {"text": "객실 온도가 너무 높아 불편했습니다.", "sentiment": "NEGATIVE"},
        {"text": "적절한 온도 유지로 쾌적했습니다.", "sentiment": "POSITIVE"},
    ],
    "가격·결제": [
        {"text": "가격 대비 서비스가 부족하다고 느꼈습니다.", "sentiment": "NEGATIVE"},
        {"text": "합리적인 가격에 좋은 서비스였습니다.", "sentiment": "POSITIVE"},
    ],
    "예약·안내": [
        {"text": "예약 확인 과정이 혼란스러웠습니다.", "sentiment": "NEGATIVE"},
        {"text": "시설 안내가 명확하고 편리했습니다.", "sentiment": "POSITIVE"},
    ],
}


def _uuid(seed_extra: str = "") -> str:
    """결정론적 UUID v5 생성."""
    ns = uuid.UUID("12345678-1234-5678-1234-567812345678")
    return str(uuid.uuid5(ns, f"{SEED}:{seed_extra}"))


def _ts(dt: datetime) -> str:
    """ISO 8601 UTC 문자열."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Generator functions (각 테이블별)
# ---------------------------------------------------------------------------

def gen_manifest() -> dict[str, Any]:
    """dataset_manifest 생성."""
    return {
        "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "is_synthetic": True,
        "property_id": PROPERTY_ID,
        "storage_timezone": STORAGE_TZ,
        "display_timezone": DISPLAY_TZ,
        "currency": CURRENCY,
        "virtual_period_start": "2026-07-14T00:00:00Z",
        "virtual_period_end": "2026-07-20T23:59:59Z",
        "virtual_as_of_date": "2026-07-20",
        "data_cutoff": "2026-07-20T23:59:59Z",
        "created_at": "2026-07-20T12:00:00Z",
        "scenarios": ["NORMAL", "CRITICAL", "LOCK"],
        "pii_check": "passed",
        "total_tables": 16,
    }


def gen_dim_date(rng: random.Random) -> list[dict[str, Any]]:
    """dim_date: 12주 (84일) 가상 기간."""
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    for i in range(84):
        d = start + timedelta(days=i)
        dow = d.strftime("%A")
        is_weekend = dow in ("Saturday", "Sunday")
        week_id = f"W{(i // 7) + 1:02d}"
        rows.append({
            "service_date": d.strftime("%Y-%m-%d"),
            "day_of_week": dow,
            "is_weekend": is_weekend,
            "virtual_week_id": week_id,
        })
    return rows


def gen_dim_service_area() -> list[dict[str, Any]]:
    """dim_service_area: ZONES 기반 전체 시설."""
    rows: list[dict[str, Any]] = []
    idx = 1
    for zone, facilities in ZONES.items():
        for fac in facilities:
            prefix = ZONE_PREFIX[zone]
            rows.append({
                "service_area_id": f"{prefix}-{idx:03d}",
                "display_name": fac,
                "zone": zone,
                "is_synthetic": True,
            })
            idx += 1
    return rows


def gen_hotels(rng: random.Random) -> list[dict[str, Any]]:
    """호텔/시설 마스터 데이터 (ZONES 전체 포함)."""
    areas = gen_dim_service_area()
    rooms_base = [120, 85, 60, 55, 0, 0, 0, 0, 0, 0, 0, 0, 200, 0, 0, 800, 0, 0]
    rows: list[dict[str, Any]] = []
    for i, area in enumerate(areas):
        zone_name = area["zone"]
        fac_name = area["display_name"]
        is_accommodation = zone_name == "객실동"
        is_dining = zone_name == "다이닝"
        is_leisure = zone_name == "레저·웰니스"
        is_mice = zone_name == "MICE·엔터"
        is_infra = zone_name == "인프라"

        if is_accommodation:
            capacity = rooms_base[i] + rng.randint(-10, 10)
        elif is_dining:
            capacity = rng.randint(60, 150)
        elif is_leisure:
            capacity = rng.randint(30, 200)
        elif is_mice:
            capacity = rng.randint(100, 500)
        else:
            capacity = rng.randint(50, 300)

        rows.append({
            "hotel_id": area["service_area_id"],
            "name": fac_name,
            "zone": zone_name,
            "capacity": max(capacity, 1),
            "is_synthetic": True,
        })
    return rows


def gen_fact_rooms_daily(rng: random.Random) -> list[dict[str, Any]]:
    """fact_rooms_daily: 객실동 4개 호텔 × 84일."""
    hotel_ids = ["HTL-001", "HTL-002", "HTL-003", "HTL-004"]
    inventories = [120, 85, 60, 55]
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)

    for h_idx, (hid, inv) in enumerate(zip(hotel_ids, inventories)):
        for day in range(84):
            d = start + timedelta(days=day)
            is_weekend = d.weekday() >= 5
            ooo = rng.randint(0, max(1, inv // 15))
            available = inv - ooo
            # 주말에 점유율 높음
            occ_rate = rng.uniform(0.75, 0.95) if is_weekend else rng.uniform(0.55, 0.80)
            sold = min(available, int(available * occ_rate))
            inhouse = sold + rng.randint(0, max(1, sold // 10))
            breakfast = rng.randint(max(1, sold - 5), sold)

            rows.append({
                "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
                "hotel_id": hid,
                "service_date": d.strftime("%Y-%m-%d"),
                "room_inventory": inv,
                "rooms_out_of_order": ooo,
                "rooms_available": available,
                "rooms_sold": sold,
                "inhouse_guests": inhouse,
                "breakfast_entitled_guests": breakfast,
                "rooms_unsold": available - sold,
            })
    return rows


def gen_fact_breakfast_15m(rng: random.Random) -> list[dict[str, Any]]:
    """fact_breakfast_15m: GW_BREAKFAST_DEMO × 84일 × 32buckets(06:00~14:00)."""
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    capacity = 40

    for day in range(84):
        d = start + timedelta(days=day)
        is_weekend = d.weekday() >= 5
        queue = 0
        for bucket in range(32):  # 06:00 ~ 14:00, 15분 간격
            hour = 6 + bucket // 4
            minute = (bucket % 4) * 15
            bucket_start = d.replace(hour=hour, minute=minute)

            # 피크: 07:30~09:30
            if 7 <= hour < 10:
                base_arrivals = rng.randint(8, 18) if is_weekend else rng.randint(5, 12)
            else:
                base_arrivals = rng.randint(1, 5)

            actual = min(base_arrivals, rng.randint(max(1, base_arrivals - 3), base_arrivals))
            expected = actual + rng.randint(0, 3)
            seated = min(capacity, rng.randint(max(1, capacity - 10), capacity))
            queue = max(0, queue + actual - capacity)
            avg_wait = round(rng.uniform(2, 15) + queue * 0.5, 1)
            p90_wait = round(avg_wait * rng.uniform(1.3, 2.0), 1)
            max_queue = queue + rng.randint(0, 5)

            rows.append({
                "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
                "service_area_id": SERVICE_AREA_ID,
                "bucket_start": _ts(bucket_start),
                "expected_arrivals": expected,
                "actual_arrivals": actual,
                "service_capacity": capacity,
                "seated_guests": seated,
                "avg_wait_min": avg_wait,
                "p90_wait_min": p90_wait,
                "max_queue_length": max_queue,
            })
    return rows


def gen_fact_breakfast_daily(rng: random.Random) -> list[dict[str, Any]]:
    """fact_breakfast_daily."""
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)

    for day in range(84):
        d = start + timedelta(days=day)
        is_weekend = d.weekday() >= 5
        total = rng.randint(180, 350) if is_weekend else rng.randint(120, 250)
        cap = 40 * 8  # 8시간 × 40석
        avg_w = round(rng.uniform(5, 12), 1)
        p90_w = round(avg_w * rng.uniform(1.4, 2.2), 1)
        voc_neg = rng.randint(0, 3)

        rows.append({
            "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
            "service_area_id": SERVICE_AREA_ID,
            "service_date": d.strftime("%Y-%m-%d"),
            "arrivals_total": total,
            "capacity_total": cap,
            "avg_wait_min": avg_w,
            "p90_wait_min": p90_w,
            "voc_negative_count": voc_neg,
        })
    return rows


def gen_fact_staff_shift(rng: random.Random) -> list[dict[str, Any]]:
    """fact_staff_shift."""
    shifts = ["AM", "PM", "SWING"]
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)

    for day in range(84):
        d = start + timedelta(days=day)
        for code in shifts:
            planned = rng.randint(4, 10)
            absence = rng.randint(0, 2)
            actual = max(1, planned - absence)
            labor = actual * (8 if code != "SWING" else 6) * 60

            rows.append({
                "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
                "service_date": d.strftime("%Y-%m-%d"),
                "service_area_id": SERVICE_AREA_ID,
                "shift_code": code,
                "planned_headcount": planned,
                "actual_headcount": actual,
                "absence_count": absence,
                "labor_minutes": labor,
            })
    return rows


def gen_fact_voc(
    rng: random.Random,
    *,
    negative_ratio: float = 0.15,
    count: int = 84,
) -> list[dict[str, Any]]:
    """fact_voc: CATS 기반 합성 VOC. negative_ratio로 감성 분포 제어."""
    areas = gen_dim_service_area()
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)

    for i in range(count):
        cat = rng.choice(CATS)
        templates = VOC_TEMPLATES[cat]
        # negative_ratio에 따라 감성 선택
        if rng.random() < negative_ratio:
            t = next((t for t in templates if t["sentiment"] == "NEGATIVE"), templates[0])
        else:
            t = next((t for t in templates if t["sentiment"] == "POSITIVE"), templates[-1])

        area = rng.choice(areas)
        day_offset = rng.randint(0, 83)
        hour = rng.randint(6, 22)
        minute = rng.randint(0, 59)
        recv_dt = start + timedelta(days=day_offset, hours=hour, minutes=minute)
        occ_dt = recv_dt - timedelta(minutes=rng.randint(0, 30))

        confidence = round(rng.uniform(0.60, 0.98), 2)

        rows.append({
            "voc_id": f"VOC-{i + 1:04d}",
            "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
            "received_at": _ts(recv_dt),
            "occurred_at": _ts(occ_dt),
            "service_area_id": area["service_area_id"],
            "topic_code": cat,
            "sentiment_label": t["sentiment"],
            "review_text": t["text"],
            "confidence": confidence,
            "is_synthetic": True,
        })
    return rows


def gen_metric_catalog() -> list[dict[str, Any]]:
    """metric_catalog: 필수 메트릭."""
    metrics = [
        ("WAIT_AVG_MIN", "평균 대기시간", "도착~좌석까지 평균 대기", "min", False, ["15m", "daily"]),
        ("WAIT_P90_MIN", "P90 대기시간", "상위 10% 대기시간", "min", False, ["15m", "daily"]),
        ("ARRIVALS_TOTAL", "총 도착 수", "일간 총 도착", "count", True, ["daily"]),
        ("CAPACITY_TOTAL", "총 수용량", "일간 총 수용 좌석", "count", True, ["daily"]),
        ("VOC_NEGATIVE_RATE", "부정 VOC 비율", "부정 VOC / 전체 VOC", "ratio", False, ["daily"]),
        ("VOC_COUNT", "VOC 건수", "일간 VOC 접수 건수", "count", True, ["daily"]),
        ("ROOMS_SOLD", "판매 객실 수", "일간 판매 객실", "count", True, ["daily"]),
        ("ROOMS_AVAILABLE", "가능 객실 수", "일간 가능 객실", "count", True, ["daily"]),
        ("QUEUE_MAX", "최대 대기열", "15분 내 최대 대기열 길이", "count", False, ["15m"]),
        ("STAFF_HEADCOUNT", "근무 인원", "shift별 실제 근무 인원", "count", True, ["daily"]),
    ]
    rows: list[dict[str, Any]] = []
    for code, name, defn, unit, additive, grains in metrics:
        rows.append({
            "metric_code": code,
            "display_name": name,
            "definition": defn,
            "unit": unit,
            "additive": additive,
            "allowed_grains": grains,
            "synonyms": [name],
            "source_view": f"analytics.v_{code.lower()}",
            "version": "1.0",
        })
    return rows


def gen_role_scope() -> list[dict[str, Any]]:
    """role_scope: 3역할 RBAC."""
    resources = ["rooms", "breakfast", "staff", "voc", "reports"]
    roles = [
        ("OPERATIONS_MANAGER", True),
        ("FACILITY_MANAGER", False),
        ("EXTERNAL_REVIEWER", False),
    ]
    rows: list[dict[str, Any]] = []
    for role, full_access in roles:
        for res in resources:
            allowed = full_access or res in ("voc", "reports")
            rows.append({
                "role_code": role,
                "resource_type": "module",
                "resource_code": res,
                "allowed": allowed,
                "scope_version": "1.0",
            })
    return rows


def gen_incidents(rng: random.Random, vocs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """incidents: 부정 VOC에서 파생된 incidents."""
    neg_vocs = [v for v in vocs if v["sentiment_label"] == "NEGATIVE"]
    rng.shuffle(neg_vocs)
    selected = neg_vocs[: min(12, len(neg_vocs))]
    rows: list[dict[str, Any]] = []
    for i, v in enumerate(selected):
        # 심각도 결정
        conf = v["confidence"]
        if conf >= 0.85:
            severity = "danger"
        elif conf >= 0.65:
            severity = "warn"
        else:
            severity = "ok"

        status = rng.choice(["recv", "check", "prog", "done"])
        opened_at = v["received_at"]

        rows.append({
            "incident_id": f"INC-{i + 1:04d}",
            "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
            "voc_id": v["voc_id"],
            "service_area_id": v["service_area_id"],
            "topic_code": v["topic_code"],
            "severity": severity,
            "status": status,
            "opened_at": opened_at,
            "resolved_at": _ts(
                datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                + timedelta(minutes=rng.randint(10, 180))
            ) if status == "done" else None,
            "is_synthetic": True,
        })
    return rows


def gen_jobs(rng: random.Random) -> list[dict[str, Any]]:
    """jobs: 분석 작업."""
    job_templates = [
        ("analysis", "SUCCEEDED"),
        ("analysis", "SUCCEEDED"),
        ("report", "SUCCEEDED"),
        ("analysis", "PARTIAL"),
        ("analysis", "SUCCEEDED"),
        ("report", "SUCCEEDED"),
    ]
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)

    for i, (jtype, status) in enumerate(job_templates):
        created = start + timedelta(days=i, hours=rng.randint(8, 16))
        completed = created + timedelta(minutes=rng.randint(2, 30))
        rows.append({
            "job_id": f"JOB-{i + 1:04d}",
            "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
            "job_type": jtype,
            "status": status,
            "created_at": _ts(created),
            "completed_at": _ts(completed) if status in ("SUCCEEDED", "PARTIAL", "FAILED") else None,
            "is_synthetic": True,
        })
    return rows


def gen_detections(rng: random.Random) -> list[dict[str, Any]]:
    """detections: 이상 감지 이벤트."""
    detections = [
        ("WAIT_P90_EXCEED", "P90 대기시간 초과", "warn"),
        ("VOC_SPIKE", "부정 VOC 급증", "danger"),
        ("CAPACITY_DROP", "수용량 급감", "danger"),
        ("STAFF_SHORTAGE", "인력 부족 감지", "warn"),
        ("QUEUE_OVERFLOW", "대기열 초과", "danger"),
    ]
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)

    for i, (code, desc, sev) in enumerate(detections):
        triggered = start + timedelta(days=rng.randint(5, 70), hours=rng.randint(8, 18))
        rows.append({
            "detection_id": f"DET-{i + 1:04d}",
            "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
            "detection_code": code,
            "description": desc,
            "severity": sev,
            "triggered_at": _ts(triggered),
            "metric_value": round(rng.uniform(15, 45), 1),
            "threshold": 30.0,
            "is_synthetic": True,
        })
    return rows


# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------

def gen_scenario_normal() -> dict[str, Any]:
    """scenario_normal: 정상 운영 (NEGATIVE 감성 < 20%)."""
    return {
        "scenario_id": "NORMAL",
        "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "description": "정상 운영 시나리오 - NEGATIVE 감성 20% 미만",
        "expected_trigger": False,
        "expected_status": "SUCCEEDED",
        "sentiment_distribution": {
            "NEGATIVE": "< 0.20",
            "NEUTRAL": "~ 0.30",
            "POSITIVE": "> 0.50",
        },
        "required_evidence": [],
        "forbidden_claims": [
            "이상 감지가 트리거되었다",
            "VOC 급증이 발생했다",
        ],
    }


def gen_scenario_critical() -> dict[str, Any]:
    """scenario_critical: 임계 초과 (NEGATIVE 감성 > 30%)."""
    return {
        "scenario_id": "CRITICAL",
        "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "description": "임계 초과 시나리오 - NEGATIVE 감성 30% 초과, 이상 감지 트리거",
        "expected_trigger": True,
        "expected_status": "READY_FOR_REVIEW",
        "sentiment_distribution": {
            "NEGATIVE": "> 0.30",
            "NEUTRAL": "~ 0.25",
            "POSITIVE": "< 0.45",
        },
        "required_evidence": [
            "wait_p90_min",
            "breakfast_arrivals",
            "service_capacity",
            "negative_wait_voc_rate",
        ],
        "forbidden_claims": [
            "실제 호텔에서 인력 부족이 발생했다",
            "합성 인력 감소가 유일한 원인이다",
        ],
        "injection": {
            "type": "voc_spike",
            "target_zones": ["다이닝", "객실동"],
            "negative_voc_boost": "+15%",
        },
    }


def gen_scenario_lock() -> dict[str, Any]:
    """scenario_lock: 로그인 잠금 (5회 실패)."""
    return {
        "scenario_id": "LOCK",
        "dataset_version": f"gw-synthetic-{GENERATOR_VERSION}",
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "description": "로그인 잠금 시나리오 - 연속 5회 실패 후 계정 잠금 (423)",
        "expected_trigger": True,
        "expected_status": "LOCKED",
        "lockout": {
            "max_attempts": 5,
            "lockout_http_status": 423,
            "lockout_duration_min": 30,
            "test_actor_id": "STAFF-TEST-001",
        },
        "events": [
            {"attempt": 1, "result": "FAIL", "error": "INVALID_CREDENTIALS"},
            {"attempt": 2, "result": "FAIL", "error": "INVALID_CREDENTIALS"},
            {"attempt": 3, "result": "FAIL", "error": "INVALID_CREDENTIALS"},
            {"attempt": 4, "result": "FAIL", "error": "INVALID_CREDENTIALS"},
            {"attempt": 5, "result": "FAIL", "error": "ACCOUNT_LOCKED"},
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    rng = random.Random(SEED)
    out_dir = Path(__file__).resolve().parent

    # manifest
    manifest = gen_manifest()
    _write_json(out_dir / "manifest.json", manifest)

    # hotels
    hotels = gen_hotels(rng)
    _write_json(out_dir / "hotels.json", hotels)

    # vocs (normal 분포)
    vocs = gen_fact_voc(rng, negative_ratio=0.15, count=84)
    _write_json(out_dir / "vocs.json", vocs)

    # incidents
    incidents = gen_incidents(rng, vocs)
    _write_json(out_dir / "incidents.json", incidents)

    # jobs
    jobs = gen_jobs(rng)
    _write_json(out_dir / "jobs.json", jobs)

    # detections
    detections = gen_detections(rng)
    _write_json(out_dir / "detections.json", detections)

    # scenarios
    _write_json(out_dir / "scenario_normal.json", gen_scenario_normal())
    _write_json(out_dir / "scenario_critical.json", gen_scenario_critical())
    _write_json(out_dir / "scenario_lock.json", gen_scenario_lock())

    print(f"[OK] {len(manifest)} manifest fields")
    print(f"[OK] {len(hotels)} hotels")
    print(f"[OK] {len(vocs)} vocs")
    print(f"[OK] {len(incidents)} incidents")
    print(f"[OK] {len(jobs)} jobs")
    print(f"[OK] {len(detections)} detections")
    print(f"[OK] 3 scenarios generated")
    print(f"[OK] All files written to {out_dir}")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  → {path.name}")


if __name__ == "__main__":
    main()
