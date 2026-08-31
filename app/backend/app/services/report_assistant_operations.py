"""Report Assistant 평가의 비용 추정과 기간 품질 지표를 순수 함수로 계산한다."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import os
from typing import Any, Iterable


@dataclass(frozen=True)
class ReportAssistantModelCostPolicy:
    """한 요청 동안 고정해 사용하는 provider 단가와 최대 허용 비용이다."""

    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    max_estimated_cost_usd: Decimal

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
        """검증된 token 수를 정책 단가로 계산한다."""

        if (
            isinstance(input_tokens, bool)
            or isinstance(output_tokens, bool)
            or not isinstance(input_tokens, int)
            or not isinstance(output_tokens, int)
            or input_tokens < 0
            or output_tokens < 0
        ):
            raise RuntimeError("Report Assistant token 사용량이 유효하지 않습니다.")
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ) / million


def report_assistant_model_cost_policy() -> ReportAssistantModelCostPolicy:
    """외부 모델 호출에 필요한 단가와 비용 상한을 명시 설정에서만 읽는다."""

    names = (
        "REPORT_ASSISTANT_INPUT_USD_PER_MILLION",
        "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION",
        "REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD",
    )
    raw = tuple(os.getenv(name) for name in names)
    if any(value is None or not value.strip() for value in raw):
        raise RuntimeError("Report Assistant 비용 설정이 필요합니다.")
    try:
        input_price, output_price, cost_limit = (
            Decimal(value) for value in raw if value is not None
        )
    except (InvalidOperation, ValueError) as error:
        raise RuntimeError("Report Assistant 비용 설정이 유효하지 않습니다.") from error
    values = (input_price, output_price, cost_limit)
    if any(not value.is_finite() or value <= 0 for value in values):
        raise RuntimeError("Report Assistant 비용 설정이 유효하지 않습니다.")
    return ReportAssistantModelCostPolicy(
        input_usd_per_million=input_price,
        output_usd_per_million=output_price,
        max_estimated_cost_usd=cost_limit,
    )


def estimate_model_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    policy: ReportAssistantModelCostPolicy | None = None,
) -> Decimal | None:
    """실제 token 사용량을 호출 전 고정한 비용 정책으로 추정한다."""

    if input_tokens is None or output_tokens is None:
        return None
    active_policy = policy or report_assistant_model_cost_policy()
    return active_policy.estimate(input_tokens, output_tokens)


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
