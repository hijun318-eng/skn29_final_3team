"""백엔드 요청 문맥과 애플리케이션 RAG 검색 결과를 통합 계층의 typed 계약으로 변환한다."""

from __future__ import annotations

import hashlib
from typing import Any

from src.rag.vector_application import VectorRagApplication

from .contracts import DocumentEvidence, IntegrationContext


class RoleMappingError(ValueError):
    """백엔드 역할의 RAG 역할 매핑이 미승인되었거나 정의되지 않았을 때 발생한다."""


class AnswerviceContextAdapter:
    """백엔드 모듈을 직접 의존하지 않고 RequestContext 속성을 통합 문맥으로 옮긴다."""

    @staticmethod
    def convert(context: Any) -> IntegrationContext:
        """요청·trace·사용자·역할·기준일과 선택적 대화 ID를 문자열 문맥으로 정규화한다."""

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
    """명시적으로 승인된 역할 대응표만 사용하며 기본 역할이나 권한 상승 fallback을 두지 않는다."""

    def __init__(self, mapping: dict[str, str], approved: bool = False) -> None:
        self._mapping = dict(mapping)
        self._approved = approved

    def map(self, answervice_role: str) -> str:
        """백엔드 역할을 승인된 RAG 역할로 변환하고 미승인·누락 매핑은 서로 다른 코드로 거부한다."""

        if not self._approved:
            raise RoleMappingError("ROLE_MAPPING_NOT_APPROVED")
        try:
            return self._mapping[answervice_role]
        except KeyError as error:
            raise RoleMappingError("ROLE_MAPPING_MISSING") from error


class LocalRagEvidenceAdapter:
    """통합 문맥을 권한 필터된 로컬 Vector RAG 검색에 전달해 문서 근거로 변환한다."""

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
        """질문과 추적 문맥으로 검색하고 각 결과의 출처·인용·유효기간을 typed 근거로 반환한다."""

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
