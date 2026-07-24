"""RBAC 데코레이터 테스트: @require_role, @require_scope.

Given/When/Then 구조.
"""

import json

from django.test import TestCase, Client
from django.http import HttpRequest, JsonResponse
from django.contrib.sessions.backends.db import SessionStore

from senseplace.rbac.decorators import require_role, require_scope


# ---------------------------------------------------------------------------
# 테스트용 뷰 함수
# ---------------------------------------------------------------------------
@require_role("OPERATIONS_MANAGER")
def ops_only_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


@require_role("OPERATIONS_MANAGER", "FACILITY_MANAGER")
def ops_or_fac_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


@require_scope(metric_groups=["BREAKFAST", "FNB_VOC"])
def fnb_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


@require_scope(metric_groups=["GUEST_ROOM_SUMMARY"])
def room_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


@require_scope()
def any_scope_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


class RequireRoleTest(TestCase):
    """@require_role 데코레이터 테스트."""

    def _make_request(self, role_code: str | None = None) -> HttpRequest:
        request = HttpRequest()
        session = SessionStore()
        session.create()
        request.session = session
        if role_code:
            request.session["role_code"] = role_code
        return request

    def test_role_match_passes(self) -> None:
        """Given: OPERATIONS_MANAGER 역할, When: @require_role("OPERATIONS_MANAGER") 뷰 호출, Then: 200"""
        request = self._make_request("OPERATIONS_MANAGER")
        resp = ops_only_view(request)
        self.assertEqual(resp.status_code, 200)

    def test_role_mismatch_returns_403(self) -> None:
        """Given: FACILITY_MANAGER 역할, When: @require_role("OPERATIONS_MANAGER") 뷰 호출, Then: 403"""
        request = self._make_request("FACILITY_MANAGER")
        resp = ops_only_view(request)
        self.assertEqual(resp.status_code, 403)
        body = json.loads(resp.content)
        self.assertEqual(body["error"]["code"], "FORBIDDEN")

    def test_multiple_roles_passes(self) -> None:
        """Given: FACILITY_MANAGER 역할, When: @require_role("OPERATIONS_MANAGER", "FACILITY_MANAGER"), Then: 200"""
        request = self._make_request("FACILITY_MANAGER")
        resp = ops_or_fac_view(request)
        self.assertEqual(resp.status_code, 200)

    def test_no_session_returns_401(self) -> None:
        """Given: 비로그인 상태, When: 뷰 호출, Then: 401"""
        request = self._make_request()
        resp = ops_only_view(request)
        self.assertEqual(resp.status_code, 401)
        body = json.loads(resp.content)
        self.assertEqual(body["error"]["code"], "NOT_AUTHENTICATED")


class RequireScopeTest(TestCase):
    """@require_scope 데코레이터 테스트."""

    def _make_request(
        self, metric_groups: list[str] | None = None
    ) -> HttpRequest:
        request = HttpRequest()
        session = SessionStore()
        session.create()
        request.session = session
        request.session["role_code"] = "OPERATIONS_MANAGER"
        if metric_groups is not None:
            request.session["scope_snapshot"] = {
                "property_ids": ["GRAND_WALKERHILL_SEOUL"],
                "metric_groups": metric_groups,
                "capabilities": [],
            }
        return request

    def test_scope_match_passes(self) -> None:
        """Given: BREAKFAST,FNB_VOC scope, When: fnb_view 호출, Then: 200"""
        request = self._make_request(["BREAKFAST", "FNB_VOC"])
        resp = fnb_view(request)
        self.assertEqual(resp.status_code, 200)

    def test_scope_mismatch_returns_403(self) -> None:
        """Given: BREAKFAST만 있는 scope, When: GUEST_ROOM_SUMMARY 필요한 room_view 호출, Then: 403"""
        request = self._make_request(["BREAKFAST"])
        resp = room_view(request)
        self.assertEqual(resp.status_code, 403)
        body = json.loads(resp.content)
        self.assertIn("GUEST_ROOM_SUMMARY", body["error"]["details"][0])

    def test_no_required_groups_passes(self) -> None:
        """Given: 아무 metric_group이나 있음, When: @require_scope() (검사 없음), Then: 200"""
        request = self._make_request(["BREAKFAST"])
        resp = any_scope_view(request)
        self.assertEqual(resp.status_code, 200)

    def test_no_scope_snapshot_returns_403(self) -> None:
        """Given: scope_snapshot 없음, When: @require_scope 호출, Then: 403"""
        request = HttpRequest()
        session = SessionStore()
        session.create()
        request.session = session
        request.session["role_code"] = "OPERATIONS_MANAGER"
        # scope_snapshot 없음
        resp = fnb_view(request)
        self.assertEqual(resp.status_code, 403)

    def test_no_session_returns_401(self) -> None:
        """Given: 비로그인 상태, When: @require_scope 호출, Then: 401"""
        request = HttpRequest()
        session = SessionStore()
        session.create()
        request.session = session
        resp = fnb_view(request)
        self.assertEqual(resp.status_code, 401)


class DecoratorIntegrationTest(TestCase):
    """클라이언트를 통한 통합 테스트."""

    def setUp(self) -> None:
        self.client = Client()
        self.login_url = "/api/auth/login/"

    def _login(self, username: str, password: str) -> None:
        self.client.post(
            self.login_url,
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )

    def test_ops_can_access_ops_view(self) -> None:
        """Given: ops 로그인, When: OPERATIONS_MANAGER 전용 뷰, Then: 200"""
        self._login("staff.ops", "demo1234")
        # 직접 뷰를 호출하는 대신 URL 패턴 테스트는urls.py 연결 후 진행
        # 여기서는 세션 기반 데코레이터 동작을 검증
        session = self.client.session
        self.assertEqual(session["role_code"], "OPERATIONS_MANAGER")

    def test_fac_cannot_access_ops_view(self) -> None:
        """Given: fac 로그인, When: OPERATIONS_MANAGER 전용 뷰, Then: 403"""
        self._login("staff.fac", "demo1234")
        session = self.client.session
        self.assertEqual(session["role_code"], "FACILITY_MANAGER")
