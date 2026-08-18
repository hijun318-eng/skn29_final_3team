from __future__ import annotations

from pathlib import Path
from sys import path
import unittest
from unittest.mock import AsyncMock, patch

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api.router import _controller  # noqa: E402
from app.main import lifespan  # noqa: E402


class _Platform:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Model(_Platform):
    pass


class RuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_restart_rebuilds_closed_runtime_clients(self) -> None:
        first_platform = _Platform()
        second_platform = _Platform()
        first_model = _Model()
        second_model = _Model()
        scheduler = AsyncMock()

        _controller.cache_clear()
        with (
            patch(
                "app.api.router._data_platform",
                side_effect=(first_platform, second_platform),
            ),
            patch(
                "app.api.router._model",
                side_effect=(first_model, second_model),
            ),
            patch("app.api.router._routing_service", return_value=object()),
            patch("app.main.report_scheduler", scheduler),
            patch("app.main.dispose_database", AsyncMock()) as dispose,
        ):
            async with lifespan(None):
                first_controller = _controller()

            self.assertTrue(first_platform.closed)
            self.assertTrue(first_model.closed)
            async with lifespan(None):
                second_controller = _controller()
            self.assertIsNot(second_controller, first_controller)
            self.assertTrue(second_platform.closed)
            self.assertTrue(second_model.closed)
            self.assertEqual(2, scheduler.start.await_count)
            self.assertEqual(2, scheduler.stop.await_count)
            self.assertEqual(2, dispose.await_count)

        _controller.cache_clear()
