"""Report Assistant 평가의 비용 추정과 기간 품질 지표를 순수 함수로 계산한다."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import math
import os
from typing import Any, Iterable


def estimate_model_cost(
    input_tokens: int | None,
    output_tokens: int | None,
) -> Decimal | None:
    """명시된 환경 단가가 있을 때만 token 사용량의 추정 비용을 반환한다."""

    if input_tokens is None or output_tokens is None:
        return None
    raw_input = os.getenv("REPORT_ASSISTANT_INPUT_USD_PER_MILLION")
    raw_output = os.getenv("REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION")
    if raw_input is None or raw_output is None:
        return None
    try:
        input_price, output_price = Decimal(raw_input), Decimal(raw_output)
    except Exception as error:
        raise RuntimeError("Report Assistant 비용 단가 설정이 유효하지 않습니다.") from error
    if input_price < 0 or output_price < 0:
        raise RuntimeError("Report Assistant 비용 단가 설정이 유효하지 않습니다.")
    million = Decimal(1_000_000)
    return (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / million


def summarize_evaluations(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """요청별 최종 평가만 받아 분모가 명확하고 빈 표본은 null인 지표를 계산한다."""

    items = list(rows)
    count = len(items)
    if not count:
        return {
            "total_requests": 0,
            "contract_success_rate": None,
            "patch_validation_success_rate": None,
            "approval_rate": None,
            "rejection_rate": None,
            "revision_success_rate": None,
            "duplicate_revision_prevention_rate": None,
            "failure_rate_by_error_code": {},
            "average_model_latency_ms": None,
            "p95_model_latency_ms": None,
            "average_model_attempts": None,
            "total_input_tokens": None,
            "total_output_tokens": None,
            "estimated_cost_total": None,
        }

    def rate(predicate: Any, denominator: list[dict[str, Any]] | None = None) -> float | None:
        sample = denominator if denominator is not None else items
        return None if not sample else sum(1 for row in sample if predicate(row)) / len(sample)

    decisions = [row for row in items if row.get("approval_decision") != "pending"]
    duplicates = [row for row in items if row.get("approval_decision") == "approved"]
    patch_rows = [row for row in items if row.get("route") == "existing_artifact"]
    latencies = sorted(float(row["latency_ms"]) for row in items if row.get("latency_ms") is not None)
    attempts = [int(row["model_attempts"]) for row in items if row.get("model_attempts") is not None]
    input_tokens = [int(row["input_tokens"]) for row in items if row.get("input_tokens") is not None]
    output_tokens = [int(row["output_tokens"]) for row in items if row.get("output_tokens") is not None]
    costs = [Decimal(str(row["estimated_cost"])) for row in items if row.get("estimated_cost") is not None]
    failures = Counter(str(row["error_code"]) for row in items if row.get("error_code"))
    return {
        "total_requests": count,
        "contract_success_rate": rate(lambda row: bool(row.get("contract_valid"))),
        "patch_validation_success_rate": rate(
            lambda row: bool(row.get("contract_valid")) and not row.get("error_code"), patch_rows
        ),
        "approval_rate": rate(lambda row: row.get("approval_decision") == "approved", decisions),
        "rejection_rate": rate(lambda row: row.get("approval_decision") == "rejected", decisions),
        "revision_success_rate": rate(lambda row: bool(row.get("revision_created")), duplicates),
        "duplicate_revision_prevention_rate": rate(
            lambda row: bool(row.get("duplicate_revision_prevented")), duplicates
        ),
        "failure_rate_by_error_code": {
            code: value / count for code, value in sorted(failures.items())
        },
        "average_model_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "p95_model_latency_ms": latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)] if latencies else None,
        "average_model_attempts": sum(attempts) / len(attempts) if attempts else None,
        "total_input_tokens": sum(input_tokens) if input_tokens else None,
        "total_output_tokens": sum(output_tokens) if output_tokens else None,
        "estimated_cost_total": sum(costs, Decimal(0)) if costs else None,
    }
