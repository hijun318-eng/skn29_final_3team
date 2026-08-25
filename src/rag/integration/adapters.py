from __future__ import annotations

import hashlib
from typing import Any

from src.rag.vector_application import VectorRagApplication

from .contracts import DocumentEvidence, IntegrationContext


class RoleMappingError(ValueError):
    pass


class AnswerviceContextAdapter:
    """Converts the current dev RequestContext without importing backend modules."""

    @staticmethod
    def convert(context: Any) -> IntegrationContext:
        role = getattr(context.role, "value", context.role)
        as_of = getattr(context.as_of, "isoformat", lambda: str(context.as_of))()
        conversation_id = getattr(context, "conversation_id", None)
        return IntegrationContext(
            request_id=str(context.request_id),
            trace_id=str(context.trace_id),
            actor_id=str(context.user_id),
            role=str(role),
            as_of=str(as_of),
            session_id=str(conversation_id) if conversation_id else None,
        )


class ApprovedRoleMapper:
    """Requires an explicit approved mapping; no default privilege escalation is provided."""

    def __init__(self, mapping: dict[str, str], approved: bool = False) -> None:
        self._mapping = dict(mapping)
        self._approved = approved

    def map(self, answervice_role: str) -> str:
        if not self._approved:
            raise RoleMappingError("ROLE_MAPPING_NOT_APPROVED")
        try:
            return self._mapping[answervice_role]
        except KeyError as error:
            raise RoleMappingError("ROLE_MAPPING_MISSING") from error


class LocalRagEvidenceAdapter:
    def __init__(
        self,
        application: VectorRagApplication,
        role_mapper: ApprovedRoleMapper,
        top_k: int = 5,
    ) -> None:
        self._application = application
        self._role_mapper = role_mapper
        self._top_k = top_k

    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]:
        role = self._role_mapper.map(context.role)
        actor_hash = hashlib.sha256(context.actor_id.encode("utf-8")).hexdigest()
        payload = self._application.search(
            question,
            role,
            self._top_k,
            request_id=context.request_id,
            trace_id=context.trace_id,
            as_of=context.as_of,
            session_id=context.session_id,
            actor_hash=actor_hash,
            router_decision_id=context.router_decision_id,
            parent_artifact_id=context.parent_artifact_id,
            report_run_id=context.report_run_id,
            recent_utterances=context.recent_utterances,
            selected_document_ids=context.selected_document_ids,
        )
        return tuple(
            DocumentEvidence(
                document_id=str(item["manual_id"]),
                document_title=str(item["title"]),
                document_version=str(item["version"]),
                citation=str(item["citation"]),
                snippet=str(item["snippet"]),
                score=float(item["score"]),
                effective_from=item.get("effective_from"),
                expires_at=item.get("expires_at"),
            )
            for item in payload["results"]
        )
