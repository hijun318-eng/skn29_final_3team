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
from concurrent.futures import ThreadPoolExecutor
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
                "tests.support.runtime_app:app",
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

    def test_readiness_is_503_with_typed_dependency_evidence_when_not_ready(self) -> None:
        status, response = self.request("/readiness")

        self.assertEqual(503, status)
        self.assertEqual("not_ready", response["data"]["status"])
        self.assertEqual("DEPENDENCY_UNAVAILABLE", response["error"]["code"])
        self.assertEqual("RETRY", response["error"]["required_action"])
        self.assertTrue(response["error"]["retryable"])
        self.assertTrue(response["error"]["missing_requirements"])
        self.assertEqual(response["meta"]["trace_id"], response["error"]["trace_id"])
        self.assertNotIn("detail", response)

    def test_framework_404_and_405_use_the_public_error_envelope(self) -> None:
        for method, path, expected_status, expected_code in (
            ("GET", "/does-not-exist", 404, "RESOURCE_NOT_FOUND"),
            ("POST", "/health", 405, "RESOURCE_CONFLICT"),
        ):
            with self.subTest(method=method):
                status, response = self.request(path, method=method)
                self.assertEqual(expected_status, status)
                self.assertEqual(expected_code, response["error"]["code"])
                self.assertEqual(
                    response["meta"]["trace_id"],
                    response["error"]["trace_id"],
                )
                self.assertNotIn("detail", response)

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

    def test_session_validation_rejects_invalid_token_before_app_entry(self) -> None:
        status, anonymous = self.request("/auth/session")
        self.assertEqual(200, status)
        self.assertEqual("anonymous", anonymous["data"]["status"])
        self.assertIsNone(anonymous["data"]["role"])

        status, denied = self.request(
            "/auth/session",
            headers={"Authorization": "Bearer invalid-e2e-token"},
        )
        self.assertEqual(401, status)
        self.assertEqual("AUTHENTICATION_REQUIRED", denied["error"]["code"])

        status, accepted = self.request(
            "/auth/session",
            headers={"Authorization": "Bearer runtime-test-token"},
        )
        self.assertEqual(200, status)
        self.assertEqual("authenticated", accepted["data"]["status"])
        self.assertEqual("hotel_analyst", accepted["data"]["role"])

    def test_invalid_period_is_rejected_at_the_http_contract(self) -> None:
        status, response = self.request(
            "/analysis",
            method="POST",
            headers=self.context_headers(),
            body={
                "question": "GOLD 고객의 통합 매출",
                "parameters": {
                    "period_start": "2026-07-01",
                    "period_end_exclusive": "2026-05-01",
                },
            },
        )
        self.assertEqual(422, status)
        self.assertEqual("CONTEXT_INCOMPLETE", response["error"]["code"])

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

    def test_analysis_progress_is_owner_scoped_and_terminal_cancel_is_rejected(self) -> None:
        headers = self.context_headers()
        headers["X-Trace-Id"] = "runtime-progress-trace"
        status, response = self.request(
            "/analysis",
            method="POST",
            headers=headers,
            body={"question": "오늘 객실 운영 상태를 요약해줘"},
        )
        self.assertEqual(200, status)

        status, progress = self.request(
            "/analysis/progress/runtime-progress-trace",
            headers=headers,
        )
        self.assertEqual(200, status)
        self.assertEqual(response["meta"]["request_id"], progress["data"]["request_id"])
        self.assertEqual(response["data"]["status"], progress["data"]["status"])
        self.assertGreater(len(progress["data"]["trace"]), 0)

        status, by_request = self.request(
            f"/analysis/requests/{response['meta']['request_id']}/progress",
            headers=headers,
        )
        self.assertEqual(200, status)
        self.assertEqual(progress["data"], by_request["data"])

        status, _ = self.request(
            "/analysis/progress/runtime-progress-trace",
            headers=self.context_headers("report_admin"),
        )
        self.assertEqual(404, status)

        status, _ = self.request(
            "/analysis/progress/runtime-progress-trace/cancel",
            method="POST",
            headers=headers,
        )
        self.assertEqual(409, status)

    def test_same_trace_keeps_distinct_request_progress_and_artifacts(self) -> None:
        headers = self.context_headers()
        headers["X-Trace-Id"] = "shared-runtime-correlation"
        responses = []
        for question in ("first request", "second request"):
            status, response = self.request(
                "/analysis",
                method="POST",
                headers=headers,
                body={"question": question},
            )
            self.assertEqual(200, status)
            responses.append(response)

        request_ids = [item["meta"]["request_id"] for item in responses]
        artifact_ids = [item["data"]["artifact"]["artifact_id"] for item in responses]
        self.assertEqual(2, len(set(request_ids)))
        self.assertEqual(2, len(set(artifact_ids)))

        status, ambiguous = self.request(
            "/analysis/progress/shared-runtime-correlation",
            headers=headers,
        )
        self.assertEqual(409, status)
        self.assertEqual("RESOURCE_CONFLICT", ambiguous["error"]["code"])

        for request_id in request_ids:
            status, progress = self.request(
                f"/analysis/requests/{request_id}/progress",
                headers=headers,
            )
            self.assertEqual(200, status)
            self.assertEqual(request_id, progress["data"]["request_id"])

    def test_analysis_exposes_repair_trace_and_blocks_g3_artifact(self) -> None:
        status, repaired = self.request(
            "/analysis",
            method="POST",
            headers=self.context_headers(),
            body={
                "question": "합성 객실 운영 현황",
                "parameters": {"scenario": "repair_once"},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual(1, repaired["data"]["repair_count"])
        self.assertIn(
            "REPAIR",
            [step["stage"] for step in repaired["data"]["trace"]],
        )
        self.assertIsNotNone(repaired["data"]["artifact"])

        status, failed = self.request(
            "/analysis",
            method="POST",
            headers=self.context_headers(),
            body={
                "question": "합성 객실 운영 현황",
                "parameters": {"scenario": "g3_failed"},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("FAILED", failed["data"]["status"])
        self.assertIsNone(failed["data"]["artifact"])
        self.assertEqual(
            "RESULT_EVIDENCE_MISSING",
            failed["error"]["code"],
        )

    def test_third_concurrent_analysis_receives_real_http_429(self) -> None:
        def submit(index: int):
            headers = self.context_headers()
            headers["X-Trace-Id"] = f"rate-limit-{index}"
            return self.request(
                "/analysis",
                method="POST",
                headers=headers,
                body={
                    "question": f"slow room demand {index}",
                    "parameters": {"scenario": "slow"},
                },
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(submit, range(3)))

        statuses = sorted(status for status, _body in results)
        self.assertEqual([200, 200, 429], statuses)
        limited = next(body for status, body in results if status == 429)
        self.assertEqual("RATE_LIMITED", limited["error"]["code"])

    def test_missing_context_and_invalid_role_are_blocked(self) -> None:
        headers = self.context_headers()
        headers.pop("Authorization")
        status, response = self.request("/analysis", method="POST", headers=headers, body={"question": "test"})
        self.assertEqual(401, status)
        self.assertEqual("AUTHENTICATION_REQUIRED", response["error"]["code"])

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

        headers = self.context_headers()
        headers["X-Trace-Id"] = "invalid trace with spaces"
        status, response = self.request(
            "/analysis",
            method="POST",
            headers=headers,
            body={"question": "test"},
        )
        self.assertEqual(422, status)
        self.assertEqual("CONTEXT_INCOMPLETE", response["error"]["code"])
        self.assertNotEqual("invalid trace with spaces", response["meta"]["trace_id"])

    def test_non_analyst_role_is_rejected_before_question_routing(self) -> None:
        for role in ("report_admin", "data_admin"):
            with self.subTest(role=role):
                status, response = self.request(
                    "/analysis",
                    method="POST",
                    headers=self.context_headers(role),
                    body={"question": "권한 경계 검증"},
                )
                self.assertEqual(403, status)
                self.assertEqual("ACCESS_DENIED", response["error"]["code"])

    def test_analysis_and_report_share_server_owned_principal(self) -> None:
        headers = self.context_headers("report_admin")
        status, response = self.request("/reports/definitions", headers=headers)
        self.assertEqual(503, status)
        self.assertEqual("DEPENDENCY_UNAVAILABLE", response["error"]["code"])
        self.assertEqual("RETRY", response["error"]["required_action"])
        self.assertNotIn("detail", response)

        status, response = self.request(
            "/reports/definitions", headers=self.context_headers("hotel_analyst")
        )
        self.assertEqual(503, status)
        self.assertEqual("DEPENDENCY_UNAVAILABLE", response["error"]["code"])
        self.assertEqual(response["meta"]["trace_id"], response["error"]["trace_id"])
        self.assertNotIn("detail", response)

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
                "AUTH_MODE": "test",
                "TEST_REAL_DATA_PLATFORM": "1",
                "TRINO_URL": f"http://127.0.0.1:{cls.trino.server_port}",
                "TRINO_USER": "synthetic-runtime",
                "CORS_ALLOW_ORIGINS": (
                    "http://localhost:5173,http://localhost:13000,"
                    "http://192.168.0.15:13000"
                ),
            }
        )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cls.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.support.runtime_app:app",
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
            "question": "recognized room revenue summary",
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
