"""명시적으로 제공된 실제 Answervice URL의 상태 endpoint를 확인한다.

Mock이나 로컬 fixture를 사용하지 않으며 ``ANSWERVICE_RUNTIME_URL``이 없으면 skip한다.
통과 결과는 health/readiness HTTP 경계만 증명하고 분석 E2E 성공을 의미하지 않는다.
"""

import os
import unittest

import httpx


RUNTIME_URL = os.getenv("ANSWERVICE_RUNTIME_URL")


@unittest.skipUnless(RUNTIME_URL, "set ANSWERVICE_RUNTIME_URL for live runtime checks")
class AnswerviceRuntimeHealthTest(unittest.TestCase):
    """외부에서 기동한 런타임의 상태 응답 계약을 읽기 전용으로 검사한다."""

    def _get(self, path: str) -> dict:
        """상태 endpoint를 bounded timeout으로 조회하고 JSON payload를 반환한다."""

        response = httpx.get(f"{RUNTIME_URL}{path}", timeout=10.0)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_health_and_readiness_return_typed_dependency_state(self):
        """실제 배포가 건강하고 dependency 상태를 숨기지 않는지 확인한다."""

        self.assertEqual(self._get("/health")["data"]["status"], "healthy")
        readiness = self._get("/readiness")["data"]

        self.assertIn(readiness["status"], {"ready", "not_ready"})
        self.assertIsInstance(readiness["dependencies"], dict)
        self.assertTrue(readiness["dependencies"])
        for name, state in readiness["dependencies"].items():
            with self.subTest(dependency=name):
                self.assertIsInstance(name, str)
                self.assertIsInstance(state, str)
                self.assertTrue(name)
                self.assertTrue(state)
