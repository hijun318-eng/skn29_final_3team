"""승인된 DataHub·RAG 검색 후보만으로 Agent capability 적합성을 판정한다.

이 모듈의 probe는 답변을 생성하거나 Agent를 실행하지 않는다. 공통 Conversation
admission이 고정한 권한·product/semantic release를 그대로 사용해 bounded 후보만 찾고,
원문이나 후보 metadata를 노출하지 않는 checksum reference를 반환한다.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Protocol
from uuid import UUID

from app.authorization import has_capability, permission_snapshot_id
from app.contracts import Capability
from app.ports.agent import AgentKind, AgentRequest
from app.ports.data_platform import (
    AssetCandidateSet,
    DataPlatformAdapter,
    MetadataUnavailableError,
    NoEntitledAssetsError,
)
from app.services.agent_supervisor import (
    AgentCapabilityEvidence,
    AgentDispatchError,
)
from app.services.ml_prediction_service import (
    MLDeploymentPolicyError,
    MLRuntimeCapability,
    require_production_ml_capability,
)
from app.services.rag_gateway import RAG_MAX_EMBEDDING_DIMENSION


ANALYSIS_CAPABILITY_PROBE_VERSION = "GovernedAnalysisCapabilityProbe.v1"
INTERNAL_GUIDELINE_CAPABILITY_PROBE_VERSION = (
    "InternalGuidelineCapabilityProbe.v1"
)
_EVIDENCE_REFERENCE_PREFIX = "agent-capability:v1:analysis-workflow:"
_RAG_EVIDENCE_REFERENCE_PREFIX = "agent-capability:v1:internal-guideline:"
_ML_EVIDENCE_REFERENCE_PREFIX = "agent-capability:v1:ml-prediction:"
_APPROVED_SOURCE_AUTHORITIES = frozenset(
    {
        "DATAHUB_NATIVE_METRIC_V1",
        "DATAHUB_GLOSSARY_MIGRATION_V1",
    }
)
_APPROVED_RETRIEVAL_MODES = frozenset(
    {"lexical", "lexical_shadow", "datahub_lexical", "hybrid"}
)


def _validate_admitted_request(request: AgentRequest) -> None:
    """모든 capability probe가 같은 admission·권한 snapshot을 사용하게 고정한다."""

    context = request.context
    required = (
        context.permission_snapshot_id,
        context.product_release_id,
        context.semantic_release_id,
        context.command_id,
    )
    if context.conversation_id != request.conversation_id or not all(required):
        raise AgentDispatchError(
            "AGENT_CAPABILITY_CONTEXT_INCOMPLETE",
            "Agent capability probe에는 승인된 command context가 필요합니다.",
        )
    expected_permission = permission_snapshot_id(context.user_id, context.role)
    if context.permission_snapshot_id != expected_permission:
        raise AgentDispatchError(
            "AGENT_CAPABILITY_PERMISSION_MISMATCH",
            "Agent capability probe의 권한 snapshot이 현재 주체와 다릅니다.",
        )


class InternalGuidelineCapabilitySearcher(Protocol):
    """답변을 만들지 않고 승인 문서 검색 후보만 반환하는 RAG adapter다."""

    async def search_capability(
        self,
        query: str,
        app_role: str,
    ) -> dict[str, Any]:
        """원문을 제외한 versioned capability 후보를 반환한다."""

        ...


class MLPredictionCapabilityReader(Protocol):
    """예측을 실행하지 않고 현재 ML release 범위만 읽는 경계다."""

    async def capabilities(self) -> dict[str, Any]:
        """versioned 모델·property·기간 capability를 반환한다."""

        ...


class GovernedAnalysisCapabilityProbe:
    """DataHub Runtime Catalog의 권한 필터된 후보로 분석 적합성만 확인한다."""

    agent = AgentKind.ANALYSIS_WORKFLOW

    def __init__(self, data_platform: DataPlatformAdapter) -> None:
        self._data_platform = data_platform

    async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
        """admission receipt와 같은 release에서 BUSINESS Metric 후보가 있는지 판정한다."""

        _validate_admitted_request(request)
        if not has_capability(request.context.role, Capability.RUN_ANALYSIS):
            return self._evidence(
                request,
                matched=False,
                outcome="ANALYSIS_CAPABILITY_NOT_ENTITLED",
            )

        try:
            candidates = await self._data_platform.search_asset_candidates(
                request.command.user_message,
                request.context.model_dump(mode="json"),
            )
        except NoEntitledAssetsError:
            return self._evidence(
                request,
                matched=False,
                outcome="ANALYSIS_CAPABILITY_NOT_FOUND",
            )

        metric_ids, asset_urns = self._validate_candidates(request, candidates)
        return self._evidence(
            request,
            matched=True,
            outcome="ANALYSIS_CAPABILITY_MATCH",
            candidate_receipt={
                "catalog_sha256": candidates.catalog_checksum,
                "canonical_sha256": candidates.canonical_checksum,
                "runtime_projection_sha256": (
                    candidates.runtime_projection_checksum
                ),
                "source_authority": candidates.source_authority,
                "retrieval_mode": candidates.retrieval_mode,
                "metric_ids": metric_ids,
                "asset_urns": asset_urns,
            },
        )

    @staticmethod
    def _validate_candidates(
        request: AgentRequest,
        candidates: AssetCandidateSet,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """후보가 admission과 같은 release의 완전한 BUSINESS projection인지 확인한다."""

        context = request.context
        if (
            candidates.product_release_id != context.product_release_id
            or candidates.context_release != context.semantic_release_id
            or candidates.runtime_projection_checksum is None
            or candidates.source_authority not in _APPROVED_SOURCE_AUTHORITIES
            or candidates.retrieval_mode not in _APPROVED_RETRIEVAL_MODES
        ):
            raise MetadataUnavailableError(
                "analysis capability candidate release receipt is incomplete or changed"
            )

        metric_ids = tuple(
            sorted(
                {
                    str(metric.get("id") or "").strip()
                    for asset in candidates.assets
                    for metric in asset.get("metrics", ())
                    if isinstance(metric, dict)
                    and metric.get("visibility", "BUSINESS") == "BUSINESS"
                    and metric.get("candidate_selectable") is True
                    and str(metric.get("id") or "").strip()
                }
            )
        )
        asset_urns = tuple(
            sorted(
                {
                    str(asset.get("urn") or "").strip()
                    for asset in candidates.assets
                    if str(asset.get("urn") or "").strip()
                }
            )
        )
        if not metric_ids or not asset_urns:
            raise MetadataUnavailableError(
                "analysis capability candidate evidence is incomplete"
            )
        return metric_ids, asset_urns

    @classmethod
    def _evidence(
        cls,
        request: AgentRequest,
        *,
        matched: bool,
        outcome: str,
        candidate_receipt: dict[str, Any] | None = None,
    ) -> AgentCapabilityEvidence:
        """민감 원문 없이 request·권한·release·검색 결과를 canonical hash로 봉인한다."""

        context = request.context
        canonical = {
            "schema_version": ANALYSIS_CAPABILITY_PROBE_VERSION,
            "agent": cls.agent.value,
            "request_id": str(context.request_id),
            "trace_id": context.trace_id,
            "conversation_id": str(request.conversation_id),
            "command_id": str(context.command_id),
            "effective_subject_id": str(context.user_id),
            "permission_snapshot_id": context.permission_snapshot_id,
            "product_release_id": context.product_release_id,
            "semantic_release_id": context.semantic_release_id,
            "as_of": context.as_of.isoformat(),
            "timezone": context.timezone,
            "question_sha256": hashlib.sha256(
                request.command.user_message.encode("utf-8")
            ).hexdigest(),
            "matched": matched,
            "outcome": outcome,
            "candidate_receipt": candidate_receipt,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return AgentCapabilityEvidence(
            agent=cls.agent,
            matched=matched,
            reason=(
                "ANALYSIS_CAPABILITY_MATCH"
                if matched
                else "ANALYSIS_CAPABILITY_NOT_MATCHED"
            ),
            evidence_refs=(f"{_EVIDENCE_REFERENCE_PREFIX}{digest}",),
        )


class InternalGuidelineCapabilityProbe:
    """승인된 RAG 검색만 호출해 내부지침 Agent 적합성을 판정한다."""

    agent = AgentKind.INTERNAL_GUIDELINE
    _CANDIDATE_KEYS = frozenset(
        {
            "schema_version",
            "matched",
            "retrieval_request_id",
            "query_hash",
            "tool_code",
            "tool_version",
            "model_revision",
            "embedding_dimension",
            "evidence_ids",
            "document_ids",
            "maximum_score",
        }
    )

    def __init__(self, searcher: InternalGuidelineCapabilitySearcher) -> None:
        self._searcher = searcher

    async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
        """admission 뒤 검색 결과를 검증하고 원문 없는 checksum receipt만 반환한다."""

        _validate_admitted_request(request)
        if not has_capability(request.context.role, Capability.RUN_ANALYSIS):
            return self._evidence(
                request,
                matched=False,
                outcome="RAG_CAPABILITY_NOT_ENTITLED",
            )
        candidate = await self._searcher.search_capability(
            request.command.user_message,
            request.context.role.value,
        )
        validated = self._validate_candidate(candidate)
        return self._evidence(
            request,
            matched=bool(validated["matched"]),
            outcome=(
                "RAG_CAPABILITY_MATCH"
                if validated["matched"]
                else "RAG_CAPABILITY_NOT_FOUND"
            ),
            candidate_receipt=validated,
        )

    @classmethod
    def _validate_candidate(cls, candidate: object) -> dict[str, Any]:
        """RAG 원문·임의 필드가 route receipt에 유입되지 않도록 exact 계약을 검사한다."""

        if not isinstance(candidate, dict) or set(candidate) != cls._CANDIDATE_KEYS:
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 후보 형식이 올바르지 않습니다.",
            )
        matched = candidate["matched"]
        evidence_ids = candidate["evidence_ids"]
        document_ids = candidate["document_ids"]
        maximum_score = candidate["maximum_score"]
        try:
            UUID(str(candidate["retrieval_request_id"]))
        except ValueError as error:
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 요청 식별자가 올바르지 않습니다.",
            ) from error
        if (
            candidate["schema_version"] != "RagCapabilityCandidate.v1"
            or type(matched) is not bool
            or not re.fullmatch(r"[0-9a-f]{64}", str(candidate["query_hash"]))
            or candidate["tool_code"] != "internal-manual-search"
            or not isinstance(candidate["tool_version"], str)
            or not candidate["tool_version"].strip()
            or not isinstance(candidate["model_revision"], str)
            or not candidate["model_revision"].strip()
            or isinstance(candidate["embedding_dimension"], bool)
            or not isinstance(candidate["embedding_dimension"], int)
            or not 1
            <= candidate["embedding_dimension"]
            <= RAG_MAX_EMBEDDING_DIMENSION
            or not isinstance(evidence_ids, list)
            or not isinstance(document_ids, list)
            or len(evidence_ids) != len(set(evidence_ids))
            or len(document_ids) != len(set(document_ids))
            or any(not isinstance(item, str) or not item for item in evidence_ids)
            or any(not isinstance(item, str) or not item for item in document_ids)
            or len(evidence_ids) > 50
            or len(document_ids) > 10
        ):
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 후보 근거가 올바르지 않습니다.",
            )
        if matched:
            if (
                not evidence_ids
                or not document_ids
                or isinstance(maximum_score, bool)
                or not isinstance(maximum_score, (int, float))
                or not math.isfinite(float(maximum_score))
                or not 0 < float(maximum_score) <= 1
            ):
                raise AgentDispatchError(
                    "AGENT_CAPABILITY_EVIDENCE_INVALID",
                    "매칭된 RAG capability 후보에 승인 근거가 없습니다.",
                )
        elif evidence_ids or document_ids or maximum_score is not None:
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "근거 없음 RAG capability 후보가 검색 근거를 포함합니다.",
            )
        return dict(candidate)

    @classmethod
    def _evidence(
        cls,
        request: AgentRequest,
        *,
        matched: bool,
        outcome: str,
        candidate_receipt: dict[str, Any] | None = None,
    ) -> AgentCapabilityEvidence:
        """질문·검색 본문 없이 admission과 후보 식별자만 canonical hash로 봉인한다."""

        context = request.context
        canonical = {
            "schema_version": INTERNAL_GUIDELINE_CAPABILITY_PROBE_VERSION,
            "agent": cls.agent.value,
            "request_id": str(context.request_id),
            "trace_id": context.trace_id,
            "conversation_id": str(request.conversation_id),
            "command_id": str(context.command_id),
            "effective_subject_id": str(context.user_id),
            "permission_snapshot_id": context.permission_snapshot_id,
            "product_release_id": context.product_release_id,
            "semantic_release_id": context.semantic_release_id,
            "as_of": context.as_of.isoformat(),
            "timezone": context.timezone,
            "question_sha256": hashlib.sha256(
                request.command.user_message.encode("utf-8")
            ).hexdigest(),
            "matched": matched,
            "outcome": outcome,
            "candidate_receipt": candidate_receipt,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return AgentCapabilityEvidence(
            agent=cls.agent,
            matched=matched,
            reason=(
                "RAG_CAPABILITY_MATCH"
                if matched
                else "RAG_CAPABILITY_NOT_MATCHED"
            ),
            evidence_refs=(f"{_RAG_EVIDENCE_REFERENCE_PREFIX}{digest}",),
        )


class MLPredictionCapabilityProbe:
    """구조화 invocation과 현재 모델 capability만 비교하는 search-only probe다."""

    agent = AgentKind.ML_PREDICTION

    def __init__(self, reader: MLPredictionCapabilityReader) -> None:
        self._reader = reader

    async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
        """자연어·예측 실행 없이 property·date·horizon 범위 적합성만 판정한다."""

        _validate_admitted_request(request)
        invocation = request.invocation
        if (
            invocation is None
            or not has_capability(request.context.role, Capability.RUN_ANALYSIS)
        ):
            return self._evidence(
                request,
                matched=False,
                outcome=(
                    "STRUCTURED_INVOCATION_MISSING"
                    if invocation is None
                    else "ROLE_NOT_ENTITLED"
                ),
            )
        try:
            capability = require_production_ml_capability(
                MLRuntimeCapability.model_validate(
                    await self._reader.capabilities()
                )
            )
        except MLDeploymentPolicyError as error:
            return self._evidence(
                request,
                matched=False,
                outcome=error.code,
            )
        except Exception as error:
            raise AgentDispatchError(
                "AGENT_CAPABILITY_EVIDENCE_INVALID",
                "ML capability 후보 근거가 올바르지 않습니다.",
            ) from error

        property_capability = next(
            (
                item
                for item in capability.properties
                if item.property_id.upper() == invocation.property_id.upper()
            ),
            None,
        )
        matched = bool(
            property_capability is not None
            and capability.min_horizon_days
            <= invocation.horizon_days
            <= capability.max_horizon_days
            and property_capability.min_as_of
            <= invocation.as_of
            <= property_capability.max_as_of
        )
        capability_payload = capability.model_dump(mode="json")
        capability_digest = hashlib.sha256(
            json.dumps(
                capability_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return self._evidence(
            request,
            matched=matched,
            outcome=(
                "ML_CAPABILITY_MATCH"
                if matched
                else "ML_CAPABILITY_NOT_MATCHED"
            ),
            capability_receipt={
                "schema_version": capability.schema_version,
                "model_hash": capability.model_hash,
                "capability_sha256": capability_digest,
            },
        )

    @classmethod
    def _evidence(
        cls,
        request: AgentRequest,
        *,
        matched: bool,
        outcome: str,
        capability_receipt: dict[str, str] | None = None,
    ) -> AgentCapabilityEvidence:
        """구조화 입력 원문 대신 canonical hash와 release receipt만 봉인한다."""

        context = request.context
        invocation = request.invocation
        invocation_hash = (
            hashlib.sha256(
                json.dumps(
                    invocation.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if invocation is not None
            else None
        )
        canonical = {
            "schema_version": "MLPredictionCapabilityProbe.v1",
            "agent": cls.agent.value,
            "request_id": str(context.request_id),
            "conversation_id": str(request.conversation_id),
            "command_id": str(context.command_id),
            "effective_subject_id": str(context.user_id),
            "permission_snapshot_id": context.permission_snapshot_id,
            "product_release_id": context.product_release_id,
            "semantic_release_id": context.semantic_release_id,
            "invocation_sha256": invocation_hash,
            "matched": matched,
            "outcome": outcome,
            "capability_receipt": capability_receipt,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return AgentCapabilityEvidence(
            agent=cls.agent,
            matched=matched,
            reason=(
                "ML_CAPABILITY_MATCH"
                if matched
                else (
                    outcome
                    if outcome.startswith("ML_")
                    else "ML_CAPABILITY_NOT_MATCHED"
                )
            ),
            evidence_refs=(f"{_ML_EVIDENCE_REFERENCE_PREFIX}{digest}",),
        )
