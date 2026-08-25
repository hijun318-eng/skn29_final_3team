from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from no_show_ml.config import ProjectConfig
from no_show_ml.dataset import ReservationDatasetBuilder


class SourceLabelDatasetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.source_dir = root / "source"
        self.source_dir.mkdir()
        self.config = ProjectConfig(
            project_dir=root,
            repo_dir=root,
            source_dir=self.source_dir,
            raw_dir=root / "raw",
            artifacts_dir=root / "artifacts",
            model_dir=root / "artifacts" / "models",
            source_snapshot_id="test-snapshot-001",
            source_extracted_at="2026-08-10T00:00:00Z",
        )
        pd.DataFrame([{"guest_id": "G-1", "country_group": "KR"}]).to_csv(
            self.config.guest_csv, index=False
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_uses_confirmed_pms_no_show_outcome(self) -> None:
        rows = [
            self._reservation("R-TRAIN-P", "2024-06-01", "NO_SHOW"),
            self._reservation("R-TRAIN-N", "2024-06-02", "CHECKED_OUT"),
            self._reservation("R-VALID-P", "2025-06-01", "NO_SHOW"),
            self._reservation("R-VALID-N", "2025-06-02", "CHECKED_IN"),
            self._reservation("R-TEST-P", "2026-06-01", "NO_SHOW"),
            self._reservation("R-TEST-N", "2026-06-02", "COMPLETED"),
            self._reservation("R-FUTURE", "2026-09-01", "BOOKED", True),
        ]
        pd.DataFrame(rows).to_csv(self.config.reservation_csv, index=False)

        bundle = ReservationDatasetBuilder(self.config).build()

        self.assertEqual(bundle.profile["source_no_show_rows"], 3)
        self.assertEqual(bundle.train["is_no_show"].tolist(), [1, 0])
        self.assertEqual(
            set(bundle.train["label_source"]), {"PMS_RESERVATION_STATUS_V1"}
        )

    def test_blocks_training_when_source_has_no_no_show(self) -> None:
        pd.DataFrame(
            [self._reservation("R-TRAIN-N", "2024-06-02", "CHECKED_OUT")]
        ).to_csv(self.config.reservation_csv, index=False)

        with self.assertRaisesRegex(ValueError, "zero NO_SHOW"):
            ReservationDatasetBuilder(self.config).build()

    def test_blocks_training_without_source_lineage(self) -> None:
        config = replace(self.config, source_snapshot_id=None)
        with self.assertRaisesRegex(ValueError, "source lineage"):
            ReservationDatasetBuilder(config).build()

    @staticmethod
    def _reservation(
        reservation_id: str,
        checkin_date: str,
        status: str,
        is_forecast: bool = False,
    ) -> dict:
        checkin = pd.Timestamp(checkin_date)
        return {
            "reservation_id": reservation_id,
            "guest_id": "G-1",
            "checkin_date": checkin.date().isoformat(),
            "checkout_date": (checkin + pd.Timedelta(days=2)).date().isoformat(),
            "booked_at": (checkin - pd.Timedelta(days=10)).isoformat() + "+09:00",
            "reservation_status": status,
            "outcome_recorded_at": (checkin + pd.Timedelta(hours=20)).isoformat() + "+09:00",
            "is_forecast": is_forecast,
            "adult_count": 2,
            "child_count": 0,
            "quoted_room_rate": 100000,
            "gross_room_amount": 200000,
            "discount_amount": 0,
            "booked_amount": 200000,
            "room_type_code": "STANDARD",
            "rate_plan_code": "BAR",
            "market_segment": "LEISURE",
            "booking_channel": "DIRECT",
            "is_synthetic": True,
        }


if __name__ == "__main__":
    unittest.main()
