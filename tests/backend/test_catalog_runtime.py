from __future__ import annotations

from datetime import date
from pathlib import Path
from sys import path
from unittest.mock import patch

import pytest
from fastapi import HTTPException


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.i2_data_platform import I2DataPlatformAdapter  # noqa: E402
from app.api import catalog_router as catalog_api  # noqa: E402
from app.catalog_contracts import CatalogSourceListResponse  # noqa: E402
from app.contracts import RequestContext  # noqa: E402


def test_real_catalog_reads_exact_five_live_datahub_datasets_and_trino_health():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    requested = []
    adapter._datahub_health = lambda: True
    adapter._trino.health = lambda: True

    def dataset(urn):
        requested.append(urn)
        return {
            "urn": urn,
            "name": urn,
            "status": {"removed": False},
            "platform": {"name": urn.split("dataPlatform:", 1)[1].split(",", 1)[0]},
            "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:data-owner", "username": "data-owner"}, "type": "TECHNICAL_OWNER"}]},
            "schemaMetadata": {"name": urn.split(",", 1)[1].rsplit(",", 1)[0], "fields": [{"fieldPath": "id", "nativeDataType": "bigint"}]},
        }

    adapter._datahub_dataset = dataset
    payload = CatalogSourceListResponse.model_validate({"items": adapter.catalog_sources()})

    assert [item.source_id for item in payload.items] == ["pms", "pos", "crm", "facility", "banquet"]
    assert len(requested) == len(set(requested)) == 5
    assert all(item.owners == ["data-owner"] for item in payload.items)
    assert all(item.schema_status == item.search_status == item.connection_status == "AVAILABLE" for item in payload.items)


def test_catalog_route_returns_503_instead_of_success_when_datahub_is_unavailable():
    class Unavailable:
        def catalog_sources(self):
            raise ValueError("live DataHub runtime verification is unavailable")

    with patch.object(catalog_api, "_catalog_adapter", return_value=Unavailable()):
        with pytest.raises(HTTPException) as unavailable:
            catalog_api.list_catalog_sources(RequestContext(as_of=date(2026, 8, 12)))
    assert unavailable.value.status_code == 503


def test_versioned_mode_cannot_masquerade_as_live_catalog():
    with patch.dict("os.environ", {"DATA_PLATFORM_MODE": "versioned-trino"}, clear=True):
        with pytest.raises(HTTPException) as unavailable:
            catalog_api._catalog_adapter()
    assert unavailable.value.status_code == 503
