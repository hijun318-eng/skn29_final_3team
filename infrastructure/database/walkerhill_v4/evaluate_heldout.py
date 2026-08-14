#!/usr/bin/env python3
"""Validate v4 held-out gold SQL through G2 and the live Trino read-only path."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CASES = HERE / "heldout_cases.v1.json"
DEFAULT_REPORT = ROOT / "output" / "walkerhill_v4_runtime" / "heldout_report.json"
REFERENCE = re.compile(r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)", re.IGNORECASE)
MUTATION = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|call)\b", re.IGNORECASE)


def references(sql: str) -> set[str]:
    return {
        value.replace('"', "").lower()
        for value in REFERENCE.findall(sql)
        if value.count(".") >= 2
    }


def g2_validate(case: dict) -> dict:
    sql = case["sql"]
    actual = references(sql)
    allowed = {value.lower() for value in case["allowed_assets"]}
    required = {value.lower() for value in case["required_assets"]}
    violations = []
    if MUTATION.search(sql):
        violations.append("MUTATION_FORBIDDEN")
    if re.search(r"\bselect\s+\*", sql, re.IGNORECASE):
        violations.append("SELECT_STAR_FORBIDDEN")
    if not actual <= allowed:
        violations.append("ASSET_NOT_ALLOWED")
    if not required <= actual:
        violations.append("REQUIRED_ASSET_MISSING")
    if any(value.startswith(("pms.public.", "crm.dbo.", "pos.pos_db.", "facility.facility.")) for value in actual):
        violations.append("LEGACY_ASSET_FORBIDDEN")
    return {"status": "PASS" if not violations else "FAIL", "references": sorted(actual), "violations": violations}


def run_trino(sql: str, container: str, user: str) -> dict:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "trino",
            "--server",
            "http://localhost:8080",
            "--user",
            user,
            "--output-format",
            "JSON",
            "--execute",
            sql,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode:
        error = "\n".join(line for line in completed.stderr.splitlines() if line.strip())
        return {"status": "FAIL", "error": error[-1000:]}
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "status": "PASS",
        "row_count": len(rows),
        "result_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def evaluate(cases_path: Path, report_path: Path, container: str, user: str) -> dict:
    contract = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    for case in contract["cases"]:
        g2 = g2_validate(case)
        execution = run_trino(case["sql"], container, user) if g2["status"] == "PASS" else {"status": "NOT_RUN"}
        results.append(
            {
                "id": case["id"],
                "family": case["family"],
                "g2": g2,
                "g1_readonly_execution": execution["status"],
                "g3_result_evidence": execution,
            }
        )
        print(f"{case['id']} g2={g2['status']} trino={execution['status']}", flush=True)
    gold_pass = all(
        result["g2"]["status"] == "PASS" and result["g1_readonly_execution"] == "PASS"
        for result in results
    )
    report = {
        "version": contract["version"],
        "gold_sql_status": "PASS" if gold_pass else "FAIL",
        "case_count": len(results),
        "gold_sql_pass_count": sum(
            result["g2"]["status"] == "PASS" and result["g1_readonly_execution"] == "PASS"
            for result in results
        ),
        "qwen_model_status": "BLOCKED_ENDPOINT_UNAVAILABLE",
        "retraining_decision": "NOT_DECIDED_UNTIL_LIVE_HELDOUT",
        "promotion_eligible": False,
        "results": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--container", default="hotel-synthetic-db-trino-1")
    parser.add_argument("--user", default="hotel_analyst")
    args = parser.parse_args()
    report = evaluate(args.cases.resolve(), args.report.resolve(), args.container, args.user)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return 0 if report["gold_sql_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
