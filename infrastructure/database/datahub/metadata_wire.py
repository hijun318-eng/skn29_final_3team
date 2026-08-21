"""정규화된 aspect를 DataHub v1.7 동기 MCP의 PDL JSON wire로 인코딩한다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


ENTITY_PATHS = {
    "dataset": "dataset",
    "glossaryTerm": "glossaryterm",
    "metric": "metric",
    "domain": "domain",
    "tag": "tag",
    "lifecycleStageType": "lifecyclestagetype",
}
_SUPPORTED_ASPECTS = frozenset(
    {
        "datasetKey",
        "datasetProperties",
        "schemaMetadata",
        "status",
        "ownership",
        "domains",
        "editableSchemaMetadata",
        "glossaryTerms",
        "glossaryTermKey",
        "glossaryTermInfo",
        "metricKey",
        "metricInfo",
        "metricRelationships",
        "metricUpstreams",
        "domainKey",
        "domainProperties",
        "tagKey",
        "tagProperties",
        "lifecycleStageTypeKey",
        "lifecycleStageTypeInfo",
    }
)
_TECHNICAL_OWNER_TYPE = "urn:li:ownershipType:__system__technical_owner"


def entity_path(entity_type: str) -> str:
    """지원하는 DataHub entity type만 canonical Rest.li collection 이름으로 매핑한다."""

    try:
        return ENTITY_PATHS[entity_type]
    except KeyError as error:
        raise ValueError(f"unsupported DataHub OpenAPI entity type: {entity_type}") from error


def metadata_change_proposals(
    entity_type: str,
    urn: str,
    aspects: Mapping[str, Mapping[str, Any]],
    audit_stamp: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """동기 MCP endpoint에 전달할 aspect별 UPSERT proposal을 구성한다."""

    entity_path(entity_type)
    audit = validated_audit_stamp(audit_stamp)
    if not aspects:
        raise ValueError("DataHub entity request requires aspects")
    proposals: list[dict[str, Any]] = []
    for aspect_name, raw in aspects.items():
        if aspect_name not in _SUPPORTED_ASPECTS:
            raise ValueError(f"unsupported DataHub metadata aspect: {aspect_name}")
        value = _proposal_aspect_value(aspect_name, raw, audit)
        encoded = json.dumps(
            value,
            # DataHub Python emitter의 preserve_unicode_escapes와 동일하게
            # Rest.li bytes 문자열에는 비ASCII 문자를 \uXXXX로 보낸다.
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        proposals.append(
            {
                "aspect": {
                    "value": encoded,
                    "contentType": "application/json",
                },
                "aspectName": aspect_name,
                "entityType": entity_type,
                "entityUrn": urn,
                "changeType": "UPSERT",
            }
        )
    return proposals


def _proposal_aspect_value(
    name: str,
    raw: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    """OpenAPI discriminator 없이 PDL JSON union을 보존해 aspect 값을 만든다."""

    value = json.loads(json.dumps(raw))
    if name == "datasetProperties":
        value.setdefault("customProperties", {})
        value.setdefault("tags", [])
    elif name == "schemaMetadata":
        value.setdefault("created", dict(audit))
        value.setdefault("lastModified", dict(audit))
    elif name == "ownership":
        owners = value.get("owners") or []
        owner_urns = [owner["owner"] for owner in owners]
        value.setdefault("ownerTypes", {_TECHNICAL_OWNER_TYPE: owner_urns})
        value.setdefault("lastModified", dict(audit))
    elif name == "domains":
        value.setdefault(
            "domainAssociations",
            [{"domain": urn} for urn in value.get("domains", [])],
        )
    elif name == "status" and value.get("lifecycleStage"):
        value.setdefault("lifecycleLastUpdated", dict(audit))
    elif name == "editableSchemaMetadata":
        value.setdefault("created", dict(audit))
        value.setdefault("lastModified", dict(audit))
        for field in value.get("editableSchemaFieldInfo", []):
            if "glossaryTerms" in field:
                field["glossaryTerms"] = _proposal_glossary_terms(
                    field["glossaryTerms"], audit
                )
    elif name == "glossaryTerms":
        value = _proposal_glossary_terms(value, audit)
    elif name == "metricInfo":
        value.setdefault("created", dict(audit))
        value.setdefault("lastModified", dict(audit))
    elif name == "metricRelationships":
        for edge in (*value.get("derivedFrom", []), *value.get("relatedMetrics", [])):
            edge.setdefault("created", dict(audit))
            edge.setdefault("lastModified", dict(audit))
    elif name == "metricUpstreams":
        for edge in (*value.get("datasetUpstreams", []), *value.get("fieldUpstreams", [])):
            edge.setdefault("created", dict(audit))
            edge.setdefault("lastModified", dict(audit))
    elif name == "domainProperties":
        value.setdefault("customProperties", {})
        value.setdefault("created", dict(audit))
    elif name == "tagProperties":
        value.setdefault("created", dict(audit))
    elif name == "lifecycleStageTypeInfo":
        value.setdefault("created", dict(audit))
        value.setdefault("lastModified", dict(audit))
    return value


def _proposal_glossary_terms(
    value: Mapping[str, Any], audit: Mapping[str, Any]
) -> dict[str, Any]:
    """MCP용 용어 연결에 audit stamp를 추가하되 PDL 객체 형태를 유지한다."""

    return {"terms": list(value.get("terms", [])), "auditStamp": dict(audit)}


def validated_audit_stamp(value: Mapping[str, Any]) -> dict[str, Any]:
    """구체적인 publishing actor와 양수 epoch timestamp를 요구한다."""

    actor, timestamp = value.get("actor"), value.get("time")
    if (
        not isinstance(actor, str)
        or not actor.startswith("urn:li:corpuser:")
        or actor.endswith(":unknown")
        or not isinstance(timestamp, int)
        or isinstance(timestamp, bool)
        or timestamp <= 0
    ):
        raise ValueError("publication audit requires an explicit actor and positive epoch ms")
    return {"actor": actor, "time": timestamp}
