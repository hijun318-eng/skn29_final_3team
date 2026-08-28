"""Report Assistant deterministic 결과를 route·operation·승인·오류 계약으로 평가한다."""

from __future__ import annotations

from typing import Any, Iterable


def evaluate_report_assistant_quality(
    cases: Iterable[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """모델 호출 없이 주입된 fake 결과를 기대 route와 허용 operation에 맞춰 판정한다."""

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            raise ValueError("Report Assistant eval case ID must be unique")
        seen.add(case_id)
        output = outputs.get(case_id)
        if output is None:
            raise ValueError(f"missing deterministic output: {case_id}")
        allowed = set(case.get("allowed", ()))
        operations = set(output.get("operations", ()))
        passed = (
            output.get("route") == case.get("route")
            and operations.issubset(allowed)
            and output.get("error_code") == case.get("error_code")
            and (
                "approval" not in case
                or output.get("approval") == case.get("approval")
            )
            and (
                "report_changed" not in case
                or output.get("report_changed") == case.get("report_changed")
            )
            and (
                "duplicate_revision" not in case
                or output.get("duplicate_revision") == case.get("duplicate_revision")
            )
        )
        results.append({"case_id": case_id, "status": "PASS" if passed else "FAIL"})
    return {
        "mode": "deterministic_fake",
        "total": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] == "FAIL" for item in results),
        "results": results,
    }
