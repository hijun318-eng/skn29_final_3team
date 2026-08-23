"""App-owned analysis capability를 DataHub runtime asset에 결속하는 경계를 검증한다."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.data.analysis_capability_contract import (
    AnalysisCapabilityError,
    apply_analysis_capability_contract,
    compile_analysis_capability_contract,
)


FQN = "serving.example.daily"


def _contract(
    *,
    time_field: str = "business_date",
    availability: bool = False,
    conversation_default: bool = False,
):
    asset = {
        "fqn": FQN,
        "time": {
            "mode": "range",
            "field": time_field,
            "default": "required_period",
        },
        "dimensions": [
            {"id": "hotel", "columns": ["hotel_code"]}
        ],
    }
    if availability:
        asset["data_availability"] = {
            "data_available_from": "2025-07-01",
            "data_available_through": "2025-08-31",
        }
    if conversation_default:
        asset["conversation_default_operation"] = "time_trend"
    return compile_analysis_capability_contract(
        {
            "version": "ANSWERVICE-ANALYSIS-CAPABILITY-v1",
            "max_metrics_per_plan": 4,
            "operations": ["aggregate", "period_comparison", "time_trend"],
            "assets": [asset],
        },
        available_fields_by_asset={
            FQN: {"business_date", "other_date", "hotel_code", "amount"}
        },
        dimension_family_columns={"hotel": {"hotel_code"}},
    )


def _asset() -> dict[str, object]:
    return {
        "fqn": FQN,
        "time_metadata": {
            "calendar_id": "iso8601",
            "start_parameter": "start_date",
            "end_parameter": "end_date",
            "fields": [
                {
                    "field": {"asset_fqn": FQN, "column": "business_date"},
                    "bucket": "day",
                    "native_type": "date",
                    "timezone_mode": "preserve",
                }
            ],
        },
        "dimensions": [
            {"id": "hotel", "asset_fqn": FQN, "column": "hotel_code"}
        ],
    }


def test_sealed_capability_adds_only_the_versioned_comparison_window() -> None:
    source = _asset()
    result = apply_analysis_capability_contract(_contract(), [source])

    assert "comparison_window" not in source["time_metadata"]
    assert result[0]["time_metadata"]["comparison_window"] == {
        "start_parameter": "comparison_start_date",
        "end_parameter": "comparison_end_date",
    }


def test_capability_cannot_override_a_different_datahub_time_field() -> None:
    source = _asset()
    before = deepcopy(source)

    with pytest.raises(AnalysisCapabilityError, match="time field"):
        apply_analysis_capability_contract(
            _contract(time_field="other_date"),
            [source],
        )

    assert source == before


def test_sealed_availability_adds_release_bound_watermarks() -> None:
    result = apply_analysis_capability_contract(
        _contract(availability=True),
        [{**_asset(), "product_release_id": "release-7"}],
    )

    assert result[0]["data_available_from"] == "2025-07-01"
    assert result[0]["data_available_through"] == "2025-08-31"
    assert result[0]["evidence_cutoff"] == "2025-08-31"


def test_sealed_availability_cannot_override_a_different_runtime_watermark() -> None:
    source = {**_asset(), "evidence_cutoff": "2025-09-30"}

    with pytest.raises(AnalysisCapabilityError, match="availability differs"):
        apply_analysis_capability_contract(
            _contract(availability=True),
            [source],
        )


def test_sealed_conversation_default_is_explicit_and_cannot_be_overridden() -> None:
    result = apply_analysis_capability_contract(
        _contract(conversation_default=True),
        [_asset()],
    )

    assert result[0]["conversation_default_operation"] == "time_trend"
    with pytest.raises(AnalysisCapabilityError, match="default operation differs"):
        apply_analysis_capability_contract(
            _contract(conversation_default=True),
            [{**_asset(), "conversation_default_operation": "aggregate"}],
        )
