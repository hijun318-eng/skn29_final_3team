from __future__ import annotations

import os
from time import perf_counter

from app.adapters.contract_model import openai_transport
from src.ai.prompt_registry import get_prompt


class ReportAssistantModelError(RuntimeError):
    pass


def generate_report_draft(payload: dict[str, object]) -> tuple[dict[str, str], dict[str, object]]:
    endpoint = os.getenv("OPENAI_ENDPOINT", "")
    token = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "")
    if not endpoint or not token or not model:
        raise ReportAssistantModelError("Report Assistant model configuration is unavailable")
    timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            result = openai_transport(
                endpoint,
                token,
                "report_assistant",
                payload,
                timeout,
                model=model,
                provider="openai",
            )
            fields = ("title", "executive_summary", "table_title", "chart_title")
            if any(not isinstance(result.get(field), str) or not result[field].strip() for field in fields):
                raise ValueError("Report Assistant returned an invalid draft")
            prompt = get_prompt("report.assistant")
            return (
                {field: result[field].strip() for field in fields},
                {
                    "model_version": model,
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.metadata()["hash"],
                    "attempts": attempt,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                },
            )
        except (OSError, TimeoutError, TypeError, ValueError) as error:
            last_error = error
    raise ReportAssistantModelError("Report Assistant model call failed") from last_error
