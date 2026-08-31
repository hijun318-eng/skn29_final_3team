"""승인된 분석 의미를 원문 질문과 분리한 불변 재실행 snapshot 계약이다."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Mapping
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contract_core import Scalar
from app.services.analysis.logical_plan import (
    ANALYSIS_PLAN_FIELDS,
    ANALYSIS_PLAN_VERSION,
    validate_analysis_plan_structure,
)


APPROVED_SEMANTIC_REQUEST_VERSION = "ANSWERVICE-APPROVED-SEMANTIC-REQUEST-v1"
_REPLAY_QUESTION = "승인된 Semantic Request 재실행"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def semantic_plan_parameter_names(value: Mapping[str, Any]) -> frozenset[str]:
    """AnalysisPlan이 의미 입력으로 직접 소유한 placeholder 이름만 반환한다."""

    names = {
        str(item["parameter"])
        for item in value.get("filter_fields", ())
        if isinstance(item, Mapping) and "parameter" in item
    }
    names.update(
        str(name)
        for item in value.get("period_parameters", ())
        if isinstance(item, Mapping)
        for name in (item.get("start_parameter"), item.get("end_parameter"))
        if name is not None
    )
    snapshot_parameter = value.get("snapshot_parameter")
    if snapshot_parameter is not None:
        names.add(str(snapshot_parameter))
    return frozenset(names)


def assert_current_semantic_bindings(
    snapshot: "ApprovedSemanticRequestSnapshot",
    current_bindings: tuple[object, ...],
) -> None:
    """현재 G1 package의 사용자 의미 binding이 승인 snapshot과 exact인지 검증한다.

    현재 entitlement가 새로 만드는 정책 필수 filter는 비교 대상에서 제외한다. 반대로
    Plan이 직접 참조하는 기간·snapshot·사용자 filter는 이름·타입·값 모두 같아야 하며,
    current context의 cutoff 보정이나 parameter 재명명도 fail-closed로 차단한다.
    """

    expected_names = semantic_plan_parameter_names(snapshot.analysis_plan)
    expected = {
        item.name: (item.value_type, item.value)
        for item in snapshot.parameter_bindings
    }
    selected = [
        item
        for item in current_bindings
        if getattr(item, "name", None) in expected_names
    ]
    if len(selected) != len(expected_names):
        raise ValueError("현재 Semantic parameter binding 개수가 snapshot과 다릅니다.")
    current: dict[str, tuple[str, Scalar]] = {}
    for item in selected:
        binding = SemanticParameterBinding.model_validate(
            {
                "name": getattr(item, "name", None),
                "value_type": getattr(item, "value_type", None),
                "value": getattr(item, "value", None),
            }
        )
        if binding.name in current:
            raise ValueError("현재 Semantic parameter binding이 중복되었습니다.")
        current[binding.name] = (binding.value_type, binding.value)
    if current != expected:
        raise ValueError("현재 Semantic parameter binding 값이 snapshot과 다릅니다.")


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class _SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticParameterBinding(_SnapshotModel):
    """승인 SQL placeholder에 결속된 이름·타입·스칼라 값을 보존한다."""

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    value_type: Literal["string", "date", "timestamp", "number", "boolean"]
    value: Scalar

    @model_validator(mode="after")
    def validate_value_type(self) -> "SemanticParameterBinding":
        """선언 타입과 값이 어긋난 binding을 저장 전에 거부한다."""

        if self.value is None or isinstance(self.value, (dict, list, tuple)):
            raise ValueError("Semantic parameter binding은 null이 아닌 scalar여야 합니다.")
        if self.value_type in {"string", "date", "timestamp"} and not isinstance(
            self.value, str
        ):
            raise ValueError("문자열 parameter binding의 값 형식이 일치하지 않습니다.")
        if self.value_type == "boolean" and not isinstance(self.value, bool):
            raise ValueError("boolean parameter binding의 값 형식이 일치하지 않습니다.")
        if self.value_type == "number" and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
            or not math.isfinite(self.value)
        ):
            raise ValueError("number parameter binding의 값 형식이 일치하지 않습니다.")
        if self.value_type in {"string", "date", "timestamp"} and not self.value:
            raise ValueError("문자열 parameter binding은 비어 있을 수 없습니다.")
        if self.value_type == "date":
            try:
                date.fromisoformat(self.value)
            except ValueError as error:
                raise ValueError("date parameter binding은 ISO 날짜여야 합니다.") from error
        if self.value_type == "timestamp":
            try:
                parsed = datetime.fromisoformat(self.value)
            except ValueError as error:
                raise ValueError("timestamp parameter binding은 ISO 시각이어야 합니다.") from error
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timestamp parameter binding은 timezone을 포함해야 합니다.")
        return self


class SemanticReleaseReceipt(_SnapshotModel):
    """원 실행의 catalog·제품·권한 release와 projection 무결성 영수증이다."""

    product_release_id: str = Field(min_length=1, max_length=160)
    permission_snapshot_id: str = Field(min_length=1, max_length=160)
    semantic_release_id: str = Field(min_length=1, max_length=160)
    context_release: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=160)
    catalog_checksum: str = Field(pattern=_SHA256_PATTERN)
    canonical_checksum: str = Field(pattern=_SHA256_PATTERN)
    runtime_projection_checksum: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_semantic_release(self) -> "SemanticReleaseReceipt":
        """semantic release와 context release의 교차 결속을 검증한다."""

        if self.semantic_release_id != self.context_release:
            raise ValueError("semantic release와 context release가 일치하지 않습니다.")
        return self


class SemanticLineage(_SnapshotModel):
    """승인 snapshot을 만든 실행·query·artifact를 독립적으로 식별한다."""

    source_request_id: UUID
    query_execution_id: UUID
    artifact_id: UUID


class SemanticDimensionMemberReceipt(_SnapshotModel):
    """승인 Dimension Member의 8개 identity 필드만 snapshot에 허용한다."""

    dimension_id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    member_id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    term_urn: str = Field(pattern=r"^urn:li:glossaryTerm:.+")
    canonical_value: str = Field(min_length=1)
    version: str = Field(min_length=1, max_length=160)
    semantic_sha256: str = Field(pattern=_SHA256_PATTERN)
    asset_fqn: str
    column: str = Field(min_length=1)

    @field_validator("asset_fqn")
    @classmethod
    def validate_asset_fqn(cls, value: str) -> str:
        """Dimension Member asset을 catalog.schema.table FQN으로 제한한다."""

        if len(value.split(".")) != 3 or any(not item for item in value.split(".")):
            raise ValueError("Dimension Member asset FQN이 유효하지 않습니다.")
        return value


class ApprovedSemanticRequestSnapshot(_SnapshotModel):
    """metric·기간·필터·grain과 실행 근거를 canonical hash로 봉인한다."""

    schema_version: Literal[APPROVED_SEMANTIC_REQUEST_VERSION] = (
        APPROVED_SEMANTIC_REQUEST_VERSION
    )
    snapshot_id: UUID
    execution_as_of: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    analysis_plan: dict[str, Any]
    parameter_bindings: tuple[SemanticParameterBinding, ...]
    dimension_member_receipts: tuple[SemanticDimensionMemberReceipt, ...] = ()
    release_receipt: SemanticReleaseReceipt
    lineage: SemanticLineage
    snapshot_hash: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("analysis_plan")
    @classmethod
    def validate_analysis_plan(cls, value: dict[str, Any]) -> dict[str, Any]:
        """AnalysisPlan의 필드·버전·내부 checksum 변조를 차단한다."""

        if set(value) != ANALYSIS_PLAN_FIELDS or value.get("version") != ANALYSIS_PLAN_VERSION:
            raise ValueError("승인 AnalysisPlan version·필드 계약이 일치하지 않습니다.")
        validate_analysis_plan_structure(value)
        return value

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> "ApprovedSemanticRequestSnapshot":
        """binding 고유성과 snapshot 전체 canonical hash를 함께 검증한다."""

        names = [item.name for item in self.parameter_bindings]
        if not names or len(names) != len(set(names)):
            raise ValueError("Semantic parameter binding은 비어 있지 않고 고유해야 합니다.")
        if set(names) != semantic_plan_parameter_names(self.analysis_plan):
            raise ValueError(
                "Semantic parameter binding은 승인 Plan placeholder와 정확히 일치해야 합니다."
            )
        member_ids = [
            (item.dimension_id, item.member_id)
            for item in self.dimension_member_receipts
        ]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Dimension Member receipt는 중복될 수 없습니다.")
        expected = semantic_snapshot_hash(self)
        if self.snapshot_hash != expected:
            raise ValueError("Approved Semantic Request snapshot hash가 일치하지 않습니다.")
        return self

    @property
    def parameters(self) -> dict[str, Scalar]:
        """검증된 binding을 SQL 실행용 이름-값 사전으로 투영한다."""

        self.assert_integrity()
        return {item.name: item.value for item in self.parameter_bindings}

    def assert_integrity(self) -> None:
        """frozen model 내부 컨테이너의 사후 변조까지 replay 직전에 다시 차단한다."""

        # Pydantic의 frozen은 최상위 attribute 재할당만 막고 dict/list 내부 변경은
        # 막지 않는다. 반드시 새 dict로 재검증해 instance 재사용 최적화를 우회한다.
        type(self).model_validate(self.model_dump(mode="python"))

    def structured_request(self) -> dict[str, Any]:
        """원문 없이 current runtime context가 재검증할 typed 의미 요청을 복원한다."""

        self.assert_integrity()
        plan = self.analysis_plan
        parameters = self.parameters
        filters: list[dict[str, Any]] = []
        for item in plan["filter_fields"]:
            parameter = str(item["parameter"])
            if parameter not in parameters:
                raise ValueError("승인 필터 parameter binding이 누락되었습니다.")
            # 구조화 요청은 사용자 의미만 복원한다. 승인 당시 내부 placeholder
            # 이름을 current runtime에 주입하지 않고, 현재 filter 계약이 새 이름을
            # 할당한 뒤 재컴파일된 Plan identity로 drift를 검출한다.
            filters.append(
                {
                    "asset_fqn": str(item["asset_fqn"]),
                    "column": str(item["column"]),
                    "operator": str(item["operator"]),
                    "value_text": str(parameters[parameter]),
                }
            )
        periods: list[dict[str, str]] = []
        for item in plan["period_parameters"]:
            start_name = str(item["start_parameter"])
            end_name = str(item["end_parameter"])
            if start_name not in parameters or end_name not in parameters:
                raise ValueError("승인 기간 parameter binding이 누락되었습니다.")
            periods.append(
                {
                    "start": str(parameters[start_name]),
                    "end_exclusive": str(parameters[end_name]),
                }
            )
        operation = str(plan["operation"])
        output_metric_ids = list(plan["output_metric_ids"])
        return {
            "metric_ids": list(plan["dependency_metric_ids"]),
            "selected_metric_ids": output_metric_ids,
            "selected_metric_id": (
                output_metric_ids[0] if len(output_metric_ids) == 1 else None
            ),
            "dimension_fields": list(plan["dimension_fields"]),
            "filter_fields": filters,
            "dimension_member_receipts": [
                item.model_dump(mode="json") for item in self.dimension_member_receipts
            ],
            "period_candidates": periods,
            "period_relationship": (
                "comparison" if operation == "period_comparison" else "single"
            ),
            "analysis_operation": operation,
            "analysis_time_bucket": plan["time_bucket"],
            "analysis_result_limit": plan["result_limit"],
        }


def semantic_snapshot_hash(snapshot: ApprovedSemanticRequestSnapshot) -> str:
    """snapshot_hash 필드를 제외한 계약 본문에서 canonical SHA-256을 계산한다."""

    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    return _canonical_hash(payload)


def create_approved_semantic_request_snapshot(
    *,
    source_request_id: UUID,
    query_execution_id: UUID,
    artifact_id: UUID,
    execution_as_of: date,
    analysis_plan: Mapping[str, Any],
    parameter_bindings: tuple[object, ...],
    dimension_member_receipts: tuple[object, ...],
    release_receipt: Mapping[str, Any],
) -> ApprovedSemanticRequestSnapshot:
    """검증된 terminal 실행 객체만 canonical snapshot으로 변환한다."""

    identity = {
        "schema_version": APPROVED_SEMANTIC_REQUEST_VERSION,
        "snapshot_id": str(uuid4()),
        "execution_as_of": execution_as_of.isoformat(),
        "timezone": "Asia/Seoul",
        "analysis_plan": dict(analysis_plan),
        "parameter_bindings": [
            {
                "name": str(getattr(item, "name")),
                "value_type": str(getattr(item, "value_type")),
                "value": getattr(item, "value"),
            }
            for item in parameter_bindings
        ],
        "dimension_member_receipts": [
            {
                "dimension_id": str(getattr(item, "dimension_id")),
                "member_id": str(getattr(item, "member_id")),
                "term_urn": str(getattr(item, "term_urn")),
                "canonical_value": str(getattr(item, "canonical_value")),
                "version": str(getattr(item, "version")),
                "semantic_sha256": str(getattr(item, "semantic_sha256")),
                "asset_fqn": str(getattr(item, "asset_fqn")),
                "column": str(getattr(item, "column")),
            }
            for item in dimension_member_receipts
        ],
        "release_receipt": dict(release_receipt),
        "lineage": {
            "source_request_id": str(source_request_id),
            "query_execution_id": str(query_execution_id),
            "artifact_id": str(artifact_id),
        },
    }
    return ApprovedSemanticRequestSnapshot.model_validate(
        {**identity, "snapshot_hash": _canonical_hash(identity)}
    )


def parse_approved_semantic_request_snapshot(
    value: object,
) -> ApprovedSemanticRequestSnapshot:
    """누락·legacy·변조된 payload를 보정하지 않고 typed 오류로 닫는다."""

    if not isinstance(value, Mapping):
        raise ValueError("승인된 Semantic Request snapshot이 없습니다.")
    return ApprovedSemanticRequestSnapshot.model_validate(dict(value))


@dataclass(frozen=True, slots=True)
class SemanticReplayAnalysisRequest:
    """외부 API가 만들 수 없는 snapshot 전용 Analysis pipeline 입력이다."""

    approved_semantic_snapshot: ApprovedSemanticRequestSnapshot
    question: str = _REPLAY_QUESTION
    template_id: None = None
    resolved_slots: None = None

    def __post_init__(self) -> None:
        """pipeline 진입 시 snapshot의 canonical hash와 내부 Plan checksum을 재검증한다."""

        self.approved_semantic_snapshot.assert_integrity()

    @property
    def parameters(self) -> dict[str, Scalar]:
        """외부 override 없이 snapshot에 봉인된 실행 binding만 반환한다."""

        return self.approved_semantic_snapshot.parameters


def semantic_plan_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """현재 권한 package hash만 제외하고 승인된 의미·grain 계약을 비교한다."""

    return {
        key: value[key]
        for key in ANALYSIS_PLAN_FIELDS - {"checksum", "context_package_hash"}
    }
