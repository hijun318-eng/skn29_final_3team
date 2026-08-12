"""Fail-closed privacy boundary for outbound model payloads."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


POLICY_VERSION = "MODEL-OUTBOUND-v1"
_ALLOWED_SENSITIVITY = frozenset({"PUBLIC", "INTERNAL", "PSEUDONYMIZED", "AGGREGATED"})
_FORBIDDEN_KEYS = frozenset(
    {"authorization", "token", "api_key", "apikey", "password", "secret"}
)
DIRECT_IDENTIFIER_FIELDS = frozenset(
    {
        "email",
        "phone",
        "guest_id",
        "member_no",
        "pms_guest_id",
        "pos_customer_ref",
        "reservation_id",
    }
)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\d[ -]?){9,12}(?!\d)")
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_OPENAI_KEY = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")


class OutboundPrivacyError(ValueError):
    """Raised before transport when a payload exceeds the approved boundary."""


def prepare_outbound(node: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a redacted copy and non-sensitive G3/audit evidence."""
    if node == "node3":
        columns = ((payload.get("shaped_result") or {}).get("columns") or ())
        if any(
            isinstance(column, dict)
            and str(column.get("name", "")).lower() in DIRECT_IDENTIFIER_FIELDS
            for column in columns
        ):
            raise OutboundPrivacyError("direct identifier cannot be sent to node3")
    classifications: set[str] = set()
    redactions = 0

    def visit(value: Any, key: str = "") -> Any:
        nonlocal redactions
        normalized_key = key.lower()
        if normalized_key in _FORBIDDEN_KEYS:
            raise OutboundPrivacyError("model payload contains a forbidden secret field")
        if normalized_key == "sensitivity":
            classification = str(value).upper()
            if classification not in _ALLOWED_SENSITIVITY:
                raise OutboundPrivacyError("model payload sensitivity is not approved")
            classifications.add(classification)
            return classification
        if node == "node3" and normalized_key in DIRECT_IDENTIFIER_FIELDS:
            raise OutboundPrivacyError("direct identifier cannot be sent to node3")
        if isinstance(value, dict):
            return {str(item_key): visit(item, str(item_key)) for item_key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if isinstance(value, tuple):
            return [visit(item, key) for item in value]
        if not isinstance(value, str):
            return value
        redacted = _EMAIL.sub("[REDACTED_EMAIL]", value)
        redacted = _PHONE.sub("[REDACTED_PHONE]", redacted)
        redacted = _BEARER.sub("[REDACTED_TOKEN]", redacted)
        redacted = _OPENAI_KEY.sub("[REDACTED_TOKEN]", redacted)
        redactions += redacted != value
        return redacted

    sanitized = visit(payload)
    default_classification = "AGGREGATED" if node == "node3" else "INTERNAL"
    classifications.add(default_classification)
    encoded = json.dumps(
        sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    evidence = {
        "policy_version": POLICY_VERSION,
        "decision": "ALLOW",
        "classifications": sorted(classifications),
        "redaction_count": redactions,
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "g3_required": node == "node3",
    }
    return sanitized, evidence
