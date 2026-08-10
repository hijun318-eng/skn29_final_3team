from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from sys import path

import pytest


ROOT = Path(__file__).resolve().parents[2]
path.insert(0, str(ROOT / "app" / "backend"))

from app.adapters.contract_model import ContractModelAdapter
from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.contracts import AnalysisRequest, RequestContext
from app.services.context_builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from app.services.pipeline_support import PipelineSupport


CONTEXT_PATH = ROOT / "src/data/pms_crm_pos_context.i5.v1.json"


def _product_package(contract: dict) -> tuple[object, RequestContext]:
    filters = tuple(ContextRequiredFilter(**item) for item in contract["required_filters"])
    assets = tuple(
        ContextAsset(
            urn=item["urn"],
            fqn=item["fqn"],
            columns=tuple(item["columns"]),
            join_ids=(contract["approved_join"]["id"],),
            required_filters=filters if index == 0 else (),
        )
        for index, item in enumerate(contract["assets"])
    )
    bindings = tuple(ContextParameterBinding(**item) for item in contract["parameter_bindings"])
    package = ContextPackageBuilder().build(
        ContextBuildRequest(
            context_release=contract["contract_version"],
            policy_version="policy-v1",
            time_version="2026-07-01",
            entitlement_hash="integration-entitlement",
            assets=assets,
            token_count=100,
            model_context_tokens=24_000,
            parameter_bindings=bindings,
        ),
        frozenset(item.urn for item in assets),
    )
    return package, RequestContext(as_of=date(2026, 7, 1))


def _typed_gold_plan(contract: dict, package: object) -> dict:
    sql = (ROOT / contract["gold_evidence"]["sql_file"]).read_text(encoding="utf-8")
    replacements = {
        "s.property_id = 'SYNTHETIC_HOTEL_001'": "s.property_id = :required_filter_5",
        "s.complimentary_flag = false": "s.complimentary_flag = :required_filter_2",
        "s.house_use_flag = false": "s.house_use_flag = :required_filter_3",
        "s.is_forecast = false": "s.is_forecast = :required_filter_4",
        "s.stay_status = 'COMPLETED'": "s.stay_status = :required_filter_6",
        "o.property_id = 'SYNTHETIC_HOTEL_001'": "o.property_id = :required_filter_8",
        "o.void_flag = 0": "o.void_flag = :required_filter_9",
        "o.is_forecast = 0": "o.is_forecast = :required_filter_7",
        "TIMESTAMP '2026-05-01 00:00:00 Asia/Seoul'": "TIMESTAMP ':period_start 00:00:00 Asia/Seoul'",
        "TIMESTAMP '2026-07-01 00:00:00 Asia/Seoul'": "TIMESTAMP ':period_end_exclusive 00:00:00 Asia/Seoul'",
        "TIMESTAMP '2026-05-01 00:00:00'": "TIMESTAMP ':period_start 00:00:00'",
        "TIMESTAMP '2026-07-01 00:00:00'": "TIMESTAMP ':period_end_exclusive 00:00:00'",
    }
    for old, new in replacements.items():
        assert old in sql
        sql = sql.replace(old, new)
    sql = sql.replace("h.grade_code = 'GOLD'", "h.grade_code = :required_filter_1")
    sql = sql.rstrip() + "\nLIMIT 1000"
    return {
        "sql": sql,
        "references": [
            {
                "urn": item.urn,
                "fqn": item.fqn,
                "columns": list(item.columns),
                "join_ids": list(package.approved_join_ids),
            }
            for item in package.assets
        ],
        "parameters": {
            item.name: {"value_type": item.value_type, "value": item.value}
            for item in package.parameter_bindings
        },
        "model_version": "approved-gold-candidate-not-node2-output",
    }


def _g2_probe_plan(package: object) -> dict:
    sql = " ".join(
        (
            "SELECT 1 FROM pms.public.pms_stays s",
            "JOIN pms.public.pms_reservations r ON 1=1",
            "JOIN pms.public.pms_guests g0 ON 1=1",
            "JOIN crm.dbo.crm_customer_map m ON 1=1",
            "JOIN crm.dbo.crm_member_grade_history g ON 1=1",
            "JOIN pos.pos_db.pos_orders o ON 1=1",
            "WHERE s.actual_checkout_at >= DATE ':period_start'",
            "AND s.actual_checkout_at < DATE ':period_end_exclusive'",
            "AND g.grade_code = :required_filter_1",
            "AND s.complimentary_flag = :required_filter_2",
            "AND s.house_use_flag = :required_filter_3",
            "AND s.is_forecast = :required_filter_4",
            "AND s.property_id = :required_filter_5",
            "AND s.stay_status = :required_filter_6",
            "AND o.is_forecast = :required_filter_7",
            "AND o.property_id = :required_filter_8",
            "AND o.void_flag = :required_filter_9 LIMIT 1000",
        )
    )
    return {
        "sql": sql,
        "references": [
            {
                "urn": item.urn,
                "fqn": item.fqn,
                "columns": list(item.columns),
                "join_ids": list(package.approved_join_ids),
            }
            for item in package.assets
        ],
        "parameters": {
            item.name: {"value_type": item.value_type, "value": item.value}
            for item in package.parameter_bindings
        },
        "model_version": "g2-contract-probe-not-node2-output",
    }


def test_g120_046_components_prove_runtime_gold_but_product_e2e_fails_closed():
    contract = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    package, request_context = _product_package(contract)
    adapter = I2DataPlatformAdapter(
        "http://127.0.0.1:18080",
        "answervice-integration",
        require_live_metadata=False,
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())

    assert adapter.search_assets(contract["question"], {"role": "unauthorized"}) == []
    with pytest.raises(ValueError, match="Asset Binding runtime verification is unavailable"):
        adapter.search_assets(contract["question"], request_context.model_dump(mode="json"))

    model = ContractModelAdapter()
    model_payload = {
        "request_id": str(request_context.request_id),
        "question": contract["question"],
        "package": package,
        "context": request_context,
    }
    node2_plan = model.generate("node2", model_payload)
    assert support.g2_violation(node2_plan, package) == "METRIC_FILTER_MISSING"
    with pytest.raises(ValueError, match="unsupported normalized error code"):
        model.generate(
            "node2_repair",
            {
                **model_payload,
                "trace_id": request_context.trace_id,
                "rejected_sql": node2_plan["sql"],
                "violation": "METRIC_FILTER_MISSING",
            },
        )

    candidate = _g2_probe_plan(package)
    assert support.g2_violation(candidate, package) is None
    bound = I2DataPlatformAdapter._bind_parameters(
        candidate["sql"], candidate["parameters"]
    )
    assert ":period_" not in bound and ":required_filter_" not in bound
    outside = {
        **candidate,
        "sql": candidate["sql"].replace(
            "FROM pms.public.pms_stays s",
            "FROM pms.public.pms_stays s "
            "JOIN serving.analytics.hotel_daily_metrics x ON true",
        ),
    }
    assert support.g2_violation(outside, package) in {
        "SQL_REFERENCE_MISMATCH",
        "UNAPPROVED_JOIN",
    }
    missing = {
        **candidate,
        "sql": candidate["sql"].replace(
            "AND s.complimentary_flag = :required_filter_2 ", ""
        ),
        "parameters": {
            key: value
            for key, value in candidate["parameters"].items()
            if key != "required_filter_2"
        },
    }
    assert support.g2_violation(missing, package) == "METRIC_FILTER_MISSING"

    typed_gold = _typed_gold_plan(contract, package)
    assert support.g2_violation(typed_gold, package) == "UNSAFE_SQL"
    raw_gold_sql = (ROOT / contract["gold_evidence"]["sql_file"]).read_text(
        encoding="utf-8"
    )
    query = adapter._collect(adapter._trino.execute(raw_gold_sql))
    assert query["status"] == "SUCCEEDED"
    assert support.g3_violation(query) is None
    rows = [
        [
            str(row["property_id"]),
            str(row["month"]),
            f'{Decimal(str(row["room_revenue_krw"])):.2f}',
            f'{Decimal(str(row["fnb_revenue_krw"])):.2f}',
            f'{Decimal(str(row["total_guest_revenue_krw"])):.2f}',
        ]
        for row in query["rows"]
    ]
    canonical = "".join("|".join(row) + "\n" for row in rows)
    evidence = contract["gold_evidence"]
    assert rows == evidence["rows"]
    assert len(rows) == evidence["row_count"] == 2
    assert sum(Decimal(row[-1]) for row in rows) == Decimal("475972400.00")
    assert hashlib.sha256(canonical.encode()).hexdigest() == evidence["result_sha256"]
