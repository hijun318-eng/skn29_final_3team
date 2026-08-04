import unittest

from src.data.i3_watermarks import changed_sources, watermark_fingerprint


class I3WatermarkTest(unittest.TestCase):
    def test_fingerprint_and_changed_sources_are_stable(self):
        values = {
            "banquet": "2026-07-28T05:00:00.000Z",
            "crm": "2026-07-28T05:00:00.000Z",
            "facility": "2026-07-27T20:57:00.000Z",
            "pms": "2026-07-28T05:00:00.000Z",
            "pos": "2026-07-27T20:59:00.000Z",
        }
        self.assertEqual(
            "0e181c3f9f70b6a90bad79c90be392e3640e3f3fe454b488b4b4b2f20c10f614",
            watermark_fingerprint(values),
        )
        changed = dict(values, pos="2026-07-27T21:00:00.000Z")
        self.assertEqual(("pos",), changed_sources(values, changed))
        self.assertEqual(("new",), changed_sources(values, dict(values, new="v1")))


if __name__ == "__main__":
    unittest.main()
