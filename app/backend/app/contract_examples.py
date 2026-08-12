from __future__ import annotations

from app.contracts import CONTRACT_VERSION


ANALYSIS_REQUEST_EXAMPLES = {
    "general": {
        "summary": "일반 분석 질문",
        "value": {"question": "이번 달 객실 운영 상태를 요약해줘"},
    },
    "template": {
        "summary": "승인 Template 요청",
        "value": {
            "question": "주간 객실 운영 현황",
            "template_id": "weekly-room-operations",
            "parameters": {
                "period_start": "2026-05-01",
                "period_end_exclusive": "2026-07-01",
            },
        },
    },
}

STATE_MAPPING = {
    "contract_version": CONTRACT_VERSION,
    "controller_to_api_ui": {
        "RECEIVED": {"api": "queued", "ui": "LOADING"},
        "ROUTED": {"api": "running", "ui": "LOADING"},
        "SUCCEEDED": {"api": "success", "ui": "READY"},
        "BLOCKED": {"api": "blocked", "ui": "ERROR"},
        "PARTIAL": {"api": "partial", "ui": "PARTIAL"},
        "FAILED": {"api": "failed", "ui": "ERROR"},
        "CANCELLED": {"api": "cancelled", "ui": "CANCELLED"},
    },
    "outcome_overrides": {
        "EMPTY": {"api": "success", "ui": "EMPTY"},
        "CACHED": {"api": "success", "ui": "READY"},
        "CONTEXT_INCOMPLETE": {"api": "blocked", "ui": "EMPTY"},
        "ACCESS_DENIED": {"api": "blocked", "ui": "FORBIDDEN"},
        "RESULT_EVIDENCE_MISSING": {
            "api": "failed",
            "ui": "INSUFFICIENT_EVIDENCE",
        },
        "RATE_LIMITED": {"api": "queued", "ui": "DELAYED"},
    },
}
