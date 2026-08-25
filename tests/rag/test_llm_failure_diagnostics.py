from __future__ import annotations

import json
import socket
import unittest
import urllib.error

from src.rag.llm_failure_diagnostics import LlmFailureDiagnostics


class LlmFailureDiagnosticsTest(unittest.TestCase):
    def test_http_failure_classification_and_retryability(self) -> None:
        unauthorized = urllib.error.HTTPError("https://llm.example", 401, "Unauthorized", {}, None)
        throttled = urllib.error.HTTPError("https://llm.example", 429, "Throttled", {}, None)
        unavailable = urllib.error.HTTPError("https://llm.example", 503, "Unavailable", {}, None)

        self.assertEqual(LlmFailureDiagnostics.from_exception(unauthorized).code, "HTTP_401")
        self.assertFalse(LlmFailureDiagnostics.from_exception(unauthorized).retryable)
        self.assertEqual(LlmFailureDiagnostics.from_exception(throttled).code, "HTTP_429")
        self.assertTrue(LlmFailureDiagnostics.from_exception(throttled).retryable)
        self.assertEqual(LlmFailureDiagnostics.from_exception(unavailable).code, "HTTP_5XX")
        self.assertTrue(LlmFailureDiagnostics.from_exception(unavailable).retryable)

    def test_network_and_schema_failures_do_not_expose_error_text(self) -> None:
        timeout = urllib.error.URLError(socket.timeout("provider-internal-detail"))
        dns = urllib.error.URLError("Temporary failure in name resolution")
        schema = json.JSONDecodeError("invalid", "{", 1)

        self.assertEqual(LlmFailureDiagnostics.from_exception(timeout).code, "CONNECT_TIMEOUT")
        self.assertEqual(LlmFailureDiagnostics.from_exception(dns).code, "DNS_ERROR")
        self.assertEqual(LlmFailureDiagnostics.from_exception(schema).code, "INVALID_LLM_JSON")


if __name__ == "__main__":
    unittest.main()
