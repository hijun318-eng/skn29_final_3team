"""Generate the deterministic 2,000-case SQL SFT scenario ledger."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


SEED = 20260729
SCHEMA_VERSION = "1.0.0"

DOMAIN_SPLITS = {
    "pms": {"train": 432, "validation": 54, "gold": 43, "acceptance": 11, "reserve": 180},
    "crm": {"train": 264, "validation": 33, "gold": 27, "acceptance": 6, "reserve": 110},
    "pms_crm": {"train": 216, "validation": 27, "gold": 22, "acceptance": 5, "reserve": 90},
    "pos": {"train": 168, "validation": 21, "gold": 17, "acceptance": 4, "reserve": 70},
    "facility": {"train": 72, "validation": 9, "gold": 7, "acceptance": 2, "reserve": 30},
    "banquet": {"train": 48, "validation": 6, "gold": 4, "acceptance": 2, "reserve": 20},
}

REPAIR_COUNTS = {
    "pms": {"train": 87, "validation": 11, "gold": 9, "acceptance": 1, "reserve": 36},
    "crm": {"train": 53, "validation": 7, "gold": 6, "acceptance": 1, "reserve": 21},
    "pms_crm": {"train": 43, "validation": 6, "gold": 4, "acceptance": 1, "reserve": 18},
    "pos": {"train": 34, "validation": 4, "gold": 3, "acceptance": 1, "reserve": 14},
    "facility": {"train": 14, "validation": 1, "gold": 1, "acceptance": 1, "reserve": 7},
    "banquet": {"train": 9, "validation": 1, "gold": 1, "acceptance": 1, "reserve": 4},
}

DISTRACTOR_COUNTS = {
    "train": 360,
    "validation": 45,
    "gold": 36,
    "acceptance": 9,
    "reserve": 150,
}


@dataclass(frozen=True)
class MetricPlan:
    domain: str
    metric_id: str
    count: int
    aggregation: tuple[str, ...]
    periods: tuple[str, ...]
    dimensions: tuple[str, ...]
    filters: tuple[str, ...]


def _plan(
    domain: str,
    metric_id: str,
    count: int,
    *,
    aggregation: tuple[str, ...] = ("sum",),
    periods: tuple[str, ...] = ("day", "week", "month", "quarter", "year", "mom", "yoy"),
    dimensions: tuple[str, ...] = ("none", "time"),
    filters: tuple[str, ...] = ("actual", "type", "status", "actual_and_type"),
) -> MetricPlan:
    return MetricPlan(domain, metric_id, count, aggregation, periods, dimensions, filters)


METRICS = (
    _plan("pms", "recognized_room_revenue", 200, dimensions=("none", "time", "room_type")),
    _plan("pms", "occupancy_rate", 144, aggregation=("weighted_ratio",), dimensions=("none", "time", "room_type")),
    _plan("pms", "adr", 120, aggregation=("weighted_ratio",), dimensions=("none", "time", "room_type")),
    _plan("pms", "revpar", 104, aggregation=("weighted_ratio",), dimensions=("none", "time", "room_type")),
    _plan("pms", "rooms_sold", 88, dimensions=("none", "time", "room_type")),
    _plan("pms", "available_room_nights", 64, dimensions=("none", "time", "room_type")),
    _plan("crm", "current_active_members", 100, aggregation=("count", "distinct_count"), periods=("current_snapshot",), dimensions=("none", "membership_grade", "joined_month", "joined_year", "points_band"), filters=("active", "active_and_grade", "active_and_joined_period", "active_and_points_band")),
    _plan("crm", "earned_points", 80, dimensions=("none", "time", "membership_grade"), filters=("earn", "earn_and_grade", "earn_and_channel")),
    _plan("crm", "used_points", 80, dimensions=("none", "time", "membership_grade"), filters=("use", "use_and_grade", "use_and_channel")),
    _plan("crm", "expired_points", 60, dimensions=("none", "time", "membership_grade"), filters=("expire", "expire_and_grade")),
    _plan("crm", "current_points_balance", 60, aggregation=("sum", "average"), periods=("current_snapshot",), dimensions=("none", "membership_grade", "joined_year", "points_band"), filters=("active", "active_and_grade", "active_and_joined_period")),
    _plan("crm", "grade_change_count", 60, aggregation=("count",), dimensions=("none", "time", "change_reason", "membership_grade"), filters=("all_changes", "upgrade", "downgrade", "review")),
    _plan("pms_crm", "stay_grade_room_revenue", 160, dimensions=("membership_grade", "time", "membership_grade_and_time"), filters=("completed_paid", "completed_paid_and_grade")),
    _plan("pms_crm", "stay_grade_completed_stays", 72, aggregation=("count",), dimensions=("membership_grade", "time", "membership_grade_and_time"), filters=("completed_paid", "completed_paid_and_grade")),
    _plan("pms_crm", "stay_grade_room_nights", 64, dimensions=("membership_grade", "time", "membership_grade_and_time"), filters=("completed_paid", "completed_paid_and_grade")),
    _plan("pms_crm", "stay_grade_unique_members", 64, aggregation=("distinct_count",), dimensions=("membership_grade", "time", "membership_grade_and_time"), filters=("completed_paid", "completed_paid_and_grade")),
    _plan("pos", "fnb_net_revenue", 80, dimensions=("none", "time", "store", "daypart"), filters=("paid", "paid_and_store", "paid_and_daypart")),
    _plan("pos", "order_count", 56, aggregation=("count",), dimensions=("none", "time", "store", "daypart"), filters=("paid", "paid_and_store", "paid_and_daypart")),
    _plan("pos", "covers", 48, dimensions=("none", "time", "store", "daypart"), filters=("paid", "paid_and_store", "paid_and_daypart")),
    _plan("pos", "average_check", 48, aggregation=("weighted_ratio",), dimensions=("none", "time", "store", "daypart"), filters=("paid", "paid_and_store", "paid_and_daypart")),
    _plan("pos", "revpash", 48, aggregation=("weighted_ratio",), dimensions=("none", "time", "store", "daypart"), filters=("actual", "actual_and_store", "actual_and_daypart")),
    _plan("facility", "completed_usage_count", 32, aggregation=("count",), dimensions=("none", "time", "facility"), filters=("completed_usage", "completed_usage_and_facility")),
    _plan("facility", "incident_count", 24, aggregation=("count",), dimensions=("none", "time", "facility"), filters=("incident", "incident_and_facility")),
    _plan("facility", "downtime_minutes", 24, dimensions=("none", "time", "facility"), filters=("incident", "incident_and_facility")),
    _plan("facility", "facility_revenue", 24, dimensions=("none", "time", "facility"), filters=("completed_usage", "completed_usage_and_facility")),
    _plan("facility", "revenue_per_usage", 16, aggregation=("weighted_ratio",), dimensions=("none", "time", "facility"), filters=("completed_usage", "completed_usage_and_facility")),
    _plan("banquet", "recognized_banquet_revenue", 24, periods=("month", "quarter", "year", "mom", "yoy"), dimensions=("none", "time", "product_category"), filters=("recognized", "recognized_and_category")),
    _plan("banquet", "expected_banquet_revenue", 16, periods=("month", "quarter", "year", "mom", "yoy"), dimensions=("none", "time", "product_category"), filters=("expected", "expected_and_category")),
    _plan("banquet", "banquet_booking_count", 12, aggregation=("count",), periods=("month", "quarter", "year"), dimensions=("none", "time", "product_category"), filters=("all_bookings", "booking_and_category")),
    _plan("banquet", "confirmed_banquet_count", 8, aggregation=("count",), periods=("month", "quarter", "year"), dimensions=("none", "time", "product_category"), filters=("confirmed", "confirmed_and_category")),
    _plan("banquet", "cancelled_banquet_count", 8, aggregation=("count",), periods=("month", "quarter", "year"), dimensions=("none", "time", "product_category"), filters=("cancelled", "cancelled_and_category")),
    _plan("banquet", "actual_attendees", 12, periods=("month", "quarter", "year"), dimensions=("none", "time", "product_category"), filters=("completed", "completed_and_category")),
)

OUTPUTS = ("scalar", "grouped", "segmented_table", "trend", "comparison", "top_n")
WINDOWS = (1, 2, 3, 6, 12)
REPAIR_CODE_COUNTS = {
    "RESOURCE_POLICY_MISSING": 120,
    "REFERENCE_MISSING": 80,
    "REFERENCE_OUTSIDE_CONTEXT": 70,
    "SQL_REFERENCE_MISMATCH": 80,
    "PARAMETERS_INVALID": 50,
}


def _metric_candidates(plan: MetricPlan) -> list[dict[str, object]]:
    combinations = itertools.product(
        plan.aggregation,
        plan.periods,
        plan.dimensions,
        plan.filters,
        OUTPUTS,
        WINDOWS,
    )
    candidates = []
    for aggregation, period, dimension, filter_shape, output, window in combinations:
        if dimension == "none" and output in {"grouped", "segmented_table", "top_n"}:
            continue
        if dimension != "none" and output == "scalar":
            continue
        if period == "current_snapshot" and output in {"trend", "comparison"}:
            continue
        if period == "current_snapshot" and window != 1:
            continue
        candidates.append(
            {
                "domain": plan.domain,
                "metric_id": plan.metric_id,
                "aggregation": aggregation,
                "period_shape": period,
                "window_size": window,
                "dimension": dimension,
                "filter_shape": filter_shape,
                "output_shape": output,
            }
        )
    if len(candidates) < plan.count:
        raise ValueError(f"{plan.metric_id}: only {len(candidates)} unique scenarios for {plan.count}")
    return candidates[: plan.count]


def _slots(domain: str) -> list[tuple[str, str]]:
    slots = []
    for split, total in DOMAIN_SPLITS[domain].items():
        repairs = REPAIR_COUNTS[domain][split]
        slots.extend([(split, "node2_repair")] * repairs)
        slots.extend([(split, "node2")] * (total - repairs))
    return slots


def generate() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    by_domain: dict[str, list[dict[str, object]]] = {domain: [] for domain in DOMAIN_SPLITS}
    for plan in METRICS:
        by_domain[plan.domain].extend(_metric_candidates(plan))

    records = []
    for domain, candidates in by_domain.items():
        slots = _slots(domain)
        if len(candidates) != len(slots):
            raise ValueError(f"{domain}: metric and split totals differ")
        rng.shuffle(candidates)
        rng.shuffle(slots)
        for candidate, (split, node) in zip(candidates, slots):
            candidate["target_split"] = split
            candidate["node"] = node
            candidate["repair_error_code"] = None
            records.append(candidate)

    repairs = [record for record in records if record["node"] == "node2_repair"]
    rng.shuffle(repairs)
    repair_codes = [
        code
        for code, count in REPAIR_CODE_COUNTS.items()
        for _ in range(count)
    ]
    rng.shuffle(repair_codes)
    if len(repairs) != len(repair_codes):
        raise ValueError("repair error quota mismatch")
    for record, code in zip(repairs, repair_codes):
        record["repair_error_code"] = code

    for split, target in DISTRACTOR_COUNTS.items():
        matching = [record for record in records if record["target_split"] == split]
        rng.shuffle(matching)
        for index, record in enumerate(matching):
            record["context_shape"] = "distractor" if index < target else "minimal"

    records.sort(
        key=lambda record: (
            str(record["target_split"]),
            str(record["domain"]),
            str(record["metric_id"]),
            str(record["period_shape"]),
            str(record["dimension"]),
            str(record["filter_shape"]),
            str(record["output_shape"]),
            int(record["window_size"]),
        )
    )
    for index, record in enumerate(records, 1):
        signature = "|".join(
            str(record[key])
            for key in (
                "domain",
                "metric_id",
                "aggregation",
                "period_shape",
                "window_size",
                "dimension",
                "filter_shape",
                "output_shape",
            )
        )
        record["candidate_id"] = f"candidate-{index:04d}"
        record["scenario_group"] = hashlib.sha256(signature.encode()).hexdigest()[:16]
        record["difficulty"] = (
            "hard"
            if record["domain"] == "pms_crm" or record["output_shape"] in {"comparison", "top_n"}
            else "medium"
            if record["dimension"] != "none" or record["period_shape"] in {"mom", "yoy"}
            else "basic"
        )
        record["synthetic"] = True
        record["schema_version"] = SCHEMA_VERSION
        record["seed_version"] = str(SEED)
    validate(records)
    return records


def validate(records: list[dict[str, object]]) -> None:
    if len(records) != 2_000:
        raise ValueError(f"expected 2000 records, got {len(records)}")
    if len({record["candidate_id"] for record in records}) != len(records):
        raise ValueError("duplicate candidate_id")
    if len({record["scenario_group"] for record in records}) != len(records):
        raise ValueError("duplicate scenario_group")

    expected_domains = {domain: sum(splits.values()) for domain, splits in DOMAIN_SPLITS.items()}
    actual_domains = Counter(str(record["domain"]) for record in records)
    if actual_domains != Counter(expected_domains):
        raise ValueError(f"domain quota mismatch: {actual_domains}")

    expected_metrics = Counter({plan.metric_id: plan.count for plan in METRICS})
    actual_metrics = Counter(str(record["metric_id"]) for record in records)
    if actual_metrics != expected_metrics:
        raise ValueError("metric quota mismatch")

    expected_splits = Counter()
    expected_repairs = Counter()
    for domain, splits in DOMAIN_SPLITS.items():
        expected_splits.update(splits)
        expected_repairs.update(REPAIR_COUNTS[domain])
    actual_splits = Counter(str(record["target_split"]) for record in records)
    actual_repairs = Counter(
        str(record["target_split"])
        for record in records
        if record["node"] == "node2_repair"
    )
    if actual_splits != expected_splits or actual_repairs != expected_repairs:
        raise ValueError("split or repair quota mismatch")

    actual_distractors = Counter(
        str(record["target_split"])
        for record in records
        if record["context_shape"] == "distractor"
    )
    if actual_distractors != Counter(DISTRACTOR_COUNTS):
        raise ValueError("context quota mismatch")
    actual_repair_codes = Counter(
        str(record["repair_error_code"])
        for record in records
        if record["node"] == "node2_repair"
    )
    if actual_repair_codes != Counter(REPAIR_CODE_COUNTS):
        raise ValueError("repair error code quota mismatch")


def summarize(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "total": len(records),
        "domains": dict(sorted(Counter(record["domain"] for record in records).items())),
        "splits": dict(sorted(Counter(record["target_split"] for record in records).items())),
        "nodes": dict(sorted(Counter(record["node"] for record in records).items())),
        "contexts": dict(sorted(Counter(record["context_shape"] for record in records).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = generate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(summarize(records), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
