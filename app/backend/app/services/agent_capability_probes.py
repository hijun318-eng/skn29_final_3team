"""승인된 metadata 검색만으로 Agent capability 적합성을 판정한다.

이 모듈의 probe는 답변을 생성하거나 Agent를 실행하지 않는다. 공통 Conversation
admission이 고정한 권한·product/semantic release를 그대로 사용해 bounded 후보만 찾고,
원문이나 후보 metadata를 노출하지 않는 checksum reference를 반환한다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

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


ANALYSIS_CAPABILITY_PROBE_VERSION = "GovernedAnalysisCapabilityProbe.v1"
_EVIDENCE_REFERENCE_PREFIX = "agent-capability:v1:analysis-workflow:"
_APPROVED_SOURCE_AUTHORITIES = frozenset(
    {
        "DATAHUB_NATIVE_METRIC_V1",
        "DATAHUB_GLOSSARY_MIGRATION_V1",
    }
)
_APPROVED_RETRIEVAL_MODES = frozenset(
    {"lexical", "lexical_shadow", "datahub_lexical", "hybrid"}
)


class GovernedAnalysisCapabilityProbe:
    """DataHub Runtime Catalog의 권한 필터된 후보로 분석 적합성만 확인한다."""

    agent = AgentKind.ANALYSIS_WORKFLOW

    def __init__(self, data_platform: DataPlatformAdapter) -> None:
        self._data_platform = data_platform

    async def probe(self, request: AgentRequest) -> AgentCapabilityEvidence:
        """admission receipt와 같은 release에서 BUSINESS Metric 후보가 있는지 판정한다."""

        self._validate_admitted_request(request)
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
    def _validate_admitted_request(request: AgentRequest) -> None:
        """route probe가 idempotency·release admission보다 먼저 실행되지 않게 한다."""

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
