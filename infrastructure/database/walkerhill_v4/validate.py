#!/usr/bin/env python3
"""Independently validate a Walkerhill v4 candidate and emit release gates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


HERE = Path(__file__).resolve().parent
PRODUCT_PATH = HERE / "product_contract.v2.json"
SCHEMA_PATH = HERE / "schema_contract.v2.json"
GATE_IDS = [
    "structural_integrity",
    "capacity_integrity",
    "financial_reconciliation",
    "temporal_identity",
    "behavioral_coverage",
    "metric_equivalence",
    "metadata_completeness",
    "semantic_uniqueness",
    "determinism",
    "asset_binding_verification",
    "held_out_evaluation",
    "runtime_canary",
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dec(value: str | int | Decimal) -> Decimal:
    return Decimal(str(value))


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def day(value: str) -> date:
    return date.fromisoformat(value)


def close_enough(left: str | int | Decimal, right: str | int | Decimal, tolerance: Decimal = Decimal("0.00001")) -> bool:
    if left == "" and right == "":
        return True
    if left == "" or right == "":
        return False
    return abs(dec(left) - dec(right)) <= tolerance


def safe_ratio(numerator: int | Decimal, denominator: int | Decimal) -> str:
    if not denominator:
        return ""
    return str(dec(numerator) / dec(denominator))


class Validator:
    def __init__(self, candidate: Path, determinism_reference: Path | None = None) -> None:
        self.candidate = candidate.resolve()
        self.reference = determinism_reference.resolve() if determinism_reference else None
        self.product = read_json(PRODUCT_PATH)
        self.schema = read_json(SCHEMA_PATH)
        self.datasets = {item["id"]: item for item in self.schema["datasets"]}
        self.rows: dict[str, list[dict[str, str]]] = {}
        self.issue_count = defaultdict(int)
        self.issue_samples: dict[str, list[str]] = defaultdict(list)
        self.manifest: dict = {}
        self.catalog: dict = {}
        self.observations: dict[str, object] = {}

    def fail(self, gate: str, message: str) -> None:
        self.issue_count[gate] += 1
        if len(self.issue_samples[gate]) < 40:
            self.issue_samples[gate].append(message)

    def load(self) -> None:
        manifest_path = self.candidate / "manifest.json"
        if not manifest_path.exists():
            self.fail("structural_integrity", "manifest.json이 없습니다.")
            return
        self.manifest = read_json(manifest_path)
        expected_contract_hashes = {
            PRODUCT_PATH.name: sha256(PRODUCT_PATH),
            SCHEMA_PATH.name: sha256(SCHEMA_PATH),
        }
        if self.manifest.get("contract_hashes") != expected_contract_hashes:
            self.fail("structural_integrity", "manifest의 계약 hash가 현재 계약과 다릅니다.")
        catalog_path = self.candidate / self.manifest.get("catalog", {}).get(
            "relative_path", "metadata/datahub_catalog.json"
        )
        if catalog_path.exists():
            self.catalog = read_json(catalog_path)
        else:
            self.fail("metadata_completeness", f"카탈로그가 없습니다: {catalog_path}")

        manifest_files = {item["dataset_id"]: item for item in self.manifest.get("files", [])}
        for dataset_id, dataset in self.datasets.items():
            item = manifest_files.get(dataset_id)
            if item is None:
                self.fail("structural_integrity", f"manifest에 {dataset_id}가 없습니다.")
                self.rows[dataset_id] = []
                continue
            path = self.candidate / item["relative_path"]
            if not path.exists():
                self.fail("structural_integrity", f"데이터 파일이 없습니다: {item['relative_path']}")
                self.rows[dataset_id] = []
                continue
            if sha256(path) != item["sha256"]:
                self.fail("structural_integrity", f"파일 hash 불일치: {dataset_id}")
            with path.open("r", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                expected_fields = list(dataset["fields"])
                if reader.fieldnames != expected_fields:
                    self.fail(
                        "structural_integrity",
                        f"{dataset_id} header가 계약과 다릅니다: {reader.fieldnames}",
                    )
                data = list(reader)
            if len(data) != item["row_count"]:
                self.fail("structural_integrity", f"{dataset_id} row_count 불일치")
            self.rows[dataset_id] = data

    def validate_contract_and_metadata(self) -> None:
        catalog_contract_values = {
            "catalog_version": self.product["versions"]["catalog_version"],
            "contract_version": self.product["contract_version"],
            "schema_version": self.schema["schema_version"],
            "claim_boundary": self.product["claim_boundary"],
            "provenance_classes": self.product["provenance_classes"],
            "public_references": self.product["public_references"],
            "supported_question_families": self.product["supported_question_families"],
            "metrics": self.product["metrics"],
            "approved_joins": self.product["approved_joins"],
            "selection_policy": self.schema["selection_policy"],
        }
        for key, expected in catalog_contract_values.items():
            if self.catalog.get(key) != expected:
                self.fail("metadata_completeness", f"카탈로그의 {key}가 현재 계약과 다릅니다.")
        dataset_ids = list(self.datasets)
        fqns = [dataset["fqn"] for dataset in self.datasets.values()]
        if len(dataset_ids) != len(set(dataset_ids)):
            self.fail("semantic_uniqueness", "Dataset id가 중복됩니다.")
        if len(fqns) != len(set(fqns)):
            self.fail("semantic_uniqueness", "Dataset FQN이 중복됩니다.")
        preferred_names: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        allowed_provenance = set(self.product["provenance_classes"])
        for dataset in self.datasets.values():
            if dataset["provenance_class"] not in allowed_provenance:
                self.fail(
                    "metadata_completeness",
                    f"{dataset['id']}의 provenance class가 계약에 없습니다: {dataset['provenance_class']}",
                )
            if dataset["preferred_asset"] and not dataset["deprecated"]:
                preferred_names[(dataset["domain"], dataset["business_name"], dataset["grain"])].append(dataset["id"])
        for key, values in preferred_names.items():
            if len(values) > 1:
                self.fail("semantic_uniqueness", f"동일 의미 preferred asset 중복 {key}: {values}")

        for metric in self.product["metrics"]:
            source_parts = metric["source"].split(".")
            source_id = ".".join(source_parts[:2])
            if source_id not in self.datasets:
                self.fail("structural_integrity", f"Metric {metric['id']}의 source가 없습니다: {source_id}")
        for join in self.product["approved_joins"]:
            for side in ("left", "right"):
                if join[side] not in self.datasets:
                    self.fail("structural_integrity", f"JOIN {join['id']}의 {side} asset이 없습니다: {join[side]}")

        required_dataset = self.product["metadata_contract"]["dataset_required"]
        required_field = self.product["metadata_contract"]["field_required"]
        catalog_datasets = {item.get("id"): item for item in self.catalog.get("datasets", [])}
        if len(catalog_datasets) != len(self.datasets):
            self.fail(
                "metadata_completeness",
                f"카탈로그 dataset 수 {len(catalog_datasets)} != 계약 {len(self.datasets)}",
            )
        qualified_keys: list[str] = []
        for dataset_id, dataset in self.datasets.items():
            catalog_dataset = catalog_datasets.get(dataset_id)
            if not catalog_dataset:
                self.fail("metadata_completeness", f"카탈로그에 {dataset_id}가 없습니다.")
                continue
            for key in required_dataset:
                if key not in catalog_dataset or catalog_dataset[key] in (None, "") and key not in ("time_field",):
                    self.fail("metadata_completeness", f"{dataset_id}.{key} metadata가 비었습니다.")
            fields = {item.get("name"): item for item in catalog_dataset.get("fields", [])}
            if set(fields) != set(dataset["fields"]):
                self.fail("metadata_completeness", f"{dataset_id} field catalog가 schema와 다릅니다.")
            for field_name, item in fields.items():
                for key in required_field:
                    if key not in item or item[key] in (None, "") and key not in ("unit",):
                        self.fail("metadata_completeness", f"{dataset_id}.{field_name}.{key}가 비었습니다.")
                expected_key = f"{dataset['fqn']}.{field_name}"
                if item.get("qualified_key") != expected_key:
                    self.fail("metadata_completeness", f"qualified field key 불일치: {expected_key}")
                qualified_keys.append(item.get("qualified_key", ""))
        if len(qualified_keys) != len(set(qualified_keys)):
            self.fail("semantic_uniqueness", "qualified field key가 중복됩니다.")

    def validate_structure(self) -> None:
        type_checks = {
            "integer": lambda value: int(value),
            "money": lambda value: Decimal(value),
            "decimal": lambda value: Decimal(value),
            "boolean": lambda value: value if value in ("true", "false") else (_ for _ in ()).throw(ValueError()),
            "date": date.fromisoformat,
            "timestamp": datetime.fromisoformat,
            "time": lambda value: datetime.strptime(value, "%H:%M"),
            "string": lambda value: value,
        }
        for dataset_id, dataset in self.datasets.items():
            seen: set[tuple[str, ...]] = set()
            primary_key = dataset.get("primary_key", [])
            for row_number, row in enumerate(self.rows.get(dataset_id, []), 2):
                if "provenance_class" in row and row["provenance_class"] not in self.product["provenance_classes"]:
                    self.fail(
                        "metadata_completeness",
                        f"{dataset_id}:{row_number} provenance class가 계약에 없습니다: {row['provenance_class']}",
                    )
                for field_name, field_contract in dataset["fields"].items():
                    value = row.get(field_name, "")
                    nullable = field_contract[1]
                    if value == "":
                        if not nullable:
                            self.fail("structural_integrity", f"{dataset_id}:{row_number}.{field_name} NULL")
                        continue
                    try:
                        type_checks[field_contract[0]](value)
                    except (ValueError, TypeError, InvalidOperation):
                        self.fail(
                            "structural_integrity",
                            f"{dataset_id}:{row_number}.{field_name} type={field_contract[0]} value={value}",
                        )
                key = tuple(row.get(field, "") for field in primary_key)
                if any(value == "" for value in key):
                    self.fail("structural_integrity", f"{dataset_id}:{row_number} PK가 비었습니다.")
                elif key in seen:
                    self.fail("structural_integrity", f"{dataset_id} PK 중복: {key}")
                seen.add(key)

        fqn_to_id = {dataset["fqn"]: dataset_id for dataset_id, dataset in self.datasets.items()}
        for dataset_id, dataset in self.datasets.items():
            for local_field, target in dataset.get("references", {}).items():
                target_fqn, target_field = target.rsplit(".", 1)
                target_id = fqn_to_id[target_fqn]
                allowed = {row[target_field] for row in self.rows[target_id]}
                for row in self.rows[dataset_id]:
                    value = row[local_field]
                    if value and value not in allowed:
                        self.fail("structural_integrity", f"{dataset_id}.{local_field} FK 위반: {value}")

    def validate_pms(self) -> None:
        inventories = {
            (row["hotel_code"], day(row["business_date"]), row["room_type_code"]): row
            for row in self.rows["pms.room_inventory_daily"]
        }
        for key, row in inventories.items():
            expected = int(row["physical_rooms"]) - int(row["out_of_order_rooms"]) - int(row["house_use_rooms"])
            if expected != int(row["available_room_nights"]):
                self.fail("capacity_integrity", f"inventory 식 불일치: {key}")

        reservations = {row["reservation_id"]: row for row in self.rows["pms.reservations"]}
        rooms = {row["room_id"]: row for row in self.rows["pms.rooms"]}
        occupancy: dict[tuple[str, date], str] = {}
        sold = defaultdict(int)
        allocated_revenue = defaultdict(Decimal)
        recognized_revenue = defaultdict(Decimal)
        for reservation in reservations.values():
            if day(reservation["checkin_date"]) >= day(reservation["checkout_date"]):
                self.fail("structural_integrity", f"예약 날짜 역전: {reservation['reservation_id']}")
            if dt(reservation["booked_at"]).date() > day(reservation["checkin_date"]):
                self.fail("temporal_identity", f"예약 생성이 체크인 이후: {reservation['reservation_id']}")
            cancelled = reservation["reservation_status"] == "CANCELLED"
            if cancelled != bool(reservation["cancelled_at"]):
                self.fail("structural_integrity", f"취소 timestamp 불일치: {reservation['reservation_id']}")

        for stay in self.rows["pms.stays"]:
            reservation = reservations[stay["reservation_id"]]
            room = rooms[stay["room_id"]]
            if any(
                [
                    stay["guest_id"] != reservation["guest_id"],
                    stay["hotel_code"] != reservation["hotel_code"],
                    stay["room_type_code"] != reservation["room_type_code"],
                    stay["hotel_code"] != room["hotel_code"],
                    stay["room_type_code"] != room["room_type_code"],
                ]
            ):
                self.fail("structural_integrity", f"투숙-예약-객실 속성 불일치: {stay['stay_id']}")
            checkin = dt(stay["actual_checkin_at"]).date()
            checkout = dt(stay["actual_checkout_at"]).date()
            nights = (checkout - checkin).days
            if nights != int(stay["occupied_room_nights"]) or nights <= 0:
                self.fail("structural_integrity", f"투숙 박수 불일치: {stay['stay_id']}")
                continue
            nightly_revenue = dec(stay["room_revenue"]) / nights
            for offset in range(nights):
                business_date = checkin.fromordinal(checkin.toordinal() + offset)
                room_day = (stay["room_id"], business_date)
                if room_day in occupancy:
                    self.fail(
                        "capacity_integrity",
                        f"객실 중복 배정: {stay['room_id']} {business_date} {occupancy[room_day]} {stay['stay_id']}",
                    )
                occupancy[room_day] = stay["stay_id"]
                metric_key = (stay["hotel_code"], business_date, stay["room_type_code"])
                sold[metric_key] += 1
                allocated_revenue[metric_key] += nightly_revenue
            recognized_revenue[(stay["hotel_code"], checkout, stay["room_type_code"])] += dec(stay["room_revenue"])

        for key, count in sold.items():
            inventory = inventories.get(key)
            if inventory is None:
                self.fail("capacity_integrity", f"투숙에 대응하는 inventory 없음: {key}")
            elif count > int(inventory["available_room_nights"]):
                self.fail("capacity_integrity", f"객실 용량 초과: {key} {count}")

        serving = {
            (row["hotel_code"], day(row["business_date"]), row["room_type_code"]): row
            for row in self.rows["serving.hotel_daily_metrics"]
        }
        if set(serving) != set(inventories):
            self.fail("metric_equivalence", "hotel_daily_metrics grain coverage가 inventory와 다릅니다.")
        for key, inventory in inventories.items():
            metric = serving.get(key)
            if not metric:
                continue
            available = int(inventory["available_room_nights"])
            rooms_sold = sold[key]
            revenue = allocated_revenue[key]
            checks = {
                "available_room_nights": available,
                "rooms_sold": rooms_sold,
                "stay_day_room_revenue": revenue,
                "recognized_room_revenue": recognized_revenue[key],
                "occupancy_rate": safe_ratio(rooms_sold, available),
                "adr": safe_ratio(revenue, rooms_sold),
                "revpar": safe_ratio(revenue, available),
            }
            for field, expected in checks.items():
                if not close_enough(metric[field], expected):
                    self.fail("metric_equivalence", f"hotel metric 불일치 {key}.{field}")
            if metric["occupancy_rate"] and not Decimal("0") <= dec(metric["occupancy_rate"]) <= Decimal("1"):
                self.fail("capacity_integrity", f"점유율 범위 위반: {key}")

    def validate_pos(self) -> None:
        items_by_order: dict[str, list[dict]] = defaultdict(list)
        for item in self.rows["pos.order_items"]:
            items_by_order[item["order_id"]].append(item)
            if dec(item["gross_amount"]) != dec(item["quantity"]) * dec(item["unit_price"]):
                self.fail("financial_reconciliation", f"POS item gross 불일치: {item['order_item_id']}")
            if dec(item["net_amount"]) != dec(item["gross_amount"]) - dec(item["discount_amount"]):
                self.fail("financial_reconciliation", f"POS item net 불일치: {item['order_item_id']}")

        outlets = {row["outlet_id"]: row for row in self.rows["pos.outlets"]}
        outlet_activity = defaultdict(int)
        aggregates = defaultdict(lambda: {"count": 0, "covers": 0, "net": Decimal(0)})
        for order in self.rows["pos.orders"]:
            order_items = items_by_order.get(order["order_id"], [])
            if not order_items:
                self.fail("financial_reconciliation", f"항목 없는 POS 주문: {order['order_id']}")
                continue
            gross = sum(dec(item["gross_amount"]) for item in order_items)
            discount = sum(dec(item["discount_amount"]) for item in order_items)
            item_net = sum(dec(item["net_amount"]) for item in order_items)
            if gross != dec(order["item_gross_amount"]) or discount != dec(order["discount_amount"]):
                self.fail("financial_reconciliation", f"POS header-item 합계 불일치: {order['order_id']}")
            expected_net = item_net - dec(order["refund_amount"]) - dec(order["void_amount"])
            if expected_net != dec(order["net_amount"]):
                self.fail("financial_reconciliation", f"POS net 불일치: {order['order_id']}")
            outlet = outlets[order["outlet_id"]]
            event = dt(order["ordered_at"])
            event_minute = event.hour * 60 + event.minute
            opening = int(outlet["open_time"][:2]) * 60 + int(outlet["open_time"][3:])
            closing = int(outlet["close_time"][:2]) * 60 + int(outlet["close_time"][3:])
            if not opening <= event_minute < closing or event.date() != day(order["business_date"]):
                self.fail("behavioral_coverage", f"영업시간 밖 POS 주문: {order['order_id']}")
            outlet_activity[order["outlet_id"]] += 1
            key = (order["outlet_id"], order["business_date"], order["service_period"])
            aggregates[key]["count"] += 1
            aggregates[key]["covers"] += int(order["guest_count"])
            aggregates[key]["net"] += dec(order["net_amount"])

        for outlet_id, outlet in outlets.items():
            if outlet["is_active"] == "true" and outlet_activity[outlet_id] == 0:
                self.fail("behavioral_coverage", f"활성 업장에 주문이 없습니다: {outlet_id}")
        serving = {
            (row["outlet_id"], row["business_date"], row["service_period"]): row
            for row in self.rows["serving.fnb_daily_metrics"]
        }
        if set(serving) != set(aggregates):
            self.fail("metric_equivalence", "fnb_daily_metrics grain coverage 불일치")
        for key, values in aggregates.items():
            row = serving.get(key)
            if not row:
                continue
            checks = {
                "order_count": values["count"],
                "fnb_covers": values["covers"],
                "fnb_net_revenue": values["net"],
                "average_check": safe_ratio(values["net"], values["covers"]),
                "revpash": safe_ratio(values["net"], dec(row["available_seat_hours"])),
            }
            for field, expected in checks.items():
                if not close_enough(row[field], expected):
                    self.fail("metric_equivalence", f"F&B metric 불일치 {key}.{field}")

    def validate_crm(self) -> None:
        members = {row["member_no"]: row for row in self.rows["crm.members"]}
        histories = defaultdict(list)
        for row in self.rows["crm.member_grade_history"]:
            histories[row["member_no"]].append(row)
        for member_no, member in members.items():
            ordered = sorted(histories[member_no], key=lambda row: row["valid_from"])
            if not ordered or dt(ordered[0]["valid_from"]) != dt(member["joined_at"]):
                self.fail("temporal_identity", f"등급 이력이 가입 시점부터 시작하지 않음: {member_no}")
            for left, right in zip(ordered, ordered[1:]):
                if not left["valid_to"] or dt(left["valid_to"]) != dt(right["valid_from"]):
                    self.fail("temporal_identity", f"등급 이력 gap/overlap: {member_no}")
            if ordered and ordered[-1]["valid_to"]:
                self.fail("temporal_identity", f"현재 등급 이력이 닫혀 있음: {member_no}")
            if ordered and ordered[-1]["tier_code"] != member["current_tier_code"]:
                self.fail("temporal_identity", f"현재 등급 불일치: {member_no}")

        maps = self.rows["crm.customer_map"]
        for mapping in maps:
            if dt(mapping["valid_from"]) < dt(members[mapping["member_no"]]["joined_at"]):
                self.fail("temporal_identity", f"가입 전 identity map: {mapping['customer_map_id']}")
            if mapping["valid_to"] and dt(mapping["valid_to"]) <= dt(mapping["valid_from"]):
                self.fail("temporal_identity", f"identity map 유효구간 역전: {mapping['customer_map_id']}")

        transactions = defaultdict(list)
        for row in self.rows["crm.point_transactions"]:
            transactions[row["member_no"]].append(row)
        for member_no, member in members.items():
            balance = 0
            for row in sorted(transactions[member_no], key=lambda item: (item["event_at"], item["point_txn_id"])):
                delta = int(row["points_delta"])
                if row["txn_type"] in ("OPENING", "EARN") and delta <= 0:
                    self.fail("financial_reconciliation", f"포인트 양수 유형 부호 오류: {row['point_txn_id']}")
                if row["txn_type"] in ("USE", "EXPIRE") and delta >= 0:
                    self.fail("financial_reconciliation", f"포인트 차감 유형 부호 오류: {row['point_txn_id']}")
                if dt(row["event_at"]) < dt(member["joined_at"]):
                    self.fail("temporal_identity", f"가입 전 포인트 이벤트: {row['point_txn_id']}")
                balance += delta
                if balance < 0:
                    self.fail("financial_reconciliation", f"포인트 running balance 음수: {member_no}")
            if balance != int(member["points_balance"]):
                self.fail("financial_reconciliation", f"포인트 잔액-원장 불일치: {member_no}")

    def validate_banquet_facility(self) -> None:
        venues = {row["venue_id"]: row for row in self.rows["banquet.venues"]}
        bookings = {row["banquet_event_id"]: row for row in self.rows["banquet.bookings"]}
        venue_activity = defaultdict(int)
        lines_by_event = defaultdict(list)
        banquet_agg = defaultdict(lambda: {"bookings": 0, "completed": 0, "cancelled": 0, "attendees": 0, "revenue": Decimal(0), "reserved": 0, "pickup": 0})
        for line in self.rows["banquet.revenue_lines"]:
            lines_by_event[line["banquet_event_id"]].append(line)
            expected = dec(line["gross_amount"]) - dec(line["discount_amount"]) - dec(line["reversal_amount"])
            if expected != dec(line["recognized_amount"]):
                self.fail("financial_reconciliation", f"연회 revenue line 불일치: {line['revenue_line_id']}")
        for event_id, booking in bookings.items():
            venue = venues[booking["venue_id"]]
            capacity = int(venue["synthetic_capacity"])
            venue_activity[booking["venue_id"]] += 1
            if int(booking["expected_guests"]) > capacity:
                self.fail("capacity_integrity", f"연회 예상 인원 초과: {event_id}")
            completed = booking["booking_status"] == "COMPLETED"
            cancelled = booking["booking_status"] == "CANCELLED"
            if completed and (not booking["actual_attendees"] or int(booking["actual_attendees"]) > capacity):
                self.fail("capacity_integrity", f"연회 실제 인원 오류: {event_id}")
            line_total = sum(dec(line["recognized_amount"]) for line in lines_by_event[event_id])
            if completed and line_total != dec(booking["contracted_amount"]):
                self.fail("financial_reconciliation", f"연회 계약-매출 line 불일치: {event_id}")
            if cancelled and line_total != 0:
                self.fail("financial_reconciliation", f"취소 연회에 인식매출 존재: {event_id}")
            key = (booking["venue_id"], booking["event_date"])
            banquet_agg[key]["bookings"] += 1
            banquet_agg[key]["completed"] += int(completed)
            banquet_agg[key]["cancelled"] += int(cancelled)
            banquet_agg[key]["attendees"] += int(booking["actual_attendees"] or 0)
            banquet_agg[key]["revenue"] += line_total
        for venue_id, venue in venues.items():
            if venue["is_active"] == "true" and venue_activity[venue_id] == 0:
                self.fail("behavioral_coverage", f"활성 연회장에 예약이 없습니다: {venue_id}")
        for block in self.rows["banquet.room_blocks"]:
            if int(block["pickup_room_nights"]) > int(block["reserved_room_nights"]):
                self.fail("capacity_integrity", f"객실 block pickup 초과: {block['room_block_id']}")
            if day(block["checkin_date"]) >= day(block["checkout_date"]):
                self.fail("structural_integrity", f"객실 block 날짜 역전: {block['room_block_id']}")
            booking = bookings[block["banquet_event_id"]]
            key = (booking["venue_id"], booking["event_date"])
            banquet_agg[key]["reserved"] += int(block["reserved_room_nights"])
            banquet_agg[key]["pickup"] += int(block["pickup_room_nights"])
        serving = {(row["venue_id"], row["business_date"]): row for row in self.rows["serving.banquet_daily_metrics"]}
        if set(serving) != set(banquet_agg):
            self.fail("metric_equivalence", "banquet_daily_metrics grain coverage 불일치")
        for key, values in banquet_agg.items():
            row = serving.get(key)
            if not row:
                continue
            checks = {
                "booking_count": values["bookings"],
                "completed_count": values["completed"],
                "cancelled_count": values["cancelled"],
                "actual_attendees": values["attendees"],
                "recognized_revenue": values["revenue"],
                "reserved_room_nights": values["reserved"],
                "pickup_room_nights": values["pickup"],
                "room_block_pickup_rate": safe_ratio(values["pickup"], values["reserved"]),
            }
            for field, expected in checks.items():
                if not close_enough(row[field], expected):
                    self.fail("metric_equivalence", f"연회 metric 불일치 {key}.{field}")

        facilities = {row["facility_id"]: row for row in self.rows["facility.master"]}
        facility_activity = defaultdict(int)
        facility_agg = defaultdict(lambda: {"count": 0, "guests": 0, "net": Decimal(0), "incidents": 0, "downtime": 0})
        for event in self.rows["facility.usage_events"]:
            facility = facilities[event["facility_id"]]
            if int(event["guest_count"]) > int(facility["synthetic_capacity"]):
                self.fail("capacity_integrity", f"시설 party 정원 초과: {event['usage_event_id']}")
            if dec(event["gross_amount"]) - dec(event["discount_amount"]) != dec(event["net_amount"]):
                self.fail("financial_reconciliation", f"시설 순매출 불일치: {event['usage_event_id']}")
            facility_activity[event["facility_id"]] += 1
            key = (event["facility_id"], event["business_date"])
            facility_agg[key]["count"] += 1
            facility_agg[key]["guests"] += int(event["guest_count"])
            facility_agg[key]["net"] += dec(event["net_amount"])
        for incident in self.rows["facility.incidents"]:
            actual_minutes = int((dt(incident["resolved_at"]) - dt(incident["started_at"])).total_seconds() / 60)
            if actual_minutes != int(incident["downtime_minutes"]):
                self.fail("structural_integrity", f"시설 중단시간 불일치: {incident['incident_id']}")
            key = (incident["facility_id"], dt(incident["started_at"]).date().isoformat())
            facility_agg[key]["incidents"] += 1
            facility_agg[key]["downtime"] += int(incident["downtime_minutes"])
        for facility_id, facility in facilities.items():
            if facility["is_active"] == "true" and facility_activity[facility_id] == 0:
                self.fail("behavioral_coverage", f"활성 시설에 이용 이벤트가 없습니다: {facility_id}")
        serving_facility = {
            (row["facility_id"], row["business_date"]): row
            for row in self.rows["serving.facility_daily_metrics"]
        }
        for key, row in serving_facility.items():
            values = facility_agg[key]
            checks = {
                "usage_count": values["count"],
                "facility_guests": values["guests"],
                "facility_net_revenue": values["net"],
                "incident_count": values["incidents"],
                "downtime_minutes": values["downtime"],
            }
            for field, expected in checks.items():
                if not close_enough(row[field], expected):
                    self.fail("metric_equivalence", f"시설 metric 불일치 {key}.{field}")

    def validate_cross_domain_serving(self) -> None:
        maps_by_guest = {row["pms_guest_id"]: row for row in self.rows["crm.customer_map"]}
        maps_by_pos = {row["pos_customer_ref"]: row for row in self.rows["crm.customer_map"]}
        maps_by_facility = {row["facility_user_ref"]: row for row in self.rows["crm.customer_map"]}
        maps_by_banquet = {row["banquet_customer_id"]: row for row in self.rows["crm.customer_map"]}
        expected_member = defaultdict(lambda: {"count": 0, "revenue": Decimal(0)})

        for stay in self.rows["pms.stays"]:
            mapping = maps_by_guest.get(stay["guest_id"])
            if not mapping:
                continue
            checkin = dt(stay["actual_checkin_at"]).date()
            nights = int(stay["occupied_room_nights"])
            nightly = dec(stay["room_revenue"]) / nights
            for offset in range(nights):
                business_date = checkin.fromordinal(checkin.toordinal() + offset)
                if dt(mapping["valid_from"]).date() <= business_date:
                    key = (mapping["member_no"], business_date.isoformat(), stay["hotel_code"], "ROOMS")
                    expected_member[key]["count"] += 1
                    expected_member[key]["revenue"] += nightly
        outlet_hotel = {row["outlet_id"]: row["hotel_code"] for row in self.rows["pos.outlets"]}
        for order in self.rows["pos.orders"]:
            mapping = maps_by_pos.get(order["pos_customer_ref"])
            if mapping and dec(order["net_amount"]) > 0 and dt(mapping["valid_from"]) <= dt(order["ordered_at"]):
                key = (mapping["member_no"], order["business_date"], outlet_hotel[order["outlet_id"]], "FNB")
                expected_member[key]["count"] += 1
                expected_member[key]["revenue"] += dec(order["net_amount"])
        facility_hotel = {row["facility_id"]: row["hotel_code"] for row in self.rows["facility.master"]}
        for event in self.rows["facility.usage_events"]:
            mapping = maps_by_facility.get(event["facility_user_ref"])
            if mapping and dec(event["net_amount"]) > 0 and dt(mapping["valid_from"]) <= dt(event["event_at"]):
                key = (mapping["member_no"], event["business_date"], facility_hotel[event["facility_id"]], "FACILITY")
                expected_member[key]["count"] += 1
                expected_member[key]["revenue"] += dec(event["net_amount"])
        bookings = {row["banquet_event_id"]: row for row in self.rows["banquet.bookings"]}
        venue_hotel = {row["venue_id"]: row["hotel_code"] for row in self.rows["banquet.venues"]}
        banquet_event_revenue = defaultdict(Decimal)
        for line in self.rows["banquet.revenue_lines"]:
            banquet_event_revenue[line["banquet_event_id"]] += dec(line["recognized_amount"])
        for event_id, revenue in banquet_event_revenue.items():
            booking = bookings[event_id]
            mapping = maps_by_banquet.get(booking["banquet_customer_id"])
            if mapping and revenue > 0 and dt(mapping["valid_from"]).date() <= day(booking["event_date"]):
                key = (
                    mapping["member_no"],
                    booking["event_date"],
                    venue_hotel[booking["venue_id"]],
                    "BANQUET",
                )
                expected_member[key]["count"] += 1
                expected_member[key]["revenue"] += revenue
        actual_member = {
            (row["member_no"], row["business_date"], row["hotel_code"], row["source_domain"]): row
            for row in self.rows["serving.member_daily_revenue_metrics"]
        }
        if set(expected_member) != set(actual_member):
            self.fail("metric_equivalence", "회원 기여매출 serving grain coverage 불일치")
        for key, expected in expected_member.items():
            row = actual_member.get(key)
            if not row:
                continue
            if int(row["transaction_count"]) != expected["count"] or dec(row["revenue_amount"]) != expected["revenue"]:
                self.fail("metric_equivalence", f"회원 기여매출 불일치: {key}")

        hotel_metrics = defaultdict(Decimal)
        for row in self.rows["serving.hotel_daily_metrics"]:
            hotel_metrics[(row["hotel_code"], row["business_date"])] += dec(row["stay_day_room_revenue"])
        fnb_metrics = defaultdict(Decimal)
        for row in self.rows["pos.orders"]:
            fnb_metrics[(outlet_hotel[row["outlet_id"]], row["business_date"])] += dec(row["net_amount"])
        banquet_metrics = defaultdict(Decimal)
        for line in self.rows["banquet.revenue_lines"]:
            booking = bookings[line["banquet_event_id"]]
            banquet_metrics[(venue_hotel[booking["venue_id"]], line["recognized_date"])] += dec(line["recognized_amount"])
        facility_metrics = defaultdict(Decimal)
        for event in self.rows["facility.usage_events"]:
            facility_metrics[(facility_hotel[event["facility_id"]], event["business_date"])] += dec(event["net_amount"])
        for row in self.rows["serving.total_operating_daily_metrics"]:
            key = (row["hotel_code"], row["business_date"])
            expected = {
                "room_revenue": hotel_metrics[key],
                "fnb_net_revenue": fnb_metrics[key],
                "banquet_recognized_revenue": banquet_metrics[key],
                "facility_net_revenue": facility_metrics[key],
            }
            expected_total = sum(expected.values(), Decimal(0))
            for field, value in expected.items():
                if dec(row[field]) != value:
                    self.fail("metric_equivalence", f"통합 매출 불일치 {key}.{field}")
            if dec(row["total_operating_revenue"]) != expected_total:
                self.fail("metric_equivalence", f"통합 매출 total 불일치: {key}")

        resources = {
            (row["hotel_code"], row["business_date"]): row for row in self.rows["facility.resource_daily"]
        }
        resource_serving = {
            (row["hotel_code"], row["business_date"]): row
            for row in self.rows["serving.resource_daily_metrics"]
        }
        if set(resources) != set(resource_serving):
            self.fail("metric_equivalence", "resource serving coverage 불일치")
        occupancy_values: list[float] = []
        energy_values: list[float] = []
        for key, source in resources.items():
            target = resource_serving.get(key)
            if not target:
                continue
            for field in ("occupied_room_nights", "energy_kwh", "water_m3", "waste_kg", "resource_cost"):
                if not close_enough(source[field], target[field]):
                    self.fail("metric_equivalence", f"resource metric 불일치 {key}.{field}")
            occupied = int(source["occupied_room_nights"])
            if not close_enough(target["energy_per_occupied_room"], safe_ratio(source["energy_kwh"], occupied)):
                self.fail("metric_equivalence", f"energy efficiency 불일치: {key}")
            occupancy_values.append(float(occupied))
            energy_values.append(float(source["energy_kwh"]))
        if len(occupancy_values) > 2:
            mean_x = sum(occupancy_values) / len(occupancy_values)
            mean_y = sum(energy_values) / len(energy_values)
            numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(occupancy_values, energy_values))
            denominator = math.sqrt(
                sum((x - mean_x) ** 2 for x in occupancy_values)
                * sum((y - mean_y) ** 2 for y in energy_values)
            )
            correlation = numerator / denominator if denominator else 0
            self.observations["occupied_rooms_energy_correlation"] = round(correlation, 6)
            if correlation < 0.65:
                self.fail("behavioral_coverage", f"점유-에너지 상관이 너무 약함: {correlation:.3f}")

    def validate_coverage(self) -> None:
        calendar_days = {row["business_date"] for row in self.rows["reference.calendar_daily"]}
        if not calendar_days:
            self.fail("behavioral_coverage", "calendar가 비었습니다.")
            return
        operational_hotels = {"GRAND", "VISTA", "DOUGLAS"}
        resource_keys = {(row["hotel_code"], row["business_date"]) for row in self.rows["facility.resource_daily"]}
        total_keys = {
            (row["hotel_code"], row["business_date"])
            for row in self.rows["serving.total_operating_daily_metrics"]
        }
        expected_hotel_days = {(hotel, value) for hotel in operational_hotels for value in calendar_days}
        if resource_keys != expected_hotel_days:
            self.fail("behavioral_coverage", "resource_daily의 hotel-day coverage가 불완전합니다.")
        if total_keys != expected_hotel_days:
            self.fail("metric_equivalence", "통합 매출의 hotel-day coverage가 불완전합니다.")
        staffing_keys = {
            (row["hotel_code"], row["business_date"], row["department"])
            for row in self.rows["facility.staffing_daily"]
        }
        expected_staffing = {
            (hotel, value, department)
            for hotel in operational_hotels
            for value in calendar_days
            for department in ("ROOMS", "FNB", "FACILITY", "BANQUET")
        }
        if staffing_keys != expected_staffing:
            self.fail("behavioral_coverage", "staffing_daily의 hotel-day-department coverage가 불완전합니다.")
        statuses = {row["order_status"] for row in self.rows["pos.orders"]}
        if len(statuses) < 3:
            self.fail("behavioral_coverage", f"POS 상태 분포가 지나치게 단순합니다: {statuses}")
        channels = {row["booking_channel"] for row in self.rows["pms.reservations"]}
        if not {"DIRECT", "OTA", "CORPORATE"}.issubset(channels):
            self.fail("behavioral_coverage", f"예약 채널 분포가 부족합니다: {channels}")

    def validate_determinism(self) -> None:
        if self.reference is None:
            self.fail("determinism", "동일 seed 재생성 경로가 제공되지 않아 재현성을 검증하지 못했습니다.")
            return
        reference_manifest_path = self.reference / "manifest.json"
        if not reference_manifest_path.exists():
            self.fail("determinism", f"재현성 기준 manifest가 없습니다: {reference_manifest_path}")
            return
        reference = read_json(reference_manifest_path)
        current_files = {
            item["dataset_id"]: (item["row_count"], item["sha256"])
            for item in self.manifest.get("files", [])
        }
        reference_files = {
            item["dataset_id"]: (item["row_count"], item["sha256"])
            for item in reference.get("files", [])
        }
        if self.manifest.get("seed") != reference.get("seed"):
            self.fail("determinism", "재현성 기준 seed가 다릅니다.")
        if self.manifest.get("period") != reference.get("period"):
            self.fail("determinism", "재현성 기준 기간이 다릅니다.")
        if current_files != reference_files:
            self.fail("determinism", "동일 계약·seed 생성 파일 hash가 다릅니다.")
        if self.manifest.get("catalog", {}).get("sha256") != reference.get("catalog", {}).get("sha256"):
            self.fail("determinism", "DataHub catalog hash가 다릅니다.")

    def run(self) -> dict:
        self.load()
        if not self.manifest:
            return self.report()
        self.validate_contract_and_metadata()
        self.validate_structure()
        self.validate_pms()
        self.validate_pos()
        self.validate_crm()
        self.validate_banquet_facility()
        self.validate_cross_domain_serving()
        self.validate_coverage()
        self.validate_determinism()
        return self.report()

    def report(self) -> dict:
        occupancies = [float(row["occupancy_rate"]) for row in self.rows.get("serving.hotel_daily_metrics", []) if row["occupancy_rate"]]
        outlet_activity_days: dict[str, set[str]] = defaultdict(set)
        for row in self.rows.get("pos.orders", []):
            outlet_activity_days[row["outlet_id"]].add(row["business_date"])
        facility_activity_days: dict[str, set[str]] = defaultdict(set)
        for row in self.rows.get("facility.usage_events", []):
            facility_activity_days[row["facility_id"]].add(row["business_date"])
        if occupancies:
            self.observations["occupancy_rate"] = {
                "min": round(min(occupancies), 6),
                "mean": round(sum(occupancies) / len(occupancies), 6),
                "max": round(max(occupancies), 6),
            }
        self.observations.update(
            {
                "dataset_count": len(self.datasets),
                "total_row_count": sum(len(rows) for rows in self.rows.values()),
                "row_counts": {key: len(value) for key, value in sorted(self.rows.items())},
                "reservation_status_counts": dict(
                    sorted(Counter(row["reservation_status"] for row in self.rows.get("pms.reservations", [])).items())
                ),
                "pos_status_counts": dict(
                    sorted(Counter(row["order_status"] for row in self.rows.get("pos.orders", [])).items())
                ),
                "membership_tier_counts": dict(
                    sorted(Counter(row["current_tier_code"] for row in self.rows.get("crm.members", [])).items())
                ),
                "banquet_status_counts": dict(
                    sorted(Counter(row["booking_status"] for row in self.rows.get("banquet.bookings", [])).items())
                ),
                "outlet_activity_days": {
                    key: len(value) for key, value in sorted(outlet_activity_days.items())
                },
                "facility_activity_days": {
                    key: len(value) for key, value in sorted(facility_activity_days.items())
                },
            }
        )
        gates = []
        for gate in GATE_IDS:
            if gate in {"asset_binding_verification", "held_out_evaluation", "runtime_canary"}:
                status = "NOT_RUN"
                notes = {
                    "asset_binding_verification": "물리 적재 후 DataHub exact URN과 Trino metadata를 대조해야 합니다.",
                    "held_out_evaluation": "Qwen/SQL 경로의 별도 held-out 질문 평가는 데이터 후보 승격 전에 실행해야 합니다.",
                    "runtime_canary": "격리된 catalog·Qwen·G1/G2·Trino·G3 canary는 물리 적재와 모델 평가 뒤 실행해야 합니다.",
                }
                note = notes[gate]
                issue_count = 0
                samples: list[str] = []
            else:
                issue_count = self.issue_count[gate]
                status = "PASSED" if issue_count == 0 else "FAILED"
                note = ""
                samples = self.issue_samples[gate]
            gates.append(
                {
                    "id": gate,
                    "status": status,
                    "issue_count": issue_count,
                    "issue_samples": samples,
                    "note": note,
                }
            )
        external_gates = {"asset_binding_verification", "held_out_evaluation", "runtime_canary"}
        data_gates_passed = all(gate["status"] == "PASSED" for gate in gates if gate["id"] not in external_gates)
        promotion_eligible = all(gate["status"] == "PASSED" for gate in gates)
        return {
            "dataset_id": self.product["dataset_id"],
            "candidate": str(self.candidate),
            "claim_boundary": self.product["claim_boundary"],
            "data_gates_passed": data_gates_passed,
            "promotion_eligible": promotion_eligible,
            "promotion_state": "DATA_VALIDATED" if data_gates_passed else "DRAFT",
            "observations": self.observations,
            "gates": gates,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--determinism-reference", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-promotion", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validator = Validator(args.candidate, args.determinism_reference)
    report = validator.run()
    report_path = args.report or args.candidate / "validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "report": str(report_path.resolve()),
                "data_gates_passed": report["data_gates_passed"],
                "promotion_eligible": report["promotion_eligible"],
                "promotion_state": report["promotion_state"],
                "failed_gates": [gate["id"] for gate in report["gates"] if gate["status"] == "FAILED"],
            },
            ensure_ascii=False,
        )
    )
    if not report["data_gates_passed"]:
        return 1
    if args.require_promotion and not report["promotion_eligible"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
