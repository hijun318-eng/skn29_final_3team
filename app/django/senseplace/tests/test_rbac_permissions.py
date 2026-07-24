"""RBAC 권한 매트릭스 테스트.

Given/When/Then 구조.
"""

from django.test import TestCase

from senseplace.rbac.permissions import (
    Permission,
    ROLE_PERMISSIONS,
    has_permission,
    get_permissions,
)


class PermissionMatrixTest(TestCase):
    """3역할 권한 매트릭스 검증."""

    # --- OPERATIONS_MANAGER ---

    def test_ops_has_view_all_aggregates(self) -> None:
        """Given: OPERATIONS_MANAGER, When: 전체 운영 집계 권한 확인, Then: 허용"""
        self.assertTrue(
            has_permission("OPERATIONS_MANAGER", Permission.VIEW_ALL_AGGREGATES)
        )

    def test_ops_has_approve_report(self) -> None:
        """Given: OPERATIONS_MANAGER, When: 보고서 결정 권한 확인, Then: 허용"""
        self.assertTrue(
            has_permission("OPERATIONS_MANAGER", Permission.APPROVE_REPORT)
        )

    def test_ops_has_all_permissions(self) -> None:
        """Given: OPERATIONS_MANAGER, When: 전체 권한 목록 확인, Then: 6개"""
        perms = get_permissions("OPERATIONS_MANAGER")
        self.assertEqual(len(perms), 6)

    # --- FACILITY_MANAGER ---

    def test_fac_has_fnb_aggregates(self) -> None:
        """Given: FACILITY_MANAGER, When: F&B 집계 권한 확인, Then: 허용"""
        self.assertTrue(
            has_permission("FACILITY_MANAGER", Permission.VIEW_FNB_AGGREGATES)
        )

    def test_fac_has_breakfast_staff(self) -> None:
        """Given: FACILITY_MANAGER, When: 조식 인력 상세 권한 확인, Then: 허용"""
        self.assertTrue(
            has_permission("FACILITY_MANAGER", Permission.VIEW_BREAKFAST_STAFF)
        )

    def test_fac_no_approve_report(self) -> None:
        """Given: FACILITY_MANAGER, When: 보고서 결정 권한 확인, Then: 거부"""
        self.assertFalse(
            has_permission("FACILITY_MANAGER", Permission.APPROVE_REPORT)
        )

    def test_fac_no_view_all_aggregates(self) -> None:
        """Given: FACILITY_MANAGER, When: 전체 운영 집계 권한 확인, Then: 거부"""
        self.assertFalse(
            has_permission("FACILITY_MANAGER", Permission.VIEW_ALL_AGGREGATES)
        )

    # --- EXTERNAL_REVIEWER ---

    def test_ext_has_room_aggregates(self) -> None:
        """Given: EXTERNAL_REVIEWER, When: 객실 집계 권한 확인, Then: 허용"""
        self.assertTrue(
            has_permission("EXTERNAL_REVIEWER", Permission.VIEW_ROOM_AGGREGATES)
        )

    def test_ext_has_room_detail(self) -> None:
        """Given: EXTERNAL_REVIEWER, When: 객실 상세 권한 확인, Then: 허용"""
        self.assertTrue(
            has_permission("EXTERNAL_REVIEWER", Permission.VIEW_ROOM_DETAIL)
        )

    def test_ext_no_approve_report(self) -> None:
        """Given: EXTERNAL_REVIEWER, When: 보고서 결정 권한 확인, Then: 거부"""
        self.assertFalse(
            has_permission("EXTERNAL_REVIEWER", Permission.APPROVE_REPORT)
        )

    def test_ext_no_breakfast_staff(self) -> None:
        """Given: EXTERNAL_REVIEWER, When: 조식 인력 상세 권한 확인, Then: 거부"""
        self.assertFalse(
            has_permission("EXTERNAL_REVIEWER", Permission.VIEW_BREAKFAST_STAFF)
        )

    # --- 미존재 역할 ---

    def test_unknown_role_no_permissions(self) -> None:
        """Given: 미존재 역할, When: 권한 확인, Then: 빈 집합"""
        self.assertFalse(has_permission("UNKNOWN_ROLE", Permission.VIEW_ALL_AGGREGATES))
        self.assertEqual(get_permissions("UNKNOWN_ROLE"), frozenset())

    # --- 매트릭스 전체 일관성 ---

    def test_all_roles_have_write_field_note(self) -> None:
        """Given: 모든 역할, When: 현장 확인 메모 권한, Then: 모두 허용"""
        for role in ROLE_PERMISSIONS:
            self.assertTrue(has_permission(role, Permission.WRITE_FIELD_NOTE))

    def test_only_ops_can_approve_report(self) -> None:
        """Given: 모든 역할, When: 보고서 결정 권한, Then: OPERATIONS_MANAGER만 허용"""
        for role in ROLE_PERMISSIONS:
            expected = role == "OPERATIONS_MANAGER"
            actual = has_permission(role, Permission.APPROVE_REPORT)
            self.assertEqual(actual, expected)
