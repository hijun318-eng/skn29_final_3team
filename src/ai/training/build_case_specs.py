"""Turn scenario-ledger rows into deterministic SQL SFT case specifications."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ai.training.dataset import load_specs, write_jsonl


PROPERTY = "SYNTHETIC_HOTEL_001"
JOIN_ID = "pms_stay_to_crm_membership_grade_event_time_v1"
CONTEXT_CONTRACT = Path(__file__).resolve().parents[2] / "data" / "analytics_context_contract.i4.v2.json"
RAW_URNS = {
    asset["fqn"]: asset["urn"]
    for asset in json.loads(CONTEXT_CONTRACT.read_text(encoding="utf-8"))["raw_assets"]
}


def _urn(fqn: str) -> str:
    return RAW_URNS.get(fqn, f"urn:li:dataset:(urn:li:dataPlatform:trino,{fqn},PROD)")


@dataclass(frozen=True)
class Source:
    fqn: str
    time_field: str
    value: str
    alias: str
    columns: tuple[str, ...]
    dimensions: dict[str, str]
    required_filter: str
    denominator: str | None = None

    @property
    def urn(self) -> str:
        return _urn(self.fqn)


SOURCES = {
    "recognized_room_revenue": Source("serving.analytics.hotel_daily_metrics", "business_date", "room_revenue", "recognized_room_revenue_krw", ("property_id", "business_date", "room_type_code", "data_period_status", "is_forecast", "room_revenue"), {"room_type": "room_type_code"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "occupancy_rate": Source("serving.analytics.hotel_daily_metrics", "business_date", "rooms_sold", "occupancy_rate", ("property_id", "business_date", "room_type_code", "data_period_status", "is_forecast", "rooms_sold", "available_room_nights"), {"room_type": "room_type_code"}, "data_period_status = 'ACTUAL' AND is_forecast = false", "available_room_nights"),
    "adr": Source("serving.analytics.hotel_daily_metrics", "business_date", "room_revenue", "adr_krw", ("property_id", "business_date", "room_type_code", "data_period_status", "is_forecast", "room_revenue", "rooms_sold"), {"room_type": "room_type_code"}, "data_period_status = 'ACTUAL' AND is_forecast = false", "rooms_sold"),
    "revpar": Source("serving.analytics.hotel_daily_metrics", "business_date", "room_revenue", "revpar_krw", ("property_id", "business_date", "room_type_code", "data_period_status", "is_forecast", "room_revenue", "available_room_nights"), {"room_type": "room_type_code"}, "data_period_status = 'ACTUAL' AND is_forecast = false", "available_room_nights"),
    "rooms_sold": Source("serving.analytics.hotel_daily_metrics", "business_date", "rooms_sold", "rooms_sold", ("property_id", "business_date", "room_type_code", "data_period_status", "is_forecast", "rooms_sold"), {"room_type": "room_type_code"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "available_room_nights": Source("serving.analytics.hotel_daily_metrics", "business_date", "available_room_nights", "available_room_nights", ("property_id", "business_date", "room_type_code", "data_period_status", "is_forecast", "available_room_nights"), {"room_type": "room_type_code"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "fnb_net_revenue": Source("serving.analytics.fnb_daypart_metrics", "business_date", "fnb_net_revenue", "fnb_net_revenue_krw", ("property_id", "business_date", "store_id", "service_period", "data_period_status", "is_forecast", "fnb_net_revenue"), {"store": "store_id", "daypart": "service_period"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "order_count": Source("serving.analytics.fnb_daypart_metrics", "business_date", "order_count", "order_count", ("property_id", "business_date", "store_id", "service_period", "data_period_status", "is_forecast", "order_count"), {"store": "store_id", "daypart": "service_period"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "covers": Source("serving.analytics.fnb_daypart_metrics", "business_date", "covers", "covers", ("property_id", "business_date", "store_id", "service_period", "data_period_status", "is_forecast", "covers"), {"store": "store_id", "daypart": "service_period"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "average_check": Source("serving.analytics.fnb_daypart_metrics", "business_date", "fnb_net_revenue", "average_check_krw", ("property_id", "business_date", "store_id", "service_period", "data_period_status", "is_forecast", "fnb_net_revenue", "covers"), {"store": "store_id", "daypart": "service_period"}, "data_period_status = 'ACTUAL' AND is_forecast = false", "covers"),
    "revpash": Source("serving.analytics.fnb_daypart_metrics", "business_date", "fnb_net_revenue", "revpash_krw", ("property_id", "business_date", "store_id", "service_period", "data_period_status", "is_forecast", "fnb_net_revenue", "seat_hours_available"), {"store": "store_id", "daypart": "service_period"}, "data_period_status = 'ACTUAL' AND is_forecast = false", "seat_hours_available"),
    "completed_usage_count": Source("serving.analytics.facility_daily_metrics", "business_date", "completed_usage_count", "completed_usage_count", ("property_id", "business_date", "facility_id", "data_period_status", "is_forecast", "completed_usage_count"), {"facility": "facility_id"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "incident_count": Source("serving.analytics.facility_daily_metrics", "business_date", "incident_count", "incident_count", ("property_id", "business_date", "facility_id", "data_period_status", "is_forecast", "incident_count"), {"facility": "facility_id"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "downtime_minutes": Source("serving.analytics.facility_daily_metrics", "business_date", "downtime_minutes", "downtime_minutes", ("property_id", "business_date", "facility_id", "data_period_status", "is_forecast", "downtime_minutes"), {"facility": "facility_id"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "facility_revenue": Source("serving.analytics.facility_daily_metrics", "business_date", "facility_revenue", "facility_revenue_krw", ("property_id", "business_date", "facility_id", "data_period_status", "is_forecast", "facility_revenue"), {"facility": "facility_id"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "revenue_per_usage": Source("serving.analytics.facility_daily_metrics", "business_date", "facility_revenue", "revenue_per_usage_krw", ("property_id", "business_date", "facility_id", "data_period_status", "is_forecast", "facility_revenue", "completed_usage_count"), {"facility": "facility_id"}, "data_period_status = 'ACTUAL' AND is_forecast = false", "completed_usage_count"),
    "recognized_banquet_revenue": Source("serving.analytics.banquet_monthly_metrics", "year_month", "recognized_revenue", "recognized_banquet_revenue_krw", ("property_id", "year_month", "product_category", "data_period_status", "is_forecast", "recognized_revenue"), {"product_category": "product_category"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "expected_banquet_revenue": Source("serving.analytics.banquet_monthly_metrics", "year_month", "expected_revenue", "expected_banquet_revenue_krw", ("property_id", "year_month", "product_category", "data_period_status", "is_forecast", "expected_revenue"), {"product_category": "product_category"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "banquet_booking_count": Source("serving.analytics.banquet_monthly_metrics", "year_month", "booking_count", "banquet_booking_count", ("property_id", "year_month", "product_category", "data_period_status", "is_forecast", "booking_count"), {"product_category": "product_category"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "confirmed_banquet_count": Source("serving.analytics.banquet_monthly_metrics", "year_month", "confirmed_count", "confirmed_banquet_count", ("property_id", "year_month", "product_category", "data_period_status", "is_forecast", "confirmed_count"), {"product_category": "product_category"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "cancelled_banquet_count": Source("serving.analytics.banquet_monthly_metrics", "year_month", "cancelled_count", "cancelled_banquet_count", ("property_id", "year_month", "product_category", "data_period_status", "is_forecast", "cancelled_count"), {"product_category": "product_category"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
    "actual_attendees": Source("serving.analytics.banquet_monthly_metrics", "year_month", "actual_attendees", "actual_attendees", ("property_id", "year_month", "product_category", "data_period_status", "is_forecast", "actual_attendees"), {"product_category": "product_category"}, "data_period_status = 'ACTUAL' AND is_forecast = false"),
}


CRM_SOURCES = {
    "current_active_members": Source("crm.dbo.crm_members", "joined_at", "member_no", "current_active_members", ("property_id", "member_no", "membership_grade", "points_balance", "joined_at", "member_status", "is_forecast"), {"membership_grade": "membership_grade", "joined_month": "date_format(date_trunc('month', joined_at), '%Y-%m')", "joined_year": "CAST(year(joined_at) AS varchar)", "points_band": "CASE WHEN points_balance < 10000 THEN 'LOW' WHEN points_balance < 50000 THEN 'MID' ELSE 'HIGH' END"}, "member_status = 'ACTIVE' AND is_forecast = false"),
    "current_points_balance": Source("crm.dbo.crm_members", "joined_at", "points_balance", "current_points_balance", ("property_id", "member_no", "membership_grade", "points_balance", "joined_at", "member_status", "is_forecast"), {"membership_grade": "membership_grade", "joined_year": "CAST(year(joined_at) AS varchar)", "points_band": "CASE WHEN points_balance < 10000 THEN 'LOW' WHEN points_balance < 50000 THEN 'MID' ELSE 'HIGH' END"}, "member_status = 'ACTIVE' AND is_forecast = false"),
    "earned_points": Source("crm.dbo.crm_point_transactions", "event_at", "points_delta", "earned_points", ("property_id", "member_no", "event_at", "txn_type", "points_delta", "related_source", "is_forecast"), {"membership_grade": "related_source"}, "txn_type = 'EARN' AND is_forecast = false"),
    "used_points": Source("crm.dbo.crm_point_transactions", "event_at", "-points_delta", "used_points", ("property_id", "member_no", "event_at", "txn_type", "points_delta", "related_source", "is_forecast"), {"membership_grade": "related_source"}, "txn_type = 'USE' AND is_forecast = false"),
    "expired_points": Source("crm.dbo.crm_point_transactions", "event_at", "-points_delta", "expired_points", ("property_id", "member_no", "event_at", "txn_type", "points_delta", "related_source", "is_forecast"), {"membership_grade": "related_source"}, "txn_type = 'EXPIRE' AND is_forecast = false"),
    "grade_change_count": Source("crm.dbo.crm_member_grade_history", "valid_from", "member_no", "grade_change_count", ("property_id", "member_no", "grade_code", "valid_from", "valid_to", "change_reason_code"), {"change_reason": "change_reason_code", "membership_grade": "grade_code"}, "1 = 1"),
}

METRIC_NAMES = {
    "recognized_room_revenue": "인식 객실 매출",
    "occupancy_rate": "객실 점유율",
    "adr": "평균 객실 단가(ADR)",
    "revpar": "판매 가능 객실당 매출(RevPAR)",
    "rooms_sold": "판매 객실 수",
    "available_room_nights": "판매 가능 객실 수",
    "current_active_members": "현재 활성 회원 수",
    "current_points_balance": "현재 포인트 잔액",
    "earned_points": "적립 포인트",
    "used_points": "사용 포인트",
    "expired_points": "소멸 포인트",
    "grade_change_count": "회원 등급 변경 건수",
    "stay_grade_room_revenue": "투숙 당시 회원 등급별 객실 매출",
    "stay_grade_completed_stays": "투숙 당시 회원 등급별 완료 투숙 수",
    "stay_grade_room_nights": "투숙 당시 회원 등급별 객실박",
    "stay_grade_unique_members": "투숙 당시 회원 등급별 고유 회원 수",
    "fnb_net_revenue": "식음 순매출",
    "order_count": "결제 완료 주문 수",
    "covers": "식음 이용 인원 수",
    "average_check": "이용 인원당 객단가",
    "revpash": "좌석 시간당 매출(RevPASH)",
    "completed_usage_count": "완료 시설 이용 건수",
    "incident_count": "시설 사고 건수",
    "downtime_minutes": "시설 중단 시간",
    "facility_revenue": "시설 매출",
    "revenue_per_usage": "시설 이용 건당 매출",
    "recognized_banquet_revenue": "인식 연회 매출",
    "expected_banquet_revenue": "예상 연회 매출",
    "banquet_booking_count": "연회 예약 건수",
    "confirmed_banquet_count": "확정 연회 건수",
    "cancelled_banquet_count": "취소 연회 건수",
    "actual_attendees": "실제 연회 참석자 수",
}

DIMENSION_NAMES = {
    "time": "월별로",
    "room_type": "객실 유형별로",
    "membership_grade": "회원 등급별로",
    "membership_grade_and_time": "월과 회원 등급별로",
    "joined_month": "가입 월별로",
    "joined_year": "가입 연도별로",
    "points_band": "포인트 구간별로",
    "store": "매장별로",
    "daypart": "영업 시간대별로",
    "facility": "시설별로",
    "product_category": "연회 상품 유형별로",
}

OUTPUT_NAMES = {
    "scalar": "하나의 값",
    "grouped": "항목별 결과",
    "segmented_table": "구분별 표",
    "trend": "월별 추이",
    "comparison": "기간별 비교",
    "top_n": "상위 10개 결과",
}

QUESTION_INTROS = (
    "",
    "호텔 운영 현황을 확인하기 위해 ",
    "실적 분석용으로 ",
    "내부 보고용으로 ",
    "현재 데이터를 기준으로 ",
    "의사 결정 참고용으로 ",
    "정기 점검용으로 ",
)

QUESTION_ENDINGS = (
    "조회해 줘.",
    "보여 줘.",
    "확인하고 싶어.",
    "알려 줘.",
    "정리해 줘.",
    "확인해 줘.",
)

VALIDATION_QUESTION_ENDINGS = (
    "조회해 주세요.",
    "보여 주세요.",
    "확인하고 싶습니다.",
    "알려 주세요.",
    "정리해 주세요.",
    "확인해 주세요.",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _period(record: dict[str, Any]) -> tuple[str, str, str]:
    index = int(str(record["candidate_id"]).rsplit("-", 1)[1])
    crm = record["domain"] == "crm" and record["metric_id"] not in {"current_active_members", "current_points_balance"}
    year = 2024 if crm else 2026
    month = 1 + (index % (4 if crm else 6))
    shape = record["period_shape"]
    if shape == "current_snapshot":
        return "2026-01-01", "2026-08-01", "2026년 8월 1일 기준"
    if shape == "year":
        return f"{year}-01-01", f"{year + 1}-01-01", f"{year}년"
    if shape == "quarter":
        quarter_start = 1 + 3 * ((month - 1) // 3)
        end_month = quarter_start + 3
        return f"{year}-{quarter_start:02d}-01", f"{year}-{end_month:02d}-01", f"{year}년 {(quarter_start - 1) // 3 + 1}분기"
    if shape == "day":
        day = 1 + (index % 27)
        return f"{year}-{month:02d}-{day:02d}", f"{year}-{month:02d}-{day + 1:02d}", f"{year}년 {month}월 {day}일"
    if shape == "week":
        day = 1 + 7 * (index % 3)
        return f"{year}-{month:02d}-{day:02d}", f"{year}-{month:02d}-{day + 7:02d}", f"{year}년 {month}월 {day}일 시작 1주"
    months = 2 if shape == "mom" else 13 if shape == "yoy" else max(1, int(record["window_size"]))
    start_year = year
    start_month = month - months + 1
    while start_month <= 0:
        start_year -= 1
        start_month += 12
    end_year, end_month = year, month + 1
    if end_month == 13:
        end_year, end_month = year + 1, 1
    label = f"{start_year}년 {start_month}월부터 {year}년 {month}월까지"
    return f"{start_year}-{start_month:02d}-01", f"{end_year}-{end_month:02d}-01", label


def _group_expression(record: dict[str, Any], source: Source) -> tuple[str | None, str]:
    dimension = str(record["dimension"])
    output = str(record["output_shape"])
    if dimension == "time" or output in {"trend", "comparison"}:
        return f"date_format(date_trunc('month', {source.time_field}), '%Y-%m')", "period"
    expression = source.dimensions.get(dimension)
    return (expression, dimension) if expression else (None, "")


def _value_expression(record: dict[str, Any], source: Source) -> str:
    if record["metric_id"] == "current_active_members":
        return "COUNT(DISTINCT member_no)"
    if record["metric_id"] == "grade_change_count":
        return "COUNT(*)"
    if source.denominator:
        return f"CAST(SUM({source.value}) / NULLIF(SUM({source.denominator}), 0) AS DECIMAL(18,6))"
    if record["aggregation"] == "average":
        return f"CAST(AVG({source.value}) AS DECIMAL(18,2))"
    return f"CAST(SUM({source.value}) AS DECIMAL(18,2))"


def _single_source(record: dict[str, Any], source: Source) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    start, end, _ = _period(record)
    where = [f"property_id = '{PROPERTY}'", source.required_filter]
    if record["period_shape"] != "current_snapshot":
        where.extend((f"{source.time_field} >= DATE '{start}'", f"{source.time_field} < DATE '{end}'"))
    index = int(str(record["candidate_id"]).rsplit("-", 1)[1])
    if "type" in str(record["filter_shape"]) and "room_type_code" in source.columns:
        where.append(f"room_type_code = '{('DELUXE', 'SUITE', 'STANDARD', 'RESIDENCE')[index % 4]}'")
    if "store" in str(record["filter_shape"]) and "store_id" in source.columns:
        where.append(f"store_id = 'STORE-{index % 8 + 1:02d}'")
    if "facility" in str(record["filter_shape"]) and "facility_id" in source.columns:
        where.append(f"facility_id = 'FAC-{index % 20 + 1:03d}'")
    if "category" in str(record["filter_shape"]) and "product_category" in source.columns:
        where.append(f"product_category = '{('CORPORATE_EVENT', 'WEDDING', 'CONFERENCE', 'SOCIAL_EVENT', 'MEETING')[index % 5]}'")
    if "grade" in str(record["filter_shape"]) and "membership_grade" in source.columns:
        where.append(f"membership_grade = '{('BASIC', 'SILVER', 'GOLD', 'VIP')[index % 4]}'")
    group, group_alias = _group_expression(record, source)
    value = _value_expression(record, source)
    select = f"{group} AS {group_alias}, {value} AS {source.alias}" if group else f"{value} AS {source.alias}"
    sql = f"SELECT {select} FROM {source.fqn} WHERE {' AND '.join(where)}"
    if group:
        sql += " GROUP BY 1"
        sql += f" ORDER BY 2 DESC" if record["output_shape"] == "top_n" else " ORDER BY 1"
    sql += " LIMIT 10" if record["output_shape"] == "top_n" else " LIMIT 1000"
    used = {"property_id", source.time_field, source.value}
    if source.denominator:
        used.add(source.denominator)
    used.update(column for column in source.columns if column in sql)
    reference_columns = [column for column in source.columns if column in used]
    context_columns = list(source.columns) if record["context_shape"] == "distractor" else reference_columns
    asset = {"urn": source.urn, "trino_fqn": source.fqn, "columns": context_columns}
    reference = {"urn": source.urn, "trino_fqn": source.fqn, "columns": reference_columns, "join_ids": [], "metric_ids": [record["metric_id"]]}
    return sql, [asset], [reference]


def _pms_crm(record: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    start, end, _ = _period(record)
    metric = str(record["metric_id"])
    value = {
        "stay_grade_room_revenue": "CAST(SUM(s.room_revenue) AS DECIMAL(18,2))",
        "stay_grade_completed_stays": "COUNT(DISTINCT s.stay_id)",
        "stay_grade_room_nights": "CAST(SUM(s.occupied_room_nights) AS DECIMAL(18,2))",
        "stay_grade_unique_members": "COUNT(DISTINCT gh.member_no)",
    }[metric]
    alias = {
        "stay_grade_room_revenue": "recognized_room_revenue_krw",
        "stay_grade_completed_stays": "completed_stay_count",
        "stay_grade_room_nights": "occupied_room_nights",
        "stay_grade_unique_members": "unique_staying_members",
    }[metric]
    group = "gh.grade_code"
    if record["dimension"] in {"time", "membership_grade_and_time"} or record["output_shape"] in {"trend", "comparison"}:
        group = "date_format(date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m')"
        if record["dimension"] == "membership_grade_and_time":
            group = f"concat({group}, '|', gh.grade_code)"
    sql = (
        f"SELECT {group} AS segment, {value} AS {alias} FROM pms.public.pms_stays s "
        "JOIN pms.public.pms_reservations r ON r.property_id = s.property_id AND r.reservation_id = s.reservation_id "
        "JOIN pms.public.pms_guests g ON g.property_id = r.property_id AND g.guest_id = r.guest_id "
        "JOIN crm.dbo.crm_customer_map cm ON cm.property_id = g.property_id AND cm.pms_guest_id = g.guest_id "
        "AND cm.valid_from <= s.actual_checkout_at AND (cm.valid_to IS NULL OR s.actual_checkout_at < cm.valid_to) "
        "JOIN crm.dbo.crm_member_grade_history gh ON gh.property_id = cm.property_id AND gh.member_no = cm.member_no "
        "AND gh.valid_from <= s.actual_checkout_at AND (gh.valid_to IS NULL OR s.actual_checkout_at < gh.valid_to) "
        f"WHERE s.property_id = '{PROPERTY}' AND s.stay_status = 'COMPLETED' AND s.room_revenue > 0 "
        "AND s.complimentary_flag = false AND s.house_use_flag = false AND s.is_forecast = false "
        f"AND s.actual_checkout_at >= TIMESTAMP '{start} 00:00:00 Asia/Seoul' AND s.actual_checkout_at < TIMESTAMP '{end} 00:00:00 Asia/Seoul' "
        f"GROUP BY 1 ORDER BY {'2 DESC' if record['output_shape'] == 'top_n' else '1'} "
        f"LIMIT {10 if record['output_shape'] == 'top_n' else 1000}"
    )
    tables = {
        "pms.public.pms_stays": ("property_id", "stay_id", "reservation_id", "actual_checkout_at", "occupied_room_nights", "room_revenue", "stay_status", "complimentary_flag", "house_use_flag", "is_forecast"),
        "pms.public.pms_reservations": ("property_id", "reservation_id", "guest_id"),
        "pms.public.pms_guests": ("property_id", "guest_id"),
        "crm.dbo.crm_customer_map": ("property_id", "pms_guest_id", "member_no", "valid_from", "valid_to"),
        "crm.dbo.crm_member_grade_history": ("property_id", "member_no", "grade_code", "valid_from", "valid_to"),
    }
    assets, references = [], []
    for fqn, columns in tables.items():
        urn = _urn(fqn)
        assets.append({"urn": urn, "trino_fqn": fqn, "columns": list(columns)})
        references.append({"urn": urn, "trino_fqn": fqn, "columns": list(columns), "join_ids": [JOIN_ID], "metric_ids": [metric]})
    return sql, assets, references


def _repair_sql(sql: str, code: str) -> str:
    if code == "RESOURCE_POLICY_MISSING":
        return sql.rsplit(" LIMIT ", 1)[0]
    if code == "SQL_REFERENCE_MISMATCH":
        replacements = (
            ("serving.analytics.", "serving.reference."),
            ("crm.dbo.crm_point_transactions", "crm.dbo.crm_members"),
            ("crm.dbo.crm_member_grade_history", "crm.dbo.crm_members"),
            ("crm.dbo.crm_members", "crm.dbo.crm_point_transactions"),
            ("pms.public.pms_stays", "pms.public.pms_reservations"),
        )
        for source, replacement in replacements:
            if source in sql:
                return sql.replace(source, replacement, 1)
        raise ValueError("SQL_REFERENCE_MISMATCH requires a replaceable table")
    return sql


def build_case(record: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
    if approved and record["target_split"] not in {"gold", "acceptance"}:
        raise ValueError("only held-out gold and acceptance cases can be approved here")
    start, end, label = _period(record)
    metric = str(record["metric_id"])
    if record["domain"] == "pms_crm":
        sql, assets, references = _pms_crm(record)
        time_field = "pms.public.pms_stays.actual_checkout_at"
        field = metric
    else:
        source = (CRM_SOURCES if record["domain"] == "crm" else SOURCES)[metric]
        sql, assets, references = _single_source(record, source)
        time_field = f"{source.fqn}.{source.time_field}"
        field = f"{source.fqn}.{source.value}"
    context = {
        "context_version": "I3-DATA-v1.0.0",
        "policy_version": "G2-v1.0.0",
        "execution_time": {"as_of": f"{end}T00:00:00+09:00", "timezone": "Asia/Seoul", "calendar_id": "gregorian-kr", "period_start": f"{start}T00:00:00+09:00", "period_end_exclusive": f"{end}T00:00:00+09:00"},
        "assets": assets,
        "metrics": [{"id": metric, "field": field, "aggregation": str(record["aggregation"]), "time_field": time_field}],
        "joins": ([{"id": JOIN_ID, "left": "pms.public.pms_stays", "right": "crm.dbo.crm_member_grade_history", "cardinality": "many_to_zero_or_one", "status": "approved"}] if record["domain"] == "pms_crm" else []),
    }
    index = int(str(record["candidate_id"]).rsplit("-", 1)[1])
    dimension = str(record["dimension"])
    dimension_text = "" if record["output_shape"] in {"trend", "comparison"} else DIMENSION_NAMES.get(dimension, "")
    request = f"{label}의 {METRIC_NAMES[metric]}을 {dimension_text} {OUTPUT_NAMES[str(record['output_shape'])]} 형태로"
    endings = VALIDATION_QUESTION_ENDINGS if record["target_split"] == "validation" else QUESTION_ENDINGS
    style = index % (len(QUESTION_INTROS) * len(endings))
    intro = QUESTION_INTROS[style // len(endings)]
    ending = endings[style % len(endings)]
    question = f"{intro}{request} {ending}"
    question = " ".join(question.split())
    common = {
        "case_id": str(record["candidate_id"]).replace("candidate", str(record["target_split"])),
        "split": record["target_split"],
        "node": record["node"],
        "domain": record["domain"],
        "scenario_group": record["scenario_group"],
        "synthetic": True,
        "schema_version": "1.0.0",
        "seed_version": "20260729",
        "review_status": "APPROVED" if approved else "AUTO_PASSED",
        "trino_status": "NOT_RUN",
        "result_sha256": None,
    }
    if record["node"] == "node2":
        common["input"] = {"normalized_question": question, "context_package": context}
        common["expected_output"] = {"sql": sql, "references": references, "parameters": []}
    else:
        code = str(record["repair_error_code"])
        common["input"] = {"normalized_question": question, "trace_id": f"trace-{common['case_id']}", "attempt": 1, "rejected_sql": _repair_sql(sql, code), "context_package": context, "normalized_error_code": code, "repair_scope": ["sql", "references", "parameters"]}
        common["expected_output"] = {"corrected_sql": sql, "references": references, "parameters": []}
    return common


def select(records: list[dict[str, Any]], per_domain: int) -> list[dict[str, Any]]:
    if per_domain == 0:
        return [row for row in records if row["target_split"] in {"train", "validation"}]
    selected = []
    for domain in ("pms", "crm", "pms_crm", "pos", "facility", "banquet"):
        domain_rows = [row for row in records if row["domain"] == domain and row["target_split"] in {"train", "validation"}]
        for node in ("node2", "node2_repair"):
            selected.extend([row for row in domain_rows if row["node"] == node][: per_domain // 2])
    return selected


def select_coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [row for row in records if row["target_split"] in {"train", "validation"}]
    selected = []
    for metric_id in dict.fromkeys(row["metric_id"] for row in eligible):
        selected.append(next(row for row in eligible if row["metric_id"] == metric_id and row["node"] == "node2"))
    for error_code in ("RESOURCE_POLICY_MISSING", "REFERENCE_MISSING", "REFERENCE_OUTSIDE_CONTEXT", "SQL_REFERENCE_MISMATCH", "PARAMETERS_INVALID"):
        selected.append(next(row for row in eligible if row["node"] == "node2_repair" and row["repair_error_code"] == error_code))
    return selected


def select_held_out(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in records if row["target_split"] in {"gold", "acceptance"}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--per-domain", type=int, default=4)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--coverage-smoke", action="store_true")
    selection.add_argument(
        "--held-out",
        action="store_true",
        help="build the reviewed Gold 120 and Acceptance 30 cases",
    )
    args = parser.parse_args()
    if args.per_domain != 0 and (args.per_domain < 2 or args.per_domain % 2):
        raise ValueError("--per-domain must be 0 or an even number of at least 2")
    if args.held_out and args.per_domain != 4:
        raise ValueError("--per-domain cannot be combined with --held-out")
    ledger = _read_jsonl(args.ledger)
    selected = (
        select_held_out(ledger)
        if args.held_out
        else select_coverage(ledger)
        if args.coverage_smoke
        else select(ledger, args.per_domain)
    )
    cases = [build_case(row, approved=args.held_out) for row in selected]
    write_jsonl(args.output, cases)
    load_specs(args.output)
    print(json.dumps({"total": len(cases), "domains": dict(Counter(case["domain"] for case in cases)), "nodes": dict(Counter(case["node"] for case in cases))}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
