"""SQL 검토 설명을 신규 DataHub Dataset에만 병합하는 경계를 검증한다."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
if str(DATAHUB) not in sys.path:
    sys.path.insert(0, str(DATAHUB))

from metadata_contract_primitives import SemanticMetadataError  # noqa: E402
from release_bundle import ReleaseBinding  # noqa: E402
from release_datahub import DataHubDataset, DataHubField  # noqa: E402
from release_scope import ReleaseScope  # noqa: E402
from release_trino import PhysicalColumn, PhysicalRelation  # noqa: E402
from reviewed_description_publication import (  # noqa: E402
    build_reviewed_description_plan,
    publish_reviewed_description_plan,
)
from runtime_governance_draft import (  # noqa: E402
    FieldEvidence,
    GovernanceDraft,
    ViewEvidence,
)


FQN = "serving.sample.daily_observations"
URN = "urn:li:dataset:(urn:li:dataPlatform:trino,sample.daily_observations,PROD)"


def _evidence() -> GovernanceDraft:
    fields = tuple(
        FieldEvidence(name, f"Reviewed {name}.", name, (), "PASS_THROUGH", ())
        for name in ("observed_on", "segment", "amount")
    )
    return GovernanceDraft(
        release_version="sample-release-v1",
        serving_schema="serving.sample",
        source_sha256="a" * 64,
        views=(
            ViewEvidence(
                fqn=FQN,
                description="Reviewed daily observations.",
                source_file="20_observations.sql",
                source_relations=("source.sample.observations",),
                grain_candidates=("observed_on", "segment"),
                fields=fields,
            ),
        ),
    )


def _review() -> dict[str, object]:
    return {
        "contract_version": "answervice.metric_review.v2",
        "review_status": "REVIEW_REQUIRED",
        "release_id": "sample-release-v1",
        "serving_schema": "serving.sample",
        "source_sql_sha256": "a" * 64,
        "business_metric_target_count": 1,
        "allowed_roles": ["analyst"],
        "review_owner_candidate_urn": "urn:li:corpGroup:sample_stewards",
        "asset_additions": [
            {
                "fqn": FQN,
                "domain_urn": "urn:li:domain:sample",
                "grain": {
                    "kind": "periodic",
                    "keys": ["observed_on", "segment"],
                },
            }
        ],
        "dimension_additions": [
            {
                "id": "sample_segment",
                "aliases": ["sample segment", "표본 구분"],
                "definition": "Arbitrary segment captured on the observation row.",
                "asset_fqn": FQN,
                "column": "segment",
            }
        ],
        "metrics": [
            {
                "id": "total_amount",
                "name": "Total Amount",
                "visibility": "BUSINESS",
                "review_status": "REVIEW_REQUIRED",
                "definition": "Sum of the reviewed amount at observation grain.",
                "formula": {
                    "kind": "COLUMN",
                    "aggregation": "sum",
                    "reduction": "sum",
                },
                "source": {
                    "kind": "COLUMN",
                    "asset_fqn": FQN,
                    "column": "amount",
                },
                "grain": {
                    "kind": "segment_day",
                    "keys": ["observed_on", "segment"],
                    "dimensions": ["segment"],
                },
                "time": {
                    "field": "observed_on",
                    "semantics": "OBSERVATION_DATE",
                    "timezone": "UTC",
                    "interval": "[start,end)",
                    "bucket": "day",
                    "timezone_mode": "preserve",
                },
                "join": {"required": False, "allowed_edge_ids": []},
                "aliases": ["total observed amount"],
                "permission": {
                    "roles": ["analyst"],
                    "contains_pii": False,
                    "synthetic": False,
                },
                "unit": "amount",
                "result_field": "total_amount",
                "query_strategies": ["VIEW_REUSE"],
            }
        ],
    }


def _binding(*, custom_properties: dict[str, str] | None = None) -> ReleaseBinding:
    scope = ReleaseScope("serving", "sample", "serving", "serving.sample", "PROD")
    names = ("observed_on", "segment", "amount")
    relation = PhysicalRelation(
        scope,
        "daily_observations",
        "VIEW",
        tuple(
            PhysicalColumn(index, name, "varchar", True)
            for index, name in enumerate(names, start=1)
        ),
    )
    dataset = DataHubDataset(
        urn=URN,
        dataset_key_name="serving.sample.daily_observations",
        origin="PROD",
        platform_urn="urn:li:dataPlatform:trino",
        name=FQN,
        qualified_name=FQN,
        description=None,
        schema_name="sample.daily_observations",
        schema_version=0,
        schema_hash="schema-hash",
        removed=False,
        owners=(),
        domain=None,
        lifecycle=None,
        custom_properties=custom_properties or {},
        fields=tuple(
            DataHubField(name, "varchar", True, False, None) for name in names
        ),
    )
    return ReleaseBinding(relation, dataset)


class _FakeClient:
    def __init__(self) -> None:
        self.entities = {
            URN: {
                "aspects": {
                    "datasetProperties": {
                        "value": {
                            "name": "daily_observations",
                            "qualifiedName": FQN,
                            "customProperties": {"connector.source": "trino"},
                        }
                    }
                }
            }
        }
        self.audit_stamps: list[dict[str, object]] = []

    async def get_entity(
        self, urn: str, aspects: tuple[str, ...]
    ) -> dict[str, object]:
        entity = self.entities[urn]
        return {
            "aspects": {
                name: deepcopy(entity["aspects"][name])
                for name in aspects
                if name in entity["aspects"]
            }
        }

    async def upsert_entity(
        self,
        _entity_type: str,
        urn: str,
        aspects: dict[str, dict[str, object]],
        audit_stamp: dict[str, object],
    ) -> None:
        for name, value in aspects.items():
            self.entities[urn]["aspects"][name] = {"value": deepcopy(value)}
        self.audit_stamps.append(deepcopy(audit_stamp))


def test_reviewed_descriptions_are_merged_without_losing_connector_metadata():
    plan = build_reviewed_description_plan(_review(), _evidence(), (_binding(),))
    client = _FakeClient()

    receipt = asyncio.run(
        publish_reviewed_description_plan(
            client,
            plan,
            actor_urn="urn:li:corpuser:semantic_publisher",
            expected_plan_sha256=plan.plan_sha256,
            clock_ms=1_777_777_777_000,
        )
    )

    properties = client.entities[URN]["aspects"]["datasetProperties"]["value"]
    editable = client.entities[URN]["aspects"]["editableSchemaMetadata"]["value"]
    assert receipt["status"] == "PUBLISHED_AND_VERIFIED"
    assert receipt["dataset_count"] == 1
    assert receipt["field_count"] == 3
    assert properties["customProperties"] == {"connector.source": "trino"}
    assert properties["description"] == "Reviewed daily observations."
    assert {
        item["fieldPath"]: item["description"]
        for item in editable["editableSchemaFieldInfo"]
    } == {
        "observed_on": "Reviewed observed_on.",
        "segment": "Reviewed segment.",
        "amount": "Reviewed amount.",
    }
    assert client.audit_stamps == [
        {"actor": "urn:li:corpuser:semantic_publisher", "time": 1_777_777_777_000}
    ]


def test_reviewed_description_staging_refuses_an_already_governed_dataset():
    governed = _binding(
        custom_properties={"answervice.contract_version": "answervice.semantic.v1"}
    )

    with pytest.raises(SemanticMetadataError, match="governed Dataset"):
        build_reviewed_description_plan(_review(), _evidence(), (governed,))


def test_reviewed_description_publication_requires_the_exact_plan_checksum():
    plan = build_reviewed_description_plan(_review(), _evidence(), (_binding(),))

    with pytest.raises(SemanticMetadataError, match="receipt is invalid"):
        asyncio.run(
            publish_reviewed_description_plan(
                _FakeClient(),
                plan,
                actor_urn="urn:li:corpuser:semantic_publisher",
                expected_plan_sha256="0" * 64,
                clock_ms=1_777_777_777_000,
            )
        )
