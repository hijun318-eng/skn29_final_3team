from __future__ import annotations

import pandas as pd

from .config import BANNED_FEATURES, FEATURES
from .dataset import DatasetBundle


class DataQualityValidator:
    def validate(self, bundle: DatasetBundle) -> pd.DataFrame:
        rows = []

        def add(check_id: str, status: str, observed: str, rule: str) -> None:
            rows.append({"check_id": check_id, "status": status, "observed": observed, "rule": rule})

        labeled = pd.concat([bundle.train, bundle.validation, bundle.test])
        duplicates = int(labeled["reservation_id"].duplicated().sum())
        add("DQ-01", "PASS" if duplicates == 0 else "FAIL", str(duplicates), "reservation_id duplicate = 0")
        missing_target = int(labeled["is_no_show"].isna().sum())
        add("DQ-02", "PASS" if missing_target == 0 else "FAIL", str(missing_target), "target missing = 0")
        invalid_target = int((~labeled["is_no_show"].isin([0, 1])).sum())
        add("DQ-03", "PASS" if invalid_target == 0 else "FAIL", str(invalid_target), "target in {0,1}")
        cutoff_date = pd.to_datetime(labeled["prediction_cutoff_at"]).dt.normalize()
        expected_date = pd.to_datetime(labeled["checkin_date"]) - pd.Timedelta(days=1)
        invalid_cutoff = int((cutoff_date != expected_date).sum())
        add("DQ-04", "PASS" if invalid_cutoff == 0 else "FAIL", str(invalid_cutoff), "cutoff date is one day before arrival")
        leaked = sorted(set(FEATURES).intersection(BANNED_FEATURES))
        add("DQ-05", "PASS" if not leaked else "FAIL", ",".join(leaked) or "none", "banned outcome columns absent")
        missing_features = int(labeled[FEATURES].isna().sum().sum())
        add("DQ-05A", "PASS" if missing_features == 0 else "FAIL", str(missing_features), "feature missing = 0")
        temporal = (
            bundle.train["checkin_date"].max() < bundle.validation["checkin_date"].min()
            and bundle.validation["checkin_date"].max() < bundle.test["checkin_date"].min()
        )
        add("DQ-06", "PASS" if temporal else "FAIL", str(bool(temporal)), "time splits do not overlap")
        all_synthetic = bool(labeled["is_synthetic"].astype(bool).all())
        add("DQ-07", "PASS" if all_synthetic else "FAIL", str(all_synthetic), "all rows explicitly synthetic")
        positive_ok = all(0.002 <= frame["is_no_show"].mean() <= 0.04 for frame in [bundle.train, bundle.validation, bundle.test])
        add("DQ-08", "PASS" if positive_ok else "FAIL", str(positive_ok), "positive rate between 0.2% and 4.0%")
        source_count = bundle.profile["source_no_show_rows"]
        add("DQ-09", "FAIL" if source_count == 0 else "PASS", str(source_count), "source PMS must contain outcome NO_SHOW labels")
        combinations = labeled[["booking_channel", "market_segment"]].drop_duplicates()
        expected = labeled["booking_channel"].nunique() * labeled["market_segment"].nunique()
        coupled = len(combinations) < expected
        add("DQ-10", "WARN" if coupled else "PASS", f"{len(combinations)}/{expected}", "channel-segment combinations should not be structurally coupled")
        return pd.DataFrame(rows)
