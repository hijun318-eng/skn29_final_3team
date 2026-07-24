"""scope_snapshot 생성 테스트.

Given/When/Then 구조.
"""

from django.test import TestCase

from senseplace.rbac.scope import (
    PROPERTY_ID,
    build_scope_snapshot,
    scope_allows_metric,
    scope_allows_capability,
)


class BuildScopeSnapshotTest(TestCase):
    """역할별 scope_snapshot 생성 검증."""

    def test_ops_scope_has_all_metric_groups(self) -> None:
        """Given: OPERATIONS_MANAGER, When: scope 생성, Then: 6개 metric_groups"""
        snap = build_scope_snapshot("OPERATIONS_MANAGER")
        self.assertEqual(snap["property_ids"], [PROPERTY_ID])
        self.assertEqual(len(snap["metric_groups"]), 6)
        self.assertIn("BREAKFAST", snap["metric_groups"])
        self.assertIn("FNB_VOC", snap["metric_groups"])
        self.assertIn("GUEST_ROOM", snap["metric_groups"])
        self.assertIn("STAFF", snap["metric_groups"])
        self.assertIn("INCIDENTS", snap["metric_groups"])
        self.assertIn("REPORTS", snap["metric_groups"])

    def test_fac_scope_has_fnb_metric_groups(self) -> None:
        """Given: FACILITY_MANAGER, When: scope 생성, Then: BREAKFAST, FNB_VOC"""
        snap = build_scope_snapshot("FACILITY_MANAGER")
        self.assertEqual(snap["metric_groups"], ["BREAKFAST", "FNB_VOC"])

    def test_ext_scope_has_room_summary(self) -> None:
        """Given: EXTERNAL_REVIEWER, When: scope 생성, Then: GUEST_ROOM_SUMMARY"""
        snap = build_scope_snapshot("EXTERNAL_REVIEWER")
        self.assertEqual(snap["metric_groups"], ["GUEST_ROOM_SUMMARY"])

    def test_ops_scope_has_capabilities(self) -> None:
        """Given: OPERATIONS_MANAGER, When: scope 생성, Then: approve_report 포함"""
        snap = build_scope_snapshot("OPERATIONS_MANAGER")
        self.assertIn("approve_report", snap["capabilities"])

    def test_unknown_role_empty_scope(self) -> None:
        """Given: 미존재 역할, When: scope 생성, Then: 빈 범위"""
        snap = build_scope_snapshot("UNKNOWN")
        self.assertEqual(snap["property_ids"], [PROPERTY_ID])
        self.assertEqual(snap["metric_groups"], [])
        self.assertEqual(snap["capabilities"], [])


class ScopeAllowsMetricTest(TestCase):
    """scope_allows_metric 함수 검증."""

    def test_ops_allows_breakfast(self) -> None:
        """Given: OPERATIONS_MANAGER scope, When: BREAKFAST 확인, Then: True"""
        snap = build_scope_snapshot("OPERATIONS_MANAGER")
        self.assertTrue(scope_allows_metric(snap, "BREAKFAST"))

    def test_fac_allows_fnb_voc(self) -> None:
        """Given: FACILITY_MANAGER scope, When: FNB_VOC 확인, Then: True"""
        snap = build_scope_snapshot("FACILITY_MANAGER")
        self.assertTrue(scope_allows_metric(snap, "FNB_VOC"))

    def test_fac_not_allows_guest_room(self) -> None:
        """Given: FACILITY_MANAGER scope, When: GUEST_ROOM 확인, Then: False"""
        snap = build_scope_snapshot("FACILITY_MANAGER")
        self.assertFalse(scope_allows_metric(snap, "GUEST_ROOM"))

    def test_ext_not_allows_breakfast(self) -> None:
        """Given: EXTERNAL_REVIEWER scope, When: BREAKFAST 확인, Then: False"""
        snap = build_scope_snapshot("EXTERNAL_REVIEWER")
        self.assertFalse(scope_allows_metric(snap, "BREAKFAST"))


class ScopeAllowsCapabilityTest(TestCase):
    """scope_allows_capability 함수 검증."""

    def test_ops_allows_approve_report(self) -> None:
        """Given: OPERATIONS_MANAGER scope, When: approve_report 확인, Then: True"""
        snap = build_scope_snapshot("OPERATIONS_MANAGER")
        self.assertTrue(scope_allows_capability(snap, "approve_report"))

    def test_fac_not_allows_approve_report(self) -> None:
        """Given: FACILITY_MANAGER scope, When: approve_report 확인, Then: False"""
        snap = build_scope_snapshot("FACILITY_MANAGER")
        self.assertFalse(scope_allows_capability(snap, "approve_report"))

    def test_ext_allows_write_field_note(self) -> None:
        """Given: EXTERNAL_REVIEWER scope, When: write_field_note 확인, Then: True"""
        snap = build_scope_snapshot("EXTERNAL_REVIEWER")
        self.assertTrue(scope_allows_capability(snap, "write_field_note"))
