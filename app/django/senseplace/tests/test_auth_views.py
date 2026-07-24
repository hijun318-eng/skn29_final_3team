"""auth 뷰 테스트: 로그인/로그아웃/me.

Given/When/Then 구조.
"""

import json

from django.test import TestCase, Client


class LoginViewTest(TestCase):
    """POST /api/auth/login/ 테스트."""

    def setUp(self) -> None:
        self.client = Client()
        self.url = "/api/auth/login/"

    # --- 성공 케이스 ---

    def test_login_success_ops(self) -> None:
        """Given: staff.ops 자격증명, When: 로그인, Then: 200 + role_code=OPERATIONS_MANAGER"""
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "staff.ops", "password": "demo1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["role_code"], "OPERATIONS_MANAGER")
        self.assertEqual(data["username"], "staff.ops")
        self.assertIn("scope_snapshot", data)
        self.assertIn("BREAKFAST", data["scope_snapshot"]["metric_groups"])

    def test_login_success_fac(self) -> None:
        """Given: staff.fac 자격증명, When: 로그인, Then: 200 + role_code=FACILITY_MANAGER"""
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "staff.fac", "password": "demo1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["role_code"], "FACILITY_MANAGER")

    def test_login_success_ext_review(self) -> None:
        """Given: ext.review 자격증명, When: 로그인, Then: 200 + role_code=EXTERNAL_REVIEWER"""
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "ext.review", "password": "demo1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["role_code"], "EXTERNAL_REVIEWER")

    # --- 실패 케이스 ---

    def test_login_wrong_password(self) -> None:
        """Given: 잘못된 비밀번호, When: 로그인, Then: 401"""
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "staff.ops", "password": "wrong"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "AUTH_FAILED")

    def test_login_unknown_user(self) -> None:
        """Given: 존재하지 않는 사용자, When: 로그인, Then: 401"""
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "unknown", "password": "demo1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_login_missing_fields(self) -> None:
        """Given: 빈 요청, When: 로그인, Then: 400"""
        resp = self.client.post(
            self.url,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_login_empty_body(self) -> None:
        """Given: 잘못된 JSON, When: 로그인, Then: 400"""
        resp = self.client.post(
            self.url,
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class LogoutViewTest(TestCase):
    """POST /api/auth/logout/ 테스트."""

    def setUp(self) -> None:
        self.client = Client()
        self.login_url = "/api/auth/login/"
        self.logout_url = "/api/auth/logout/"

    def test_logout_success(self) -> None:
        """Given: 로그인 상태, When: 로그아웃, Then: 200 + 세션 만료"""
        # 로그인
        self.client.post(
            self.login_url,
            data=json.dumps({"username": "staff.ops", "password": "demo1234"}),
            content_type="application/json",
        )
        # 로그아웃
        resp = self.client.post(self.logout_url)
        self.assertEqual(resp.status_code, 200)

        # 세션 만료 확인
        me_resp = self.client.get("/api/auth/me/")
        self.assertEqual(me_resp.status_code, 401)

    def test_logout_without_login(self) -> None:
        """Given: 비로그인 상태, When: 로그아웃, Then: 200 (멱등)"""
        resp = self.client.post(self.logout_url)
        self.assertEqual(resp.status_code, 200)


class MeViewTest(TestCase):
    """GET /api/auth/me/ 테스트."""

    def setUp(self) -> None:
        self.client = Client()
        self.login_url = "/api/auth/login/"
        self.me_url = "/api/auth/me/"

    def test_me_authenticated(self) -> None:
        """Given: 로그인 상태, When: me 조회, Then: 200 + 사용자 정보"""
        self.client.post(
            self.login_url,
            data=json.dumps({"username": "staff.ops", "password": "demo1234"}),
            content_type="application/json",
        )
        resp = self.client.get(self.me_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["role_code"], "OPERATIONS_MANAGER")
        self.assertIsNotNone(data["scope_snapshot"])

    def test_me_unauthenticated(self) -> None:
        """Given: 비로그인 상태, When: me 조회, Then: 401"""
        resp = self.client.get(self.me_url)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "NOT_AUTHENTICATED")
