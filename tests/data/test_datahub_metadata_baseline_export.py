"""DataHub 전체 P0 metadata baseline의 결정론·exact set·무변경 검증을 고정한다."""

from __future__ import annotations

import asyncio
import copy
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from export_datahub_metadata_baseline import (  # noqa: E402
    build_datahub_metadata_baseline,
    validate_datahub_metadata_baseline,
    verify_datahub_metadata_baseline,
    write_datahub_metadata_baseline,
)


DATASET = "urn:li:dataset:(urn:li:dataPlatform:trino,iceberg.serving.hotel_daily,PROD)"
UPSTREAM = "urn:li:dataset:(urn:li:dataPlatform:trino,iceberg.pms.stays,PROD)"
TERM = "urn:li:glossaryTerm:hotel.revenue.room"
METRIC = "urn:li:metric:(urn:li:dataPlatform:answervice,answervice.business_metrics,room_revenue)"
DOMAIN = "urn:li:domain:answervice_serving"
OWNER = "urn:li:corpGroup:hotel_analytics"
TAG = "urn:li:tag:SENSITIVE_INTERNAL"
LIFECYCLE = "urn:li:lifecycleStageType:PROD_APPROVED"
FIELD = f"urn:li:schemaField:({DATASET},room_revenue_krw)"
READ_AT = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Hit:
    urn: str


class Catalog:
    def __init__(self, *, reverse: bool = False) -> None:
        self.reverse = reverse

    async def list_datasets(self) -> tuple[Hit, ...]:
        return tuple(Hit(urn) for urn in sorted((DATASET, UPSTREAM), reverse=self.reverse))

    async def list_glossary_terms(self) -> tuple[Hit, ...]:
        return (Hit(TERM),)

    async def list_metrics(self) -> tuple[Hit, ...]:
        return (Hit(METRIC),)


def _entity(urn: str, **aspects: object) -> dict[str, object]:
    return {
        "urn": urn,
        "aspects": {name: {"value": value} for name, value in aspects.items()},
    }


class Reader:
    def __init__(self) -> None:
        ownership = {
            "owners": [{"owner": OWNER, "type": "TECHNICAL_OWNER"}],
            "lastModified": {"actor": "urn:li:corpuser:service_publisher", "time": 1},
        }
        status = {
            "removed": False,
            "lifecycleStage": LIFECYCLE,
            "lifecycleLastUpdated": {
                "actor": "urn:li:corpuser:service_publisher",
                "time": 1,
            },
        }
        self.entities = {
            DATASET: _entity(
                DATASET,
                datasetKey={"platform": "urn:li:dataPlatform:trino", "name": "iceberg.serving.hotel_daily", "origin": "PROD"},
                datasetProperties={"name": "hotel_daily", "customProperties": {"answervice.grain": "hotel_id,business_date", "created": "business-defined"}},
                schemaMetadata={
                    "fields": [{"fieldPath": "room_revenue_krw", "nativeDataType": "decimal(18,2)", "nullable": False, "isPartOfKey": False}],
                    "lastModified": {"actor": "urn:li:corpuser:service_publisher", "time": 1},
                },
                editableSchemaMetadata={"editableSchemaFieldInfo": [{"fieldPath": "room_revenue_krw", "glossaryTerms": {"terms": [{"urn": TERM}]}}]},
                status=status,
                ownership=ownership,
                domains={"domains": [DOMAIN]},
                globalTags={"tags": [{"tag": TAG}]},
                glossaryTerms={"terms": [{"urn": TERM}]},
                upstreamLineage={"upstreams": [{"dataset": UPSTREAM, "type": "TRANSFORMED"}]},
            ),
            UPSTREAM: _entity(
                UPSTREAM,
                datasetKey={"platform": "urn:li:dataPlatform:trino", "name": "iceberg.pms.stays", "origin": "PROD"},
                datasetProperties={"name": "stays", "customProperties": {"answervice.source": "PMS"}},
                schemaMetadata={"fields": [{"fieldPath": "stay_id", "nativeDataType": "varchar", "nullable": False, "isPartOfKey": True}]},
                status=status,
                ownership=ownership,
                domains={"domains": [DOMAIN]},
            ),
            TERM: _entity(
                TERM,
                glossaryTermKey={"name": "hotel.revenue.room"},
                glossaryTermInfo={"name": "객실 매출", "definition": "승인된 객실 매출"},
                status=status,
                ownership=ownership,
                domains={"domains": [DOMAIN]},
            ),
            METRIC: _entity(
                METRIC,
                metricKey={"platform": "urn:li:dataPlatform:answervice", "path": "answervice.business_metrics", "id": "room_revenue"},
                metricInfo={"name": "객실 매출", "expression": {"dialects": []}},
                status={"removed": False},
                ownership=ownership,
                domains={"domains": [DOMAIN]},
                glossaryTerms={"terms": [{"urn": TERM}]},
                metricUpstreams={"datasetUpstreams": [{"destinationUrn": DATASET}], "fieldUpstreams": [{"destinationUrn": FIELD}]},
            ),
            DOMAIN: _entity(DOMAIN, domainKey={"id": "answervice_serving"}, domainProperties={"name": "Serving"}),
            OWNER: _entity(OWNER, corpGroupKey={"name": "hotel_analytics"}, corpGroupInfo={"displayName": "호텔 분석팀"}),
            TAG: _entity(TAG, tagKey={"name": "SENSITIVE_INTERNAL"}, tagProperties={"name": "SENSITIVE_INTERNAL"}),
            LIFECYCLE: _entity(LIFECYCLE, lifecycleStageTypeKey={"id": "PROD_APPROVED"}, lifecycleStageTypeInfo={"name": "승인 운영"}, status={"removed": False}),
        }

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict[str, object]:
        source = copy.deepcopy(self.entities[urn])
        source["aspects"] = {
            name: wrapper
            for name, wrapper in source["aspects"].items()
            if name in aspects
        }
        return source


def _build(*, reverse: bool = False, reader: Reader | None = None) -> dict[str, object]:
    return asyncio.run(
        build_datahub_metadata_baseline(
            Catalog(reverse=reverse),
            reader or Reader(),
            actor_urn="urn:li:corpuser:service_catalog_reader",
            read_at=READ_AT,
        )
    )


def test_baseline_captures_all_p0_entities_and_exact_sets_without_audit_noise() -> None:
    document = _build()

    assert document["inventory"] == {
        "datasets": 2,
        "columns": 2,
        "glossary_terms": 1,
        "metrics": 1,
        "domains": 1,
        "owners": 1,
        "tags": 1,
        "lifecycle_stages": 1,
        "dataset_lineage_edges": 1,
        "metric_input_edges": 2,
    }
    assert document["exact_sets"]["dataset_urns"] == sorted([DATASET, UPSTREAM])
    assert document["exact_sets"]["dataset_lineage_edges"] == [[UPSTREAM, DATASET]]
    assert document["exact_sets"]["metric_input_edges"] == [
        [METRIC, DATASET, "room_revenue_krw"],
        [METRIC, DATASET, None],
    ]
    dataset = next(item for item in document["entities"] if item["urn"] == DATASET)
    assert dataset["aspects"]["datasetProperties"]["customProperties"]["created"] == "business-defined"
    assert "lastModified" not in str(document["entities"])
    assert "lifecycleLastUpdated" not in str(document["entities"])
    validate_datahub_metadata_baseline(document)


def test_baseline_is_deterministic_and_rejects_content_or_receipt_tampering() -> None:
    first = _build()
    second = _build(reverse=True)

    assert first == second
    tampered = copy.deepcopy(first)
    tampered["entities"][0]["aspects"][next(iter(tampered["entities"][0]["aspects"]))]["tampered"] = True
    with pytest.raises(ValueError, match="content checksum"):
        validate_datahub_metadata_baseline(tampered)

    bad_receipt = copy.deepcopy(first)
    bad_receipt["deployment_receipt"]["actor_urn"] = "urn:li:corpuser:unknown"
    with pytest.raises(ValueError, match="deployment receipt checksum"):
        validate_datahub_metadata_baseline(bad_receipt)


def test_live_verification_compares_exact_content_and_export_never_overwrites(tmp_path: Path) -> None:
    document = _build()
    receipt = asyncio.run(
        verify_datahub_metadata_baseline(document, Catalog(), Reader())
    )
    assert receipt["status"] == "LIVE_EXACT_SET_VERIFIED_WITHOUT_MUTATION"

    changed = Reader()
    changed.entities[DATASET]["aspects"]["schemaMetadata"]["value"]["fields"][0]["nullable"] = True
    with pytest.raises(ValueError, match="live DataHub content"):
        asyncio.run(verify_datahub_metadata_baseline(document, Catalog(), changed))

    target = tmp_path / "datahub-metadata-baseline.json"
    export = write_datahub_metadata_baseline(document, target)
    assert export["status"] == "EXPORTED_WITHOUT_MUTATION"
    with pytest.raises(FileExistsError):
        write_datahub_metadata_baseline(document, target)
    with pytest.raises(ValueError, match="absolute"):
        write_datahub_metadata_baseline(document, Path("relative.json"))
