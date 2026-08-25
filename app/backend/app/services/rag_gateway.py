"""승인된 RAG Tool을 HMAC으로 호출하고 최소 실행 근거를 App DB에 남긴다."""

from __future__ import annotations

import hashlib
import hmac
import json
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
_ROLE_MAP = {
    "analyst": "STAFF",
    "report_admin": "MANAGER",
    "data_admin": "MANAGER",
    "platform_admin": "SYSTEM_ADMIN",
}


class RagToolError(RuntimeError):
    """RAG 입력·권한·외부 의존성 실패를 공개 코드와 HTTP 상태로 전달한다."""

    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class InternalManualAgent:
    """App role을 RAG role로 변환하고 승인된 검색·답변 Tool 호출을 조정한다."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._base_url = os.getenv("RAG_API_URL", "http://rag-api:8000").rstrip("/")
        self._secret = os.getenv("RAG_GATEWAY_HMAC_SECRET", "")
        self._timeout = float(os.getenv("RAG_TOOL_TIMEOUT_SECONDS", "30"))
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
    ) -> dict[str, Any]:
        """서명된 검색과 답변을 순서대로 호출하고 인용 근거가 일치할 때만 성공을 반환한다."""

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
                    "top_k": 5,
                    "recent_utterances": list(recent),
                    "selected_document_ids": [],
                },
                rag_role,
            )
            results = search.get("results") if isinstance(search, dict) else None
            if search.get("no_evidence") is True or not isinstance(results, list) or not results:
                output = {"status": "NO_EVIDENCE", "trace_id": trace_id}
                await self._record(actor_id, app_role, trace_id, normalized, output, started)
                return output

            evidence_blocks = [self._evidence_block(item) for item in results if isinstance(item, dict)]
            evidence_blocks = [item for item in evidence_blocks if item["evidence_id"] and item["text"]]
            if not evidence_blocks:
                raise RagToolError("RAG_OUTPUT_INVALID", "검색 근거 형식이 올바르지 않습니다.")
            answer = await self._signed_post(
                "/v1/tools/internal-manual-answer",
                {"query": contextual_query, "evidence_blocks": evidence_blocks},
                rag_role,
            )
            answer_status = str(answer.get("status") or "")
            if answer_status == "NO_EVIDENCE":
                output = {
                    "status": "NO_EVIDENCE",
                    "answer_id": str(answer.get("request_id") or ""),
                    "trace_id": trace_id,
                    "processing_steps": list(search.get("processing_steps") or []),
                }
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
            cited_ids = {
                str(item.get("evidence_id") or "")
                for item in answer.get("citations", [])
                if isinstance(item, dict)
            }
            if not cited_ids or not cited_ids.issubset(retrieved_ids):
                raise RagToolError("RAG_CITATION_INVALID", "검색 결과와 답변 근거가 일치하지 않습니다.")
            comparison_results: list[dict[str, Any]] = []
            seen_titles: set[str] = set()
            for item in results:
                title = str(item.get("title") or "").strip()
                if title and title not in seen_titles:
                    comparison_results.append(item)
                    seen_titles.add(title)
                if len(comparison_results) == 2:
                    break
            cited_results = [
                item for item in results
                if str(item.get("evidence_id") or "") in cited_ids
            ]
            displayed_candidates = cited_results if len(cited_ids) >= 2 else comparison_results
            displayed = (
                displayed_candidates[:2]
                if len(displayed_candidates) >= 2 and (intent == "COMPARISON" or len(cited_ids) >= 2)
                else [results[0]]
            )
            top = displayed[0]
            normalized_body = top.get("normalized_body") if isinstance(top.get("normalized_body"), dict) else {}
            answer_summary = [
                str(item).strip()
                for item in answer.get("summary", [])
                if str(item).strip()
            ][:4]
            if not answer_summary:
                answer_summary = [self._answer_body(str(answer.get("answer") or ""), evidence_blocks[0]["text"])]
            output = {
                "status": "ANSWER",
                "response_status": "ANSWERED",
                "answer_type": answer.get("answer_type") or ("COMPARE" if intent == "COMPARISON" else "SUMMARY"),
                "answer_id": str(answer.get("request_id") or ""),
                "answer": {"text": "\n\n".join(answer_summary)},
                "agent": str(search.get("agent") or "INTERNAL_GUIDELINE"),
                "processing_steps": list(search.get("processing_steps") or []),
                "evidence_bundle": self._evidence_bundle(results),
                "citations": list(answer.get("citations") or []),
                "request_id": str(answer.get("request_id") or ""),
                "trace_id": trace_id,
                "routing": {"domains": list(domains), "intent": intent, "resolved_with_context": contextual_query != normalized},
                "document": {
                    "document_name": " / ".join(str(item.get("title") or "확인 불가") for item in displayed),
                    "document_version": str(top.get("version") or "확인 불가"),
                    "guideline_number": " / ".join(str(item.get("manual_id") or "확인 불가") for item in displayed),
                    "area": self._answer_area(
                        str(answer.get("answer") or ""),
                        str(top.get("section_title") or "확인 불가"),
                    ),
                    "body": "\n\n".join(answer_summary),
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
            raise RagToolError("RAG_DEPENDENCY_FAILED", "RAG 검색 서비스에 연결하지 못했습니다.") from error

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

    async def fetch_catalog(self, app_role: str) -> list[dict[str, Any]]:
        """App 역할을 RAG 역할로 변환해 허용된 내부 문서 목록만 조회한다."""

        rag_role = _ROLE_MAP.get(app_role)
        if rag_role is None:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 문서 검색 권한이 없습니다.", 403)
        await self._assert_enabled(app_role)
        result = await self._signed_post("/v1/tools/internal-manual-catalog", {}, rag_role)
        return list(result.get("documents") or [])

    async def fetch_pdf(self, manual_id: str, app_role: str) -> tuple[bytes, str]:
        """문서 ID와 역할을 검증하고 HMAC 서명으로 원본 PDF와 disposition을 조회한다."""

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
    def _evidence_block(item: dict[str, Any]) -> dict[str, str]:
        return {
            "evidence_id": str(item.get("evidence_id") or ""),
            "text": str(item.get("content") or item.get("snippet") or ""),
            "title": str(item.get("title") or ""),
            "manual_id": str(item.get("manual_id") or ""),
            "section_title": str(item.get("section_title") or ""),
            "citation": str(item.get("citation") or ""),
        }

    @staticmethod
    def _answer_body(answer: str, fallback: str) -> str:
        marker = "본문내용:\n"
        if marker not in answer:
            return answer.strip() or fallback
        body = answer.split(marker, 1)[1]
        return body.rsplit("\n근거:", 1)[0].strip() or fallback

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
