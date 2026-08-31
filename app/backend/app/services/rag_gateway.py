"""승인된 RAG Tool을 HMAC으로 호출하고 최소 실행 근거를 App DB에 남긴다."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import time
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import session_scope


RAG_TOOL_ID = UUID("8edce655-e454-5b76-b56f-5e49aa2884d4")
RAG_TOOL_CODE = "rag.answer"
RAG_CAPABILITY_CANDIDATE_VERSION = "RagCapabilityCandidate.v1"
RAG_RUNTIME_RECEIPT_VERSION = "RagRuntimeReceipt.v1"
RAG_MAX_EMBEDDING_DIMENSION = 65536
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
        """앱 역할을 검증해 검색·답변 도구를 호출하고 근거가 있는 결과만 반환한다."""
        normalized = query.strip()
        if not 2 <= len(normalized) <= 500:
            raise RagToolError("RAG_INPUT_INVALID", "질문은 2자 이상 500자 이하여야 합니다.", 422)
        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 검색 권한이 없습니다.", 403)
        started = time.perf_counter()
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
        ))[-500:]
        await self._assert_enabled(app_role)
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
                },
                rag_role,
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
                await self._record(actor_id, app_role, trace_id, normalized, output, started)
                return output

            evidence_blocks = [
                self._evidence_block(item)
                for item in results
                if isinstance(item, dict)
            ]
            evidence_blocks = [item for item in evidence_blocks if item["evidence_id"] and item["text"]]
            if not evidence_blocks:
                raise RagToolError("RAG_OUTPUT_INVALID", "검색 근거 형식이 올바르지 않습니다.")
            answer = await self._signed_post(
                "/v1/tools/internal-manual-answer",
                {
                    "query": contextual_query,
                    "evidence_blocks": evidence_blocks,
                    "intent": intent,
                    "retrieval_request_id": str(search.get("request_id") or "") or None,
                },
                rag_role,
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
                await self._record(actor_id, app_role, trace_id, normalized, output, started)
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
                await self._record(actor_id, app_role, trace_id, normalized, output, started)
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
            await self._record(actor_id, app_role, trace_id, normalized, output, started)
            return output
        except RagToolError as error:
            await self._record(actor_id, app_role, trace_id, normalized, {}, started, error.code)
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            await self._record(actor_id, app_role, trace_id, normalized, {}, started, "RAG_DEPENDENCY_FAILED")
            return self._empty_answer_output(
                "ERROR",
                trace_id,
                intent,
                _DEPENDENCY_FAILURE_MESSAGE,
                ["DEPENDENCY_FAILED"],
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
        retrieval_release = search.get("retrieval_release")
        embedding_dimension = (
            retrieval_release.get("embedding_dimension")
            if isinstance(retrieval_release, dict)
            else None
        )
        if (
            not isinstance(execution_state, dict)
            or execution_state.get("p2_gate") != "TECHNICALLY_VALIDATED"
            or execution_state.get("production_integration")
            != "LOCAL_DOCKER_VALIDATED"
            or not isinstance(tool, dict)
            or tool.get("tool_code") != "internal-manual-search"
            or not isinstance(tool.get("semantic_version"), str)
            or not re.fullmatch(r"[A-Za-z0-9._+-]{1,80}", tool["semantic_version"])
            or not isinstance(retrieval_release, dict)
            or retrieval_release.get("schema_version")
            != "RagRetrievalRelease.v1"
            or not isinstance(retrieval_release.get("model_revision"), str)
            or not retrieval_release["model_revision"].strip()
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
            or not isinstance(documents, list)
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

    async def fetch_pdf(self, manual_id: str, app_role: str) -> tuple[bytes, str]:
        """문서 식별자와 역할을 검증한 뒤 허용된 PDF 원문을 내려받는다."""
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,99}", manual_id):
            raise RagToolError("RAG_INPUT_INVALID", "문서 식별자가 올바르지 않습니다.", 422)
        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 문서 열람 권한이 없습니다.", 403)
        await self._assert_enabled(app_role)
        canonical = json.dumps(
            {"manual_id": manual_id}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        request_id = str(uuid4())
        timestamp = str(int(time.time()))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        message = f"{timestamp}\n{request_id}\n{rag_role}\n{digest}".encode("utf-8")
        signature = hmac.new(self._secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.get(
                    f"{self._base_url}/v1/documents/{quote(manual_id, safe='')}/source.pdf",
                    headers={
                        "X-Verified-Role": rag_role,
                        "X-Request-Timestamp": timestamp,
                        "X-Request-Id": request_id,
                        "X-Request-Signature": signature,
                    },
                )
                response.raise_for_status()
            return response.content, response.headers.get(
                "Content-Disposition", f'inline; filename="{manual_id}.pdf"'
            )
        except httpx.HTTPStatusError as error:
            status = 404 if error.response.status_code == 404 else 503
            raise RagToolError("RAG_DOCUMENT_UNAVAILABLE", "RAG 원본 PDF를 찾을 수 없습니다.", status) from error
        except httpx.HTTPError as error:
            raise RagToolError("RAG_DEPENDENCY_FAILED", "RAG 문서 서비스에 연결하지 못했습니다.") from error

    async def _assert_enabled(self, app_role: str) -> None:
        try:
            async with session_scope(self._database_url) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT required_roles_json FROM tooling.tool_registry "
                            "WHERE tool_id=:tool_id AND tool_code=:tool_code AND is_enabled=true"
                        ),
                        {"tool_id": RAG_TOOL_ID, "tool_code": RAG_TOOL_CODE},
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise RagToolError("RAG_REGISTRY_UNAVAILABLE", "RAG Tool Registry를 확인하지 못했습니다.") from error
        if row is None:
            raise RagToolError("RAG_TOOL_DISABLED", "RAG Tool이 승인되지 않았습니다.", 503)
        roles = row if isinstance(row, list) else json.loads(row)
        if app_role not in roles:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 검색 권한이 없습니다.", 403)

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
                        "(tool_run_id,tool_id,caller_user_id,caller_role,trace_id,input_hash,status,latency_ms,output_ref_json,error_code) "
                        "VALUES (:run_id,:tool_id,:actor,:role,:trace,:input_hash,:status,:latency,CAST(:output AS jsonb),:error)"
                    ),
                    {
                        "run_id": uuid4(), "tool_id": RAG_TOOL_ID, "actor": actor_id, "role": role,
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
        return {
            "evidence_id": str(item.get("evidence_id") or ""),
            "text": str(item.get("content") or item.get("snippet") or ""),
            "title": str(item.get("title") or ""),
            "manual_id": str(item.get("manual_id") or ""),
            "section_title": str(item.get("section_title") or ""),
            "page_start": str(item.get("page_start") or ""),
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
