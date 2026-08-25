from __future__ import annotations

import json

import pandas as pd

from no_show_ml.config import ProjectConfig
from no_show_ml.io_utils import write_json
from no_show_ml.service import NoShowToolService, ToolRequest, write_jsonl


def main() -> None:
    config = ProjectConfig.default()
    inference = pd.read_csv(config.inference_csv)
    row = inference.iloc[0]
    feature_as_of = pd.Timestamp(row["prediction_cutoff_at"]).tz_localize(
        "Asia/Seoul"
    ).isoformat()
    service = NoShowToolService(config)
    requests = [
        ToolRequest(
            reservation_id=str(row["reservation_id"]),
            feature_as_of=feature_as_of,
            feature_set_version=config.feature_set_version,
            input_schema_version=service.input_schema_version,
        ),
        ToolRequest(
            reservation_id=str(row["reservation_id"]),
            feature_as_of=feature_as_of,
            feature_set_version=config.feature_set_version,
            input_schema_version=service.input_schema_version,
        ),
        ToolRequest(
            reservation_id="RES-NOT-FOUND",
            feature_as_of=feature_as_of,
            feature_set_version=config.feature_set_version,
            input_schema_version=service.input_schema_version,
        ),
        ToolRequest(
            reservation_id=str(row["reservation_id"]),
            feature_as_of=feature_as_of,
            feature_set_version="invalid-feature-version",
            input_schema_version=service.input_schema_version,
        ),
    ]
    results = [service.execute(request) for request in requests]
    write_json(config.artifacts_dir / "tool_fixture_results.json", results)
    write_jsonl(config.artifacts_dir / "tool_audit_fixture.jsonl", results)
    verification = {
        "success_count": sum(row["prediction_status"] == "SUCCESS" for row in results),
        "error_statuses": sorted(
            {row["prediction_status"] for row in results if row["prediction_status"] != "SUCCESS"}
        ),
        "same_input_probability_match": results[0]["no_show_probability"]
        == results[1]["no_show_probability"],
        "unique_execution_ids": len({row["execution_id"] for row in results}) == len(results),
        "audit_rows": len(results),
    }
    verification["status"] = "PASS" if (
        verification["success_count"] == 2
        and verification["same_input_probability_match"]
        and verification["unique_execution_ids"]
        and verification["error_statuses"] == ["FEATURE_NOT_FOUND", "SCHEMA_MISMATCH"]
    ) else "FAIL"
    write_json(config.artifacts_dir / "local_tool_verification.json", verification)
    readiness_path = config.artifacts_dir / "readiness_gate.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    for check in readiness["checks"]:
        if check["gate"] in {"local_tool_fixture", "local_audit_fixture"}:
            check["status"] = verification["status"]
    write_json(readiness_path, readiness)
    summary_path = config.artifacts_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["local_tool_status"] = verification["status"]
    summary["local_tool_verification"] = verification
    write_json(summary_path, summary)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
