import unittest

from src.ai.training.benchmark_serving import benchmark, percentile


class ServingBenchmarkTests(unittest.TestCase):
    def test_fixed_endpoint_contract_and_concurrency(self):
        calls = []

        def requester(method, url, payload, token, timeout):
            calls.append((method, url, token))
            if url.endswith("/v1/models"):
                return {"data": [{"id": "answervice-sql-lora-qwen3.5-4b"}]}
            return {
                "id": "completion-1",
                "choices": [{"message": {"role": "assistant", "content": "READY"}}],
            }

        result = benchmark(
            base_url="https://model.example/",
            model="answervice-sql-lora-qwen3.5-4b",
            model_revision="fixed-revision",
            warm_requests=3,
            token="not-recorded",
            requester=requester,
            peak_vram_bytes=123,
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(2, result["concurrency"]["completed"])
        self.assertEqual(123, result["peak_vram_bytes"])
        self.assertIsNone(result["observed"]["accuracy"])
        self.assertEqual(123, result["observed"]["peak_vram_bytes"])
        self.assertIsNone(result["observed"]["cost_usd"])
        self.assertEqual(64, len(result["response_evidence_sha256"]))
        self.assertNotIn("not-recorded", str(result))
        self.assertEqual(7, len(calls))

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(3, percentile([3, 1, 2], 95))
        with self.assertRaises(ValueError):
            percentile([], 50)


if __name__ == "__main__":
    unittest.main()
