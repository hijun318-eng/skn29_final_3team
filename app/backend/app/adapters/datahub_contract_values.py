"""DataHub custom property에 직렬화된 공통 runtime 거버넌스 값을 엄격한 형식으로 복원한다."""

from __future__ import annotations

import json

from app.adapters.datahub_metadata_values import (
    GovernedMetadataError,
    clone_mapping,
    custom_properties,
    fqn,
    required_text,
)


PROPERTY_PREFIX = "answervice."


def governed_properties(value, expected):
    """``answervice.`` 속성만 추출하고 key 집합이 계약과 정확히 같지 않으면 ``GovernedMetadataError``를 발생시킨다."""
    properties = custom_properties(value)
    governed = {
        key[len(PROPERTY_PREFIX):]: item
        for key, item in properties.items()
        if key.startswith(PROPERTY_PREFIX)
    }
    # 알 수 없는 key도 거부해야 publisher와 runtime의 contract version 불일치를 숨기지 않는다.
    if set(governed) != expected:
        raise GovernedMetadataError("DataHub governed custom properties are incomplete")
    return governed


def json_object(value, name):
    """JSON 문자열을 object로 복원하며 다른 JSON 유형은 지정된 DataHub 필드 오류로 거부한다."""
    parsed = json_value(value, name)
    if not isinstance(parsed, dict):
        raise GovernedMetadataError(f"DataHub {name} must be an object")
    return parsed


def json_array(value, name):
    """JSON 문자열을 array로 복원하며 scalar나 object가 들어오면 거버넌스 계약 위반을 알린다."""
    parsed = json_value(value, name)
    if not isinstance(parsed, list):
        raise GovernedMetadataError(f"DataHub {name} must be an array")
    return parsed


def json_boolean(value, name):
    """JSON literal을 Python bool로 복원하고 숫자·문자열로 표현된 유사 boolean은 수용하지 않는다."""
    parsed = json_value(value, name)
    if not isinstance(parsed, bool):
        raise GovernedMetadataError(f"DataHub {name} must be boolean")
    return parsed


def json_value(value, name):
    """custom property 문자열을 JSON 값으로 해석하며 decode·입력 유형 실패를 ``GovernedMetadataError``로 정규화한다."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise GovernedMetadataError(f"DataHub {name} is invalid JSON") from error


def governance_urns(value):
    """owner·domain·승인 lifecycle URN 목록의 prefix·정렬·유일성을 검증해 canonical release 참조를 만든다."""
    required = {
        "owners": "urn:li:corpGroup:",
        "domains": "urn:li:domain:",
        "approved_lifecycles": "urn:li:lifecycleStageType:",
    }
    if set(value) != set(required):
        raise GovernedMetadataError("DataHub governance URN groups are invalid")
    result = {}
    for name, prefix in required.items():
        values = value[name]
        if (
            not isinstance(values, list)
            or not values
            or values != sorted(values)
            or len(values) != len(set(values))
            or any(not isinstance(item, str) or not item.startswith(prefix) for item in values)
        ):
            raise GovernedMetadataError(f"DataHub {name} governance URNs are invalid")
        result[name] = list(values)
    return result


def dataset_key(urn: str):
    """DataHub dataset URN을 platform·physical name·origin으로 분해하고 모호한 물리 식별자는 거부한다."""
    prefix = "urn:li:dataset:("
    if not urn.startswith(prefix) or not urn.endswith(")"):
        raise GovernedMetadataError("DataHub dataset URN is invalid")
    values = urn[len(prefix):-1].split(",")
    if len(values) != 3:
        raise GovernedMetadataError("DataHub dataset URN identity is ambiguous")
    platform, name, origin = values
    if (
        not platform.startswith("urn:li:dataPlatform:")
        or not name
        or not origin
        or any(item != item.strip() for item in values)
    ):
        raise GovernedMetadataError("DataHub dataset URN physical identity is invalid")
    return platform, {"platform": platform, "name": name, "origin": origin}


def qualified_fields(value, name):
    """최대 64개의 ``asset_fqn``·column 참조만 허용해 metric 차원 필드를 정규화한다."""
    if not isinstance(value, list) or len(value) > 64:
        raise GovernedMetadataError(f"DataHub {name} must be bounded")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"asset_fqn", "column"}:
            raise GovernedMetadataError(f"DataHub {name} field is invalid")
        result.append(
            {
                "asset_fqn": fqn(item["asset_fqn"]),
                "column": required_text(item["column"], f"{name} column"),
            }
        )
    return result


def parameter_contract(value):
    """named parameter의 이름·유형·scope·유일성을 확인하고 JSON 값으로만 구성된 독립 복사본을 반환한다."""
    if set(value) != {"style", "parameters"} or value.get("style") != "named":
        raise GovernedMetadataError("DataHub parameter contract is invalid")
    values = value["parameters"]
    if not isinstance(values, list) or not values:
        raise GovernedMetadataError("DataHub parameters must be non-empty")
    names = set()
    for item in values:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "type", "scope"}
            or not required_text(item["name"], "parameter name")
            or item["type"] not in {"string", "boolean", "number", "date", "timestamp"}
            or item["scope"] not in {"time", "filter", "limit"}
            or item["name"] in names
        ):
            raise GovernedMetadataError("DataHub parameter definition is invalid")
        names.add(item["name"])
    return clone_mapping(value)


def time_rules(value, parameters):
    """반개구간 시간 규칙을 parameter 계약과 교차 검증하고 원본 규칙과 context용 요약을 함께 반환한다."""
    required = {
        "timezone", "calendar_id", "interval", "start_parameter", "end_parameter", "fields"
    }
    if set(value) != required or value["interval"] != "[start,end)":
        raise GovernedMetadataError("DataHub time rules are invalid")
    types = {
        item["name"]: (item["type"], item["scope"])
        for item in parameters["parameters"]
    }
    start = required_text(value["start_parameter"], "time start parameter")
    end = required_text(value["end_parameter"], "time end parameter")
    if start == end or any(
        types.get(name, (None, None))[1] != "time" for name in (start, end)
    ):
        raise GovernedMetadataError("DataHub time parameters are invalid")
    fields = value["fields"]
    if not isinstance(fields, list) or not fields:
        raise GovernedMetadataError("DataHub time fields are missing")
    for item in fields:
        if not isinstance(item, dict) or set(item) != {
            "field", "native_type", "bucket", "timezone_mode"
        }:
            raise GovernedMetadataError("DataHub time field metadata is invalid")
        qualified_fields([item["field"]], "time fields")
    normalized = {
        "calendar_id": required_text(value["calendar_id"], "calendar id"),
        "start_parameter": start,
        "end_parameter": end,
        "fields": clone_mapping({"values": fields})["values"],
    }
    required_text(value["timezone"], "time rule timezone")
    return clone_mapping(value), normalized


def grain(value, columns):
    """dataset grain 종류와 key가 실제 governed column에 속하는지 검증한 뒤 안전한 복사본을 반환한다."""
    if set(value) != {"kind", "keys"} or value.get("kind") not in {
        "row", "event", "periodic", "aggregate"
    }:
        raise GovernedMetadataError("DataHub grain metadata is invalid")
    keys = value.get("keys")
    column_names = {item["name"] for item in columns}
    if not isinstance(keys, list) or not keys or not set(keys).issubset(column_names):
        raise GovernedMetadataError("DataHub grain keys are invalid")
    return clone_mapping(value)


def join_graph(value):
    """join graph 최상위 shape를 ``edges`` 배열로 제한하고 후속 typed resolver가 읽을 복사본을 반환한다."""
    if set(value) != {"edges"} or not isinstance(value["edges"], list):
        raise GovernedMetadataError("DataHub join graph is invalid")
    return clone_mapping(value)


def query_policy(value):
    """Trino SELECT·read-only·필수 LIMIT 정책과 허용 함수·catalog 목록의 정확한 필드를 fail-closed로 검증한다."""
    required = {
        "dialect", "statement_type", "read_only", "require_limit", "max_limit",
        "allowed_functions", "allowed_catalogs",
    }
    if (
        set(value) != required
        or value["dialect"] != "trino"
        or value["statement_type"] != "select"
        or value["read_only"] is not True
        or value["require_limit"] is not True
        or not isinstance(value["max_limit"], int)
        or isinstance(value["max_limit"], bool)
        or value["max_limit"] < 1
        or not isinstance(value["allowed_functions"], list)
        or not isinstance(value["allowed_catalogs"], list)
    ):
        raise GovernedMetadataError("DataHub query policy is invalid")
    return clone_mapping(value)
