"""기술형 Glossary 정리 baseline의 분류·결정론·변조 거부를 검증한다."""

from __future__ import annotations

import asyncio
import copy
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))

from src.data.governance_contract import canonical_sha256  # noqa: E402
from export_catalog_baseline import (  # noqa: E402
    BASELINE_SCOPE,
    build_catalog_baseline,
    validate_catalog_baseline,
)


TECHNICAL_URN = (
    "urn:li:glossaryTerm:answervice_release_x_dataset_"
    "0123456789abcdef01234567"
)
BUSINESS_URN = "urn:li:glossaryTerm:hotel.revenue.room"
DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:trino,serving.hotel_daily,PROD)"
LOGICAL_DATASET_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:semantic,hotel.logical_model,PROD)"
)


@dataclass(frozen=True)
class Hit:
    urn: str


class BaselineClient:
    def __init__(self, *, reverse: bool = False, orphaned: bool = False) -> None:
        self.reverse = reverse
        self.terms = {
            TECHNICAL_URN: {
                "urn": TECHNICAL_URN,
                "exists": True,
                "status": None,
                "glossaryTermInfo": {
                    "name": "hotel_daily",
                    "description": "기술 데이터셋 설명",
                    "termSource": "INTERNAL",
                    "sourceRef": "release-x",
                    "customProperties": [
                        {"key": "answervice.catalog_release", "value": "release-x"}
                    ],
                },
                "ownership": {
                    "owners": [
                        {
                            "owner": {"urn": "urn:li:corpuser:service_catalog"},
                            "associatedUrn": TECHNICAL_URN,
                            "ownershipType": {
                                "urn": "urn:li:ownershipType:__system__technical_owner"
                            },
                            "type": "TECHNICAL_OWNER",
                        }
                    ]
                },
                "domain": {"domain": {"urn": "urn:li:domain:answervice_serving"}},
            },
            BUSINESS_URN: {
                "urn": BUSINESS_URN,
                "exists": True,
                "glossaryTermInfo": {
                    "name": "객실 매출",
                    "description": "승인된 비즈니스 지표",
                    "termSource": "INTERNAL",
                    "sourceRef": "semantic-release",
                    "customProperties": [],
                },
            },
        }
        self.datasets = {
            DATASET_URN: {
                "urn": DATASET_URN,
                "glossaryTerms": {"terms": [{"term": {"urn": BUSINESS_URN}}]},
                "schemaMetadata": {
                    "fields": [
                        {
                            "fieldPath": "room_revenue_krw",
                            "description": "객실 매출",
                            "glossaryTerms": {
                                "terms": [{"term": {"urn": TECHNICAL_URN}}]
                            },
                        }
                    ]
                },
                "editableSchemaMetadata": {
                    "editableSchemaFieldInfo": [
                        {
                            "fieldPath": "room_revenue_krw",
                            "description": "객실 매출",
                            "glossaryTerms": {
                                "terms": [
                                    {"term": {"urn": BUSINESS_URN}},
                                    {"term": {"urn": TECHNICAL_URN}},
                                ]
                            },
                        }
                    ]
                },
            },
            LOGICAL_DATASET_URN: {
                "urn": LOGICAL_DATASET_URN,
                "glossaryTerms": {"terms": [{"term": {"urn": BUSINESS_URN}}]},
                "schemaMetadata": None,
                "editableSchemaMetadata": None,
            },
        }
        if orphaned:
            self.datasets[DATASET_URN]["schemaMetadata"]["fields"][0][
                "glossaryTerms"
            ] = {"terms": [{"term": {"urn": BUSINESS_URN}}]}
            self.datasets[DATASET_URN]["editableSchemaMetadata"][
                "editableSchemaFieldInfo"
            ][0]["glossaryTerms"] = {"terms": [{"term": {"urn": BUSINESS_URN}}]}

    async def list_glossary_terms(self) -> tuple[Hit, ...]:
        urns = sorted(self.terms, reverse=self.reverse)
        return tuple(Hit(urn) for urn in urns)

    async def get_glossary_term(self, urn: str) -> dict[str, object]:
        return self.terms[urn]

    async def get_entity_status(self, urn: str) -> dict[str, object]:
        return {"urn": urn, "status": {"removed": False}}

    async def list_datasets(self) -> tuple[Hit, ...]:
        urns = sorted(self.datasets, reverse=self.reverse)
        return tuple(Hit(urn) for urn in urns)

    async def get_dataset(self, urn: str) -> dict[str, object]:
        return self.datasets[urn]


def test_baseline_keeps_only_proven_technical_terms_and_complete_associations() -> None:
    document = asyncio.run(build_catalog_baseline(BaselineClient()))

    assert document["inventory"] == {
        "scanned_datasets": 2,
        "scanned_glossary_terms": 2,
        "affected_datasets": 1,
        "technical_terms": 1,
    }
    assert [term["urn"] for term in document["terms"]] == [TECHNICAL_URN]
    assert document["datasets"][0]["dataset_term_urns"] == [BUSINESS_URN]
    assert document["datasets"][0]["editable_fields"][0]["term_urns"] == sorted(
        [BUSINESS_URN, TECHNICAL_URN]
    )
    validate_catalog_baseline(document)


def test_baseline_is_deterministic_and_rejects_tampering() -> None:
    first = asyncio.run(build_catalog_baseline(BaselineClient()))
    second = asyncio.run(build_catalog_baseline(BaselineClient(reverse=True)))
    assert first == second

    tampered = copy.deepcopy(first)
    tampered["terms"][0]["name"] = "변조"
    with pytest.raises(ValueError, match="checksum"):
        validate_catalog_baseline(tampered)

    wrong_scope = copy.deepcopy(first)
    wrong_scope["scope"] = "UNRELATED_SCOPE"
    payload = copy.deepcopy(wrong_scope)
    payload.pop("content_sha256")
    wrong_scope["content_sha256"] = canonical_sha256(payload)
    with pytest.raises(ValueError, match="scope"):
        validate_catalog_baseline(wrong_scope)


def test_baseline_records_orphaned_technical_terms_without_fake_dataset_links() -> None:
    document = asyncio.run(build_catalog_baseline(BaselineClient(orphaned=True)))

    assert document["inventory"]["technical_terms"] == 1
    assert document["inventory"]["affected_datasets"] == 0
    assert document["datasets"] == []
    validate_catalog_baseline(document)
