import unittest

from src.data.i2_adapters import (
    AdapterError,
    AdapterErrorCode,
    DataHubAdapter,
    TrinoAdapter,
)


class I2AdapterTest(unittest.TestCase):
    def test_datahub_search_paginates_and_distinguishes_empty(self):
        def transport(method, url, body):
            self.assertEqual("GET", method)
            return {
                "value": {
                    "numEntities": 2,
                    "entities": [
                        {
                            "entity": "urn:li:dataset:(urn:li:dataPlatform:postgres,pms.public.pms_stays,PROD)",
                            "matchedFields": [{"value": "pms.public.pms_stays"}],
                        }
                    ],
                }
            }

        page = DataHubAdapter("http://datahub", transport).search("pms", limit=1)
        self.assertEqual("pms.public.pms_stays", page.items[0].fqn)
        self.assertEqual(1, page.next_offset)

        with self.assertRaisesRegex(AdapterError, "no matching dataset") as raised:
            DataHubAdapter("http://datahub", lambda *_: {"value": {"entities": []}}).search("none")
        self.assertEqual(AdapterErrorCode.NOT_FOUND, raised.exception.code)

    def test_trino_query_lifecycle_and_failures_are_typed(self):
        responses = iter(
            [
                {"id": "q1", "stats": {"state": "RUNNING"}, "nextUri": "next"},
                {
                    "id": "q1",
                    "stats": {"state": "FINISHED"},
                    "columns": [{"name": "month"}, {"name": "revenue"}],
                    "data": [["2026-06", "180813600.00"]],
                },
            ]
        )
        calls = []

        def transport(method, url, body):
            calls.append((method, url, body))
            return {} if method == "DELETE" else next(responses)

        adapter = TrinoAdapter("http://trino", transport)
        first = adapter.execute("SELECT 1")
        final = adapter.next_page(first.next_uri)
        adapter.cancel("next")
        self.assertEqual("FINISHED", final.state)
        self.assertEqual((("2026-06", "180813600.00"),), final.rows)
        self.assertEqual("DELETE", calls[-1][0])

        with self.assertRaises(AdapterError) as raised:
            TrinoAdapter(
                "http://trino",
                lambda *_: {"id": "q2", "stats": {"state": "CANCELED"}},
            ).execute("SELECT 1")
        self.assertEqual(AdapterErrorCode.CANCELLED, raised.exception.code)

        with self.assertRaises(AdapterError) as raised:
            TrinoAdapter(
                "http://trino",
                lambda *_: {
                    "id": "q3",
                    "stats": {"state": "FINISHED"},
                    "warnings": [{"message": "source partial"}],
                },
            ).execute("SELECT 1")
        self.assertEqual(AdapterErrorCode.PARTIAL, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
