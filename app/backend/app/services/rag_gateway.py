"""승인된 RAG Tool을 HMAC으로 호출하고 최소 실행 근거를 App DB에 남긴다."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import time
import unicodedata
from typing import Any, Mapping, NoReturn
from urllib.parse import quote, unquote_to_bytes
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import session_scope


RAG_TOOL_DESCRIPTOR: dict[str, Any] = {
    "tool_id": UUID("8edce655-e454-5b76-b56f-5e49aa2884d4"),
    "tool_code": "rag.answer",
    "semantic_version": "1.2.0",
    "title": "Answer from Internal Documents",
    "description": (
        "Answer only from approved internal documents with citation-bound evidence."
    ),
    "transport": "MCP_STREAMABLE_HTTP",
    "timeout_seconds": 30,
    "required_roles": ("analyst",),
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 2, "maxLength": 500},
            "selected_document_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 100},
                "maxItems": 10,
                "uniqueItems": True,
            },
            "recent_utterances": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
                "maxItems": 3,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ANSWER", "NO_EVIDENCE", "CONFLICT"],
            },
            "trace_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "answer": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "evidence_id": {"type": "string", "minLength": 1},
                        "citation": {"type": "string"},
                    },
                    "required": ["evidence_id", "citation"],
                    "additionalProperties": False,
                },
            },
            "evidence_bundle": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "evidence_id": {"type": "string", "minLength": 1},
                        "document_id": {"type": "string", "minLength": 1},
                        "document_name": {"type": "string"},
                        "section": {"type": "string"},
                        "snippet": {"type": "string"},
                        "score": {"type": "number", "minimum": 0},
                    },
                    "required": [
                        "evidence_id",
                        "document_id",
                        "document_name",
                        "section",
                        "snippet",
                        "score",
                    ],
                    "additionalProperties": False,
                },
            },
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "minLength": 1},
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 2,
                            "uniqueItems": True,
                        },
                    },
                    "required": ["description", "evidence_ids"],
                    "additionalProperties": False,
                },
                "minItems": 1,
            },
        },
        "required": ["status", "trace_id", "evidence_bundle"],
        "additionalProperties": False,
        "allOf": [
            {
                "if": {
                    "properties": {"status": {"enum": ["ANSWER", "NO_EVIDENCE"]}}
                },
                "then": {
                    "required": ["answer", "citations"],
                    "not": {"required": ["conflicts"]},
                },
            },
            {
                "if": {"properties": {"status": {"const": "CONFLICT"}}},
                "then": {
                    "required": ["conflicts"],
                    "not": {
                        "anyOf": [
                            {"required": ["answer"]},
                            {"required": ["citations"]},
                        ]
                    },
                },
            },
        ],
    },
}
RAG_TOOL_ID = RAG_TOOL_DESCRIPTOR["tool_id"]
RAG_TOOL_CODE = RAG_TOOL_DESCRIPTOR["tool_code"]
RAG_TOOL_SEMANTIC_VERSION = RAG_TOOL_DESCRIPTOR["semantic_version"]
RAG_TOOL_TITLE = RAG_TOOL_DESCRIPTOR["title"]
RAG_TOOL_DESCRIPTION = RAG_TOOL_DESCRIPTOR["description"]
RAG_TOOL_TRANSPORT = RAG_TOOL_DESCRIPTOR["transport"]
RAG_TOOL_TIMEOUT_SECONDS = RAG_TOOL_DESCRIPTOR["timeout_seconds"]
RAG_TOOL_ROLES = RAG_TOOL_DESCRIPTOR["required_roles"]
RAG_TOOL_ANNOTATIONS = RAG_TOOL_DESCRIPTOR["annotations"]
RAG_TOOL_INPUT_SCHEMA = RAG_TOOL_DESCRIPTOR["input_schema"]
RAG_TOOL_OUTPUT_SCHEMA = RAG_TOOL_DESCRIPTOR["output_schema"]
RAG_CAPABILITY_CANDIDATE_VERSION = "RagCapabilityCandidate.v1"
RAG_RUNTIME_RECEIPT_VERSION = "RagRuntimeReceipt.v1"
RAG_MAX_EMBEDDING_DIMENSION = 65536
RAG_SOURCE_MAX_BODY_BYTES = 32 * 1024 * 1024
RAG_SOURCE_MEDIA_TYPES = {
    "application/pdf": (".pdf", "inline"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        ".docx",
        "attachment",
    ),
}
_RAG_MANUAL_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9-]{1,99}")
_ROLE_MAP = {
    "analyst": "STAFF",
    "report_admin": "MANAGER",
    "data_admin": "MANAGER",
    "platform_admin": "SYSTEM_ADMIN",
}
_ANSWER_TYPE_BY_INTENT = {
    "PROCESS": "PROCEDURE",
    "IMMEDIATE_ACTION": "IMMEDIATE",
    "DECISION_CRITERIA": "CRITERIA",
    "REGULATION_CHECK": "POLICY",
    "COMPARISON": "COMPARE",
    "SUMMARY": "SUMMARY",
}
_NO_EVIDENCE_MESSAGE = (
    "질문과 일치하는 내부 지침 근거를 찾지 못했습니다.\n\n"
    "업무 영역, 발생 상황, 확인할 기준을 함께 적어 다시 질문해 주세요."
)
_DEPENDENCY_FAILURE_MESSAGE = (
    "내부 지침 검색 중 일시적인 오류가 발생했습니다. 잠시 후 다시 질문해 주세요."
)


class RagToolError(RuntimeError):
    """RAG Gateway 실패를 서비스 코드와 안전한 공개 메시지로 전달한다."""

    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class InternalManualAgent:
    """App role을 RAG role로 변환하고 승인된 검색·답변 Tool 호출을 조정한다."""

    @staticmethod
    def selected_document_limit(
        intent: str,
        selected_document_ids: tuple[str, ...],
    ) -> int:
        """명시적 비교 또는 승인된 두 문서 snapshot을 최대 두 개까지 유지한다."""
        return 2 if intent == "COMPARISON" or len(selected_document_ids) > 1 else 1

    @staticmethod
    def public_tool_output(result: Mapping[str, Any]) -> dict[str, Any]:
        """Conversation 표시 필드를 제외한 closed MCP 결과만 반환한다."""

        def invalid() -> NoReturn:
            raise RagToolError(
                "RAG_PUBLIC_OUTPUT_INVALID",
                "RAG 공개 결과 계약이 올바르지 않습니다.",
                502,
            )

        if not isinstance(result, Mapping):
            invalid()
        status = result.get("status")
        trace_id = result.get("trace_id")
        raw_evidence = result.get("evidence_bundle")
        if (
            not isinstance(status, str)
            or status not in {"ANSWER", "NO_EVIDENCE", "CONFLICT"}
            or not isinstance(trace_id, str)
            or not 1 <= len(trace_id) <= 128
            or not isinstance(raw_evidence, list)
            or len(raw_evidence) > 50
        ):
            invalid()

        evidence_bundle: list[dict[str, Any]] = []
        for item in raw_evidence:
            if not isinstance(item, Mapping):
                invalid()
            evidence_id = item.get("evidence_id")
            document_id = item.get("document_id")
            document_name = item.get("document_name")
            section = item.get("section")
            snippet = item.get("snippet")
            score = item.get("score")
            if (
                not isinstance(evidence_id, str)
                or not evidence_id
                or not isinstance(document_id, str)
                or not document_id
                or not isinstance(document_name, str)
                or not isinstance(section, str)
                or not isinstance(snippet, str)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or float(score) < 0
            ):
                invalid()
            evidence_bundle.append(
                {
                    "evidence_id": evidence_id,
                    "document_id": document_id,
                    "document_name": document_name,
                    "section": section,
                    "snippet": snippet,
                    "score": score,
                }
            )

        public: dict[str, Any] = {
            "status": status,
            "trace_id": trace_id,
            "evidence_bundle": evidence_bundle,
        }
        if status in {"ANSWER", "NO_EVIDENCE"}:
            raw_answer = result.get("answer")
            raw_citations = result.get("citations")
            if (
                not isinstance(raw_answer, Mapping)
                or not isinstance(raw_answer.get("text"), str)
                or not isinstance(raw_citations, list)
                or len(raw_citations) > 50
            ):
                invalid()
            citations: list[dict[str, str]] = []
            for item in raw_citations:
                if (
                    not isinstance(item, Mapping)
                    or not isinstance(item.get("evidence_id"), str)
                    or not item["evidence_id"]
                    or not isinstance(item.get("citation"), str)
                ):
                    invalid()
                citations.append(
                    {
                        "evidence_id": item["evidence_id"],
                        "citation": item["citation"],
                    }
                )
            public["answer"] = {"text": raw_answer["text"]}
            public["citations"] = citations
            return public

        raw_conflicts = result.get("conflicts")
        if not isinstance(raw_conflicts, list) or not 1 <= len(raw_conflicts) <= 50:
            invalid()
        conflicts: list[dict[str, Any]] = []
        for item in raw_conflicts:
            if not isinstance(item, Mapping):
                invalid()
            description = item.get("description")
            evidence_ids = item.get("evidence_ids")
            if (
                not isinstance(description, str)
                or not description
                or not isinstance(evidence_ids, list)
                or len(evidence_ids) < 2
                or any(not isinstance(value, str) or not value for value in evidence_ids)
                or len(evidence_ids) != len(set(evidence_ids))
            ):
                invalid()
            conflicts.append(
                {"description": description, "evidence_ids": list(evidence_ids)}
            )
        public["conflicts"] = conflicts
        return public

    @staticmethod
    def _validate_search_contract(search: Mapping[str, Any]) -> dict[str, Any]:
        """검색 결과가 현재 corpus release를 식별하는 closed v2 계약인지 확인한다."""

        release = search.get("retrieval_release")
        expected_keys = {
            "schema_version",
            "release_id",
            "model_revision",
            "embedding_dimension",
            "corpus_manifest_sha256",
            "processing_profile_sha256",
        }
        if not isinstance(release, dict) or set(release) != expected_keys:
            raise RagToolError(
                "RAG_OUTPUT_INVALID",
                "RAG 검색 release 계약이 올바르지 않습니다.",
                502,
            )
        release_id = release["release_id"]
        try:
            parsed_release_id = UUID(release_id) if isinstance(release_id, str) else None
        except ValueError:
            parsed_release_id = None
        dimension = release["embedding_dimension"]
        if (
            release["schema_version"] != "RagRetrievalRelease.v2"
            or parsed_release_id is None
            or str(parsed_release_id) != release_id
            or not isinstance(release["model_revision"], str)
            or re.fullmatch(
                r"[A-Za-z0-9._:/+-]{1,160}", release["model_revision"]
            )
            is None
            or isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or not 1 <= dimension <= RAG_MAX_EMBEDDING_DIMENSION
            or not isinstance(release["corpus_manifest_sha256"], str)
            or re.fullmatch(
                r"[0-9a-f]{64}", release["corpus_manifest_sha256"]
            )
            is None
            or not isinstance(release["processing_profile_sha256"], str)
            or re.fullmatch(
                r"[0-9a-f]{64}", release["processing_profile_sha256"]
            )
            is None
        ):
            raise RagToolError(
                "RAG_OUTPUT_INVALID",
                "RAG 검색 release 계약이 올바르지 않습니다.",
                502,
            )
        return dict(release)

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._base_url = os.getenv("RAG_API_URL", "http://rag-api:8000").rstrip("/")
        self._secret = os.getenv("RAG_GATEWAY_HMAC_SECRET", "")
        try:
            timeout = float(os.getenv("RAG_TOOL_TIMEOUT_SECONDS", "30"))
        except ValueError as error:
            raise RagToolError(
                "RAG_CONFIG_INVALID",
                "RAG Tool 제한 시간이 올바르지 않습니다.",
            ) from error
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 300:
            raise RagToolError(
                "RAG_CONFIG_INVALID",
                "RAG Tool 제한 시간이 올바르지 않습니다.",
            )
        self._timeout = timeout
        endpoint = httpx.URL(self._base_url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.host or endpoint.userinfo:
            raise RagToolError("RAG_CONFIG_INVALID", "RAG API 주소가 올바르지 않습니다.")
        if len(self._secret) < 32:
            raise RagToolError("RAG_CONFIG_INVALID", "RAG Gateway 서명이 구성되지 않았습니다.")
        self._source_max_body_bytes = RAG_SOURCE_MAX_BODY_BYTES

    async def execute(
        self,
        query: str,
        actor_id: UUID,
        app_role: str,
        trace_id: str,
        recent_utterances: tuple[str, ...] = (),
        resolved_question: str | None = None,
        domains: tuple[str, ...] = (),
        intent: str = "REGULATION_CHECK",
        selected_document_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """legacy API 경로에서 registry·감사를 소유하고 순수 runtime을 호출한다."""

        normalized = query.strip()
        if not 2 <= len(normalized) <= 500:
            raise RagToolError("RAG_INPUT_INVALID", "질문은 2자 이상 500자 이하여야 합니다.", 422)
        if _ROLE_MAP.get(app_role) is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 검색 권한이 없습니다.", 403)
        started = time.perf_counter()
        await self._assert_enabled(app_role)
        try:
            output = await self._execute_runtime(
                query=query,
                actor_id=actor_id,
                app_role=app_role,
                trace_id=trace_id,
                recent_utterances=recent_utterances,
                resolved_question=resolved_question,
                domains=domains,
                intent=intent,
                selected_document_ids=selected_document_ids,
            )
        except RagToolError as error:
            await self._record(
                actor_id,
                app_role,
                trace_id,
                normalized,
                {},
                started,
                error.code,
            )
            raise
        error_code = (
            "RAG_DEPENDENCY_FAILED" if output.get("status") == "ERROR" else None
        )
        await self._record(
            actor_id,
            app_role,
            trace_id,
            normalized,
            output if error_code is None else {},
            started,
            error_code,
        )
        return output

    async def _execute_runtime(
        self,
        query: str,
        actor_id: UUID,
        app_role: str,
        trace_id: str,
        recent_utterances: tuple[str, ...] = (),
        resolved_question: str | None = None,
        domains: tuple[str, ...] = (),
        intent: str = "REGULATION_CHECK",
        selected_document_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """DB registry·감사와 분리된 서명 RAG runtime adapter를 실행한다."""

        normalized = query.strip()
        if not 2 <= len(normalized) <= 500:
            raise RagToolError("RAG_INPUT_INVALID", "질문은 2자 이상 500자 이하여야 합니다.", 422)
        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 검색 권한이 없습니다.", 403)
        recent = tuple(
            utterance.strip()
            for utterance in recent_utterances[-3:]
            if utterance.strip() and utterance.strip() != normalized
        )
        document_limit = self.selected_document_limit(intent, selected_document_ids)
        selected_ids = tuple(dict.fromkeys(
            document_id.strip()
            for document_id in selected_document_ids
            if document_id.strip()
        ))[:document_limit]
        search_top_k = 10 if selected_ids else 8 if domains else 5
        contextual_query = (resolved_question or "\n".join(
            [*(f"이전 질문: {utterance}" for utterance in recent), f"현재 질문: {normalized}"]
        ))[-500:].strip()
        actor_hash = hashlib.sha256(str(actor_id).encode("utf-8")).hexdigest()
        try:
            search = await self._signed_post(
                "/v1/tools/internal-manual-search",
                {
                    "query": normalized,
                    "resolved_question": contextual_query,
                    "domains": list(domains),
                    "intent": intent,
                    "top_k": search_top_k,
                    "recent_utterances": list(recent),
                    "selected_document_ids": list(selected_ids),
                    "trace_id": trace_id,
                    "actor_hash": actor_hash,
                },
                rag_role,
            )
            self._validate_search_contract(search)
            answer_query = search.get("answer_query")
            retrieval_request_id = str(search.get("request_id") or "")
            try:
                parsed_retrieval_request_id = UUID(retrieval_request_id)
            except ValueError:
                parsed_retrieval_request_id = None
            if (
                not isinstance(answer_query, str)
                or answer_query != contextual_query
                or not 2 <= len(answer_query) <= 500
                or search.get("trace_id") != trace_id
                or parsed_retrieval_request_id is None
                or str(parsed_retrieval_request_id) != retrieval_request_id
            ):
                raise RagToolError(
                    "RAG_OUTPUT_INVALID",
                    "RAG 검색 답변 질문 계약이 올바르지 않습니다.",
                    502,
                )
            results = search.get("results") if isinstance(search, dict) else None
            if search.get("no_evidence") is True or not isinstance(results, list) or not results:
                output = self._empty_answer_output(
                    "NO_EVIDENCE",
                    trace_id,
                    intent,
                    _NO_EVIDENCE_MESSAGE,
                    list(search.get("processing_steps") or []) + ["NO_EVIDENCE_RETURNED"],
                )
                return output

            evidence_blocks = [
                self._evidence_block(item)
                for item in results
                if isinstance(item, dict)
            ]
            if not evidence_blocks or any(
                not item[field].strip()
                for item in evidence_blocks
                for field in (
                    "evidence_id",
                    "text",
                    "version",
                    "document_type",
                    "owner_team",
                )
            ):
                raise RagToolError("RAG_OUTPUT_INVALID", "검색 근거 형식이 올바르지 않습니다.")
            answer = await self._signed_post(
                "/v1/tools/internal-manual-answer",
                {
                    "query": answer_query,
                    "evidence_blocks": evidence_blocks,
                    "intent": intent,
                    "retrieval_request_id": retrieval_request_id,
                    "trace_id": trace_id,
                    "actor_hash": actor_hash,
                },
                rag_role,
            )
            if answer.get("trace_id") != trace_id:
                raise RagToolError(
                    "RAG_OUTPUT_INVALID",
                    "RAG 답변 추적 계약이 올바르지 않습니다.",
                    502,
                )
            answer_status = str(answer.get("status") or "")
            if answer_status == "NO_EVIDENCE":
                output = self._empty_answer_output(
                    "NO_EVIDENCE",
                    trace_id,
                    intent,
                    _NO_EVIDENCE_MESSAGE,
                    list(search.get("processing_steps") or []) + ["ANSWER_EVIDENCE_REJECTED"],
                )
                output["answer_id"] = str(answer.get("request_id") or "")
                return output
            if answer_status == "POTENTIAL_CONFLICT":
                output = {
                    "status": "CONFLICT",
                    "answer_id": str(answer.get("request_id") or ""),
                    "trace_id": trace_id,
                    "processing_steps": list(search.get("processing_steps") or []),
                    "conflicts": list(answer.get("conflicts") or []),
                    "evidence_bundle": self._evidence_bundle(results),
                }
                return output
            if answer_status != "ANSWER":
                raise RagToolError("RAG_ANSWER_FAILED", "근거 답변을 생성하지 못했습니다.")
            retrieved_ids = {item["evidence_id"] for item in evidence_blocks}
            cited_ids = [
                str(item.get("evidence_id") or "")
                for item in answer.get("citations", [])
                if isinstance(item, dict)
            ]
            if not cited_ids or not set(cited_ids).issubset(retrieved_ids):
                raise RagToolError("RAG_CITATION_INVALID", "검색 결과와 답변 근거가 일치하지 않습니다.")
            result_by_evidence_id = {
                str(item.get("evidence_id") or ""): item
                for item in results
                if isinstance(item, dict) and item.get("evidence_id")
            }
            cited_results = [
                result_by_evidence_id[evidence_id]
                for evidence_id in dict.fromkeys(cited_ids)
            ]
            displayed = cited_results[:document_limit]
            top = displayed[0]
            normalized_body = top.get("normalized_body") if isinstance(top.get("normalized_body"), dict) else {}
            answer_body = self._answer_body(str(answer.get("answer") or ""))
            if not answer_body:
                raise RagToolError(
                    "RAG_ANSWER_INVALID",
                    "근거 답변 본문이 비어 있습니다.",
                    502,
                )
            answer_summary = [
                paragraph.strip()
                for paragraph in answer_body.split("\n\n")
                if paragraph.strip()
            ]
            cited_document_ids = tuple(dict.fromkeys(
                str(item.get("document_id") or item.get("manual_id") or "").strip()
                for item in cited_results
                if str(item.get("document_id") or item.get("manual_id") or "").strip()
            ))[:document_limit]
            approved_document_ids = selected_ids or cited_document_ids
            output = {
                "status": "ANSWER",
                "response_status": "ANSWERED",
                "answer_type": answer.get("answer_type") or _ANSWER_TYPE_BY_INTENT.get(intent, "SUMMARY"),
                "answer_id": str(answer.get("request_id") or ""),
                "answer": {"text": answer_body},
                "agent": str(search.get("agent") or "INTERNAL_GUIDELINE"),
                "processing_steps": list(search.get("processing_steps") or []),
                "evidence_bundle": self._evidence_bundle(cited_results),
                "citations": list(answer.get("citations") or []),
                "request_id": str(answer.get("request_id") or ""),
                "trace_id": trace_id,
                "routing": {
                    "domains": list(domains),
                    "intent": intent,
                    "resolved_with_context": contextual_query != normalized,
                    "context_question": contextual_query,
                    "snapshot_question": normalized,
                    "selected_document_ids": list(approved_document_ids),
                },
                "document": {
                    "document_name": " / ".join(str(item.get("title") or "확인 불가") for item in displayed),
                    "document_version": str(top.get("version") or "확인 불가"),
                    "guideline_number": " / ".join(str(item.get("manual_id") or "확인 불가") for item in displayed),
                    "area": self._answer_area(
                        str(answer.get("answer") or ""),
                        str(top.get("section_title") or "확인 불가"),
                    ),
                    "body": answer_body,
                    "body_paragraphs": list(normalized_body.get("body_paragraphs") or []),
                    "related_guidelines": list(normalized_body.get("related_guidelines") or []),
                    "action_rules": list(normalized_body.get("action_rules") or []),
                    "answer_summary": answer_summary,
                    "evidence": " / ".join(str(item.get("citation") or "확인 불가") for item in displayed),
                    "source_text": str(top.get("content") or top.get("snippet") or ""),
                    "document_id": str(top.get("document_id") or top.get("manual_id") or ""),
                    "evidence_id": str(top.get("evidence_id") or ""),
                    "score": float(top.get("score") or 0),
                    "approval_status": (
                        "미승인 작업지침"
                        if top.get("validity_status") == "UNRESOLVED"
                        else "유효 문서"
                    ),
                    "access_status": "조회 가능",
                    "warning": (
                        "정식 승인 전 작업지침입니다. 승인 담당자 확인 후 적용하세요."
                        if top.get("validity_status") == "UNRESOLVED"
                        or top.get("document_status") == "WORKING_KNOWLEDGE"
                        else ""
                    ),
                },
            }
            return output
        except RagToolError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            return self._empty_answer_output(
                "ERROR",
                trace_id,
                intent,
                _DEPENDENCY_FAILURE_MESSAGE,
                ["DEPENDENCY_FAILED"],
            )

    async def execute_mcp_handler(
        self,
        query: str,
        actor_id: UUID,
        app_role: str,
        trace_id: str,
        recent_utterances: tuple[str, ...] = (),
        selected_document_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """공용 MCP registry·dispatcher가 승인한 한 번의 RAG handler 실행이다."""

        return await self._execute_runtime(
            query=query,
            actor_id=actor_id,
            app_role=app_role,
            trace_id=trace_id,
            recent_utterances=recent_utterances,
            selected_document_ids=selected_document_ids,
        )

    async def search_capability(
        self,
        query: str,
        app_role: str,
    ) -> dict[str, Any]:
        """답변 생성 없이 승인 registry와 RAG 검색 근거만 capability 후보로 축약한다."""

        normalized = query.strip()
        if not 2 <= len(normalized) <= 500:
            raise RagToolError(
                "RAG_INPUT_INVALID",
                "질문은 2자 이상 500자 이하여야 합니다.",
                422,
            )
        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError(
                "RAG_ACCESS_DENIED",
                "RAG 검색 권한이 없습니다.",
                403,
            )
        await self._assert_enabled(app_role)
        trace_id = str(uuid4())
        actor_hash = hashlib.sha256(b"RAG_CAPABILITY_PROBE").hexdigest()
        try:
            search = await self._signed_post(
                "/v1/tools/internal-manual-search",
                {
                    "query": normalized,
                    "resolved_question": normalized,
                    "domains": [],
                    "intent": "REGULATION_CHECK",
                    "top_k": 3,
                    "recent_utterances": [],
                    "selected_document_ids": [],
                    "trace_id": trace_id,
                    "actor_hash": actor_hash,
                },
                rag_role,
            )
        except RagToolError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise RagToolError(
                "RAG_CAPABILITY_UNAVAILABLE",
                "RAG capability를 확인하지 못했습니다.",
            ) from error
        return self._capability_candidate(
            search,
            expected_query_hash=self._capability_query_hash(normalized),
        )

    @staticmethod
    def _capability_query_hash(query: str) -> str:
        """RAG 검색 감사 hash를 답변 없는 probe의 고정 입력과 동일하게 계산한다."""

        canonical = json.dumps(
            {
                "query": query,
                "resolved_question": query,
                "domains": [],
                "intent": "REGULATION_CHECK",
                "recent_utterances": [],
                "selected_document_ids": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _capability_candidate(
        search: dict[str, Any],
        *,
        expected_query_hash: str,
    ) -> dict[str, Any]:
        """검색 원문을 버리고 route receipt에 필요한 식별자·release만 검증한다."""

        request_id = str(search.get("request_id") or "").strip()
        query_hash = str(search.get("query_hash") or "").strip().lower()
        try:
            UUID(request_id)
        except ValueError as error:
            raise RagToolError(
                "RAG_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 요청 식별자가 올바르지 않습니다.",
            ) from error
        if (
            not re.fullmatch(r"[0-9a-f]{64}", query_hash)
            or query_hash != expected_query_hash
        ):
            raise RagToolError(
                "RAG_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 검색 hash가 올바르지 않습니다.",
            )

        execution_state = search.get("execution_state")
        tool = search.get("tool")
        try:
            retrieval_release = InternalManualAgent._validate_search_contract(search)
        except RagToolError as error:
            raise RagToolError(
                "RAG_CAPABILITY_RELEASE_INVALID",
                "RAG capability release 근거가 올바르지 않습니다.",
            ) from error
        embedding_dimension = retrieval_release["embedding_dimension"]
        if (
            not isinstance(execution_state, dict)
            or execution_state.get("p2_gate") != "TECHNICALLY_VALIDATED"
            or execution_state.get("production_integration")
            != "LOCAL_DOCKER_VALIDATED"
            or not isinstance(tool, dict)
            or tool.get("tool_code") != "internal-manual-search"
            or not isinstance(tool.get("semantic_version"), str)
            or not re.fullmatch(r"[A-Za-z0-9._+-]{1,80}", tool["semantic_version"])
            or isinstance(embedding_dimension, bool)
            or not isinstance(embedding_dimension, int)
            or not 1 <= embedding_dimension <= RAG_MAX_EMBEDDING_DIMENSION
        ):
            raise RagToolError(
                "RAG_CAPABILITY_RELEASE_INVALID",
                "RAG capability release 근거가 올바르지 않습니다.",
            )

        raw_results = search.get("results")
        no_evidence = search.get("no_evidence")
        if type(no_evidence) is not bool or not isinstance(raw_results, list):
            raise RagToolError(
                "RAG_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 검색 결과가 올바르지 않습니다.",
            )
        if no_evidence:
            if raw_results:
                raise RagToolError(
                    "RAG_CAPABILITY_EVIDENCE_INVALID",
                    "RAG capability의 근거 없음 상태가 결과와 충돌합니다.",
                )
            return {
                "schema_version": RAG_CAPABILITY_CANDIDATE_VERSION,
                "matched": False,
                "retrieval_request_id": request_id,
                "query_hash": query_hash,
                "tool_code": tool["tool_code"],
                "tool_version": tool["semantic_version"],
                "model_revision": retrieval_release["model_revision"],
                "embedding_dimension": embedding_dimension,
                "evidence_ids": [],
                "document_ids": [],
                "maximum_score": None,
            }
        if not raw_results or len(raw_results) > 50:
            raise RagToolError(
                "RAG_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 근거 수가 올바르지 않습니다.",
            )

        evidence_ids: list[str] = []
        document_ids: list[str] = []
        scores: list[float] = []
        for item in raw_results:
            if not isinstance(item, dict):
                raise RagToolError(
                    "RAG_CAPABILITY_EVIDENCE_INVALID",
                    "RAG capability 근거 형식이 올바르지 않습니다.",
                )
            evidence_id = str(item.get("evidence_id") or "").strip()
            document_id = str(item.get("manual_id") or "").strip()
            raw_score = item.get("score")
            try:
                score = float(raw_score)
            except (TypeError, ValueError) as error:
                raise RagToolError(
                    "RAG_CAPABILITY_EVIDENCE_INVALID",
                    "RAG capability 검색 점수가 올바르지 않습니다.",
                ) from error
            if (
                not evidence_id
                or not _RAG_MANUAL_ID_PATTERN.fullmatch(document_id)
                or item.get("approval_status") != "APPROVED"
                or item.get("document_status") != "WORKING_KNOWLEDGE"
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise RagToolError(
                    "RAG_CAPABILITY_EVIDENCE_INVALID",
                    "RAG capability 근거가 승인된 검색 계약과 일치하지 않습니다.",
                )
            evidence_ids.append(evidence_id)
            document_ids.append(document_id)
            scores.append(score)
        unique_evidence_ids = tuple(dict.fromkeys(evidence_ids))
        unique_document_ids = tuple(dict.fromkeys(document_ids))
        maximum_score = max(scores)
        if len(unique_evidence_ids) != len(evidence_ids) or maximum_score <= 0:
            raise RagToolError(
                "RAG_CAPABILITY_EVIDENCE_INVALID",
                "RAG capability 근거가 중복되었거나 관련성 점수가 없습니다.",
            )
        return {
            "schema_version": RAG_CAPABILITY_CANDIDATE_VERSION,
            "matched": True,
            "retrieval_request_id": request_id,
            "query_hash": query_hash,
            "tool_code": tool["tool_code"],
            "tool_version": tool["semantic_version"],
            "model_revision": retrieval_release["model_revision"],
            "embedding_dimension": embedding_dimension,
            "evidence_ids": list(unique_evidence_ids),
            "document_ids": list(unique_document_ids),
            "maximum_score": maximum_score,
        }

    async def _signed_post(self, path: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        request_id = str(uuid4())
        timestamp = str(int(time.time()))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        message = f"{timestamp}\n{request_id}\n{role}\n{digest}".encode("utf-8")
        signature = hmac.new(self._secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={
                    "X-Verified-Role": role,
                    "X-Request-Timestamp": timestamp,
                    "X-Request-Id": request_id,
                    "X-Request-Signature": signature,
                },
            )
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise RagToolError("RAG_OUTPUT_INVALID", "RAG 응답 형식이 올바르지 않습니다.")
        return result

    async def runtime_receipt(self, app_role: str) -> dict[str, Any]:
        """DB 승인, runtime health와 실제 HMAC 서명 endpoint를 함께 검증한다."""

        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError(
                "RAG_ACCESS_DENIED",
                "RAG 실행 준비 상태를 확인할 권한이 없습니다.",
                403,
            )
        await self._assert_enabled(app_role)
        try:
            health = await self._get_json("/health/ready")
            catalog = await self._signed_post(
                "/v1/tools/internal-manual-catalog",
                {},
                rag_role,
            )
        except RagToolError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise RagToolError(
                "RAG_RUNTIME_NOT_READY",
                "RAG 실행 서비스를 확인하지 못했습니다.",
            ) from error

        execution_state = health.get("execution_state")
        tool = health.get("tool")
        dimension = health.get("expected_dimension")
        corpus_manifest_sha256 = health.get("corpus_manifest_sha256")
        processing_profile_sha256 = health.get("processing_profile_sha256")
        active_corpus_release = health.get("active_corpus_release")
        documents = catalog.get("documents")
        if (
            health.get("status") != "healthy"
            or health.get("embedding_api_configured") is not True
            or not isinstance(execution_state, dict)
            or execution_state.get("p2_gate") != "TECHNICALLY_VALIDATED"
            or execution_state.get("production_integration")
            != "LOCAL_DOCKER_VALIDATED"
            or not isinstance(tool, dict)
            or tool.get("tool_code") != "internal-manual-search"
            or not isinstance(tool.get("semantic_version"), str)
            or not tool["semantic_version"].strip()
            or tool.get("read_only") is not True
            or tool.get("destructive") is not False
            or not isinstance(health.get("model_revision"), str)
            or not re.fullmatch(
                r"[A-Za-z0-9._:/+-]{1,160}",
                health["model_revision"],
            )
            or isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or not 1 <= dimension <= RAG_MAX_EMBEDDING_DIMENSION
            or not isinstance(corpus_manifest_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", corpus_manifest_sha256) is None
            or not isinstance(processing_profile_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", processing_profile_sha256) is None
            or not isinstance(active_corpus_release, dict)
            or active_corpus_release.get("corpus_manifest_sha256")
            != corpus_manifest_sha256
            or active_corpus_release.get("processing_profile_sha256")
            != processing_profile_sha256
            or active_corpus_release.get("provider")
            != health.get("embedding_provider")
            or active_corpus_release.get("model") != health.get("model_id")
            or active_corpus_release.get("dimensions") != dimension
            or active_corpus_release.get("version") != health.get("model_revision")
            or isinstance(active_corpus_release.get("approved_document_count"), bool)
            or not isinstance(
                active_corpus_release.get("approved_document_count"), int
            )
            or active_corpus_release["approved_document_count"] < 1
            or not isinstance(documents, list)
            or not documents
        ):
            raise RagToolError(
                "RAG_RUNTIME_RECEIPT_INVALID",
                "RAG 실행 준비 상태 계약이 올바르지 않습니다.",
            )
        canonical = json.dumps(
            {
                "schema_version": RAG_RUNTIME_RECEIPT_VERSION,
                "tool_code": tool["tool_code"],
                "tool_version": tool["semantic_version"],
                "model_revision": health["model_revision"],
                "embedding_dimension": dimension,
                "corpus_manifest_sha256": corpus_manifest_sha256,
                "processing_profile_sha256": processing_profile_sha256,
                "document_count": len(documents),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return {
            "schema_version": RAG_RUNTIME_RECEIPT_VERSION,
            "tool_code": tool["tool_code"],
            "tool_version": tool["semantic_version"],
            "model_revision": health["model_revision"],
            "embedding_dimension": dimension,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "processing_profile_sha256": processing_profile_sha256,
            "capability_hash": hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest(),
        }

    async def _get_json(self, path: str) -> dict[str, Any]:
        """공개 health endpoint도 bounded transport와 object 계약으로만 읽는다."""

        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await client.get(f"{self._base_url}{path}")
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise RagToolError(
                "RAG_OUTPUT_INVALID",
                "RAG 응답 형식이 올바르지 않습니다.",
            )
        return result

    async def fetch_catalog(self, app_role: str) -> list[dict[str, Any]]:
        """앱 역할이 열람할 수 있는 내부 매뉴얼 목록만 조회한다."""
        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 문서 검색 권한이 없습니다.", 403)
        await self._assert_enabled(app_role)
        result = await self._signed_post("/v1/tools/internal-manual-catalog", {}, rag_role)
        return list(result.get("documents") or [])

    async def _source_role(self, manual_id: str, app_role: str) -> str:
        """문서 ID와 App 역할을 검증하고 현재 Registry 승인까지 확인한다."""

        if _RAG_MANUAL_ID_PATTERN.fullmatch(manual_id) is None:
            raise RagToolError("RAG_INPUT_INVALID", "문서 식별자가 올바르지 않습니다.", 422)
        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 문서 열람 권한이 없습니다.", 403)
        await self._assert_enabled(app_role)
        return rag_role

    def _source_request_headers(self, manual_id: str, rag_role: str) -> dict[str, str]:
        """Runtime 원문 요청에 사용할 canonical body digest와 HMAC header를 만든다."""

        canonical = json.dumps(
            {"manual_id": manual_id}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        request_id = str(uuid4())
        timestamp = str(int(time.time()))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        message = f"{timestamp}\n{request_id}\n{rag_role}\n{digest}".encode("utf-8")
        signature = hmac.new(self._secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return {
            "X-Verified-Role": rag_role,
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Request-Signature": signature,
        }

    @staticmethod
    def _source_filename(content_disposition: str | None) -> str | None:
        """Content-Disposition에서 UTF-8 filename을 중복 없이 추출한다."""

        if content_disposition is None:
            return None
        if "\r" in content_disposition or "\n" in content_disposition:
            raise RagToolError(
                "RAG_DOCUMENT_RESPONSE_INVALID",
                "RAG 원본 문서 응답 header가 올바르지 않습니다.",
                502,
            )
        encoded_names = re.findall(
            r"(?:^|;)\s*filename\*\s*=\s*([^;]*)",
            content_disposition,
            flags=re.IGNORECASE,
        )
        plain_names = re.findall(
            r'(?:^|;)\s*filename(?!\*)\s*=\s*("[^"]*"|[^;]*)',
            content_disposition,
            flags=re.IGNORECASE,
        )
        if len(encoded_names) > 1 or len(plain_names) > 1:
            raise RagToolError(
                "RAG_DOCUMENT_RESPONSE_INVALID",
                "RAG 원본 문서 파일명이 올바르지 않습니다.",
                502,
            )
        try:
            if encoded_names:
                encoded = encoded_names[0].strip()
                if not encoded.lower().startswith("utf-8''"):
                    raise ValueError("unsupported filename encoding")
                return unquote_to_bytes(encoded[7:]).decode("utf-8")
            if plain_names:
                plain = plain_names[0].strip()
                return plain[1:-1] if plain.startswith('"') and plain.endswith('"') else plain
        except (UnicodeDecodeError, ValueError) as error:
            raise RagToolError(
                "RAG_DOCUMENT_RESPONSE_INVALID",
                "RAG 원본 문서 파일명이 올바르지 않습니다.",
                502,
            ) from error
        raise RagToolError(
            "RAG_DOCUMENT_RESPONSE_INVALID",
            "RAG 원본 문서 파일명이 누락되었습니다.",
            502,
        )

    @staticmethod
    def _source_metadata(
        manual_id: str,
        media_type_header: str | None,
        content_disposition: str | None,
        allowed_media_types: frozenset[str],
    ) -> tuple[str, str]:
        """허용 MIME과 안전한 파일명만 수용해 새 Content-Disposition을 만든다."""

        media_type = (media_type_header or "").split(";", 1)[0].strip().lower()
        if media_type not in allowed_media_types or media_type not in RAG_SOURCE_MEDIA_TYPES:
            raise RagToolError(
                "RAG_DOCUMENT_MEDIA_TYPE_INVALID",
                "RAG 원본 문서 형식이 허용되지 않았습니다.",
                502,
            )
        suffix, disposition = RAG_SOURCE_MEDIA_TYPES[media_type]
        filename = InternalManualAgent._source_filename(content_disposition)
        if filename is None:
            filename = f"{manual_id}{suffix}"
        filename = unicodedata.normalize("NFC", filename).strip()
        if (
            not suffix
            or not filename
            or len(filename) > 180
            or not filename.lower().endswith(suffix)
            or len(filename) <= len(suffix)
            or filename.endswith((".", " "))
            or re.search(r'[<>:"/\\|?*]', filename) is not None
            or any(unicodedata.category(character).startswith("C") for character in filename)
        ):
            raise RagToolError(
                "RAG_DOCUMENT_RESPONSE_INVALID",
                "RAG 원본 문서 파일명이 올바르지 않습니다.",
                502,
            )
        return media_type, f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}"

    async def _fetch_source(
        self,
        manual_id: str,
        rag_role: str,
        source_path: str,
        allowed_media_types: frozenset[str],
    ) -> tuple[bytes, str, str]:
        """Redirect 없이 원문을 읽고 body·MIME·파일명 경계를 모두 검증한다."""

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    f"{self._base_url}/v1/documents/{quote(manual_id, safe='')}/{source_path}",
                    headers=self._source_request_headers(manual_id, rag_role),
                ) as response:
                    if response.is_redirect:
                        raise RagToolError(
                            "RAG_DOCUMENT_REDIRECT_REJECTED",
                            "RAG 원본 문서 redirect를 허용하지 않습니다.",
                            502,
                        )
                    response.raise_for_status()
                    media_type, disposition = self._source_metadata(
                        manual_id,
                        response.headers.get("Content-Type"),
                        response.headers.get("Content-Disposition"),
                        allowed_media_types,
                    )
                    declared_length = response.headers.get("Content-Length")
                    if declared_length is not None:
                        if (
                            not declared_length.isdecimal()
                            or int(declared_length) > self._source_max_body_bytes
                        ):
                            raise RagToolError(
                                "RAG_DOCUMENT_TOO_LARGE",
                                "RAG 원본 문서 크기가 허용 범위를 초과했습니다.",
                                502,
                            )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self._source_max_body_bytes:
                            raise RagToolError(
                                "RAG_DOCUMENT_TOO_LARGE",
                                "RAG 원본 문서 크기가 허용 범위를 초과했습니다.",
                                502,
                            )
                        chunks.append(chunk)
            content = b"".join(chunks)
            if not content:
                raise RagToolError(
                    "RAG_DOCUMENT_RESPONSE_INVALID",
                    "RAG 원본 문서가 비어 있습니다.",
                    502,
                )
            return content, disposition, media_type
        except RagToolError:
            raise
        except httpx.HTTPStatusError as error:
            status = 404 if error.response.status_code == 404 else 503
            raise RagToolError(
                "RAG_DOCUMENT_UNAVAILABLE",
                "RAG 원본 문서를 찾을 수 없습니다.",
                status,
            ) from error
        except httpx.HTTPError as error:
            raise RagToolError("RAG_DEPENDENCY_FAILED", "RAG 문서 서비스에 연결하지 못했습니다.") from error

    async def fetch_document(
        self,
        manual_id: str,
        app_role: str,
    ) -> tuple[bytes, str, str]:
        """승인된 PDF 또는 DOCX 원문을 generic Runtime 경로에서 중계한다."""

        rag_role = await self._source_role(manual_id, app_role)
        return await self._fetch_source(
            manual_id,
            rag_role,
            "source",
            frozenset(RAG_SOURCE_MEDIA_TYPES),
        )

    async def fetch_pdf(self, manual_id: str, app_role: str) -> tuple[bytes, str]:
        """기존 PDF 전용 Runtime 경로와 App 반환 계약을 유지한다."""

        rag_role = await self._source_role(manual_id, app_role)
        content, disposition, _media_type = await self._fetch_source(
            manual_id,
            rag_role,
            "source.pdf",
            frozenset({"application/pdf"}),
        )
        return content, disposition

    async def _assert_enabled(self, app_role: str) -> None:
        try:
            async with session_scope(self._database_url) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT tool_id, tool_code, semantic_version, title, description, "
                            "input_schema_json, output_schema_json, annotations_json, transport, "
                            "timeout_seconds, required_roles_json, is_enabled "
                            "FROM tooling.tool_registry "
                            "WHERE tool_id=:tool_id OR tool_code=:tool_code"
                        ),
                        {"tool_id": RAG_TOOL_ID, "tool_code": RAG_TOOL_CODE},
                    )
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise RagToolError("RAG_REGISTRY_UNAVAILABLE", "RAG Tool Registry를 확인하지 못했습니다.") from error
        if not self._registry_contract_matches(row):
            raise RagToolError("RAG_TOOL_DISABLED", "RAG Tool이 승인되지 않았습니다.", 503)
        if app_role not in RAG_TOOL_ROLES:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 검색 권한이 없습니다.", 403)

    @staticmethod
    def _registry_contract_matches(row: Mapping[str, Any] | None) -> bool:
        """활성 Registry 행이 canonical rag.answer descriptor 전체와 일치하는지 판정한다."""

        if row is None:
            return False
        try:
            roles = row["required_roles_json"]
            if isinstance(roles, str):
                roles = json.loads(roles)
            return bool(
                UUID(str(row["tool_id"])) == RAG_TOOL_ID
                and row["tool_code"] == RAG_TOOL_CODE
                and row["semantic_version"] == RAG_TOOL_SEMANTIC_VERSION
                and row["title"] == RAG_TOOL_DESCRIPTOR["title"]
                and row["description"] == RAG_TOOL_DESCRIPTION
                and row["input_schema_json"] == RAG_TOOL_INPUT_SCHEMA
                and row["output_schema_json"] == RAG_TOOL_OUTPUT_SCHEMA
                and row["annotations_json"] == RAG_TOOL_DESCRIPTOR["annotations"]
                and row["transport"] == RAG_TOOL_TRANSPORT
                and type(row["timeout_seconds"]) is int
                and row["timeout_seconds"] == RAG_TOOL_TIMEOUT_SECONDS
                and type(roles) is list
                and tuple(roles) == RAG_TOOL_ROLES
                and row["is_enabled"] is True
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False

    async def _record(
        self,
        actor_id: UUID,
        role: str,
        trace_id: str,
        query: str,
        output: dict[str, Any],
        started: float,
        error_code: str | None = None,
    ) -> None:
        reference = {
            "status": output.get("status"),
            "evidence_id": (output.get("document") or {}).get("evidence_id"),
        }
        try:
            async with session_scope(self._database_url) as session:
                await session.execute(
                    text(
                        "INSERT INTO tooling.tool_runs "
                        "(tool_run_id,tool_id,tool_semantic_version,caller_user_id,caller_role,trace_id,input_hash,status,latency_ms,output_ref_json,error_code) "
                        "VALUES (:run_id,:tool_id,:tool_version,:actor,:role,:trace,:input_hash,:status,:latency,CAST(:output AS jsonb),:error)"
                    ),
                    {
                        "run_id": uuid4(), "tool_id": RAG_TOOL_ID,
                        "tool_version": RAG_TOOL_SEMANTIC_VERSION,
                        "actor": actor_id, "role": role,
                        "trace": trace_id, "input_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                        "status": "FAILED" if error_code else "SUCCEEDED",
                        "latency": max(0, round((time.perf_counter() - started) * 1000)),
                        "output": json.dumps(reference), "error": error_code,
                    },
                )
        except SQLAlchemyError as error:
            raise RagToolError("RAG_AUDIT_FAILED", "RAG 실행 근거를 저장하지 못했습니다.") from error

    @staticmethod
    def _empty_answer_output(
        status: str,
        trace_id: str,
        intent: str,
        message: str,
        processing_steps: list[str],
    ) -> dict[str, Any]:
        paragraphs = [part.strip() for part in message.split("\n\n") if part.strip()]
        return {
            "status": status,
            "response_status": status,
            "answer_type": _ANSWER_TYPE_BY_INTENT.get(intent, "SUMMARY"),
            "answer": {"text": message},
            "document": {"body": message, "body_paragraphs": paragraphs},
            "citations": [],
            "evidence_bundle": [],
            "processing_steps": processing_steps,
            "trace_id": trace_id,
        }

    @staticmethod
    def _evidence_block(item: dict[str, Any]) -> dict[str, str]:
        """검색 결과를 metadata 손실 없는 signed answer evidence로 투영한다."""

        return {
            "evidence_id": str(item.get("evidence_id") or ""),
            "text": str(item.get("content") or item.get("snippet") or ""),
            "title": str(item.get("title") or ""),
            "manual_id": str(item.get("manual_id") or ""),
            "version": str(item.get("version") or ""),
            "document_type": str(item.get("document_type") or ""),
            "owner_team": str(item.get("owner_team") or ""),
            "section_title": str(item.get("section_title") or ""),
            "citation": str(item.get("citation") or ""),
        }

    @staticmethod
    def _answer_body(answer: str) -> str:
        marker = "본문내용:\n"
        if marker not in answer:
            body = answer.strip()
        else:
            body = answer.split(marker, 1)[1]
            body = body.rsplit("\n근거:", 1)[0].strip()
        body = re.sub(
            r"\s*내부\s*업무지침\s*[·ㆍ]\s*현장\s*실행형\s*[·ㆍ]\s*의미전달\s*검증완료본",
            "",
            body,
        )
        return re.sub(
            r"(?:^|\n)\s*자세한 내용은 PDF 원문 보기를 확인하세요\.?\s*(?=\n|$)",
            "\n",
            body,
        ).strip()

    @staticmethod
    def _answer_area(answer: str, fallback: str) -> str:
        match = re.search(r"^영역:\s*(.+)$", answer, re.MULTILINE)
        return match.group(1).strip() if match else fallback

    @staticmethod
    def _evidence_bundle(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": str(item.get("evidence_id") or ""),
                "document_id": str(item.get("manual_id") or ""),
                "document_name": str(item.get("title") or ""),
                "document_version": str(item.get("version") or ""),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "section": str(item.get("section_title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "score": float(item.get("score") or 0),
                "confidence": "LOW" if item.get("validity_status") == "UNRESOLVED" else "MEDIUM",
            }
            for item in results
            if isinstance(item, dict) and item.get("evidence_id")
        ]


RagGatewayTool = InternalManualAgent
