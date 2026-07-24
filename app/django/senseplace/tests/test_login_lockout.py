"""로그인 실패 잠금 테스트.

Given/When/Then 구조.
"""

import json

from django.test import TestCase, Client
from django.core.cache import cache

from senseplace.auth.login_lockout import (
    check_locked,
    record_failure,
    clear_failures,
    get_failure_count,
)


class LoginLockoutUnitTest(TestCase):
    """login_lockout 모듈 단위 테스트."""

    def setUp(self) -> None:
        cache.clear()

    def test_record_failure_increments_count(self) -> None:
        """Given: 새로운 IP, When: 실패 기록, Then: 카운트 1"""
        count = record_failure("10.0.0.1")
        self.assertEqual(count, 1)

    def test_record_failure_accumulates(self) -> None:
        """Given: 3회 실패 기록된 IP, When: 1회 더 실패, Then: 카운트 4"""
        for _ in range(3):
            record_failure("10.0.0.2")
        count = record_failure("10.0.0.2")
        self.assertEqual(count, 4)

    def test_lockout_at_5_failures(self) -> None:
        """Given: 4회 실패 기록, When: 5회 실패, Then: 잠금 활성화"""
        for _ in range(4):
            record_failure("10.0.0.3")
        self.assertFalse(check_locked("10.0.0.3"))
        record_failure("10.0.0.3")
        self.assertTrue(check_locked("10.0.0.3"))

    def test_clear_failures_resets(self) -> None:
        """Given: 5회 실패 (잠금), When: clear_failures, Then: 잠금 해제"""
        for _ in range(5):
            record_failure("10.0.0.4")
        self.assertTrue(check_locked("10.0.0.4"))
        clear_failures("10.0.0.4")
        self.assertFalse(check_locked("10.0.0.4"))
        self.assertEqual(get_failure_count("10.0.0.4"), 0)

    def test_different_ips_independent(self) -> None:
        """Given: IP-A 5회 실패, When: IP-B 실패 확인, Then: 독립적"""
        for _ in range(5):
            record_failure("10.0.0.5")
        self.assertTrue(check_locked("10.0.0.5"))
        self.assertFalse(check_locked("10.0.0.6"))


class LoginLockoutIntegrationTest(TestCase):
    """로그인 뷰와 잠금 통합 테스트."""

    def setUp(self) -> None:
        self.client = Client()
        self.url = "/api/auth/login/"
        cache.clear()

    def _attempt_login(self) -> int:
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "staff.ops", "password": "wrong"}),
            content_type="application/json",
        )
        return resp.status_code

    def test_lockout_after_5_failures(self) -> None:
        """Given: 5회 실패 로그인 시도, When: 6회 시도, Then: 423 Locked"""
        for _ in range(5):
            status = self._attempt_login()
            self.assertEqual(status, 401)

        # 6번째 시도는 잠금
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "staff.ops", "password": "demo1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(resp.json()["error"]["code"], "LOCKED")

    def test_successful_login_clears_failures(self) -> None:
        """Given: 4회 실패, When: 성공적 로그인, Then: 카운트 초기화"""
        for _ in range(4):
            self._attempt_login()

        # 성공적 로그인
        resp = self.client.post(
            self.url,
            data=json.dumps({"username": "staff.ops", "password": "demo1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        # 다시 4회 실패해도 잠금 안 됨
        for _ in range(4):
            status = self._attempt_login()
            self.assertEqual(status, 401)
