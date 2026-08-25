from __future__ import annotations

import sys
import unittest
from pathlib import Path


ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR))

from local_console import LocalToolConsole  # noqa: E402


class LocalConsoleValidationTest(unittest.TestCase):
    def test_required_text_rejects_missing_and_oversized_input(self) -> None:
        with self.assertRaises(ValueError):
            LocalToolConsole._required_text({}, "query", 2, 5)
        with self.assertRaises(ValueError):
            LocalToolConsole._required_text({"query": "123456"}, "query", 2, 5)
        self.assertEqual(
            LocalToolConsole._required_text({"query": " 질문 "}, "query", 2, 5),
            "질문",
        )

    def test_manual_search_returns_openable_real_pdf(self) -> None:
        console = LocalToolConsole.__new__(LocalToolConsole)
        result = console.search_manuals("SOP-ROOM-003")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["documents"][0]["manual_id"], "SOP-ROOM-003")
        self.assertTrue(console.manual_pdf("SOP-ROOM-003").is_file())
        with self.assertRaises(LookupError):
            console.manual_pdf("../SOP-ROOM-003")


if __name__ == "__main__":
    unittest.main()
