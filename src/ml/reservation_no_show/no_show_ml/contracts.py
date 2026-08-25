from __future__ import annotations

from .config import CATEGORICAL_FEATURES, NUMERIC_FEATURES, ProjectConfig


def feature_contract(config: ProjectConfig) -> dict:
    return {
        "feature_set_name": "reservation_no_show_features",
        "feature_set_version": config.feature_set_version,
        "owner": "R3 AI·모델·ModelOps",
        "lifecycle": "P2_FUTURE_CANDIDATE_INACTIVE",
        "source_snapshot_id": config.source_snapshot_id,
        "source_extracted_at": config.source_extracted_at,
        "entity_key": "reservation_id",
        "event_time": "checkin_date",
        "feature_as_of": "checkin_date - 1 day at 18:00 Asia/Seoul",
        "source_asset_urns": [
            "urn:answervice:pms:pms_reservations",
            "urn:answervice:pms:pms_guests",
        ],
        "query_asset": "sql/reservation_no_show_feature_set_v1.sql",
        "query_policy_version": "reservation-no-show-query-v1.0",
        "label": {
            "name": "is_no_show",
            "positive": "NO_SHOW",
            "negative": "CHECKED_IN or COMPLETED",
            "excluded": ["CANCELLED", "unresolved future reservation"],
            "current_source": config.label_rule_version,
        },
        "features": [
            *[{"name": name, "type": "number", "missing": "reject"} for name in NUMERIC_FEATURES],
            *[{"name": name, "type": "string", "missing": "reject", "unknown": "ignore"} for name in CATEGORICAL_FEATURES],
        ],
        "leakage_policy": "Only values known at feature_as_of; outcome/status fields are banned.",
        "label_time_policy": "outcome_recorded_at must be later than feature_as_of and is used only to establish the label.",
    }


def tool_contract(config: ProjectConfig, threshold: float, model_name: str) -> dict:
    return {
        "tool_name": "predict_reservation_no_show",
        "registry_status": "INACTIVE",
        "activation_reason": "I5 and R1 P2 approval, valid source labels, UI, persistent audit, deployed timeout, and production integration are not verified.",
        "activation_gate": "All readiness_gate.json checks must be PASS.",
        "input": {
            "required": [
                "reservation_id",
                "feature_as_of",
                "feature_set_version",
                "input_schema_version",
            ],
            "schema": {
                "reservation_id": "string",
                "feature_as_of": "RFC3339 timestamp with timezone",
                "feature_set_version": {"const": config.feature_set_version},
                "input_schema_version": {"const": "reservation-no-show-input-v1.0"},
            },
        },
        "output": {
            "required": [
                "reservation_id",
                "no_show_probability",
                "risk_level",
                "prediction_status",
                "is_synthetic",
                "model_name",
                "model_version",
                "feature_set_version",
                "input_schema_version",
                "feature_as_of",
                "execution_id",
            ],
            "risk_levels": {
                "LOW": "daily cohort score rank below Top 15%",
                "HIGH": "daily cohort score rank within Top 15%",
            },
            "ranking_policy": "TOP_15_PERCENT_DAILY_COHORT",
            "validation_reference_threshold": threshold,
            "error_status": ["SUCCESS", "INVALID_INPUT", "FEATURE_NOT_FOUND", "SCHEMA_MISMATCH", "TIMEOUT", "MODEL_ERROR"],
        },
        "runtime": {
            "format": "ONNX",
            "engine": "ONNX Runtime CPU",
            "timeout_ms": 2000,
            "fallback": "Return prediction_status error; do not substitute an observed fact.",
            "local_runner": "no_show_ml.service.NoShowToolService",
        },
        "model": {
            "name": model_name,
            "version": config.model_version,
            "feature_set_version": config.feature_set_version,
            "threshold": threshold,
        },
        "ui_policy": "Display as 모델 예측 and 합성 데이터 기반 예측; never as confirmed fact.",
    }
