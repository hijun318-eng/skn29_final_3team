"""명시적으로 제공된 실제 Answervice URL의 배포 준비 상태를 확인한다.

Mock이나 로컬 fixture를 사용하지 않으며 ``ANSWERVICE_RUNTIME_URL``이 없으면 skip한다.
모든 공개 dependency가 ready여야 통과하지만 분석 E2E 성공까지 의미하지는 않는다.
"""

import os
import unittest

import httpx


RUNTIME_URL = os.getenv("ANSWERVICE_RUNTIME_URL")


def _readiness_timeout_seconds() -> float:
    """배포 release read-back용 opt-in timeout을 안전한 범위로 해석한다."""

    try:
        configured = float(
            os.getenv("ANSWERVICE_RUNTIME_READINESS_TIMEOUT_SECONDS", "65")
        )
    except ValueError:
        return 65.0
    return min(125.0, max(1.0, configured))


@unittest.skipUnless(RUNTIME_URL, "set ANSWERVICE_RUNTIME_URL for live runtime checks")
class AnswerviceRuntimeHealthTest(unittest.TestCase):
    """외부에서 기동한 런타임의 상태 응답 계약을 읽기 전용으로 검사한다."""

    def _get(self, path: str) -> dict:
        """상태 endpoint를 bounded timeout으로 조회하고 JSON payload를 반환한다."""

        timeout = _readiness_timeout_seconds() if path == "/readiness" else 10.0
        response = httpx.get(f"{RUNTIME_URL}{path}", timeout=timeout)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_health_and_readiness_return_typed_dependency_state(self):
        """실제 배포가 건강하고 dependency 상태를 숨기지 않는지 확인한다."""

        self.assertEqual(self._get("/health")["data"]["status"], "healthy")
        readiness = self._get("/readiness")["data"]

        self.assertEqual(readiness["status"], "ready")
        self.assertIsInstance(readiness["dependencies"], dict)
        self.assertTrue(readiness["dependencies"])
        for name, state in readiness["dependencies"].items():
            with self.subTest(dependency=name):
                self.assertIsInstance(name, str)
                self.assertIsInstance(state, str)
                self.assertTrue(name)
                self.assertEqual(state, "ready")
