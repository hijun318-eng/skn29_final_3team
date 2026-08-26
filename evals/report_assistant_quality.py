"""Report Assistant 캡처 결과를 안전한 품질 지표로 평가한다."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


def _rate(checks: list[bool]) -> float | None:
    return sum(checks) / len(checks) if checks else None


def _operation_values(output: dict[str, Any]) -> tuple[set[str], list[str]]:
    operations: set[str] = set()
    evidence_refs: list[str] = []
    for item in output.get("operations", ()):
        if isinstance(item, str):
            operations.add(item)
            continue
        if isinstance(item, dict) and isinstance(item.get("op"), str):
            operations.add(item["op"])
            evidence_refs.extend(
                ref for ref in item.get("evidence_refs", ()) if isinstance(ref, str)
            )
    return operations, evidence_refs


def evaluate_report_assistant_quality(
    cases: Iterable[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    *,
    mode: str = "deterministic_fake",
) -> dict[str, Any]:
    """원문을 반환하지 않고 주입된 fake 또는 캡처 결과를 동일 기준으로 채점한다."""

    if mode not in {"deterministic_fake", "captured_live"}:
        raise ValueError("unsupported Report Assistant evaluation mode")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    contract_checks: list[bool] = []
    route_checks: list[bool] = []
    operation_checks: list[bool] = []
    dry_run_checks: list[bool] = []
    evidence_checks: list[bool] = []
    refinement_checks: list[bool] = []
    unnecessary = operation_count = 0
    attempts: list[int] = []
    latencies: list[float] = []
    input_tokens: list[int] = []
    output_tokens: list[int] = []
    costs: list[Decimal] = []
    prompt_versions: set[str] = set()
    model_versions: set[str] = set()

    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            raise ValueError("Report Assistant eval case ID must be unique")
        seen.add(case_id)
        output = outputs.get(case_id)
        if output is None:
            raise ValueError(f"missing deterministic output: {case_id}")

        operations, evidence_refs = _operation_values(output)
        allowed = set(case.get("allowed", ()))
        required = set(case.get("required", ()))
        allowed_refs = set(case.get("allowed_evidence_refs", ()))
        contract_ok = output.get("contract_valid", True) is True
        route_ok = output.get("route") == case.get("route")
        operation_ok = required.issubset(operations) and operations.issubset(allowed)
        evidence_ok = set(evidence_refs).issubset(allowed_refs) and (
            not case.get("evidence_required") or bool(evidence_refs)
        )
        refinement_ok = not operations.intersection(case.get("refinement_removes", ()))
        checks = [contract_ok, route_ok, operation_ok, evidence_ok, refinement_ok]

        if "dry_run_expected" in case:
            dry_run_ok = output.get("dry_run_valid") == case["dry_run_expected"]
            dry_run_checks.append(dry_run_ok)
            checks.append(dry_run_ok)
        if "approval" in case:
            checks.append(output.get("approval") == case["approval"])
        if "error_code" in case:
            checks.append(output.get("error_code") == case["error_code"])

        contract_checks.append(contract_ok)
        route_checks.append(route_ok)
        operation_checks.append(operation_ok)
        evidence_checks.append(evidence_ok)
        if case.get("refinement_removes"):
            refinement_checks.append(refinement_ok)
        operation_count += len(operations)
        unnecessary += len(operations - allowed)
        if isinstance(output.get("attempts"), int) and not isinstance(output["attempts"], bool):
            attempts.append(output["attempts"])
        if isinstance(output.get("latency_ms"), (int, float)) and not isinstance(output["latency_ms"], bool):
            latencies.append(float(output["latency_ms"]))
        for field, target in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
            if isinstance(output.get(field), int) and not isinstance(output[field], bool):
                target.append(output[field])
        if output.get("estimated_cost") is not None:
            costs.append(Decimal(str(output["estimated_cost"])))
        if isinstance(output.get("prompt_version"), str):
            prompt_versions.add(output["prompt_version"])
        if isinstance(output.get("model_version"), str):
            model_versions.add(output["model_version"])

        results.append({
            "case_id": case_id,
            "status": "PASS" if all(checks) else "FAIL",
            "contract_valid": contract_ok,
            "route_match": route_ok,
            "operation_match": operation_ok,
            "evidence_valid": evidence_ok,
        })

    return {
        "mode": mode,
        "prompt_versions": sorted(prompt_versions),
        "model_versions": sorted(model_versions),
        "total": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] == "FAIL" for item in results),
        "metrics": {
            "strict_contract_success_rate": _rate(contract_checks),
            "route_accuracy": _rate(route_checks),
            "operation_accuracy": _rate(operation_checks),
            "server_dry_run_success_rate": _rate(dry_run_checks),
            "unnecessary_operation_rate": unnecessary / operation_count if operation_count else None,
            "evidence_ref_validity_rate": _rate(evidence_checks),
            "refinement_instruction_success_rate": _rate(refinement_checks),
            "average_model_attempts": sum(attempts) / len(attempts) if attempts else None,
            "average_model_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "total_input_tokens": sum(input_tokens) if input_tokens else None,
            "total_output_tokens": sum(output_tokens) if output_tokens else None,
            "estimated_cost_total": str(sum(costs, Decimal("0"))) if costs else None,
        },
        "results": results,
    }


def main() -> int:
    """명시적으로 캡처된 JSON 결과만 읽어 네트워크 호출 없는 평가 요약을 출력한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("report_assistant_quality_cases.json"))
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--mode", choices=("deterministic_fake", "captured_live"), default="deterministic_fake")
    arguments = parser.parse_args()
    cases = json.loads(arguments.cases.read_text(encoding="utf-8"))
    outputs = json.loads(arguments.outputs.read_text(encoding="utf-8"))
    print(json.dumps(evaluate_report_assistant_quality(cases, outputs, mode=arguments.mode), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
