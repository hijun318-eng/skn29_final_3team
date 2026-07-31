import json
from datetime import date
from pathlib import Path
from sys import path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.contracts import AnalysisRequest, RequestContext
from app.services.context_builder import ContextPackageBuilder
from app.services.pipeline_support import PipelineSupport


def test_trino_transport_sends_required_user_header():
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"id": "query-1", "stats": {"state": "FINISHED"}}
    ).encode()
    response.__enter__.return_value = response
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")

    with patch("app.adapters.i2_data_platform.urlopen", return_value=response) as call:
        payload = adapter._request(
            "POST",
            "http://trino:8080/v1/statement",
            "SELECT 1",
        )

    request = call.call_args.args[0]
    assert request.get_header("X-trino-user") == "runtime-user"
    assert request.data == b"SELECT 1"
    assert payload["id"] == "query-1"


def test_approved_i2_template_passes_g2_contract():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="Approved weekly room revenue template",
        template_id="weekly-room-operations",
        parameters={
            "period_start": "2026-05-01",
            "period_end_exclusive": "2026-07-01",
        },
    )
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump())
    package = support.build_context(payload, context, assets)
    sql = (
        (
            BACKEND.parents[1]
            / "infrastructure"
            / "database"
            / "sql"
            / "queries"
            / "i2_gold_recognized_room_revenue.sql"
        )
        .read_text(encoding="utf-8")
        .replace("2026-05-01", ":period_start")
        .replace("2026-07-01", ":period_end_exclusive")
        .rstrip()
        .rstrip(";")
        + "\nLIMIT 1000"
    )
    plan = {
        "sql": sql,
        "parameters": payload.parameters,
        "references": [
            {"urn": item.urn, "fqn": item.fqn, "columns": list(item.columns)}
            for item in package.assets
        ],
        "model_version": "TEMPLATE-I2-v1.0.0",
    }

    assert support.g2_violation(plan, package) is None


def test_template_dates_are_bound_without_changing_the_approved_query_shape():
    sql = (
        "SELECT 1 WHERE event_at >= TIMESTAMP ':period_start 00:00:00 Asia/Seoul' "
        "AND event_at < TIMESTAMP ':period_end_exclusive 00:00:00 Asia/Seoul' "
        "LIMIT 1000"
    )

    bound = I2DataPlatformAdapter._bind_date_parameters(
        sql,
        {
            "period_start": "2026-05-01",
            "period_end_exclusive": "2026-07-01",
        },
    )

    assert ":period_" not in bound
    assert "2026-05-01" in bound
    assert "2026-07-01" in bound
    assert bound.endswith("LIMIT 1000")


@pytest.mark.parametrize(
    "parameters",
    [
        {"period_start": "2026-05-01' OR 1=1 --"},
        {"period_start": "2026-02-30"},
        {},
    ],
)
def test_template_date_binding_rejects_invalid_or_missing_values(parameters):
    with pytest.raises(ValueError):
        I2DataPlatformAdapter._bind_date_parameters(
            "SELECT 1 WHERE event_at >= TIMESTAMP ':period_start'",
            parameters,
        )
