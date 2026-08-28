"""Capability 호출·결과와 same-release evidence의 내부 versioned 계약을 정의한다.

이 모듈의 모델은 공개 HTTP/MCP schema를 바꾸지 않는다. 외부 요청을 인증·권한·release와
결속한 뒤 생성하는 내부 봉투이며, raw row나 credential 대신 불변 object/evidence 참조만
다음 단계로 전달한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from app.contract_core import ContractModel


CAPABILITY_INVOCATION_VERSION = "CapabilityInvocation.v1"
CAPABILITY_RESULT_VERSION = "CapabilityResult.v1"
EVIDENCE_REF_VERSION = "EvidenceRef.v1"
PRODUCT_RELEASE_EVIDENCE_VERSION = "ProductReleaseEvidenceManifest.v1"

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_IMAGE_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_CAPABILITY_PATTERN = r"^[a-z][a-z0-9_.-]{1,127}$"
_SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"


class ImmutableContractModel(ContractModel):
    """승인 뒤 값이 바뀌지 않는 내부 계약의 공통 기반이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceKind(str, Enum):
    """사실·문서·예측·추론을 혼합하지 않게 하는 evidence authority 분류다."""

    OBSERVED_DATA = "OBSERVED_DATA"
    DOCUMENTED_CONTEXT = "DOCUMENTED_CONTEXT"
    MODEL_PREDICTION = "MODEL_PREDICTION"
    DERIVED_INFERENCE = "DERIVED_INFERENCE"


class ReleaseBoundObjectKind(str, Enum):
    """제품 release receipt를 영속적으로 고정해야 하는 객체 유형이다."""

    CONVERSATION = "CONVERSATION"
    TURN = "TURN"
    CONTEXT = "CONTEXT"
    RUN = "RUN"
    ARTIFACT = "ARTIFACT"
    VIEW = "VIEW"
    REPORT = "REPORT"


class CapabilityResultStatus(str, Enum):
    """Capability가 반환할 수 있는 terminal 상태다."""

    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CapabilityReasonCode(str, Enum):
    """Capability 계층에서 소비자가 분기할 수 있는 안정적인 실패 분류다."""

    ACCESS_DENIED = "ACCESS_DENIED"
    CONTEXT_INCOMPLETE = "CONTEXT_INCOMPLETE"
    RELEASE_MISMATCH = "RELEASE_MISMATCH"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class CapabilityObjectRef(ImmutableContractModel):
    """다른 단계가 원문 대신 전달할 수 있는 immutable object 참조다."""

    object_kind: ReleaseBoundObjectKind
    object_id: str = Field(min_length=1, max_length=256)
    checksum_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)


class EvidenceRef(ImmutableContractModel):
    """근거의 권위 종류·저장 객체·checksum·release를 가리키는 참조 전용 계약이다."""

    schema_version: Literal["EvidenceRef.v1"] = EVIDENCE_REF_VERSION
    evidence_id: UUID
    kind: EvidenceKind
    object_ref: CapabilityObjectRef
    checksum_sha256: str = Field(pattern=_SHA256_PATTERN)
    product_release_id: str = Field(min_length=1, max_length=160)
    observed_at: AwareDatetime


class CapabilityBudget(ImmutableContractModel):
    """한 호출이 사용할 수 있는 시간·token·tool·query 상한이다."""

    wall_clock_ms: int = Field(ge=1, le=3_600_000)
    model_tokens: int = Field(ge=0, le=1_000_000)
    tool_calls: int = Field(ge=0, le=1_000)
    queries: int = Field(ge=0, le=1_000)


PayloadT = TypeVar("PayloadT")


class CapabilityInvocation(ImmutableContractModel, Generic[PayloadT]):
    """서버가 admission 시 권한·release·canonical hash를 확정한 호출 봉투다."""

    schema_version: Literal["CapabilityInvocation.v1"] = CAPABILITY_INVOCATION_VERSION
    invocation_id: UUID
    request_id: UUID
    conversation_id: UUID | None = None
    turn_id: UUID | None = None
    capability: str = Field(pattern=_CAPABILITY_PATTERN)
    capability_version: str = Field(pattern=_SEMVER_PATTERN)
    payload: PayloadT
    effective_subject_id: UUID
    permission_snapshot_id: str = Field(min_length=1, max_length=160)
    product_release_id: str = Field(min_length=1, max_length=160)
    capability_release_vector: dict[str, str] = Field(min_length=1)
    source_turn_refs: tuple[CapabilityObjectRef, ...] = ()
    source_artifact_refs: tuple[CapabilityObjectRef, ...] = ()
    deadline_at: AwareDatetime
    budget: CapabilityBudget
    idempotency_key: str = Field(min_length=1, max_length=128)
    canonical_input_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_reference_kinds(self) -> "CapabilityInvocation[PayloadT]":
        """source 참조가 이름과 다른 객체 유형을 가리키는 것을 거부한다."""

        if any(ref.object_kind is not ReleaseBoundObjectKind.TURN for ref in self.source_turn_refs):
            raise ValueError("source_turn_refs에는 TURN 참조만 허용됩니다.")
        if any(
            ref.object_kind is not ReleaseBoundObjectKind.ARTIFACT
            for ref in self.source_artifact_refs
        ):
            raise ValueError("source_artifact_refs에는 ARTIFACT 참조만 허용됩니다.")
        if any(not key.strip() or not value.strip() for key, value in self.capability_release_vector.items()):
            raise ValueError("capability release vector의 key와 value는 비어 있을 수 없습니다.")
        return self


class CapabilityClarification(ImmutableContractModel):
    """BLOCKED 결과가 사용자에게 요구할 구조화된 보완 정보다."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    message: str = Field(min_length=1, max_length=500)
    required_fields: tuple[str, ...] = ()


class CapabilityCoverage(ImmutableContractModel):
    """요청한 범위 중 실제로 충족한 단위를 명시한다."""

    requested: tuple[str, ...] = ()
    satisfied: tuple[str, ...] = ()
    complete: bool

    @model_validator(mode="after")
    def validate_coverage(self) -> "CapabilityCoverage":
        """충족 범위의 중복·범위 이탈과 complete 표기의 불일치를 거부한다."""

        requested = set(self.requested)
        satisfied = set(self.satisfied)
        if len(requested) != len(self.requested) or len(satisfied) != len(self.satisfied):
            raise ValueError("coverage 항목은 중복될 수 없습니다.")
        if not satisfied.issubset(requested):
            raise ValueError("satisfied coverage는 requested 범위를 벗어날 수 없습니다.")
        if self.complete != (requested == satisfied):
            raise ValueError("complete 값은 requested/satisfied 집합과 일치해야 합니다.")
        return self


class CapabilityWarning(ImmutableContractModel):
    """성공 또는 부분 성공에서 소비자가 확인해야 할 typed 경고다."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    message: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[UUID, ...] = ()


class CapabilityResult(ImmutableContractModel, Generic[PayloadT]):
    """Capability terminal 상태와 typed 결과·근거·release receipt를 반환한다."""

    schema_version: Literal["CapabilityResult.v1"] = CAPABILITY_RESULT_VERSION
    invocation_id: UUID
    request_id: UUID
    conversation_id: UUID | None = None
    turn_id: UUID | None = None
    status: CapabilityResultStatus
    payload: PayloadT | None = None
    reason_code: CapabilityReasonCode | None = None
    clarification: CapabilityClarification | None = None
    artifact_refs: tuple[CapabilityObjectRef, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    coverage: CapabilityCoverage
    warnings: tuple[CapabilityWarning, ...] = ()
    product_release_id: str = Field(min_length=1, max_length=160)
    permission_snapshot_id: str = Field(min_length=1, max_length=160)
    capability_release_vector: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_terminal_semantics(self) -> "CapabilityResult[PayloadT]":
        """terminal 상태별 payload·사유·coverage·clarification 결속을 검증한다."""

        if any(ref.object_kind is not ReleaseBoundObjectKind.ARTIFACT for ref in self.artifact_refs):
            raise ValueError("artifact_refs에는 ARTIFACT 참조만 허용됩니다.")
        if self.status is CapabilityResultStatus.SUCCEEDED:
            if self.reason_code is not None or self.clarification is not None:
                raise ValueError("SUCCEEDED 결과에는 실패 사유나 clarification을 둘 수 없습니다.")
            if not self.coverage.complete:
                raise ValueError("SUCCEEDED 결과의 coverage는 complete여야 합니다.")
        elif self.reason_code is None:
            raise ValueError("성공 외 결과에는 typed reason_code가 필요합니다.")
        if self.status is CapabilityResultStatus.PARTIAL and self.coverage.complete:
            raise ValueError("PARTIAL 결과의 coverage는 incomplete여야 합니다.")
        if self.clarification is not None and self.status is not CapabilityResultStatus.BLOCKED:
            raise ValueError("clarification은 BLOCKED 결과에서만 허용됩니다.")
        return self


class SourceReceipt(ImmutableContractModel):
    """release를 만든 source commit과 dirty patch의 비밀 없는 digest다."""

    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    dirty: bool
    dirty_patch_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_dirty_receipt(self) -> "SourceReceipt":
        """dirty 표기와 비밀 없는 patch digest가 함께 존재하거나 함께 없도록 강제한다."""

        if self.dirty != (self.dirty_patch_sha256 is not None):
            raise ValueError("dirty source에는 patch digest가 필요하고 clean source에는 없어야 합니다.")
        return self


class ImageReceipt(ImmutableContractModel):
    """제품 release를 구성하는 실행 component와 container image digest다."""

    component: str = Field(min_length=1, max_length=128)
    digest: str = Field(pattern=_IMAGE_DIGEST_PATTERN)


class MigrationReceipt(ImmutableContractModel):
    """App DB schema revision과 migration chain checksum이다."""

    revision: str = Field(min_length=1, max_length=64)
    chain_sha256: str = Field(pattern=_SHA256_PATTERN)


class ModelReceipt(ImmutableContractModel):
    """모델·prompt/schema를 포함한 검증된 model manifest receipt다."""

    release_id: str = Field(min_length=1, max_length=160)
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)


class CatalogReceipt(ImmutableContractModel):
    """DataHub source release와 compiled semantic projection checksum이다."""

    release_id: str = Field(min_length=1, max_length=256)
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    projection_sha256: str = Field(pattern=_SHA256_PATTERN)


class ProductReleaseVector(ImmutableContractModel):
    """제품 실행 결과를 재현하는 data/semantic/prompt/policy/runtime 축이다."""

    data_release_id: str = Field(min_length=1, max_length=256)
    semantic_release_id: str = Field(min_length=1, max_length=256)
    prompt_release_id: str = Field(min_length=1, max_length=160)
    policy_release_id: str = Field(min_length=1, max_length=160)
    runtime_release_id: str = Field(min_length=1, max_length=160)


class ProductReleaseEvidence(ImmutableContractModel):
    """source/image/migration/model/catalog와 전체 release vector의 typed 내용이다."""

    source: SourceReceipt
    images: tuple[ImageReceipt, ...] = Field(min_length=1)
    migration: MigrationReceipt
    model: ModelReceipt
    catalog: CatalogReceipt
    release_vector: ProductReleaseVector

    @model_validator(mode="after")
    def validate_unique_components(self) -> "ProductReleaseEvidence":
        """한 제품 release에 같은 image component가 중복 결속되는 것을 거부한다."""

        components = [image.component for image in self.images]
        if len(components) != len(set(components)):
            raise ValueError("image component는 중복될 수 없습니다.")
        return self


class ProductReleaseEvidenceManifest(ImmutableContractModel):
    """제품 release와 그 실행 evidence를 canonical checksum으로 봉인한다."""

    schema_version: Literal["ProductReleaseEvidenceManifest.v1"] = PRODUCT_RELEASE_EVIDENCE_VERSION
    product_release_id: str = Field(min_length=1, max_length=160)
    evidence: ProductReleaseEvidence
    created_at: AwareDatetime
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)

    @staticmethod
    def _checksum_payload(
        product_release_id: str,
        evidence: ProductReleaseEvidence,
        created_at: datetime,
    ) -> dict[str, JsonValue]:
        return {
            "schema_version": PRODUCT_RELEASE_EVIDENCE_VERSION,
            "product_release_id": product_release_id,
            "evidence": evidence.model_dump(mode="json"),
            "created_at": created_at.isoformat(),
        }

    @classmethod
    def seal(
        cls,
        *,
        product_release_id: str,
        evidence: ProductReleaseEvidence,
        created_at: datetime | None = None,
    ) -> "ProductReleaseEvidenceManifest":
        """제품 evidence와 생성 시각을 canonical checksum으로 봉인한 manifest를 만든다."""

        timestamp = created_at or datetime.now(timezone.utc)
        digest = _canonical_sha256(
            cls._checksum_payload(product_release_id, evidence, timestamp)
        )
        return cls(
            product_release_id=product_release_id,
            evidence=evidence,
            created_at=timestamp,
            manifest_sha256=digest,
        )

    @model_validator(mode="after")
    def validate_manifest_checksum(self) -> "ProductReleaseEvidenceManifest":
        """직렬화된 evidence를 재계산해 변조되거나 잘못 결속된 manifest를 거부한다."""

        expected = _canonical_sha256(
            self._checksum_payload(
                self.product_release_id,
                self.evidence,
                self.created_at,
            )
        )
        if self.manifest_sha256 != expected:
            raise ValueError("product release evidence manifest checksum이 일치하지 않습니다.")
        return self


def _canonical_sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()
