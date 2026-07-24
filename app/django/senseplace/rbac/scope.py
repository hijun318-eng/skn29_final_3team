"""scope_snapshot 생성 모듈.

CPS v2.0 §10의 요청 context에서 정의된 scope_snapshot 구조를
역할별로 생성한다. FastAPI 계층이 검증에 사용하는 스냅샷이다.

scope_snapshot 구조:
{
    "property_ids": ["GRAND_WALKERHILL_SEOUL"],
    "metric_groups": ["BREAKFAST", ...]
}
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
PROPERTY_ID = "GRAND_WALKERHILL_SEOUL"

# 역할별 허용 metric_groups
_ROLE_METRIC_GROUPS: dict[str, list[str]] = {
    "OPERATIONS_MANAGER": [
        "BREAKFAST",
        "FNB_VOC",
        "GUEST_ROOM",
        "STAFF",
        "INCIDENTS",
        "REPORTS",
    ],
    "FACILITY_MANAGER": [
        "BREAKFAST",
        "FNB_VOC",
    ],
    "EXTERNAL_REVIEWER": [
        "GUEST_ROOM_SUMMARY",
    ],
}

# 역할별 허용 권한 기능 (role_code → set of capability strings)
_ROLE_CAPABILITIES: dict[str, set[str]] = {
    "OPERATIONS_MANAGER": {
        "view_all_aggregates",
        "view_breakfast_staff",
        "view_room_detail",
        "view_issue_brief_all",
        "write_field_note",
        "approve_report",
    },
    "FACILITY_MANAGER": {
        "view_fnb_aggregates",
        "view_breakfast_staff",
        "view_issue_brief_fnb",
        "write_field_note",
    },
    "EXTERNAL_REVIEWER": {
        "view_room_aggregates",
        "view_room_detail",
        "view_issue_brief_room",
        "write_field_note",
    },
}


def build_scope_snapshot(role_code: str) -> dict[str, Any]:
    """역할 코드에 해당하는 scope_snapshot을 생성한다.

    Args:
        role_code: Role enum 값 (예: "OPERATIONS_MANAGER")

    Returns:
        scope_snapshot 딕셔너리.
    """
    metric_groups = _ROLE_METRIC_GROUPS.get(role_code, [])
    capabilities = _ROLE_CAPABILITIES.get(role_code, set())

    return {
        "property_ids": [PROPERTY_ID],
        "metric_groups": metric_groups,
        "capabilities": sorted(capabilities),
    }


def scope_allows_metric(scope_snapshot: dict[str, Any], metric_group: str) -> bool:
    """scope_snapshot이 특정 metric_group을 허용하는지 확인한다."""
    return metric_group in scope_snapshot.get("metric_groups", [])


def scope_allows_capability(scope_snapshot: dict[str, Any], capability: str) -> bool:
    """scope_snapshot이 특정 capability를 허용하는지 확인한다."""
    return capability in scope_snapshot.get("capabilities", [])
