import json
import os
import unittest
from urllib.request import urlopen


RUNTIME_URL = os.getenv("ANSWERVICE_RUNTIME_URL")


@unittest.skipUnless(RUNTIME_URL, "set ANSWERVICE_RUNTIME_URL for live runtime checks")
class AnswerviceDemoRuntimeTest(unittest.TestCase):
    def _get(self, path: str) -> dict:
        with urlopen(f"{RUNTIME_URL}{path}", timeout=10) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def test_health_and_readiness_are_ready_without_trino_in_fake_mode(self):
        self.assertEqual(self._get("/health")["data"]["status"], "healthy")
        readiness = self._get("/readiness")["data"]

        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(
            readiness["dependencies"],
            {
                "app_postgres": "ready",
                "migration": "ready",
                "approved_templates": "ready",
                "trino": "not_required",
            },
        )
