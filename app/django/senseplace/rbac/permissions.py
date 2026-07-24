"""3역할 권한 매트릭스 정의.

CPS v2.0 §7과 src/common/enums.py Role enum을 기반으로
운영관리자(OPERATIONS_MANAGER), 시설관리자(FACILITY_MANAGER),
외부관계자(EXTERNAL_REVIEWER)의 기능별 허용 여부를 정의한다.

권한 매트릭스:
    | 기능                 | OPERATIONS_MANAGER | FACILITY_MANAGER | EXTERNAL_REVIEWER |
    |---------------------|--------------------|--------------------|---------------------|
    | 전체 운영 집계        | O                  | F&B 범위           | 객실·허용 요약       |
    | 조식 인력 상세        | O                  | O                  | X                   |
    | 객실 집계            | O                  | 제한               | O                   |
    | 이슈 브리프          | 전체               | F&B               | 객실·허용 요약       |
    | 현장 확인 메모        | O                  | 담당 이슈           | 담당 이슈            |
    | 보고서 결정          | O                  | X                  | X                   |
"""

from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    """기능별 권한 코드."""

    VIEW_ALL_AGGREGATES = "view_all_aggregates"
    VIEW_FNB_AGGREGATES = "view_fnb_aggregates"
    VIEW_ROOM_AGGREGATES = "view_room_aggregates"
    VIEW_BREAKFAST_STAFF = "view_breakfast_staff"
    VIEW_ROOM_DETAIL = "view_room_detail"
    VIEW_ISSUE_BRIEF_ALL = "view_issue_brief_all"
    VIEW_ISSUE_BRIEF_FNB = "view_issue_brief_fnb"
    VIEW_ISSUE_BRIEF_ROOM = "view_issue_brief_room"
    WRITE_FIELD_NOTE = "write_field_note"
    APPROVE_REPORT = "approve_report"


# ---------------------------------------------------------------------------
# 역할 → 권한 매핑
# frozenset으로 불변 보장
# ---------------------------------------------------------------------------
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "OPERATIONS_MANAGER": frozenset(
        {
            Permission.VIEW_ALL_AGGREGATES,
            Permission.VIEW_BREAKFAST_STAFF,
            Permission.VIEW_ROOM_DETAIL,
            Permission.VIEW_ISSUE_BRIEF_ALL,
            Permission.WRITE_FIELD_NOTE,
            Permission.APPROVE_REPORT,
        }
    ),
    "FACILITY_MANAGER": frozenset(
        {
            Permission.VIEW_FNB_AGGREGATES,
            Permission.VIEW_BREAKFAST_STAFF,
            Permission.VIEW_ISSUE_BRIEF_FNB,
            Permission.WRITE_FIELD_NOTE,
        }
    ),
    "EXTERNAL_REVIEWER": frozenset(
        {
            Permission.VIEW_ROOM_AGGREGATES,
            Permission.VIEW_ROOM_DETAIL,
            Permission.VIEW_ISSUE_BRIEF_ROOM,
            Permission.WRITE_FIELD_NOTE,
        }
    ),
}


def has_permission(role_code: str, permission: Permission) -> bool:
    """해당 역할이 특정 권한을 가지는지 확인한다."""
    perms = ROLE_PERMISSIONS.get(role_code, frozenset())
    return permission in perms


def get_permissions(role_code: str) -> frozenset[Permission]:
    """역할의 전체 권한 집합을 반환한다."""
    return ROLE_PERMISSIONS.get(role_code, frozenset())
