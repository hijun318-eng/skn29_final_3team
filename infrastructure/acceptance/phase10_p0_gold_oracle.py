#!/usr/bin/env python3
"""P0 Gold 교정안에 독립 read-only Trino oracle을 결속한다.

runtime SQL compiler를 정답 생성에 재사용하지 않는다. 이 entrypoint는 승인된 serving view와
VOC view의 비식별 원천에서 명시적 metric 식만으로 SELECT를 만들고, 집계 결과의 숫자 또는
canonical hash를 versioned candidate Gold에 기록한다. credential·SQL 원문·원천 row는
receipt에 남기지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any, Mapping, Sequence

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.trino_async import (  # noqa: E402
    AdapterError,
    AdapterErrorCode,
    QueryPage,
    TrinoAsyncClient,
)
from evals.p0_gold import canonical_sha256, validate_manifest  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
TRINO_SERVER = "https://127.0.0.1:18443"
ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
GOLD_ROOT = ROOT / "evals" / "p0_gold"
SOURCE_MANIFEST = GOLD_ROOT / "answervice_v4_3.p0.draft.v1.manifest.json"
SOURCE_CASES = GOLD_ROOT / "answervice_v4_3.p0.draft.v1.jsonl"
SEMANTIC_CANDIDATE = (
    ROOT / "evals" / "semantic_review" / "answervice_d2_metrics.v1.json"
)
OUTPUT_MANIFEST = GOLD_ROOT / "answervice_v4_3.p0.candidate.v2.manifest.json"
OUTPUT_CASES = GOLD_ROOT / "answervice_v4_3.p0.candidate.v2.jsonl"
RECEIPT_FILE = ROOT / ".tmp" / "phase10-p0-gold-oracle-receipt.json"
REVIEW_FILE = ROOT / ".tmp" / "phase10-p0-gold-oracle-review.json"
SOURCE_CASE_SHA256 = "f487f9c323282b114b858730ce09142eaebc5e64c7e1b02ccfc2129434e92d7b"
RECEIPT_VERSION = "answervice.phase10_p0_gold_oracle_receipt.v1"
REVIEW_VERSION = "answervice.phase10_p0_gold_oracle_review.v1"
HOTEL_ASSET = "serving.analytics_v4_3.hotel_operations_daily"
VOC_ASSET = "serving.analytics_v4_3.voc_review_detail"
VOC_ORACLE_ASSET = "crm.walkerhill_v4_3.crm_voc_reviews"
MAX_ROWS = 500
# Trino는 장기 실행 중 결과가 없는 상태 page를 여러 번 돌려줄 수 있다. 제품 실행기와
# 동일하게 total deadline·row bound를 권위 경계로 두고, 이 값은 비정상적인 초고속
# nextUri loop만 차단하는 보조 상한으로 사용한다.
MAX_PAGES = 1_000
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_TRINO_NUMERIC = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")
_VOC_FORBIDDEN_SOURCE_COLUMNS = {
    "member_no",
    "related_id",
    "review_text_original",
    "review_title",
    "submitted_at",
    "voc_review_id",
}


class Phase10P0GoldOracleError(RuntimeError):
    """P0 Gold 교정·query 경계·oracle 결과가 승인 계약과 다름을 나타낸다."""


METRICS: dict[str, tuple[str, str, bool]] = {
    "room_revenue": ("SUM(room_revenue_krw)", HOTEL_ASSET, False),
    "fnb_revenue": ("SUM(fnb_revenue_krw)", HOTEL_ASSET, False),
    "banquet_revenue": ("SUM(banquet_revenue_krw)", HOTEL_ASSET, False),
    "facility_revenue": ("SUM(facility_revenue_krw)", HOTEL_ASSET, False),
    "total_operating_revenue_krw": (
        "SUM(total_operating_revenue_krw)",
        HOTEL_ASSET,
        False,
    ),
    "overtime_hours": ("SUM(overtime_hours)", HOTEL_ASSET, False),
    "occupancy_rate": (
        "CAST(SUM(occupied_room_nights) AS DOUBLE) "
        "/ NULLIF(SUM(available_room_nights), 0)",
        HOTEL_ASSET,
        True,
    ),
    "adr": (
        "CAST(SUM(room_revenue_krw) AS DOUBLE) "
        "/ NULLIF(SUM(occupied_room_nights), 0)",
        HOTEL_ASSET,
        True,
    ),
    "revpar": (
        "CAST(SUM(room_revenue_krw) AS DOUBLE) "
        "/ NULLIF(SUM(available_room_nights), 0)",
        HOTEL_ASSET,
        True,
    ),
    "voc_average_rating": (
        # source DDL은 review PK와 analysis review UNIQUE/FK로 이 view의 리뷰당
        # 1행을 보장한다. runtime의 SUM/COUNT DISTINCT를 재사용하지 않는 독립 동치식이다.
        "AVG(CAST(rating_overall AS DOUBLE))",
        VOC_ORACLE_ASSET,
        True,
    ),
}
DIMENSIONS = {
    "hotel_code": "hotel_code",
    "source_channel": "source_channel",
    "touchpoint": "touchpoint",
    "selected_category": "selected_category",
}
TIME_COLUMNS = {
    HOTEL_ASSET: "business_date",
    VOC_ORACLE_ASSET: "source_business_date",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """고정된 project·입출력과 read-only Trino 연결 인자를 받는다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--trino-server", required=True)
    parser.add_argument("--trino-ca-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-cases", type=Path, required=True)
    parser.add_argument("--semantic-candidate", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-cases", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def _exact_path(value: Path, expected: Path, label: str, *, exists: bool) -> Path:
    try:
        resolved = value.resolve(strict=exists)
        target = expected.resolve(strict=exists)
    except OSError as error:
        raise Phase10P0GoldOracleError(f"{label} is unavailable") from error
    if resolved != target:
        raise Phase10P0GoldOracleError(f"{label} differs from the approved boundary")
    return resolved


def validate_boundary(args: argparse.Namespace) -> None:
    """현재 격리 project와 versioned Gold 파일 밖의 실행을 거부한다."""

    if args.target_project != TARGET_PROJECT or args.trino_server.rstrip("/") != TRINO_SERVER:
        raise Phase10P0GoldOracleError("P0 Gold oracle target differs")
    if args.timeout <= 0 or args.timeout > 600:
        raise Phase10P0GoldOracleError("P0 Gold oracle timeout is invalid")
    _exact_path(args.env_file, ENV_FILE, "environment file", exists=True)
    _exact_path(args.source_manifest, SOURCE_MANIFEST, "source manifest", exists=True)
    _exact_path(args.source_cases, SOURCE_CASES, "source cases", exists=True)
    _exact_path(
        args.semantic_candidate,
        SEMANTIC_CANDIDATE,
        "semantic candidate",
        exists=True,
    )
    _exact_path(args.output_manifest, OUTPUT_MANIFEST, "output manifest", exists=False)
    _exact_path(args.output_cases, OUTPUT_CASES, "output cases", exists=False)
    _exact_path(args.receipt, RECEIPT_FILE, "oracle receipt", exists=False)
    _exact_path(args.review_output, REVIEW_FILE, "oracle review", exists=False)
    try:
        ca_file = args.trino_ca_file.resolve(strict=True)
    except OSError as error:
        raise Phase10P0GoldOracleError("Trino CA is unavailable") from error
    if not args.trino_ca_file.is_absolute() or not ca_file.is_file():
        raise Phase10P0GoldOracleError("Trino CA is outside the explicit boundary")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SOURCE_CASE_SHA256:
        raise Phase10P0GoldOracleError("source Gold case checksum differs")
    lines = payload.decode("utf-8").splitlines()
    if not lines or any(not line for line in lines):
        raise Phase10P0GoldOracleError("source Gold case file is invalid")
    values = [json.loads(line) for line in lines]
    if not all(isinstance(value, dict) for value in values):
        raise Phase10P0GoldOracleError("source Gold cases are invalid")
    return values


def _case_index(cases: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {str(case.get("case_id")): case for case in cases}
    if len(result) != 55 or len(result) != len(cases):
        raise Phase10P0GoldOracleError("source Gold case inventory differs")
    return result


def _mark_review(case: dict[str, Any], note: str) -> None:
    case["review_status"] = "REVIEW_REQUIRED"
    case["reviewer"] = None
    case["reviewed_at"] = None
    case["blocker"] = None
    case["provenance"]["notes"] = note


def _block(case: dict[str, Any], error_code: str, note: str) -> None:
    case["allow_or_block"] = "BLOCK"
    case["expected_error_code"] = error_code
    case["expected_query_strategy"] = None
    case["expected_assets"] = []
    case["expected_join_ids"] = []
    case["expected_result"] = {
        "kind": "NONE",
        "sha256": None,
        "value": None,
        "absolute_tolerance": None,
    }
    _mark_review(case, note)


def corrected_cases(source_cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """승인 패킷의 11개 결함과 clarification error taxonomy를 결정론적으로 교정한다."""

    cases = deepcopy(list(source_cases))
    index = _case_index(cases)

    index["P0-S-011"]["utterances"] = ["지난달 객실 매출을 일별로 보여줘"]
    _mark_review(index["P0-S-011"], "Unanchored demonstrative replaced by a relative month.")

    for case_id in ("P0-S-021", "P0-S-022", "P0-S-023"):
        case = index[case_id]
        case["expected_query_strategy"] = "VIEW_REUSE"
        case["expected_assets"] = [HOTEL_ASSET]
        _mark_review(case, "Same-view multi-metric mapping corrected to VIEW_REUSE.")
    index["P0-S-022"]["utterances"] = [
        "2025년 객실 매출과 초과근로시간의 월별 추이를 같이 보여줘"
    ]
    index["P0-S-023"]["utterances"] = [
        "2025년 8월 연회 매출과 시설 매출을 같은 날짜 기준으로 비교해줘"
    ]

    index["P0-S-024"]["utterances"] = [
        "2025년 투숙 당시 회원등급별 객실 매출을 보여줘"
    ]
    _block(
        index["P0-S-024"],
        "CONTEXT_INCOMPLETE",
        "Event-time stay membership dimension is not an approved P0 capability.",
    )
    index["P0-S-030"]["utterances"] = [
        "2025년 예약 당시 등급 기준으로 객실 매출을 비교해줘"
    ]
    _block(
        index["P0-S-030"],
        "CONTEXT_INCOMPLETE",
        "Booking-time membership dimension is not an approved P0 capability.",
    )

    for case_id in ("P0-X-009", "P0-X-010"):
        index[case_id]["expected_error_code"] = "METRIC_NOT_AVAILABLE"
        _mark_review(index[case_id], "Unknown metric uses the stable API error taxonomy.")
    index["P0-X-011"]["expected_error_code"] = "ACCESS_DENIED"
    _mark_review(
        index["P0-X-011"],
        "Sensitive invalid dimension is denied instead of treated as a suggestion.",
    )

    index["P0-M-007"]["utterances"][0] = (
        "2026년 7월 호텔별 초과근로시간을 보여줘"
    )
    index["P0-M-007"]["expected_resolved_request"]["period"] = {
        "start": "2026-07-01",
        "end_exclusive": "2026-08-01",
    }
    _mark_review(index["P0-M-007"], "Required source-analysis period added.")
    index["P0-M-009"]["utterances"][0] = (
        "2025년 8월 객실 매출과 식음 매출을 보여줘"
    )
    index["P0-M-009"]["expected_resolved_request"]["period"] = {
        "start": "2025-08-01",
        "end_exclusive": "2025-09-01",
    }
    _mark_review(index["P0-M-009"], "Required source-analysis period added.")

    for case_id in ("P0-S-026", "P0-S-027", "P0-S-028"):
        index[case_id]["expected_error_code"] = "CONTEXT_INCOMPLETE"
        _mark_review(
            index[case_id],
            "Clarification status is separated from the stable API error code.",
        )

    if sum(case["allow_or_block"] == "ALLOW" for case in cases) != 35:
        raise Phase10P0GoldOracleError("corrected ALLOW inventory differs")
    if sum(case["allow_or_block"] == "BLOCK" for case in cases) != 20:
        raise Phase10P0GoldOracleError("corrected BLOCK inventory differs")
    return cases


def _query_shape(case: Mapping[str, Any]) -> tuple[str, list[str], list[str], bool]:
    resolved = case["expected_resolved_request"]
    metric_ids = list(resolved["metric_ids"])
    if not metric_ids:
        raise Phase10P0GoldOracleError("ALLOW case has no metric")
    definitions = [METRICS.get(metric_id) for metric_id in metric_ids]
    if any(definition is None for definition in definitions):
        raise Phase10P0GoldOracleError("ALLOW case references an unsupported metric")
    assets = {definition[1] for definition in definitions if definition is not None}
    if len(assets) != 1:
        raise Phase10P0GoldOracleError("oracle never performs an implicit asset join")
    dimensions = list(resolved["dimensions"])
    if any(name not in DIMENSIONS for name in dimensions):
        raise Phase10P0GoldOracleError("ALLOW case references an unsupported dimension")
    period = resolved["period"]
    if not isinstance(period, Mapping):
        raise Phase10P0GoldOracleError("ALLOW case requires an explicit period")
    operations = set(resolved["operations"])
    time_series = (
        resolved["chart_type"] == "LINE"
        or "ADD_VALUE:comparison_period" in operations
    )
    return next(iter(assets)), metric_ids, dimensions, time_series


def build_oracle_sql(case: Mapping[str, Any]) -> tuple[str, bool]:
    """명시적 metric 식·dimension·period만 사용해 bounded SELECT를 만든다."""

    asset, metric_ids, dimensions, time_series = _query_shape(case)
    resolved = case["expected_resolved_request"]
    period = resolved["period"]
    grain = str(resolved["grain"])
    time_column = TIME_COLUMNS[asset]
    select_items: list[str] = []
    group_items: list[str] = []
    order_items: list[str] = []
    if time_series:
        if grain == "business_day":
            expression = time_column
        elif grain.startswith("month"):
            expression = f"CAST(date_trunc('month', {time_column}) AS DATE)"
        else:
            raise Phase10P0GoldOracleError("time-series grain is unsupported")
        select_items.append(f"{expression} AS period")
        group_items.append(expression)
        order_items.append("period")
    for dimension in dimensions:
        column = DIMENSIONS[dimension]
        select_items.append(f"{column} AS {dimension}")
        group_items.append(column)
        order_items.append(dimension)
    for metric_id in metric_ids:
        expression, metric_asset, _approximate = METRICS[metric_id]
        if metric_asset != asset or not _SAFE_NAME.fullmatch(metric_id):
            raise Phase10P0GoldOracleError("metric oracle mapping differs")
        select_items.append(f"{expression} AS {metric_id}")
    sql = (
        f"SELECT {', '.join(select_items)} FROM {asset} "
        f"WHERE {time_column} >= DATE '{period['start']}' "
        f"AND {time_column} < DATE '{period['end_exclusive']}'"
    )
    if group_items:
        sql += f" GROUP BY {', '.join(group_items)}"
    if order_items:
        sql += f" ORDER BY {', '.join(order_items)}"
    sql += f" LIMIT {MAX_ROWS}"
    _validate_sql(sql, asset)
    scalar = not group_items and len(metric_ids) == 1
    return sql, scalar


def _validate_sql(sql: str, asset: str) -> None:
    upper = sql.upper()
    if (
        not upper.startswith("SELECT ")
        or ";" in sql
        or asset not in {HOTEL_ASSET, VOC_ORACLE_ASSET}
        or f" FROM {asset} " not in sql
        or any(
            token in upper
            for token in (
                " INSERT ",
                " UPDATE ",
                " DELETE ",
                " CREATE ",
                " DROP ",
                " ALTER ",
                " MERGE ",
                " CALL ",
            )
        )
        or f" LIMIT {MAX_ROWS}" not in sql
    ):
        raise Phase10P0GoldOracleError("oracle SQL escaped the read-only boundary")
    if asset == VOC_ORACLE_ASSET and any(
        re.search(rf"\b{re.escape(column)}\b", sql, flags=re.IGNORECASE)
        for column in _VOC_FORBIDDEN_SOURCE_COLUMNS
    ):
        raise Phase10P0GoldOracleError("VOC oracle selected a forbidden source column")


def _normal(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise Phase10P0GoldOracleError("oracle result contains a non-finite value")
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise Phase10P0GoldOracleError("oracle result contains a non-finite value")
        return 0.0 if value == 0 else value
    raise Phase10P0GoldOracleError("oracle result contains an unsupported value")


async def _collect(
    client: TrinoAsyncClient,
    sql: str,
    *,
    timeout: float,
) -> tuple[str, list[str], list[list[Any]], int]:
    deadline = monotonic() + timeout
    page = await client.execute(sql, deadline=deadline)
    query_id = page.query_id
    columns = list(page.columns)
    rows = [list(map(_normal, row)) for row in page.rows]
    warning_count = len(page.warnings)
    for _ in range(MAX_PAGES):
        if len(rows) > MAX_ROWS:
            if page.next_uri:
                await client.cancel_query(query_id, page.next_uri, deadline=deadline)
            raise Phase10P0GoldOracleError("oracle result exceeded the row budget")
        if page.next_uri is None:
            if page.state != "FINISHED" or not columns:
                raise Phase10P0GoldOracleError("oracle query did not finish")
            return query_id, columns, rows, warning_count
        try:
            page = await client.next_page(page.next_uri, deadline=deadline)
        except AdapterError as error:
            try:
                await client.cancel_query(
                    query_id,
                    page.next_uri,
                    deadline=monotonic() + 5.0,
                )
            except AdapterError as cancel_error:
                if cancel_error.code is not AdapterErrorCode.NOT_FOUND:
                    raise Phase10P0GoldOracleError(
                        "oracle query cancellation failed"
                    ) from cancel_error
            raise error
        if page.query_id != query_id:
            raise Phase10P0GoldOracleError("oracle query identity changed")
        if page.columns:
            if columns and columns != list(page.columns):
                raise Phase10P0GoldOracleError("oracle result columns changed")
            columns = list(page.columns)
        rows.extend(list(map(_normal, row)) for row in page.rows)
        warning_count += len(page.warnings)
    if page.next_uri:
        await client.cancel_query(query_id, page.next_uri, deadline=deadline)
    raise Phase10P0GoldOracleError("oracle result exceeded the page budget")


def _result_assertion(
    *,
    metric_ids: Sequence[str],
    scalar: bool,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> tuple[dict[str, Any], Any]:
    if scalar:
        if len(metric_ids) != 1 or list(columns) != list(metric_ids) or len(rows) != 1:
            raise Phase10P0GoldOracleError("scalar oracle shape differs")
        value = rows[0][0]
        if isinstance(value, str) and _TRINO_NUMERIC.fullmatch(value):
            value = _normal(Decimal(value))
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise Phase10P0GoldOracleError(
                f"scalar oracle value type {type(value).__name__} is not numeric"
            )
        approximate = METRICS[metric_ids[0]][2]
        assertion = {
            "kind": "TOLERANCE",
            "sha256": None,
            "value": value,
            "absolute_tolerance": 1e-9 if approximate else 0,
        }
        return assertion, value
    canonical_result = {
        "columns": list(columns),
        "rows": [list(row) for row in rows],
    }
    assertion = {
        "kind": "HASH",
        "sha256": canonical_sha256(canonical_result),
        "value": None,
        "absolute_tolerance": None,
    }
    return assertion, canonical_result


def _environment(path: Path) -> tuple[str, str]:
    values = dotenv_values(path)
    user = str(values.get("TRINO_DATAHUB_USER") or "").strip()
    password = str(values.get("TRINO_DATAHUB_PASSWORD") or "")
    if not user or not password:
        raise Phase10P0GoldOracleError("Trino read-only credentials are unavailable")
    return user, password


async def author_bundle(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    """교정 case를 실행해 versioned candidate Gold와 secret-safe receipt를 만든다."""

    source_manifest = _load_json(args.source_manifest)
    semantic_candidate = _load_json(args.semantic_candidate)
    cases = corrected_cases(_load_cases(args.source_cases))
    user, password = _environment(args.env_file)
    receipts: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    async with TrinoAsyncClient(
        args.trino_server,
        user,
        password,
        ca_file=args.trino_ca_file,
        request_timeout_seconds=min(args.timeout, 30.0),
    ) as client:
        for case in cases:
            if case["allow_or_block"] == "BLOCK":
                case["expected_result"] = {
                    "kind": "NONE",
                    "sha256": None,
                    "value": None,
                    "absolute_tolerance": None,
                }
                receipts.append(
                    {
                        "case_id": case["case_id"],
                        "decision": "BLOCK",
                        "query_executed": False,
                        "expected_error_code": case["expected_error_code"],
                    }
                )
                reviews.append(
                    {
                        "case_id": case["case_id"],
                        "utterances": case["utterances"],
                        "decision": "BLOCK",
                        "error_code": case["expected_error_code"],
                        "result": None,
                    }
                )
                continue
            sql, scalar = build_oracle_sql(case)
            try:
                query_id, columns, rows, warning_count = await _collect(
                    client,
                    sql,
                    timeout=args.timeout,
                )
                assertion, review_result = _result_assertion(
                    metric_ids=case["expected_resolved_request"]["metric_ids"],
                    scalar=scalar,
                    columns=columns,
                    rows=rows,
                )
            except Phase10P0GoldOracleError as error:
                raise Phase10P0GoldOracleError(
                    f"{case['case_id']}: {error}"
                ) from error
            except AdapterError as error:
                raise Phase10P0GoldOracleError(
                    f"{case['case_id']}: Trino adapter {error.code.value}"
                ) from error
            case["expected_result"] = assertion
            receipts.append(
                {
                    "case_id": case["case_id"],
                    "decision": "ALLOW",
                    "query_executed": True,
                    "query_id": query_id,
                    "query_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                    "column_count": len(columns),
                    "row_count": len(rows),
                    "warning_count": warning_count,
                    "result_assertion": assertion,
                }
            )
            reviews.append(
                {
                    "case_id": case["case_id"],
                    "utterances": case["utterances"],
                    "decision": "ALLOW",
                    "metric_ids": case["expected_resolved_request"]["metric_ids"],
                    "period": case["expected_resolved_request"]["period"],
                    "result_assertion": assertion,
                    "aggregate_result": review_result,
                }
            )

    case_payload = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for case in cases
    ).encode("utf-8")
    case_sha256 = hashlib.sha256(case_payload).hexdigest()
    manifest = deepcopy(source_manifest)
    manifest.update(
        {
            "status": "DRAFT",
            "semantic_release_id": None,
            "product_release_id": None,
            "case_file": OUTPUT_CASES.name,
            "case_content_sha256": case_sha256,
        }
    )
    manifest["provenance"]["notes"] = (
        "Corrected v2 candidate with independent read-only Trino result oracles; "
        "final reviewer approval and release binding remain required."
    )
    summary = validate_manifest(
        manifest,
        cases,
        semantic_candidate,
        observed_case_content_sha256=case_sha256,
    )
    if (
        summary["status"] != "VALID_DRAFT"
        or summary["unsealed_result_count"] != 0
        or summary["blocked_case_count"] != 0
        or summary["review_counts"] != {"REVIEW_REQUIRED": 55}
    ):
        raise Phase10P0GoldOracleError("corrected candidate Gold summary differs")
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_VERSION,
        "target_project": TARGET_PROJECT,
        "source_case_sha256": SOURCE_CASE_SHA256,
        "candidate_case_sha256": case_sha256,
        "semantic_candidate_sha256": manifest["semantic_candidate_sha256"],
        "data_release_id": manifest["data_release_id"],
        "allow_case_count": 35,
        "block_case_count": 20,
        "oracle_sources": [HOTEL_ASSET, VOC_ORACLE_ASSET],
        "queries": receipts,
        "raw_source_rows_retained": False,
        "sql_text_retained": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    review = {
        "schema_version": REVIEW_VERSION,
        "candidate_case_sha256": case_sha256,
        "synthetic_data_notice": (
            "2026-08-16 through 2026-08-31 values are demo synthetic scenario data, "
            "not observed Walkerhill actuals."
        ),
        "cases": reviews,
    }
    return {
        "case_payload": case_payload,
        "manifest": manifest,
        "summary": summary,
        "receipt": receipt,
    }, review


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    _write_bytes(path, payload)


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    bundle, review = await author_bundle(args)
    _write_bytes(args.output_cases, bundle["case_payload"])
    _write_json(args.output_manifest, bundle["manifest"])
    _write_json(args.receipt, bundle["receipt"])
    _write_json(args.review_output, review)
    return {
        "status": "PHASE10_P0_GOLD_ORACLE_CANDIDATE_READY",
        "target_project": TARGET_PROJECT,
        "allow_case_count": bundle["receipt"]["allow_case_count"],
        "block_case_count": bundle["receipt"]["block_case_count"],
        "candidate_case_sha256": bundle["receipt"]["candidate_case_sha256"],
        "receipt_sha256": bundle["receipt"]["receipt_sha256"],
        "review_status": bundle["summary"]["review_counts"],
        "scorable": bundle["summary"]["scorable"],
    }


def main(argv: list[str] | None = None) -> int:
    """경계를 검증하고 candidate bundle만 atomic하게 기록한다."""

    try:
        args = parse_args(argv)
        validate_boundary(args)
        result = asyncio.run(_main(args))
    except (AdapterError, OSError, RuntimeError, ValueError) as error:
        message = (
            str(error)
            if isinstance(error, Phase10P0GoldOracleError)
            else "P0 Gold oracle operation failed"
        )
        print(
            json.dumps(
                {"status": "PHASE10_P0_GOLD_ORACLE_ERROR", "error": message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
