from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
CONTRACT_VERSION = "OPENAPI-v1.0.0"


class FastApiRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]

        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(BACKEND)
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cls.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--log-level",
                "warning",
            ],
            cwd=BACKEND,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
            text=True,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                stdout, stderr = cls.server.communicate()
                raise RuntimeError(f"Uvicorn exited early.\n{stdout}\n{stderr}")
            try:
                cls.request("/health")
                return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        cls.server.terminate()
        raise RuntimeError("Uvicorn did not become ready within 15 seconds.")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)
        if cls.server.stdout is not None:
            cls.server.stdout.close()
        if cls.server.stderr is not None:
            cls.server.stderr.close()

    @classmethod
    def request(
        cls,
        path: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{cls.port}{path}",
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
            data=data,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    @staticmethod
    def context_headers() -> dict[str, str]:
        return {
            "Authorization": "Bearer runtime-test-token",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Role": "hotel_analyst",
            "X-As-Of": "2026-07-30",
            "X-Trace-Id": "runtime-test-trace",
            "X-Timezone": "Asia/Seoul",
            "X-Contract-Version": CONTRACT_VERSION,
        }

    def test_health_and_openapi_are_available(self) -> None:
        status, health = self.request("/health")
        self.assertEqual(200, status)
        self.assertEqual("healthy", health["data"]["status"])

        status, schema = self.request("/openapi.json")
        self.assertEqual(200, status)
        parameters = schema["paths"]["/analysis"]["post"]["parameters"]
        names = {parameter["name"].lower() for parameter in parameters}
        expected = {
            "authorization",
            "x-user-id",
            "x-role",
            "x-as-of",
            "x-trace-id",
            "x-timezone",
            "x-contract-version",
        }
        self.assertTrue(expected.issubset(names))

    def test_analysis_preserves_context(self) -> None:
        status, response = self.request(
            "/analysis",
            method="POST",
            headers=self.context_headers(),
            body={"question": "오늘 객실 운영 상태를 요약해줘"},
        )
        self.assertEqual(200, status)
        self.assertEqual("SUCCEEDED", response["data"]["status"])
        self.assertEqual("runtime-test-trace", response["meta"]["trace_id"])
        self.assertEqual(CONTRACT_VERSION, response["meta"]["contract_version"])

    def test_missing_context_and_invalid_role_are_blocked(self) -> None:
        status, response = self.request(
            "/analysis", method="POST", body={"question": "test"}
        )
        self.assertEqual(422, status)
        self.assertEqual("CONTEXT_INCOMPLETE", response["error"]["code"])

        headers = self.context_headers()
        headers["X-Role"] = "unknown"
        status, response = self.request(
            "/analysis",
            method="POST",
            headers=headers,
            body={"question": "test"},
        )
        self.assertEqual(403, status)
        self.assertEqual("ACCESS_DENIED", response["error"]["code"])

        headers = self.context_headers()
        headers["X-Contract-Version"] = "unsupported"
        status, response = self.request(
            "/analysis",
            method="POST",
            headers=headers,
            body={"question": "test"},
        )
        self.assertEqual(409, status)
        self.assertEqual(
            "CONTRACT_VERSION_MISMATCH",
            response["error"]["code"],
        )


if __name__ == "__main__":
    unittest.main()
