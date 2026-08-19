from __future__ import annotations

import os

import httpx

from app.api import router as analysis_api
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis import AnalysisService
from tests.support.analysis_runtime_fixture import (
    AnalysisRuntimeDataPlatformFake,
    MetadataDrivenAnalysisModel,
)


class _ScenarioAnalysisService(AnalysisService):
    """Keep synthetic failure controls inside the test application only."""

    async def analyze(
        self,
        payload,
        context,
        decision,
        execution_sink=None,
        progress_sink=None,
        cancel_check=None,
    ):
        scenario = str(payload.parameters.get("scenario") or "")
        self._adapter.scenario = scenario
        self._model.scenario = scenario
        return await super().analyze(
            payload,
            context,
            decision,
            execution_sink,
            progress_sink,
            cancel_check,
        )


def _test_controller() -> AnalysisController:
    if os.getenv("TEST_REAL_DATA_PLATFORM") == "1":
        from app.adapters.governed_data_platform import GovernedDataPlatformAdapter
        from app.adapters.trino_async import TrinoAsyncClient

        trino_url = os.environ["TRINO_URL"]
        trino_upstream_url = os.environ["TRINO_TEST_UPSTREAM_URL"].rstrip("/")
        trino_user = os.environ["TRINO_RUNTIME_USER"]

        async def forward_trino(request: httpx.Request) -> httpx.Response:
            async with httpx.AsyncClient() as upstream:
                response = await upstream.request(
                    request.method,
                    f"{trino_upstream_url}{request.url.raw_path.decode('ascii')}",
                    content=await request.aread(),
                    headers={
                        key: value
                        for key, value in request.headers.items()
                        if key.casefold() != "host"
                    },
                )
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=request,
            )

        trino_client = TrinoAsyncClient(
            trino_url,
            trino_user,
            os.environ["TRINO_RUNTIME_PASSWORD"],
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(forward_trino)
            ),
        )

        data_platform = GovernedDataPlatformAdapter(
            trino_url,
            trino_user,
            os.environ["DATAHUB_GMS_URL"],
            os.environ["DATAHUB_API_TOKEN"],
            datahub_ca_file=os.environ["DATAHUB_TLS_CA_FILE"],
            trino_client=trino_client,
        )
    else:
        data_platform = AnalysisRuntimeDataPlatformFake()
    return AnalysisController(
        _ScenarioAnalysisService(data_platform, MetadataDrivenAnalysisModel()),
        analysis_api._routing_service(),
    )


analysis_api._controller = _test_controller

from app.main import app  # noqa: E402
from app.context import token_authenticator  # noqa: E402
from tests.support.auth_dependencies import injected_token_authenticator  # noqa: E402


app.dependency_overrides[token_authenticator] = injected_token_authenticator


__all__ = ["app"]
