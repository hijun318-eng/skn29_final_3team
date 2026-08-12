from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from sys import path

import pytest

ROOT = Path(__file__).resolve().parents[2]
path.insert(0, str(ROOT / "app" / "backend"))

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
LIVE_TRINO_PROFILE = "ANSWERVICE_LIVE_TRINO_E2E"


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


@pytest.mark.skipif(
    os.environ.get(LIVE_TRINO_PROFILE) != "1",
    reason=f"set {LIVE_TRINO_PROFILE}=1 to run the live Trino Gold E2E",
)
def test_g120_046_context_and_runtime_gold_are_composable():
    contract = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    package, request_context = _product_package(contract)
    adapter = I2DataPlatformAdapter(
        "http://127.0.0.1:18080",
        "answervice-integration",
        require_live_metadata=False,
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())

    assert adapter.search_assets(contract["question"], {"role": "unauthorized"}) == []
    selected = adapter.search_assets(
        contract["question"], request_context.model_dump(mode="json")
    )
    assert {item["fqn"] for item in selected} == {
        item["fqn"] for item in contract["assets"]
    }

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
