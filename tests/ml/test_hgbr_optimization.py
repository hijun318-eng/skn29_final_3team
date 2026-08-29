import unittest

import numpy as np

from src.ml.room_demand_timeseries.hgbr_optimization_support import restore_prediction, transform_target


class HgbrOptimizationTest(unittest.TestCase):
    def test_target_modes_round_trip(self) -> None:
        target = np.array([2.0, 50.0, 90.0])
        baseline = np.array([1.0, 40.0, 80.0])
        capacity = np.array([5.0, 100.0, 100.0])
        for mode in ("direct", "residual_rooms", "residual_rate", "occupancy_rate"):
            transformed = transform_target(mode, target, baseline, capacity)
            restored = restore_prediction(mode, transformed, baseline, capacity)
            np.testing.assert_allclose(restored, target)

    def test_predictions_are_capacity_bounded(self) -> None:
        result = restore_prediction("direct", np.array([-1.0, 120.0]), np.zeros(2), np.array([10.0, 100.0]))
        np.testing.assert_allclose(result, np.array([0.0, 100.0]))


if __name__ == "__main__":
    unittest.main()
