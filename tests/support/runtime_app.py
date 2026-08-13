from __future__ import annotations

import os

from app.api import router as analysis_api
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis_service import AnalysisService
from tests.support.fakes import FakeDataPlatformAdapter, FakeModelAdapter


class _ScenarioAnalysisService(AnalysisService):
    """Keep synthetic failure controls inside the test application only."""

    def analyze(self, payload, context, decision, execution_sink=None):
        scenario = str(payload.parameters.get("scenario") or "")
        self._adapter.scenario = scenario
        self._model.scenario = scenario
        return super().analyze(payload, context, decision, execution_sink)


def _test_controller() -> AnalysisController:
    if os.getenv("TEST_REAL_DATA_PLATFORM") == "1":
        from app.adapters.i2_data_platform import I2DataPlatformAdapter

        data_platform = I2DataPlatformAdapter(
            os.environ["TRINO_URL"],
            os.getenv("TRINO_USER", "answervice-test"),
            os.getenv("DATAHUB_GMS_URL", "http://datahub.invalid"),
            require_live_metadata=False,
        )
    else:
        data_platform = FakeDataPlatformAdapter()
    return AnalysisController(
        _ScenarioAnalysisService(data_platform, FakeModelAdapter()),
        analysis_api._routing_service(),
    )


analysis_api._controller = _test_controller

from app.main import app  # noqa: E402


__all__ = ["app"]
