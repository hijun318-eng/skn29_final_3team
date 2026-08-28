"""Column 명칭의 보수적 PII 분류가 업무 식별자와 일반 명칭을 구분하는지 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_classification import classify_column  # noqa: E402


def test_explicit_person_identifiers_and_free_text_are_restricted() -> None:
    expected = {
        "guest_id": "CUSTOMER_ID",
        "member_no": "CUSTOMER_ID",
        "pos_customer_ref": "CUSTOMER_ID",
        "facility_user_ref": "CUSTOMER_ID",
        "reservation_id": "RESERVATION_ID",
        "banquet_booking_id": "RESERVATION_ID",
        "guest_email": "EMAIL",
        "mobile_phone": "PHONE",
        "customer_address": "ADDRESS",
        "guest_name": "NAME",
        "review_text_original": "FREE_TEXT",
        "public_notes": "FREE_TEXT",
    }

    for column, pii_type in expected.items():
        classification = classify_column(column)
        assert classification.pii_type == pii_type
        assert classification.sensitivity == "RESTRICTED"


def test_counts_and_non_person_names_are_not_misclassified_as_pii() -> None:
    for column in (
        "guest_count",
        "review_count",
        "facility_name",
        "holiday_name",
        "event_name",
        "member_revenue_krw",
    ):
        classification = classify_column(column)
        assert classification.pii_type == "NONE"
        assert classification.sensitivity == "INTERNAL"
