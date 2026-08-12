from pathlib import Path
from sys import path
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api.router import _model, _routing_service
from app.contracts import AnalysisRequest


def test_versioned_trino_routing_ignores_legacy_database_template():
    payload = AnalysisRequest(
        question="주간 객실 운영 현황",
        template_id="weekly-room-operations",
        parameters={
            "period_start": "2026-05-01",
            "period_end_exclusive": "2026-07-01",
        },
    )

    with patch.dict(
        "os.environ",
        {
            "DATA_PLATFORM_MODE": "versioned-trino",
            "APP_RUNTIME_DATABASE_URL": "postgresql://legacy-template",
        },
        clear=True,
    ), patch(
        "app.api.router.RoutingService.from_database"
    ) as from_database:
        decision = _routing_service().decide(payload)

    from_database.assert_not_called()
    assert decision.source_fqns == {
        "serving.analytics.hotel_daily_metrics"
    }


def test_openai_model_routes_node2_lora_alias_by_default():
    with patch.dict(
        "os.environ",
        {
            "LLM": "OPENAI",
            "LLM_API_KEY": "openai-key",
            "OPENAI_MODEL": "gpt-4.1-mini",
            "NODE2_MODEL_ENDPOINT": "http://sllm:8000",
            "RUNPOD_API_KEY": "runpod-key",
        },
        clear=True,
    ), patch("app.adapters.contract_model.ContractModelAdapter.from_openai") as factory:
        _model()

    factory.assert_called_once_with(
        "https://api.openai.com",
        "openai-key",
        "gpt-4.1-mini",
        300.0,
        "http://sllm:8000",
        "runpod-key",
        "answervice-sql-lora-qwen3.5-4b",
    )
