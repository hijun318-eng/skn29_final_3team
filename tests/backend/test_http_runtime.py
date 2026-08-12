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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
        environment["PYTHONPATH"] = os.pathsep.join([str(BACKEND), str(ROOT)])
        environment.pop("APP_RUNTIME_DATABASE_URL", None)
        environment["AUTH_MODE"] = "test"
        environment["DATA_PLATFORM_MODE"] = "versioned-trino"
        environment["MODEL_MODE"] = "template-only"
        environment["CORS_ALLOW_ORIGINS"] = (
            "http://localhost:5173,http://localhost:13000,"
            "http://192.168.0.15:13000"
        )
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
    def context_headers(role: str = "hotel_analyst") -> dict[str, str]:
        tokens = {
            "hotel_analyst": "runtime-test-token",
            "report_admin": "runtime-report-admin-token",
            "data_admin": "runtime-data-admin-token",
        }
        return {
            "Authorization": f"Bearer {tokens[role]}",
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
            "x-as-of",
            "x-trace-id",
            "x-timezone",
            "x-contract-version",
        }
        self.assertTrue(expected.issubset(names))
        self.assertNotIn("authorization", names)
        self.assertNotIn("x-user-id", names)
        self.assertNotIn("x-role", names)
        self.assertEqual({"BearerAuth": []}, schema["paths"]["/analysis"]["post"]["security"][0])
        self.assertEqual("http", schema["components"]["securitySchemes"]["BearerAuth"]["type"])

    def test_analysis_and_report_preflight_use_exact_origins(self) -> None:
        for path in ("/analysis", "/reports/definitions"):
            with self.subTest(path=path, origin="allowed"):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    method="OPTIONS",
                    headers={
                        "Origin": "http://192.168.0.15:13000",
                        "Access-Control-Request-Method": "POST",
                    },
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(200, response.status)
                    self.assertEqual(
                        "http://192.168.0.15:13000",
                        response.headers["Access-Control-Allow-Origin"],
                    )

            with self.subTest(path=path, origin="denied"):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    method="OPTIONS",
                    headers={
                        "Origin": "http://untrusted.example",
                        "Access-Control-Request-Method": "POST",
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(400, error.exception.code)
                self.assertIsNone(
                    error.exception.headers.get("Access-Control-Allow-Origin")
                )

    def test_browser_preflight_allows_only_configured_origin(self) -> None:
        requested_headers = {
            "authorization", "content-type", "x-as-of", "x-contract-version",
            "x-role", "x-timezone", "x-trace-id", "x-user-id",
        }
        for path, method in (
            ("/analysis", "POST"),
            ("/reports/definitions/report-1/versions/1/blocks", "PUT"),
        ):
            with self.subTest(method=method):
                allowed_request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    method="OPTIONS",
                    headers={
                        "Origin": "http://localhost:5173",
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers": ",".join(requested_headers),
                    },
                )
                with urllib.request.urlopen(allowed_request, timeout=5) as response:
                    self.assertEqual(
                        "http://localhost:5173",
                        response.headers["Access-Control-Allow-Origin"],
                    )
                    self.assertEqual("true", response.headers["Access-Control-Allow-Credentials"])
                    allowed_methods = {
                        item.strip() for item in response.headers["Access-Control-Allow-Methods"].split(",")
                    }
                    self.assertEqual({"GET", "POST", "PUT", "OPTIONS"}, allowed_methods)
                    allowed_headers = {
                        item.strip().lower()
                        for item in response.headers["Access-Control-Allow-Headers"].split(",")
                    }
                    self.assertTrue(requested_headers.issubset(allowed_headers))
                    self.assertNotIn("*", allowed_headers | allowed_methods)

        denied_request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/reports/definitions/report-1/versions/1/blocks",
            method="OPTIONS",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "PUT",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(denied_request, timeout=5)
        self.assertEqual(400, denied.exception.code)
        self.assertIsNone(
            denied.exception.headers.get("Access-Control-Allow-Origin")
        )

    def test_missing_context_and_invalid_role_are_blocked(self) -> None:
        headers = self.context_headers()
        headers.pop("Authorization")
        status, response = self.request("/analysis", method="POST", headers=headers, body={"question": "test"})
        self.assertEqual(401, status)
        self.assertEqual("ACCESS_DENIED", response["error"]["code"])

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

    def test_analysis_and_report_share_server_owned_principal(self) -> None:
        headers = self.context_headers("report_admin")
        status, response = self.request("/reports/definitions", headers=headers)
        self.assertEqual(503, status)
        self.assertIn("저장소", response["detail"])

        status, response = self.request(
            "/reports/definitions", headers=self.context_headers("hotel_analyst")
        )
        self.assertEqual(503, status)
        self.assertIn("저장소", response["detail"])

        headers["X-User-Id"] = "00000000-0000-0000-0000-000000000001"
        status, response = self.request("/reports/definitions", headers=headers)
        self.assertEqual(403, status)
        self.assertEqual("ACCESS_DENIED", response["error"]["code"])


class BackendComposeContractTest(unittest.TestCase):
    def test_backend_bind_defaults_to_loopback_and_allows_explicit_override(self) -> None:
        compose = (BACKEND / "compose.fragment.yml").read_text(encoding="utf-8")
        self.assertIn(
            '"${BACKEND_BIND_ADDRESS:-127.0.0.1}:18000:8000"', compose
        )
        self.assertNotIn('- "0.0.0.0:18000:8000"', compose)
        self.assertNotIn("CORS_ALLOW_ORIGINS: *", compose)


class _TrinoHandler(BaseHTTPRequestHandler):
    query_count = 0

    def do_POST(self) -> None:
        type(self).query_count += 1
        partial = type(self).query_count > 1
        body = {
            "id": "real-query-partial" if partial else "real-query-positive",
            "stats": {"state": "FINISHED"},
            "columns": [
                {"name": "month"},
                {"name": "recognized_room_revenue_krw"},
            ],
            "data": [["2026-06", "125000.00"]],
        }
        if partial:
            body["warnings"] = [{"message": "synthetic partial source"}]
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *args: object) -> None:
        return


@unittest.skipUnless(
    os.getenv("R4_REAL_HTTP_TEST") == "1",
    "R4 real HTTP verification is executed separately with a temporary DB",
)
class RealTemplateHttpRuntimeTest(FastApiRuntimeTest):
    @classmethod
    def setUpClass(cls) -> None:
        if not os.getenv("APP_RUNTIME_DATABASE_URL"):
            raise RuntimeError("APP_RUNTIME_DATABASE_URL is required")
        _TrinoHandler.query_count = 0
        cls.trino = ThreadingHTTPServer(("127.0.0.1", 0), _TrinoHandler)
        import threading

        cls.trino_thread = threading.Thread(
            target=cls.trino.serve_forever,
            daemon=True,
        )
        cls.trino_thread.start()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]

        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": os.pathsep.join([str(BACKEND), str(ROOT)]),
                "DATA_PLATFORM_MODE": "real",
                "MODEL_MODE": "template-only",
                "TRINO_URL": f"http://127.0.0.1:{cls.trino.server_port}",
                "TRINO_USER": "synthetic-runtime",
                "CORS_ALLOW_ORIGINS": "http://localhost:5173",
            }
        )
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
        super().tearDownClass()
        cls.trino.shutdown()
        cls.trino.server_close()
        cls.trino_thread.join(timeout=5)

    def test_real_template_positive_role_partial_and_cors(self) -> None:
        body = {
            "question": "지난달 객실 매출을 요약해줘",
            "template_id": "weekly-room-operations",
            "parameters": {
                "period_start": "2026-05-01",
                "period_end_exclusive": "2026-07-01",
            },
        }
        status, positive = self.request(
            "/analysis",
            method="POST",
            headers=self.context_headers(),
            body=body,
        )

        self.assertEqual(200, status)
        self.assertEqual("SUCCEEDED", positive["data"]["status"])
        stages = [step["stage"] for step in positive["data"]["trace"]]
        self.assertLess(stages.index("G1"), stages.index("G2"))
        self.assertLess(stages.index("G2"), stages.index("QUERY"))
        self.assertLess(stages.index("QUERY"), stages.index("G3"))
        self.assertEqual("real-query-positive", positive["data"]["artifact"]["query_id"])
        self.assertIsNotNone(positive["data"]["artifact"]["artifact_id"])

        query_count = _TrinoHandler.query_count
        for role in ("report_admin", "data_admin"):
            headers = self.context_headers(role)
            status, denied = self.request(
                "/analysis",
                method="POST",
                headers=headers,
                body=body,
            )
            self.assertEqual(403, status)
            self.assertEqual("ACCESS_DENIED", denied["error"]["code"])
        self.assertEqual(query_count, _TrinoHandler.query_count)

        partial_body = {
            **body,
            "parameters": {
                "period_start": "2026-06-01",
                "period_end_exclusive": "2026-07-01",
            },
        }
        status, partial = self.request(
            "/analysis",
            method="POST",
            headers=self.context_headers(),
            body=partial_body,
        )
        self.assertEqual(200, status)
        self.assertEqual("PARTIAL", partial["data"]["status"])
        self.assertEqual("PARTIAL_FAILURE", partial["error"]["code"])
        self.assertEqual(
            "real-query-partial",
            partial["data"]["artifact"]["query_id"],
        )

        allowed = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/analysis",
            method="OPTIONS",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        with urllib.request.urlopen(allowed, timeout=5) as response:
            self.assertEqual(
                "http://localhost:5173",
                response.headers["Access-Control-Allow-Origin"],
            )


if __name__ == "__main__":
    unittest.main()
