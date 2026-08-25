from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from no_show_ml.config import ProjectConfig


def main() -> None:
    config = ProjectConfig.default()
    required = [
        "data_profile.json",
        "data_quality_checks.csv",
        "dataset_manifest.csv",
        "source_file_hashes.csv",
        "model_metrics.csv",
        "threshold_selection.json",
        "calibration_bins.csv",
        "test_subgroup_metrics.csv",
        "feature_contract.json",
        "tool_contract.json",
        "readiness_gate.json",
        "model_metadata.json",
        "onnx_parity.json",
        "inference_predictions.csv",
        "run_summary.json",
        "tool_fixture_results.json",
        "tool_audit_fixture.jsonl",
        "local_tool_verification.json",
        "boosting_trial_metrics.csv",
        "boosting_family_best.csv",
        "model_selection_comparison.csv",
        "test_top15_metrics.json",
        "calibration_summary.json",
        "monthly_calibration.csv",
        "main_chat_mcp_fixture.json",
        "rdb_feature_query_fixture.json",
    ]
    missing = [name for name in required if not (config.artifacts_dir / name).is_file()]
    quality = pd.read_csv(config.artifacts_dir / "data_quality_checks.csv")
    metrics = pd.read_csv(config.artifacts_dir / "model_metrics.csv")
    parity = json.loads((config.artifacts_dir / "onnx_parity.json").read_text(encoding="utf-8"))
    local_tool = json.loads((config.artifacts_dir / "local_tool_verification.json").read_text(encoding="utf-8"))
    comparison = pd.read_csv(config.artifacts_dir / "model_selection_comparison.csv")
    top15 = json.loads((config.artifacts_dir / "test_top15_metrics.json").read_text(encoding="utf-8"))
    rdb_fixture = json.loads(
        (config.artifacts_dir / "rdb_feature_query_fixture.json").read_text(encoding="utf-8")
    )
    readiness = json.loads((config.artifacts_dir / "readiness_gate.json").read_text(encoding="utf-8"))
    failures = []
    if missing:
        failures.append(f"missing artifacts: {missing}")
    unexpected_quality_failures = quality[
        quality["status"].eq("FAIL") & ~quality["check_id"].eq("DQ-09")
    ]
    if not unexpected_quality_failures.empty:
        failures.append(
            f"unexpected data quality failures: {unexpected_quality_failures['check_id'].tolist()}"
        )
    if parity["status"] != "PASS":
        failures.append("ONNX parity failed")
    if local_tool["status"] != "PASS":
        failures.append("local Tool fixture failed")
    if not {"TRAIN", "VALIDATION", "TEST"}.issubset(set(metrics["split"])):
        failures.append("required evaluation splits missing")
    if comparison["selection_eligible"].astype(str).str.lower().eq("true").any():
        failures.append("report expects no eligible challenger")
    test_rows = int(metrics.loc[metrics["split"].eq("TEST"), "rows"].iloc[0])
    if not 0.149 <= top15["selected_rows"] / test_rows <= 0.151:
        failures.append("TEST Top15 selected row ratio mismatch")
    if (
        rdb_fixture["status"] != "LOCAL_REAL_DB_PASS"
        or rdb_fixture["service_adapter_connected"]
    ):
        failures.append("local Trino fixture or production adapter status mismatch")
    gate_status = {item["gate"]: item["status"] for item in readiness["checks"]}
    if gate_status.get("source_pms_no_show_label") != "FAIL":
        failures.append("invalid source model must remain blocked by source label gate")
    if gate_status.get("live_rdb_feature_query") != "LOCAL_REAL_DB_PASS":
        failures.append("live_rdb_feature_query is not LOCAL_REAL_DB_PASS")
    registration = json.loads(
        (config.project_dir / "config" / "mcp_registration.json").read_text(encoding="utf-8")
    )
    if registration["enabled"] or registration["approval_status"] != "NOT_APPROVED":
        failures.append("production MCP registration must remain disabled")
    top15_policy = json.loads(
        (config.project_dir / "config" / "top15_policy.json").read_text(encoding="utf-8")
    )
    if top15_policy["top_fraction"] != 0.15 or top15_policy["business_approval"] != "PENDING":
        failures.append("Top15 policy must remain local and pending business approval")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        f"PASS: {len(required)} archived artifacts are consistent; "
        "official No-show activation remains blocked"
    )


if __name__ == "__main__":
    main()
