#!/usr/bin/env python3
"""Generate the isolated Walkerhill public-shape synthetic v4 candidate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


HERE = Path(__file__).resolve().parent
PRODUCT_PATH = HERE / "product_contract.v2.json"
SCHEMA_PATH = HERE / "schema_contract.v2.json"
SEOUL_SUFFIX = "+09:00"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def date_range(start: date, end_exclusive: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end_exclusive - start).days)]


def iso_at(day: date, hour: int, minute: int = 0, second: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:{second:02d}{SEOUL_SUFFIX}"


def parse_hhmm(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def money(value: float | Decimal) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ratio(numerator: int | float | Decimal, denominator: int | float | Decimal) -> str:
    if not denominator:
        return ""
    return format((Decimal(str(numerator)) / Decimal(str(denominator))).quantize(Decimal("0.000001")), "f")


def decimal_text(value: float | Decimal, places: str = "0.001") -> str:
    return format(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def stable_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Generator:
    def __init__(self, start: date, end_exclusive: date, seed: int) -> None:
        self.product = load_json(PRODUCT_PATH)
        self.schema = load_json(SCHEMA_PATH)
        self.datasets = {item["id"]: item for item in self.schema["datasets"]}
        self.start = start
        self.end = end_exclusive
        self.days = date_range(start, end_exclusive)
        self.seed = seed
        self.rng = random.Random(seed)
        self.rows: dict[str, list[dict]] = defaultdict(list)

        self.calendar: dict[date, dict] = {}
        self.hotel_names: dict[str, str] = {}
        self.room_types: list[dict] = []
        self.rooms_by_type: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.inventory: dict[tuple[str, date, str], dict] = {}
        self.unavailable: set[tuple[str, date]] = set()
        self.stays_by_hotel_day: dict[tuple[str, date], list[dict]] = defaultdict(list)
        self.stay_allocations: dict[tuple[str, date, str], dict[str, int]] = defaultdict(
            lambda: {"rooms_sold": 0, "revenue": 0}
        )
        self.recognized_room_revenue: dict[tuple[str, date, str], int] = defaultdict(int)
        self.member_revenue: dict[tuple[str, date, str, str], dict[str, int]] = defaultdict(
            lambda: {"transaction_count": 0, "revenue_amount": 0}
        )
        self.members: list[dict] = []
        self.member_by_guest: dict[str, dict] = {}
        self.member_by_pos_ref: dict[str, dict] = {}
        self.member_by_facility_ref: dict[str, dict] = {}
        self.member_by_banquet_ref: dict[str, dict] = {}
        self.banquet_by_hotel_day: dict[tuple[str, date], list[str]] = defaultdict(list)
        self.banquet_daily: dict[tuple[str, date], dict[str, int]] = defaultdict(
            lambda: {
                "booking_count": 0,
                "completed_count": 0,
                "cancelled_count": 0,
                "actual_attendees": 0,
                "recognized_revenue": 0,
                "reserved_room_nights": 0,
                "pickup_room_nights": 0,
            }
        )
        self.outlet_by_id: dict[str, dict] = {}
        self.fnb_daily: dict[tuple[str, date, str], dict[str, int]] = defaultdict(
            lambda: {"order_count": 0, "covers": 0, "net": 0}
        )
        self.fnb_hotel_daily: dict[tuple[str, date], int] = defaultdict(int)
        self.fnb_order_count: dict[tuple[str, date], int] = defaultdict(int)
        self.facility_by_id: dict[str, dict] = {}
        self.facility_daily: dict[tuple[str, date], dict[str, int]] = defaultdict(
            lambda: {
                "usage_count": 0,
                "guests": 0,
                "net": 0,
                "incident_count": 0,
                "downtime": 0,
            }
        )
        self.facility_hotel_daily: dict[tuple[str, date], int] = defaultdict(int)
        self.resource_daily: dict[tuple[str, date], dict] = {}

    def add(self, dataset_id: str, **row: object) -> None:
        expected = list(self.datasets[dataset_id]["fields"])
        missing = [name for name in expected if name not in row]
        extra = [name for name in row if name not in expected]
        if missing or extra:
            raise ValueError(f"{dataset_id}: missing={missing}, extra={extra}")
        self.rows[dataset_id].append(row)

    def active_member(self, day: date) -> dict | None:
        for _ in range(12):
            member = self.rng.choice(self.members)
            if member["joined_date"] <= day:
                return member
        eligible = [member for member in self.members if member["joined_date"] <= day]
        return self.rng.choice(eligible) if eligible else None

    def record_member_revenue(
        self,
        member: dict | None,
        day: date,
        hotel_code: str,
        source_domain: str,
        amount: int,
    ) -> None:
        if member is None or amount <= 0 or member["joined_date"] > day:
            return
        key = (member["member_no"], day, hotel_code, source_domain)
        self.member_revenue[key]["transaction_count"] += 1
        self.member_revenue[key]["revenue_amount"] += amount

    def build_reference(self) -> None:
        lodging_url = "https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro"
        vista_url = "https://www.walkerhill.com/vistawalkerhillseoul/en/room/"
        entities = [
            ("WH_COMPLEX", "", "Walkerhill Hotels & Resorts", "RESORT", 0, "https://www.walkerhill.com/en/"),
            ("GRAND", "WH_COMPLEX", "Grand Walkerhill Seoul", "HOTEL", 48, lodging_url),
            ("VISTA", "WH_COMPLEX", "Vista Walkerhill Seoul", "HOTEL", 38, vista_url),
            ("DOUGLAS", "GRAND", "Douglas House", "LODGING_PRODUCT", 18, lodging_url),
        ]
        for hotel_code, parent, public_name, entity_type, capacity, source_url in entities:
            self.hotel_names[hotel_code] = public_name
            self.add(
                "reference.hotel_entities",
                resort_id="WH_SEOUL",
                hotel_code=hotel_code,
                parent_hotel_code=parent,
                public_name=public_name,
                entity_type=entity_type,
                source_url=source_url,
                source_as_of="2026-08-13",
                synthetic_room_capacity=capacity,
                provenance_class="PUBLIC_REFERENCE" if capacity == 0 else "MIXED_REFERENCE_AND_ASSUMPTION",
                is_active=True,
            )

        for day in self.days:
            weekend = day.weekday() >= 5
            month = day.month
            if month in (12, 1, 2):
                season = "WINTER"
                weather_base = 0.40
            elif month in (3, 4, 5):
                season = "SPRING"
                weather_base = 0.72
            elif month in (6, 7, 8):
                season = "SUMMER"
                weather_base = 0.58
            else:
                season = "AUTUMN"
                weather_base = 0.78
            promotion = "WEEKEND_ESCAPE" if weekend and self.rng.random() < 0.24 else ""
            if month in (7, 8) and self.rng.random() < 0.20:
                promotion = "SUMMER_STAY"
            weather = min(1.0, max(0.05, weather_base + self.rng.uniform(-0.22, 0.18)))
            demand = 0.40 + (0.16 if weekend else 0) + (0.10 if month in (5, 10, 12) else 0)
            demand += 0.08 if promotion else 0
            demand += (weather - 0.5) * 0.10 + self.rng.uniform(-0.05, 0.05)
            demand = min(0.98, max(0.20, demand))
            row = {
                "business_date": day.isoformat(),
                "day_of_week": day.strftime("%A").upper(),
                "is_weekend": weekend,
                "season_code": season,
                "synthetic_weather_score": decimal_text(weather, "0.0001"),
                "synthetic_demand_index": decimal_text(demand, "0.0001"),
                "promotion_code": promotion,
                "provenance_class": "SYNTHETIC_ASSUMPTION",
            }
            self.calendar[day] = row
            self.add("reference.calendar_daily", **row)

    def build_people_and_membership(self) -> None:
        rewards_url = "https://www.walkerhill.com/en/membership/Rewards"
        tiers = [("CLASSIC", "Classic", 1), ("PLUS", "Plus", 2), ("PREMIER", "Premier", 3)]
        for code, public_name, rank in tiers:
            self.add(
                "crm.membership_tiers",
                tier_code=code,
                public_name=public_name,
                synthetic_rank=rank,
                source_url=rewards_url,
                provenance_class="MIXED_REFERENCE_AND_ASSUMPTION",
                is_active=True,
            )

        guest_count = 1200
        member_count = 720
        join_window_start = date(2024, 1, 1)
        join_window_end = max(join_window_start + timedelta(days=1), self.end - timedelta(days=30))
        for index in range(1, guest_count + 1):
            guest_id = f"G{index:06d}"
            created = join_window_start + timedelta(days=self.rng.randrange((self.end - join_window_start).days))
            self.add(
                "pms.guests",
                guest_id=guest_id,
                guest_segment=self.rng.choices(
                    ["LEISURE", "BUSINESS", "GROUP"], weights=[66, 24, 10], k=1
                )[0],
                country_group=self.rng.choices(
                    ["DOMESTIC", "NORTHEAST_ASIA", "SOUTHEAST_ASIA", "OTHER"],
                    weights=[68, 17, 9, 6],
                    k=1,
                )[0],
                created_at=iso_at(created, 10, self.rng.randrange(60)),
                is_synthetic=True,
            )

        for index in range(1, member_count + 1):
            guest_id = f"G{index:06d}"
            span = max(1, (join_window_end - join_window_start).days)
            joined = join_window_start + timedelta(days=self.rng.randrange(span))
            upgrades = self.rng.random()
            history: list[tuple[str, date, date | None, str]] = []
            current_tier = "CLASSIC"
            if upgrades < 0.34 and joined + timedelta(days=120) < self.end:
                plus_at = joined + timedelta(days=self.rng.randrange(90, 121))
                history.append(("CLASSIC", joined, plus_at, "SYNTHETIC_ACTIVITY_UPGRADE"))
                current_tier = "PLUS"
                if upgrades < 0.09 and plus_at + timedelta(days=150) < self.end:
                    premier_at = plus_at + timedelta(days=self.rng.randrange(120, 151))
                    history.append(("PLUS", plus_at, premier_at, "SYNTHETIC_ACTIVITY_UPGRADE"))
                    history.append(("PREMIER", premier_at, None, "SYNTHETIC_ACTIVITY_UPGRADE"))
                    current_tier = "PREMIER"
                else:
                    history.append(("PLUS", plus_at, None, "SYNTHETIC_ACTIVITY_UPGRADE"))
            else:
                history.append(("CLASSIC", joined, None, "INITIAL_ENROLLMENT"))

            member = {
                "member_no": f"M{index:06d}",
                "guest_id": guest_id,
                "pos_customer_ref": f"POSC{index:06d}",
                "facility_user_ref": f"FACU{index:06d}",
                "banquet_customer_id": f"BANQC{index:06d}",
                "joined_date": joined,
                "joined_at": iso_at(joined, 0),
                "current_tier": current_tier,
                "history": history,
                "points_balance": 0,
            }
            self.members.append(member)
            self.member_by_guest[guest_id] = member
            self.member_by_pos_ref[member["pos_customer_ref"]] = member
            self.member_by_facility_ref[member["facility_user_ref"]] = member
            self.member_by_banquet_ref[member["banquet_customer_id"]] = member

            for history_index, (tier, valid_from, valid_to, reason) in enumerate(history, 1):
                self.add(
                    "crm.member_grade_history",
                    grade_history_id=f"MGH{index:06d}-{history_index}",
                    member_no=member["member_no"],
                    tier_code=tier,
                    valid_from=iso_at(valid_from, 0),
                    valid_to=iso_at(valid_to, 0) if valid_to else "",
                    change_reason=reason,
                    is_synthetic=True,
                )
            self.add(
                "crm.customer_map",
                customer_map_id=f"CMAP{index:06d}",
                member_no=member["member_no"],
                pms_guest_id=guest_id,
                pos_customer_ref=member["pos_customer_ref"],
                facility_user_ref=member["facility_user_ref"],
                banquet_customer_id=member["banquet_customer_id"],
                valid_from=member["joined_at"],
                valid_to="",
                mapping_status="VERIFIED",
                mapping_confidence="1.0000",
                is_synthetic=True,
            )

    def build_banquet(self) -> None:
        source_url = "https://www.walkerhill.com/en/convention/Meeting"
        venue_specs = [
            ("VISTA_HALL", "VISTA", "Vista Hall", "BALLROOM", 600),
            ("WALKER_HALL", "GRAND", "Walker Hall", "BALLROOM", 450),
            ("GRAND_HALL", "GRAND", "Grand Hall", "BALLROOM", 300),
            ("ART_HALL", "GRAND", "Art Hall", "MEETING", 180),
            ("PINE", "GRAND", "Pine", "MEETING", 80),
            ("OAK", "GRAND", "Oak", "MEETING", 60),
            ("ASTON_HOUSE", "GRAND", "Aston House", "HOUSE", 220),
        ]
        venue_lookup: dict[str, tuple[str, int]] = {}
        for venue_id, hotel_code, public_name, category, capacity in venue_specs:
            venue_lookup[venue_id] = (hotel_code, capacity)
            self.add(
                "banquet.venues",
                venue_id=venue_id,
                hotel_code=hotel_code,
                public_name=public_name,
                venue_category=category,
                synthetic_capacity=capacity,
                public_capacity_note="명칭은 공식 공개 페이지 기준이며 생성용 정원은 실제 배치와 무관한 합성 가정입니다.",
                source_url=source_url,
                provenance_class="MIXED_REFERENCE_AND_ASSUMPTION",
                is_active=True,
            )

        event_index = 0
        line_index = 0
        block_index = 0
        venue_event_counts: dict[str, int] = defaultdict(int)
        for day in self.days:
            demand = float(self.calendar[day]["synthetic_demand_index"])
            for venue_id, (hotel_code, capacity) in venue_lookup.items():
                probability = 0.025 + demand * 0.045 + (0.025 if day.weekday() >= 5 else 0)
                force_first_event = day == self.days[-1] and venue_event_counts[venue_id] == 0
                if not force_first_event and self.rng.random() >= probability:
                    continue
                venue_event_counts[venue_id] += 1
                event_index += 1
                event_id = f"BE{event_index:06d}"
                member = self.active_member(day) if self.rng.random() < 0.42 else None
                customer_id = member["banquet_customer_id"] if member else f"BANQ_EXT{event_index:06d}"
                inquiry_day = day - timedelta(days=self.rng.randrange(21, 121))
                quoted_day = inquiry_day + timedelta(days=self.rng.randrange(1, 8))
                confirmed_day = quoted_day + timedelta(days=self.rng.randrange(1, 15))
                cancelled = self.rng.random() < 0.18
                status = "CANCELLED" if cancelled else "COMPLETED"
                expected = self.rng.randrange(max(8, capacity // 8), capacity + 1)
                actual = "" if cancelled else min(capacity, max(1, money(expected * self.rng.uniform(0.78, 1.02))))
                contracted = money((2500000 + expected * self.rng.uniform(85000, 190000)) / 1000) * 1000
                self.add(
                    "banquet.bookings",
                    banquet_event_id=event_id,
                    banquet_customer_id=customer_id,
                    venue_id=venue_id,
                    inquiry_at=iso_at(inquiry_day, 10, self.rng.randrange(60)),
                    quoted_at=iso_at(quoted_day, 14, self.rng.randrange(60)),
                    confirmed_at=iso_at(confirmed_day, 15, self.rng.randrange(60)) if not cancelled else "",
                    cancelled_at=iso_at(confirmed_day, 16, self.rng.randrange(60)) if cancelled else "",
                    event_date=day.isoformat(),
                    event_type=self.rng.choice(["CONFERENCE", "WEDDING", "MEETING", "SOCIAL_EVENT"]),
                    booking_status=status,
                    expected_guests=expected,
                    actual_attendees=actual,
                    contracted_amount=contracted,
                    is_synthetic=True,
                )
                daily = self.banquet_daily[(venue_id, day)]
                daily["booking_count"] += 1
                if cancelled:
                    daily["cancelled_count"] += 1
                    continue

                daily["completed_count"] += 1
                daily["actual_attendees"] += int(actual)
                self.banquet_by_hotel_day[(hotel_code, day)].append(event_id)
                shares = [("VENUE", Decimal("0.28")), ("FOOD_BEVERAGE", Decimal("0.62")), ("EQUIPMENT", Decimal("0.10"))]
                recognized_left = contracted
                for share_index, (category, share) in enumerate(shares):
                    line_index += 1
                    recognized = recognized_left if share_index == len(shares) - 1 else money(Decimal(contracted) * share)
                    recognized_left -= recognized
                    discount = money(Decimal(recognized) * Decimal("0.04"))
                    gross = recognized + discount
                    cost = money(Decimal(recognized) * (Decimal("0.42") if category == "FOOD_BEVERAGE" else Decimal("0.24")))
                    self.add(
                        "banquet.revenue_lines",
                        revenue_line_id=f"BRL{line_index:07d}",
                        banquet_event_id=event_id,
                        recognized_date=day.isoformat(),
                        revenue_category=category,
                        gross_amount=gross,
                        discount_amount=discount,
                        reversal_amount=0,
                        recognized_amount=recognized,
                        cost_amount=cost,
                        revenue_status="RECOGNIZED",
                        is_synthetic=True,
                    )
                daily["recognized_revenue"] += contracted
                self.record_member_revenue(member, day, hotel_code, "BANQUET", contracted)

                if expected >= 80 and self.rng.random() < 0.55:
                    block_index += 1
                    block_hotel = self.rng.choice(["GRAND", "VISTA", "DOUGLAS"])
                    nights = self.rng.choice([1, 2])
                    reserved = self.rng.randrange(4, 13) * nights
                    pickup = money(reserved * self.rng.uniform(0.55, 0.96))
                    self.add(
                        "banquet.room_blocks",
                        room_block_id=f"RBLK{block_index:06d}",
                        banquet_event_id=event_id,
                        hotel_code=block_hotel,
                        checkin_date=day.isoformat(),
                        checkout_date=(day + timedelta(days=nights)).isoformat(),
                        reserved_room_nights=reserved,
                        pickup_room_nights=min(reserved, pickup),
                        is_synthetic=True,
                    )
                    daily["reserved_room_nights"] += reserved
                    daily["pickup_room_nights"] += min(reserved, pickup)

    def build_inventory_and_stays(self) -> None:
        room_specs = [
            ("GRAND", "GRAND_DELUXE", "Grand Deluxe", 24, 250000),
            ("GRAND", "CLUB_DELUXE", "Club Deluxe", 12, 360000),
            ("GRAND", "GRAND_SUITE", "Grand Suite", 12, 520000),
            ("VISTA", "VISTA_DELUXE", "Vista Deluxe", 20, 300000),
            ("VISTA", "JUNIOR_CORNER_SUITE", "Junior Corner Suite", 10, 470000),
            ("VISTA", "SPA_DELUXE", "Spa Deluxe", 8, 550000),
            ("DOUGLAS", "DOUGLAS_DELUXE", "Douglas Deluxe", 12, 280000),
            ("DOUGLAS", "DOUGLAS_SUITE", "Douglas Suite", 6, 430000),
        ]
        room_url = "https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro"
        vista_url = "https://www.walkerhill.com/vistawalkerhillseoul/en/room/"
        for hotel_code, type_code, public_name, count, base_rate in room_specs:
            spec = {
                "hotel_code": hotel_code,
                "room_type_code": type_code,
                "public_name": public_name,
                "count": count,
                "base_rate": base_rate,
            }
            self.room_types.append(spec)
            self.add(
                "pms.room_types",
                hotel_code=hotel_code,
                room_type_code=type_code,
                public_name=public_name,
                synthetic_room_count=count,
                synthetic_base_rate_krw=base_rate,
                source_url=vista_url if hotel_code == "VISTA" else room_url,
                provenance_class="MIXED_REFERENCE_AND_ASSUMPTION",
                is_active=True,
            )
            for room_number in range(1, count + 1):
                room_id = f"{hotel_code}-{type_code}-{room_number:03d}"
                self.rooms_by_type[(hotel_code, type_code)].append(room_id)
                self.add(
                    "pms.rooms",
                    hotel_code=hotel_code,
                    room_id=room_id,
                    room_type_code=type_code,
                    is_active=True,
                    provenance_class="SYNTHETIC_ASSUMPTION",
                )

        for spec in self.room_types:
            rooms = self.rooms_by_type[(spec["hotel_code"], spec["room_type_code"])]
            for day_index, day in enumerate(self.days):
                out_of_order = 1 if self.rng.random() < 0.045 else 0
                house_use = 1 if self.rng.random() < 0.018 and len(rooms) > 6 else 0
                unavailable_rooms: list[str] = []
                if out_of_order:
                    unavailable_rooms.append(rooms[day_index % len(rooms)])
                if house_use:
                    candidate = rooms[(day_index + 3) % len(rooms)]
                    if candidate not in unavailable_rooms:
                        unavailable_rooms.append(candidate)
                    else:
                        house_use = 0
                for room_id in unavailable_rooms:
                    self.unavailable.add((room_id, day))
                available = len(rooms) - out_of_order - house_use
                row = {
                    "hotel_code": spec["hotel_code"],
                    "business_date": day.isoformat(),
                    "room_type_code": spec["room_type_code"],
                    "physical_rooms": len(rooms),
                    "out_of_order_rooms": out_of_order,
                    "house_use_rooms": house_use,
                    "available_room_nights": available,
                    "is_forecast": False,
                    "provenance_class": "GENERATED_FACT",
                }
                self.inventory[(spec["hotel_code"], day, spec["room_type_code"])] = row
                self.add("pms.room_inventory_daily", **row)

        occupied: dict[tuple[str, date], str] = {}
        stay_index = 0
        reservation_index = 0
        for day in self.days:
            demand = float(self.calendar[day]["synthetic_demand_index"])
            for spec in self.room_types:
                hotel_code = spec["hotel_code"]
                type_code = spec["room_type_code"]
                inventory = self.inventory[(hotel_code, day, type_code)]
                rooms = self.rooms_by_type[(hotel_code, type_code)]
                existing = sum(1 for room_id in rooms if (room_id, day) in occupied)
                occupancy_target = min(0.94, max(0.30, 0.28 + 0.70 * demand + self.rng.uniform(-0.06, 0.05)))
                target = min(inventory["available_room_nights"], money(inventory["available_room_nights"] * occupancy_target))
                needed = max(0, target - existing)
                candidates = [
                    room_id
                    for room_id in rooms
                    if (room_id, day) not in occupied and (room_id, day) not in self.unavailable
                ]
                self.rng.shuffle(candidates)
                while needed > 0 and candidates:
                    chosen_room = ""
                    chosen_nights: list[date] = []
                    for room_id in list(candidates):
                        max_los = min(self.rng.choices([1, 2, 3], weights=[50, 35, 15], k=1)[0], (self.end - day).days)
                        nights = [day + timedelta(days=offset) for offset in range(max_los)]
                        if all((room_id, night) not in occupied and (room_id, night) not in self.unavailable for night in nights):
                            chosen_room = room_id
                            chosen_nights = nights
                            candidates.remove(room_id)
                            break
                        candidates.remove(room_id)
                    if not chosen_room:
                        break
                    stay_index += 1
                    reservation_index += 1
                    guest_id = f"G{self.rng.randrange(1, 1201):06d}"
                    lead_days = self.rng.randrange(1, 121)
                    booked_day = day - timedelta(days=lead_days)
                    checkout = day + timedelta(days=len(chosen_nights))
                    quoted_rate = money(spec["base_rate"] * (0.78 + 0.62 * demand) / 1000) * 1000
                    discount_rate = self.rng.choice([0, 0, 0.05, 0.10, 0.15])
                    nightly_rate = money(quoted_rate * (1 - discount_rate) / 1000) * 1000
                    room_revenue = nightly_rate * len(chosen_nights)
                    discount_amount = (quoted_rate - nightly_rate) * len(chosen_nights)
                    linked_events = self.banquet_by_hotel_day.get((hotel_code, day), [])
                    banquet_event_id = self.rng.choice(linked_events) if linked_events and self.rng.random() < 0.18 else ""
                    booking_channel = "GROUP" if banquet_event_id else self.rng.choices(
                        ["DIRECT", "OTA", "CORPORATE"], weights=[48, 37, 15], k=1
                    )[0]
                    market_segment = "GROUP" if banquet_event_id else self.rng.choices(
                        ["LEISURE", "BUSINESS"], weights=[72, 28], k=1
                    )[0]
                    reservation_id = f"R{reservation_index:08d}"
                    stay_id = f"S{stay_index:08d}"
                    self.add(
                        "pms.reservations",
                        reservation_id=reservation_id,
                        guest_id=guest_id,
                        hotel_code=hotel_code,
                        room_type_code=type_code,
                        booked_at=iso_at(booked_day, self.rng.randrange(8, 22), self.rng.randrange(60)),
                        checkin_date=day.isoformat(),
                        checkout_date=checkout.isoformat(),
                        booking_channel=booking_channel,
                        market_segment=market_segment,
                        reservation_status="CHECKED_OUT",
                        cancelled_at="",
                        cancellation_reason_code="",
                        banquet_event_id=banquet_event_id,
                        quoted_room_rate=quoted_rate,
                        discount_amount=discount_amount,
                        booked_amount=room_revenue,
                        is_forecast=False,
                        is_synthetic=True,
                    )
                    stay_row = {
                        "stay_id": stay_id,
                        "reservation_id": reservation_id,
                        "guest_id": guest_id,
                        "hotel_code": hotel_code,
                        "room_id": chosen_room,
                        "room_type_code": type_code,
                        "actual_checkin_at": iso_at(day, 15, self.rng.randrange(60)),
                        "actual_checkout_at": iso_at(checkout, 11, self.rng.randrange(60)),
                        "occupied_room_nights": len(chosen_nights),
                        "guest_count": self.rng.choice([1, 2, 2, 2, 3]),
                        "room_revenue": room_revenue,
                        "other_room_charges": self.rng.choice([0, 0, 30000, 50000, 80000]),
                        "stay_status": "COMPLETED",
                        "complimentary_flag": False,
                        "house_use_flag": False,
                        "is_forecast": False,
                        "is_synthetic": True,
                    }
                    self.add("pms.stays", **stay_row)
                    member = self.member_by_guest.get(guest_id)
                    for night in chosen_nights:
                        occupied[(chosen_room, night)] = stay_id
                        self.stays_by_hotel_day[(hotel_code, night)].append(stay_row)
                        allocation = self.stay_allocations[(hotel_code, night, type_code)]
                        allocation["rooms_sold"] += 1
                        allocation["revenue"] += nightly_rate
                        self.record_member_revenue(member, night, hotel_code, "ROOMS", nightly_rate)
                    self.recognized_room_revenue[(hotel_code, checkout, type_code)] += room_revenue
                    needed -= 1

            for hotel_code in ("GRAND", "VISTA", "DOUGLAS"):
                cancellation_count = 1 if self.rng.random() < 0.38 else 0
                for _ in range(cancellation_count):
                    reservation_index += 1
                    spec = self.rng.choice([item for item in self.room_types if item["hotel_code"] == hotel_code])
                    guest_id = f"G{self.rng.randrange(1, 1201):06d}"
                    lead_days = self.rng.randrange(7, 91)
                    booked_day = day - timedelta(days=lead_days)
                    status = "CANCELLED" if self.rng.random() < 0.82 else "NO_SHOW"
                    quoted = spec["base_rate"]
                    self.add(
                        "pms.reservations",
                        reservation_id=f"R{reservation_index:08d}",
                        guest_id=guest_id,
                        hotel_code=hotel_code,
                        room_type_code=spec["room_type_code"],
                        booked_at=iso_at(booked_day, 12, self.rng.randrange(60)),
                        checkin_date=day.isoformat(),
                        checkout_date=(day + timedelta(days=1)).isoformat(),
                        booking_channel=self.rng.choice(["DIRECT", "OTA", "CORPORATE"]),
                        market_segment=self.rng.choice(["LEISURE", "BUSINESS"]),
                        reservation_status=status,
                        cancelled_at=iso_at(day - timedelta(days=1), 16, self.rng.randrange(60)) if status == "CANCELLED" else "",
                        cancellation_reason_code=self.rng.choice(["PLAN_CHANGE", "PRICE", "TRANSPORT"]) if status == "CANCELLED" else "",
                        banquet_event_id="",
                        quoted_room_rate=quoted,
                        discount_amount=0,
                        booked_amount=quoted,
                        is_forecast=False,
                        is_synthetic=True,
                    )

    def build_pos(self) -> None:
        dining_url = "https://www.walkerhill.com/en/book/Dining"
        outlet_specs = [
            ("ONDAL", "GRAND", "Ondal", "KOREAN", "12:00", "21:00", 80),
            ("GEUMRYONG", "GRAND", "Geumryong", "CHINESE", "12:00", "21:00", 80),
            ("THE_BUFFET", "GRAND", "The Buffet", "BUFFET", "07:00", "21:00", 160),
            ("PIZZA_HILL", "GRAND", "Pizza Hill", "PIZZA", "11:00", "22:00", 90),
            ("MYONGWOLGWAN", "GRAND", "Myongwolgwan", "GRILL", "12:00", "21:30", 120),
            ("MOEGI", "VISTA", "MOEGI", "JAPANESE", "12:00", "21:00", 70),
            ("THE_PAVILION", "VISTA", "The Pavilion", "CAFE", "10:00", "22:00", 75),
            ("LE_PASSAGE", "VISTA", "Le Passage", "CAFE", "08:00", "20:00", 55),
        ]
        for outlet_id, hotel_code, public_name, category, opening, closing, seats in outlet_specs:
            row = {
                "resort_id": "WH_SEOUL",
                "outlet_id": outlet_id,
                "hotel_code": hotel_code,
                "public_name": public_name,
                "outlet_category": category,
                "open_time": opening,
                "close_time": closing,
                "synthetic_seat_capacity": seats,
                "source_url": dining_url,
                "provenance_class": "MIXED_REFERENCE_AND_ASSUMPTION",
                "is_active": True,
            }
            self.outlet_by_id[outlet_id] = row
            self.add("pos.outlets", **row)

        menu_by_category: dict[str, list[dict]] = defaultdict(list)
        item_index = 0
        for category in sorted({spec[3] for spec in outlet_specs}):
            for item_number, (item_category, price) in enumerate(
                [("MAIN", 42000), ("MAIN", 68000), ("BEVERAGE", 12000), ("DESSERT", 18000)], 1
            ):
                item_index += 1
                item = {
                    "item_code": f"MI{item_index:04d}",
                    "outlet_category": category,
                    "item_name": f"Synthetic {category.title()} Item {item_number}",
                    "item_category": item_category,
                    "synthetic_unit_price_krw": price + (item_number * 1000),
                    "provenance_class": "SYNTHETIC_ASSUMPTION",
                    "is_active": True,
                }
                menu_by_category[category].append(item)
                self.add("pos.menu_items", **item)

        periods = {
            "BREAKFAST": (7 * 60, 10 * 60),
            "LUNCH": (12 * 60, 14 * 60),
            "AFTERNOON": (14 * 60, 17 * 60),
            "DINNER": (18 * 60, 21 * 60),
        }
        order_index = 0
        item_line_index = 0
        for day in self.days:
            demand = float(self.calendar[day]["synthetic_demand_index"])
            for outlet_id, outlet in self.outlet_by_id.items():
                opening = parse_hhmm(outlet["open_time"])
                closing = parse_hhmm(outlet["close_time"])
                allowed_periods = [
                    name
                    for name, (period_start, period_end) in periods.items()
                    if max(opening, period_start) < min(closing, period_end)
                ]
                no_sale_day = self.rng.random() < 0.025 + max(0, 0.50 - demand) * 0.10
                count = 0 if no_sale_day else max(1, int(1 + demand * 5 + self.rng.random() * 3))
                for _ in range(count):
                    order_index += 1
                    order_id = f"O{order_index:08d}"
                    service_period = self.rng.choice(allowed_periods)
                    period_start, period_end = periods[service_period]
                    minute_of_day = self.rng.randrange(max(opening, period_start), min(closing, period_end))
                    linked_stay = None
                    active_stays = self.stays_by_hotel_day.get((outlet["hotel_code"], day), [])
                    if active_stays and self.rng.random() < 0.38:
                        linked_stay = self.rng.choice(active_stays)
                    member = None
                    if linked_stay:
                        candidate = self.member_by_guest.get(linked_stay["guest_id"])
                        if candidate and candidate["joined_date"] <= day:
                            member = candidate
                    if member is None and self.rng.random() < 0.42:
                        member = self.active_member(day)
                    pos_customer_ref = member["pos_customer_ref"] if member else ""

                    selected_items = self.rng.choices(menu_by_category[outlet["outlet_category"]], k=self.rng.randrange(1, 4))
                    item_rows = []
                    header_gross = 0
                    header_discount = 0
                    for item in selected_items:
                        quantity = self.rng.choice([1, 1, 1, 2, 2, 3])
                        unit_price = item["synthetic_unit_price_krw"]
                        gross = quantity * unit_price
                        discount = money(gross * self.rng.choice([0, 0, 0, 0.05, 0.10]))
                        net = gross - discount
                        item_line_index += 1
                        item_rows.append(
                            {
                                "order_item_id": f"OI{item_line_index:09d}",
                                "order_id": order_id,
                                "item_code": item["item_code"],
                                "quantity": quantity,
                                "unit_price": unit_price,
                                "gross_amount": gross,
                                "discount_amount": discount,
                                "net_amount": net,
                                "is_synthetic": True,
                            }
                        )
                        header_gross += gross
                        header_discount += discount
                    item_net = header_gross - header_discount
                    order_status = self.rng.choices(
                        ["PAID", "PARTIAL_REFUND", "REFUNDED", "VOID"], weights=[94, 3, 2, 1], k=1
                    )[0]
                    refund = 0
                    void = 0
                    payment_status = order_status
                    if order_status == "PARTIAL_REFUND":
                        refund = money(item_net * self.rng.uniform(0.10, 0.40))
                    elif order_status == "REFUNDED":
                        refund = item_net
                    elif order_status == "VOID":
                        void = item_net
                        payment_status = "FAILED"
                    net_amount = item_net - refund - void
                    ordered_at = iso_at(day, minute_of_day // 60, minute_of_day % 60, self.rng.randrange(60))
                    self.add(
                        "pos.orders",
                        order_id=order_id,
                        outlet_id=outlet_id,
                        business_date=day.isoformat(),
                        ordered_at=ordered_at,
                        pos_customer_ref=pos_customer_ref,
                        linked_stay_id=linked_stay["stay_id"] if linked_stay else "",
                        guest_count=self.rng.choice([1, 2, 2, 3, 4]),
                        service_period=service_period,
                        order_status=order_status,
                        item_gross_amount=header_gross,
                        discount_amount=header_discount,
                        refund_amount=refund,
                        void_amount=void,
                        net_amount=net_amount,
                        payment_status=payment_status,
                        is_forecast=False,
                        is_synthetic=True,
                    )
                    for item_row in item_rows:
                        self.add("pos.order_items", **item_row)
                    daily = self.fnb_daily[(outlet_id, day, service_period)]
                    daily["order_count"] += 1
                    daily["covers"] += self.rows["pos.orders"][-1]["guest_count"]
                    daily["net"] += net_amount
                    self.fnb_hotel_daily[(outlet["hotel_code"], day)] += net_amount
                    self.fnb_order_count[(outlet["hotel_code"], day)] += 1
                    self.record_member_revenue(member, day, outlet["hotel_code"], "FNB", net_amount)

    def build_facility_and_resources(self) -> None:
        facility_url = "https://www.walkerhill.com/vistawalkerhillseoul/en"
        facility_specs = [
            ("VISTA_WELLNESS", "VISTA", "Vista Wellness Club", "WELLNESS", 80, "06:00", "22:00", 25000),
            ("V_SPA", "VISTA", "V SPA", "SPA", 30, "10:00", "21:00", 120000),
            ("SKYARD", "VISTA", "SKYARD", "OUTDOOR", 70, "09:00", "22:00", 0),
            ("RIVERPARK", "GRAND", "Riverpark", "LEISURE", 160, "09:00", "20:00", 30000),
            ("FOREST_PARK", "GRAND", "Forest Park", "OUTDOOR", 120, "08:00", "20:00", 0),
            ("DOUGLAS_LIBRARY", "DOUGLAS", "Douglas Library", "LOUNGE", 35, "07:00", "23:00", 0),
        ]
        prices: dict[str, int] = {}
        for facility_id, hotel_code, public_name, facility_type, capacity, opening, closing, price in facility_specs:
            row = {
                "facility_id": facility_id,
                "hotel_code": hotel_code,
                "public_name": public_name,
                "facility_type": facility_type,
                "synthetic_capacity": capacity,
                "open_time": opening,
                "close_time": closing,
                "source_url": facility_url,
                "provenance_class": "MIXED_REFERENCE_AND_ASSUMPTION",
                "is_active": True,
            }
            prices[facility_id] = price
            self.facility_by_id[facility_id] = row
            self.add("facility.master", **row)

        usage_index = 0
        incident_index = 0
        for day in self.days:
            weather = float(self.calendar[day]["synthetic_weather_score"])
            for facility_id, facility in self.facility_by_id.items():
                hotel_code = facility["hotel_code"]
                occupied_rooms = len(self.stays_by_hotel_day.get((hotel_code, day), []))
                capacity = sum(
                    spec["count"] for spec in self.room_types if spec["hotel_code"] == hotel_code
                )
                occupancy = occupied_rooms / capacity if capacity else 0
                outdoor_factor = weather if facility["facility_type"] in ("OUTDOOR", "LEISURE") else 0.65
                no_usage_day = self.rng.random() < 0.025
                count = 0 if no_usage_day else max(1, int(1 + occupancy * 5 + outdoor_factor * 2 + self.rng.random() * 2))
                opening = parse_hhmm(facility["open_time"])
                closing = parse_hhmm(facility["close_time"])
                for _ in range(count):
                    usage_index += 1
                    linked_stay = None
                    stays = self.stays_by_hotel_day.get((hotel_code, day), [])
                    if stays and self.rng.random() < 0.62:
                        linked_stay = self.rng.choice(stays)
                    member = None
                    if linked_stay:
                        candidate = self.member_by_guest.get(linked_stay["guest_id"])
                        if candidate and candidate["joined_date"] <= day:
                            member = candidate
                    if member is None and self.rng.random() < 0.32:
                        member = self.active_member(day)
                    guest_count = min(facility["synthetic_capacity"], self.rng.choice([1, 1, 2, 2, 3, 4]))
                    gross = prices[facility_id] * guest_count
                    discount = money(gross * (0.10 if member and gross else 0))
                    net = gross - discount
                    minute_of_day = self.rng.randrange(opening, closing)
                    self.add(
                        "facility.usage_events",
                        usage_event_id=f"FU{usage_index:08d}",
                        facility_id=facility_id,
                        business_date=day.isoformat(),
                        event_at=iso_at(day, minute_of_day // 60, minute_of_day % 60, self.rng.randrange(60)),
                        facility_user_ref=member["facility_user_ref"] if member else "",
                        linked_stay_id=linked_stay["stay_id"] if linked_stay else "",
                        usage_status="COMPLETED",
                        guest_count=guest_count,
                        gross_amount=gross,
                        discount_amount=discount,
                        net_amount=net,
                        is_synthetic=True,
                    )
                    daily = self.facility_daily[(facility_id, day)]
                    daily["usage_count"] += 1
                    daily["guests"] += guest_count
                    daily["net"] += net
                    self.facility_hotel_daily[(hotel_code, day)] += net
                    self.record_member_revenue(member, day, hotel_code, "FACILITY", net)

                if self.rng.random() < 0.018:
                    incident_index += 1
                    downtime = self.rng.randrange(15, 181)
                    start_minute = self.rng.randrange(opening, max(opening + 1, closing - min(downtime, 60)))
                    started = datetime.combine(day, time(start_minute // 60, start_minute % 60))
                    resolved = started + timedelta(minutes=downtime)
                    self.add(
                        "facility.incidents",
                        incident_id=f"INC{incident_index:07d}",
                        facility_id=facility_id,
                        started_at=started.isoformat() + SEOUL_SUFFIX,
                        resolved_at=resolved.isoformat() + SEOUL_SUFFIX,
                        severity=self.rng.choice(["LOW", "LOW", "MEDIUM", "HIGH"]),
                        downtime_minutes=downtime,
                        incident_status="RESOLVED",
                        is_synthetic=True,
                    )
                    daily = self.facility_daily[(facility_id, day)]
                    daily["incident_count"] += 1
                    daily["downtime"] += downtime

            for hotel_code in ("GRAND", "VISTA", "DOUGLAS"):
                occupied = len(self.stays_by_hotel_day.get((hotel_code, day), []))
                orders = self.fnb_order_count[(hotel_code, day)]
                banquet_events = len(self.banquet_by_hotel_day.get((hotel_code, day), []))
                departments = {
                    "ROOMS": 72 + occupied * 1.45,
                    "FNB": 48 + orders * 1.25,
                    "FACILITY": 32 + sum(
                        self.facility_daily[(facility_id, day)]["usage_count"]
                        for facility_id, facility in self.facility_by_id.items()
                        if facility["hotel_code"] == hotel_code
                    ) * 0.8,
                    "BANQUET": 20 + banquet_events * 28,
                }
                for department, scheduled in departments.items():
                    scheduled_hours = money(scheduled * 10) / 10
                    worked_hours = money(scheduled_hours * self.rng.uniform(0.94, 1.06) * 10) / 10
                    self.add(
                        "facility.staffing_daily",
                        hotel_code=hotel_code,
                        business_date=day.isoformat(),
                        department=department,
                        scheduled_hours=decimal_text(scheduled_hours, "0.1"),
                        worked_hours=decimal_text(worked_hours, "0.1"),
                        labor_cost=money(worked_hours * 26000),
                        fte=decimal_text(worked_hours / 8, "0.001"),
                        is_synthetic=True,
                    )
                season = self.calendar[day]["season_code"]
                hvac_load = {"WINTER": 165, "SUMMER": 135, "SPRING": 55, "AUTUMN": 45}[season]
                weather = float(self.calendar[day]["synthetic_weather_score"])
                energy = (
                    620
                    + hvac_load
                    + abs(weather - 0.65) * 95
                    + occupied * 14.0
                    + orders * 2.1
                    + banquet_events * 85
                    + self.rng.uniform(-105, 105)
                )
                water = 22 + occupied * 0.58 + orders * 0.07 + banquet_events * 2.1 + self.rng.uniform(-2, 2)
                waste = 18 + occupied * 0.32 + orders * 0.25 + banquet_events * 8 + self.rng.uniform(-2, 2)
                resource_cost = money(energy * 165 + water * 1200 + waste * 220)
                row = {
                    "hotel_code": hotel_code,
                    "business_date": day.isoformat(),
                    "energy_kwh": decimal_text(max(1, energy)),
                    "water_m3": decimal_text(max(1, water)),
                    "waste_kg": decimal_text(max(1, waste)),
                    "resource_cost": resource_cost,
                    "occupied_room_nights": occupied,
                    "is_synthetic": True,
                }
                self.resource_daily[(hotel_code, day)] = row
                self.add("facility.resource_daily", **row)

    def build_points_and_member_serving(self) -> None:
        eligible: dict[str, list[tuple[date, str, int]]] = defaultdict(list)
        for (member_no, day, _hotel, source), values in self.member_revenue.items():
            if source in ("ROOMS", "FNB") and values["revenue_amount"] > 0:
                eligible[member_no].append((day, "PMS" if source == "ROOMS" else "POS", values["revenue_amount"]))

        point_index = 0
        for member in self.members:
            balance = 100
            point_index += 1
            self.add(
                "crm.point_transactions",
                point_txn_id=f"PT{point_index:09d}",
                member_no=member["member_no"],
                event_at=member["joined_at"],
                txn_type="OPENING",
                points_delta=100,
                related_source="OPENING",
                related_id=f"OPEN-{member['member_no']}",
                is_synthetic=True,
            )
            for event_number, (day, source, revenue) in enumerate(sorted(eligible[member["member_no"]]), 1):
                if day < member["joined_date"] or day >= self.end:
                    continue
                earned = max(1, revenue // 2000)
                balance += earned
                point_index += 1
                self.add(
                    "crm.point_transactions",
                    point_txn_id=f"PT{point_index:09d}",
                    member_no=member["member_no"],
                    event_at=iso_at(day, 22, event_number % 50),
                    txn_type="EARN",
                    points_delta=earned,
                    related_source=source,
                    related_id=f"AGG-{member['member_no']}-{day.isoformat()}-{source}-{event_number}",
                    is_synthetic=True,
                )
                if event_number % 7 == 0 and balance > 200:
                    used = min(balance // 5, 5000)
                    balance -= used
                    point_index += 1
                    self.add(
                        "crm.point_transactions",
                        point_txn_id=f"PT{point_index:09d}",
                        member_no=member["member_no"],
                        event_at=iso_at(day, 22, 50 + event_number % 9),
                        txn_type="USE",
                        points_delta=-used,
                        related_source="CRM",
                        related_id=f"USE-{member['member_no']}-{event_number}",
                        is_synthetic=True,
                    )
                if event_number % 19 == 0 and balance > 100:
                    expired = min(balance // 20, 1000)
                    balance -= expired
                    point_index += 1
                    self.add(
                        "crm.point_transactions",
                        point_txn_id=f"PT{point_index:09d}",
                        member_no=member["member_no"],
                        event_at=iso_at(day, 23, event_number % 50),
                        txn_type="EXPIRE",
                        points_delta=-expired,
                        related_source="CRM",
                        related_id=f"EXPIRE-{member['member_no']}-{event_number}",
                        is_synthetic=True,
                    )
            member["points_balance"] = balance
            self.add(
                "crm.members",
                member_no=member["member_no"],
                joined_at=member["joined_at"],
                current_tier_code=member["current_tier"],
                member_status="ACTIVE",
                points_balance=balance,
                is_synthetic=True,
            )

        for (member_no, day, hotel_code, source), values in sorted(self.member_revenue.items()):
            self.add(
                "serving.member_daily_revenue_metrics",
                member_no=member_no,
                business_date=day.isoformat(),
                hotel_code=hotel_code,
                source_domain=source,
                transaction_count=values["transaction_count"],
                revenue_amount=values["revenue_amount"],
            )

    def build_serving(self) -> None:
        room_hotel_daily: dict[tuple[str, date], int] = defaultdict(int)
        for spec in self.room_types:
            hotel_code = spec["hotel_code"]
            type_code = spec["room_type_code"]
            for day in self.days:
                inventory = self.inventory[(hotel_code, day, type_code)]
                allocation = self.stay_allocations[(hotel_code, day, type_code)]
                available = inventory["available_room_nights"]
                sold = allocation["rooms_sold"]
                allocated_revenue = allocation["revenue"]
                room_hotel_daily[(hotel_code, day)] += allocated_revenue
                self.add(
                    "serving.hotel_daily_metrics",
                    hotel_code=hotel_code,
                    business_date=day.isoformat(),
                    room_type_code=type_code,
                    available_room_nights=available,
                    rooms_sold=sold,
                    stay_day_room_revenue=allocated_revenue,
                    recognized_room_revenue=self.recognized_room_revenue[(hotel_code, day, type_code)],
                    occupancy_rate=ratio(sold, available),
                    adr=ratio(allocated_revenue, sold),
                    revpar=ratio(allocated_revenue, available),
                )

        period_minutes = {
            "BREAKFAST": 180,
            "LUNCH": 120,
            "AFTERNOON": 180,
            "DINNER": 180,
        }
        for (outlet_id, day, service_period), values in sorted(self.fnb_daily.items()):
            outlet = self.outlet_by_id[outlet_id]
            seat_hours = Decimal(outlet["synthetic_seat_capacity"] * period_minutes[service_period]) / Decimal(60)
            self.add(
                "serving.fnb_daily_metrics",
                outlet_id=outlet_id,
                business_date=day.isoformat(),
                service_period=service_period,
                order_count=values["order_count"],
                fnb_covers=values["covers"],
                fnb_net_revenue=values["net"],
                available_seat_hours=decimal_text(seat_hours),
                average_check=ratio(values["net"], values["covers"]),
                revpash=ratio(values["net"], seat_hours),
            )

        venue_dates = {(venue_id, day) for venue_id, day in self.banquet_daily}
        for venue_id, day in sorted(venue_dates):
            values = self.banquet_daily[(venue_id, day)]
            self.add(
                "serving.banquet_daily_metrics",
                venue_id=venue_id,
                business_date=day.isoformat(),
                booking_count=values["booking_count"],
                completed_count=values["completed_count"],
                cancelled_count=values["cancelled_count"],
                actual_attendees=values["actual_attendees"],
                recognized_revenue=values["recognized_revenue"],
                reserved_room_nights=values["reserved_room_nights"],
                pickup_room_nights=values["pickup_room_nights"],
                room_block_pickup_rate=ratio(values["pickup_room_nights"], values["reserved_room_nights"]),
            )

        for facility_id in sorted(self.facility_by_id):
            for day in self.days:
                values = self.facility_daily[(facility_id, day)]
                self.add(
                    "serving.facility_daily_metrics",
                    facility_id=facility_id,
                    business_date=day.isoformat(),
                    usage_count=values["usage_count"],
                    facility_guests=values["guests"],
                    facility_net_revenue=values["net"],
                    incident_count=values["incident_count"],
                    downtime_minutes=values["downtime"],
                )

        for hotel_code in ("GRAND", "VISTA", "DOUGLAS"):
            for day in self.days:
                resource = self.resource_daily[(hotel_code, day)]
                occupied = resource["occupied_room_nights"]
                self.add(
                    "serving.resource_daily_metrics",
                    hotel_code=hotel_code,
                    business_date=day.isoformat(),
                    occupied_room_nights=occupied,
                    energy_kwh=resource["energy_kwh"],
                    water_m3=resource["water_m3"],
                    waste_kg=resource["waste_kg"],
                    resource_cost=resource["resource_cost"],
                    energy_per_occupied_room=ratio(resource["energy_kwh"], occupied),
                    water_per_occupied_room=ratio(resource["water_m3"], occupied),
                )
                banquet_revenue = sum(
                    values["recognized_revenue"]
                    for (venue_id, event_day), values in self.banquet_daily.items()
                    if event_day == day
                    and next(
                        row["hotel_code"] for row in self.rows["banquet.venues"] if row["venue_id"] == venue_id
                    )
                    == hotel_code
                )
                room_revenue = room_hotel_daily[(hotel_code, day)]
                fnb_revenue = self.fnb_hotel_daily[(hotel_code, day)]
                facility_revenue = self.facility_hotel_daily[(hotel_code, day)]
                self.add(
                    "serving.total_operating_daily_metrics",
                    hotel_code=hotel_code,
                    business_date=day.isoformat(),
                    room_revenue=room_revenue,
                    fnb_net_revenue=fnb_revenue,
                    banquet_recognized_revenue=banquet_revenue,
                    facility_net_revenue=facility_revenue,
                    total_operating_revenue=room_revenue + fnb_revenue + banquet_revenue + facility_revenue,
                )

    def generate(self) -> None:
        self.build_reference()
        self.build_people_and_membership()
        self.build_banquet()
        self.build_inventory_and_stays()
        self.build_pos()
        self.build_facility_and_resources()
        self.build_points_and_member_serving()
        self.build_serving()

    def write(self, output: Path) -> dict:
        output.mkdir(parents=True, exist_ok=True)
        files = []
        for dataset_id, dataset in sorted(self.datasets.items()):
            domain, name = dataset_id.split(".", 1)
            path = output / "data" / domain / f"{name}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            fields = list(dataset["fields"])
            rows = self.rows.get(dataset_id, [])
            primary_key = dataset.get("primary_key", [])
            rows = sorted(rows, key=lambda row: tuple(str(row.get(key, "")) for key in primary_key))
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {
                            key: "" if value is None else str(value).lower() if isinstance(value, bool) else value
                            for key, value in row.items()
                        }
                    )
            files.append(
                {
                    "dataset_id": dataset_id,
                    "relative_path": path.relative_to(output).as_posix(),
                    "row_count": len(rows),
                    "sha256": sha256(path),
                }
            )

        catalog = {
            "catalog_version": self.product["versions"]["catalog_version"],
            "contract_version": self.product["contract_version"],
            "schema_version": self.schema["schema_version"],
            "dataset_id": self.product["dataset_id"],
            "display_label": self.product["claim_boundary"]["display_label"],
            "claim_boundary": self.product["claim_boundary"],
            "provenance_classes": self.product["provenance_classes"],
            "public_references": self.product["public_references"],
            "supported_question_families": self.product["supported_question_families"],
            "metrics": self.product["metrics"],
            "approved_joins": self.product["approved_joins"],
            "selection_policy": self.schema["selection_policy"],
            "datasets": [],
        }
        for dataset in sorted(self.datasets.values(), key=lambda item: item["fqn"]):
            catalog_dataset = {
                key: dataset[key]
                for key in self.product["metadata_contract"]["dataset_required"]
                if key != "schema_version"
            }
            catalog_dataset.update(
                {
                    "id": dataset["id"],
                    "fqn": dataset["fqn"],
                    "schema_version": self.schema["schema_version"],
                    "fields": [],
                }
            )
            for field_name, (field_type, nullable, unit, sensitivity, description) in dataset["fields"].items():
                catalog_dataset["fields"].append(
                    {
                        "qualified_key": f"{dataset['fqn']}.{field_name}",
                        "name": field_name,
                        "type": field_type,
                        "nullable": nullable,
                        "unit": unit,
                        "sensitivity": sensitivity,
                        "description": description,
                    }
                )
            catalog["datasets"].append(catalog_dataset)
        catalog_path = output / "metadata" / "datahub_catalog.json"
        stable_json(catalog_path, catalog)

        manifest = {
            "dataset_id": self.product["dataset_id"],
            "display_label": self.product["claim_boundary"]["display_label"],
            "period": {"start": self.start.isoformat(), "end_exclusive": self.end.isoformat()},
            "seed": self.seed,
            "versions": self.product["versions"],
            "generated_at": f"{self.end.isoformat()}T23:59:59{SEOUL_SUFFIX}",
            "contract_hashes": {
                PRODUCT_PATH.name: sha256(PRODUCT_PATH),
                SCHEMA_PATH.name: sha256(SCHEMA_PATH),
            },
            "catalog": {
                "relative_path": catalog_path.relative_to(output).as_posix(),
                "sha256": sha256(catalog_path),
            },
            "files": files,
        }
        manifest_path = output / "manifest.json"
        stable_json(manifest_path, manifest)
        manifest["manifest_sha256"] = sha256(manifest_path)
        return manifest


def parse_args() -> argparse.Namespace:
    product = load_json(PRODUCT_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default=product["period"]["start"])
    parser.add_argument("--end-exclusive", default=product["period"]["end_exclusive"])
    parser.add_argument("--seed", type=int, default=product["versions"]["seed"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end_exclusive = date.fromisoformat(args.end_exclusive)
    if start >= end_exclusive:
        raise SystemExit("--start must be earlier than --end-exclusive")
    generator = Generator(start, end_exclusive, args.seed)
    generator.generate()
    manifest = generator.write(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "datasets": len(manifest["files"]),
                "rows": sum(item["row_count"] for item in manifest["files"]),
                "manifest_sha256": manifest["manifest_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
