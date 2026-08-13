#!/usr/bin/env python3
"""Mark the legacy golden-path serving views deprecated without deleting them."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
from sync_datahub import DEFAULT_CATALOG, dataset_urn, headers, upsert  # noqa: E402


LEGACY_CONTRACT = ROOT / "src" / "data" / "serving_analytics_contract.i4.v1.json"
SOURCE_REGISTRY = ROOT / "src" / "data" / "source_registry.v1.json"
REPLACEMENTS = {
    "banquet_monthly_metrics": "serving_v4.serving.analytics.v4_banquet_daily_metrics",
    "facility_daily_metrics": "serving_v4.serving.analytics.v4_facility_daily_metrics",
    "fnb_daypart_metrics": "serving_v4.serving.analytics.v4_fnb_daily_metrics",
    "hotel_daily_metrics": "serving_v4.serving.analytics.v4_hotel_daily_metrics",
    "hotel_monthly_metrics": "serving_v4.serving.analytics.v4_total_operating_daily_metrics",
    "hotel_yearly_metrics": "serving_v4.serving.analytics.v4_total_operating_daily_metrics",
    "resource_monthly_metrics": "serving_v4.serving.analytics.v4_resource_daily_metrics",
    "workforce_monthly_metrics": None,
}
SOURCE_PLATFORMS = {
    "pms": "postgres",
    "pos": "mysql",
    "crm": "mssql",
    "facility": "clickhouse",
    "banquet": "postgres",
}
SOURCE_REPLACEMENT_IDS = {
    "pms.pms_guests": "pms.guests",
    "pms.pms_room_inventory_daily": "pms.room_inventory_daily",
    "pms.pms_reservations": "pms.reservations",
    "pms.pms_stays": "pms.stays",
    "pos.pos_stores": "pos.outlets",
    "pos.pos_service_periods": None,
    "pos.pos_orders": "pos.orders",
    "pos.pos_order_items": "pos.order_items",
    "crm.crm_members": "crm.members",
    "crm.crm_member_grade_history": "crm.member_grade_history",
    "crm.crm_point_transactions": "crm.point_transactions",
    "crm.crm_customer_map": "crm.customer_map",
    "facility.facility_master": "facility.master",
    "facility.facility_events": None,
    "facility.hotel_staffing_daily": "facility.staffing_daily",
    "facility.facility_resource_daily": "facility.resource_daily",
    "banquet.banquet_bookings": "banquet.bookings",
    "banquet.banquet_revenue": "banquet.revenue_lines",
}


def trino_urn(name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:trino,{name},PROD)"


def legacy_source_assets() -> list[dict]:
    registry = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
    v4_by_id = {dataset["id"]: dataset for dataset in catalog["datasets"]}
    assets = []
    for source in registry["sources"]:
        source_id = source["source_id"]
        for entity in source["entities"]:
            table = entity["table"]
            if source_id in {"pos", "facility"}:
                name = f"{source_id}.{source['database_name']}.{table}"
            else:
                name = f"{source_id}.{source['database_name']}.{source['schema_name']}.{table}"
            replacement_id = SOURCE_REPLACEMENT_IDS[f"{source_id}.{table}"]
            assets.append(
                {
                    "urn": (
                        f"urn:li:dataset:(urn:li:dataPlatform:{SOURCE_PLATFORMS[source_id]},"
                        f"{name},PROD)"
                    ),
                    "fqn": name,
                    "replacement": dataset_urn(v4_by_id[replacement_id]) if replacement_id else None,
                }
            )
    return assets


def deprecate(server: str) -> dict:
    contract = json.loads(LEGACY_CONTRACT.read_text(encoding="utf-8"))
    views = contract["views"]
    if {view["name"] for view in views} != set(REPLACEMENTS):
        raise ValueError("legacy view contract and replacement map differ")
    assets = [
        {
            "urn": view["urn"],
            "fqn": view["fqn"],
            "replacement": trino_urn(REPLACEMENTS[view["name"]]) if REPLACEMENTS[view["name"]] else None,
        }
        for view in views
    ] + legacy_source_assets()
    for asset in assets:
        aspect = {
            "deprecated": True,
            "note": "golden-path 중심 legacy 합성 자산입니다. Walkerhill v4를 기본 분석 자산으로 사용합니다.",
            "actor": "urn:li:corpuser:data_governance",
        }
        if asset["replacement"]:
            aspect["replacement"] = asset["replacement"]
        upsert(server, "dataset", asset["urn"], {"deprecation": aspect})

    verified = 0
    for asset in assets:
        endpoint = f"{server}/entitiesV2/{quote(asset['urn'], safe='')}?aspects=List(status,deprecation)"
        with urlopen(Request(endpoint, headers=headers()), timeout=30) as response:
            entity = json.loads(response.read().decode("utf-8"))
        value = entity.get("aspects", {}).get("deprecation", {}).get("value", {})
        if value.get("deprecated") is not True:
            raise ValueError(f"legacy deprecation was not stored: {asset['fqn']}")
        verified += 1
    return {
        "status": "DEPRECATED",
        "legacy_view_count": len(views),
        "legacy_source_count": len(assets) - len(views),
        "verified_asset_count": verified,
        "deleted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:18081")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "output" / "walkerhill_v4_runtime" / "legacy_deprecation_report.json",
    )
    args = parser.parse_args()
    result = deprecate(args.server.rstrip("/"))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
