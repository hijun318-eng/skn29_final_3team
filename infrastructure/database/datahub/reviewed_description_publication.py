"""SQL 검토 근거로 신규 DataHub asset 설명만 선행 발행한다.

Trino connector가 view ``COMMENT ON``을 읽지 못하는 환경에서도 authoring policy가
추정 설명을 사용하지 않도록 한다. 검토안의 ``asset_additions``만 대상으로 하며,
이미 semantic property가 있는 Dataset은 수정하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from metadata_contract_primitives import SemanticMetadataError, array, mapping, text
from metadata_rest import aspect_value, optional_aspect_value
from metric_review_contract import CONTRACT_VERSION_V2, validate_metric_review
from release_bundle import ReleaseBinding
from release_datahub import PROPERTY_PREFIX
from runtime_governance_draft import GovernanceDraft
from src.data.governance_contract import canonical_sha256


@dataclass(frozen=True)
class ReviewedDescriptionPatch:
    """한 신규 Dataset에 적용할 SQL 검토 설명과 live identity를 묶는다."""

    fqn: str
    urn: str
    dataset_description: str
    fields: tuple[tuple[str, str], ...]

    def as_document(self) -> dict[str, Any]:
        """결정론적 checksum 입력에 사용할 JSON 문서를 반환한다."""

        return {
            "fqn": self.fqn,
            "urn": self.urn,
            "dataset_description": self.dataset_description,
            "fields": [
                {"name": name, "description": description}
                for name, description in self.fields
            ],
        }


@dataclass(frozen=True)
class ReviewedDescriptionPlan:
    """후보 checksum과 신규 Dataset 설명 patch의 결정론적 계획이다."""

    candidate_sha256: str
    patches: tuple[ReviewedDescriptionPatch, ...]

    def as_document(self) -> dict[str, Any]:
        """후보 checksum과 정렬된 Dataset patch를 JSON 문서로 반환한다."""

        return {
            "candidate_sha256": self.candidate_sha256,
            "patches": [patch.as_document() for patch in self.patches],
        }

    @property
    def plan_sha256(self) -> str:
        """발행 승인에 결속할 계획 전체의 정규 SHA-256을 반환한다."""

        return canonical_sha256(self.as_document())


def build_reviewed_description_plan(
    review: Mapping[str, Any],
    evidence: GovernanceDraft,
    bindings: tuple[ReleaseBinding, ...],
) -> ReviewedDescriptionPlan:
    """검증된 v2 addition과 live base-ingested Dataset을 정확히 결합한다."""

    validation = validate_metric_review(review, evidence)
    if validation["contract_version"] != CONTRACT_VERSION_V2:
        raise SemanticMetadataError("reviewed description staging requires a v2 review")
    additions = {
        text(mapping(item, "asset addition")["fqn"], "asset addition fqn")
        for item in array(review.get("asset_additions"), "asset additions", non_empty=True)
    }
    views = {view.fqn: view for view in evidence.views}
    live = {binding.relation.fqn: binding for binding in bindings}
    if not additions <= set(views) or not additions <= set(live):
        raise SemanticMetadataError(
            "reviewed description assets must exist in SQL evidence and live metadata"
        )
    patches: list[ReviewedDescriptionPatch] = []
    for fqn in sorted(additions):
        view = views[fqn]
        binding = live[fqn]
        dataset = binding.dataset
        if any(key.startswith(PROPERTY_PREFIX) for key in dataset.custom_properties):
            raise SemanticMetadataError(
                "reviewed description staging cannot rewrite a governed Dataset"
            )
        expected_fields = tuple(field.name for field in view.fields)
        if expected_fields != tuple(field.name for field in dataset.fields):
            raise SemanticMetadataError(
                "reviewed description fields differ from live DataHub order"
            )
        patches.append(
            ReviewedDescriptionPatch(
                fqn=fqn,
                urn=dataset.urn,
                dataset_description=view.description,
                fields=tuple(
                    (field.name, field.description) for field in view.fields
                ),
            )
        )
    return ReviewedDescriptionPlan(
        candidate_sha256=str(validation["candidate_sha256"]),
        patches=tuple(patches),
    )


async def publish_reviewed_description_plan(
    client: Any,
    plan: ReviewedDescriptionPlan,
    *,
    actor_urn: str,
    expected_plan_sha256: str,
    clock_ms: int,
) -> dict[str, Any]:
    """기존 aspect 값을 보존해 설명만 병합하고 즉시 exact read-back한다."""

    if (
        expected_plan_sha256 != plan.plan_sha256
        or not actor_urn.startswith("urn:li:corpuser:")
        or not isinstance(clock_ms, int)
        or isinstance(clock_ms, bool)
        or clock_ms <= 0
    ):
        raise SemanticMetadataError("reviewed description publication receipt is invalid")
    audit = {"actor": actor_urn, "time": clock_ms}
    field_count = 0
    for patch in plan.patches:
        current = await client.get_entity(
            patch.urn,
            ("datasetProperties", "editableSchemaMetadata"),
        )
        properties = deepcopy(aspect_value(current, "datasetProperties"))
        properties["description"] = patch.dataset_description
        editable = optional_aspect_value(current, "editableSchemaMetadata") or {}
        infos = editable.get("editableSchemaFieldInfo") or []
        if not isinstance(infos, list):
            raise SemanticMetadataError("editable schema field metadata is invalid")
        by_name: dict[str, dict[str, Any]] = {}
        for raw in infos:
            item = mapping(raw, "editable schema field")
            name = text(item.get("fieldPath"), "editable schema field path")
            if name in by_name:
                raise SemanticMetadataError("editable schema fields are duplicate")
            by_name[name] = deepcopy(dict(item))
        expected_names = {name for name, _description in patch.fields}
        if set(by_name) - expected_names:
            raise SemanticMetadataError(
                "editable schema contains fields outside the reviewed SQL asset"
            )
        merged = deepcopy(dict(editable))
        merged["editableSchemaFieldInfo"] = []
        for name, description in patch.fields:
            item = by_name.get(name, {"fieldPath": name})
            item["description"] = description
            merged["editableSchemaFieldInfo"].append(item)
        await client.upsert_entity(
            "dataset",
            patch.urn,
            {
                "datasetProperties": properties,
                "editableSchemaMetadata": merged,
            },
            audit,
        )
        observed = await client.get_entity(
            patch.urn,
            ("datasetProperties", "editableSchemaMetadata"),
        )
        if (
            aspect_value(observed, "datasetProperties").get("description")
            != patch.dataset_description
        ):
            raise SemanticMetadataError("DataHub dataset description read-back differs")
        observed_infos = aspect_value(observed, "editableSchemaMetadata").get(
            "editableSchemaFieldInfo"
        )
        observed_descriptions = {
            item.get("fieldPath"): item.get("description")
            for item in observed_infos or []
            if isinstance(item, Mapping)
        }
        if observed_descriptions != dict(patch.fields):
            raise SemanticMetadataError("DataHub field description read-back differs")
        field_count += len(patch.fields)
    return {
        "status": "PUBLISHED_AND_VERIFIED",
        "candidate_sha256": plan.candidate_sha256,
        "plan_sha256": plan.plan_sha256,
        "dataset_count": len(plan.patches),
        "field_count": field_count,
    }
