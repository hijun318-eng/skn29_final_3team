"""배포된 내부 문서 RAG의 health→서명 검색→근거 답변 계약을 HTTP로 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from src.rag.request_auth import (
    GatewayRequestAuthenticator,
    canonical_answer_request,
    canonical_search_request,
)


class ManualRagE2EError(RuntimeError):
    """내부 문서 RAG의 설정, 통신, 검색 근거, 답변 인용 계약 위반을 나타낸다."""


@dataclass(frozen=True)
class ManualRagE2EConfig:
    """배포 RAG 주소, Gateway 서명 비밀, 역할, 질문, 제한과 증거 저장 경로를 보관한다."""

    base_url: str
    gateway_secret: str
    role: str
    query: str
    top_k: int
    timeout_seconds: float
    artifact_dir: Path

    @classmethod
    def from_environment(cls) -> "ManualRagE2EConfig":
        """환경 변수에서 E2E 설정을 읽고 비밀 길이·질의·역할·top-k 범위를 검증한다."""

        try:
            top_k = int(os.getenv("RAG_E2E_TOP_K", "3"))
            timeout_seconds = float(os.getenv("RAG_E2E_TIMEOUT_SECONDS", "20"))
        except ValueError as error:
            raise ManualRagE2EError(
                "RAG E2E top_k and timeout must be numeric"
            ) from error
        config = cls(os.getenv("RAG_E2E_BASE_URL", "").strip().rstrip("/"), os.getenv("RAG_E2E_GATEWAY_HMAC_SECRET", "").strip(), os.getenv("RAG_E2E_ROLE", "MANAGER").strip().upper(), os.getenv("RAG_E2E_QUERY", "").strip(), top_k, timeout_seconds, Path(os.getenv("RAG_E2E_ARTIFACT_DIR", "evals/runs/rag")))
        if not config.base_url or len(config.gateway_secret) < 32:
            raise ManualRagE2EError("RAG_E2E_BASE_URL and a 32+ character gateway secret are required")
        if len(config.role) < 2 or len(config.query) < 2 or not 1 <= config.top_k <= 10:
            raise ManualRagE2EError("Invalid Manual RAG E2E role, query, or top_k")
        if not math.isfinite(config.timeout_seconds) or not 0.1 <= config.timeout_seconds <= 300.0:
            raise ManualRagE2EError(
                "RAG E2E timeout must be between 0.1 and 300 seconds"
            )
        return config


@dataclass
class ManualRagE2EReport:
    """내부 문서 E2E의 request·trace와 단계별 최소 영수증, 최종 오류를 누적한다."""

    request_id: str
    trace_id: str
    started_at: str
    final_stage: str = "STARTED"
    stages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def record(self, stage: str, payload: dict[str, Any]) -> None:
        """단계 이름과 민감 원문을 제외한 영수증을 추가하고 최종 단계를 갱신한다."""

        self.final_stage = stage
        self.stages.append({"stage": stage, "payload": payload})

    def to_dict(self) -> dict[str, Any]:
        """데이터클래스 보고서를 JSON 저장 가능한 사전으로 변환한다."""

        return asdict(self)


class JsonHttpClient:
    """배포 RAG에 리다이렉트 없이 JSON GET·POST를 수행하고 비객체 응답을 거부한다."""

    def __init__(self, timeout_seconds: float) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0.1 <= float(timeout_seconds) <= 300.0
        ):
            raise ManualRagE2EError(
                "RAG E2E timeout must be between 0.1 and 300 seconds"
            )
        self._timeout_seconds = timeout_seconds

    def get(self, url: str) -> dict[str, Any]:
        """지정 URL을 GET하고 성공한 JSON 객체만 반환하며 네트워크·형식 오류는 E2E 오류로 바꾼다."""

        return self._request(url, "GET", None, {})

    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        """서명 헤더와 JSON payload를 POST하고 Gateway 요청 ID를 응답 영수증에 덧붙인다."""

        response = self._request(url, "POST", payload, headers)
        response["gateway_request_id"] = headers.get("X-Request-Id", "")
        return response
    def _request(self, url: str, method: str, payload: dict[str, Any] | None, headers: dict[str, str]) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            with httpx.Client(
                timeout=httpx.Timeout(float(self._timeout_seconds)),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.request(
                    method,
                    url,
                    content=body,
                    headers={"Content-Type": "application/json"} | headers,
                )
            if response.is_redirect:
                raise ManualRagE2EError(f"Redirect is not allowed from {url}")
            if response.status_code >= 400:
                raise ManualRagE2EError(
                    f"HTTP {response.status_code} from {url}"
                )
            decoded = response.text
        except httpx.RequestError as error:
            raise ManualRagE2EError(f"Network failure for {url}") from error
        try:
            result = json.loads(decoded)
        except json.JSONDecodeError as error:
            raise ManualRagE2EError(f"Non-JSON response from {url}") from error
        if not isinstance(result, dict):
            raise ManualRagE2EError(f"JSON object response required from {url}")
        return result


class ManualRagE2EOrchestrator:
    """배포 RAG의 생존·준비·검색·답변 순서를 실행하고 근거 연계 결과를 보고한다."""

    def __init__(self, config: ManualRagE2EConfig, http_client: JsonHttpClient | None = None) -> None:
        self._config = config
        self._http = http_client or JsonHttpClient(config.timeout_seconds)

    def run(self) -> ManualRagE2EReport:
        """서명된 검색 근거만 답변에 전달해 trace와 citation 일치를 확인하고 실패도 보고서로 반환한다."""

        trace_id = str(uuid4())
        report = ManualRagE2EReport(str(uuid4()), trace_id, datetime.now(timezone.utc).isoformat())
        actor_hash = hashlib.sha256(
            f"manual-rag-e2e:{self._config.role}".encode("utf-8")
        ).hexdigest()
        try:
            self._verify_health(report, "/health/live", "LIVE_READY")
            self._verify_health(report, "/health/ready", "READY")
            search_payload = {
                "query": self._config.query,
                "top_k": self._config.top_k,
                "recent_utterances": [],
                "selected_document_ids": [],
                "trace_id": trace_id,
                "actor_hash": actor_hash,
            }
            search = self._http.post(f"{self._config.base_url}/v1/tools/internal-manual-search", search_payload, self._signed_headers(search_payload, trace_id))
            evidence_blocks = self._evidence_blocks(search)
            report.record("SEARCHED", {"evidence_count": len(search.get("results", [])), "gateway_request_id": search.get("gateway_request_id", "")})
            retrieval_request_id = str(search.get("request_id") or "")
            if not retrieval_request_id:
                raise ManualRagE2EError("Manual RAG search returned no retrieval receipt")
            answer_query = search.get("answer_query")
            if not isinstance(answer_query, str) or answer_query != self._config.query:
                raise ManualRagE2EError(
                    "Manual RAG search returned no normalized answer query"
                )
            answer_payload = {
                "query": answer_query,
                "evidence_blocks": evidence_blocks,
                "intent": "REGULATION_CHECK",
                "retrieval_request_id": retrieval_request_id,
                "trace_id": trace_id,
                "actor_hash": actor_hash,
            }
            answer = self._http.post(f"{self._config.base_url}/v1/tools/internal-manual-answer", answer_payload, self._signed_headers(answer_payload, trace_id))
            if answer.get("trace_id") != trace_id:
                raise ManualRagE2EError(
                    "Manual RAG answer did not preserve the signed trace"
                )
            self._validate_answer(answer, evidence_blocks)
            report.record("ANSWERED", {"status": answer["status"], "citation_count": len(answer["citations"]), "gateway_request_id": answer.get("gateway_request_id", "")})
            report.record("SUCCEEDED", {"contract": "manual-policy-rag-v1"})
        except ManualRagE2EError as error:
            report.error = str(error)
            report.record("FAILED", {"error": report.error})
        return report

    def persist(self, report: ManualRagE2EReport) -> Path:
        """E2E 보고서를 artifact 경로에 UTF-8 JSON으로 저장하고 생성된 파일 경로를 반환한다."""

        self._config.artifact_dir.mkdir(parents=True, exist_ok=True)
        output = self._config.artifact_dir / f"manual_rag_e2e_{report.request_id}.json"
        output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return output

    def _verify_health(self, report: ManualRagE2EReport, path: str, stage: str) -> None:
        status = str(self._http.get(f"{self._config.base_url}{path}").get("status", "")).lower()
        if status not in {"alive", "healthy", "ready", "ok"}:
            raise ManualRagE2EError(f"{path} returned non-ready status: {status or 'missing'}")
        report.record(stage, {"status": status})

    def _signed_headers(self, payload: dict[str, Any], trace_id: str) -> dict[str, str]:
        request_id, timestamp = str(uuid4()), str(int(time.time()))
        canonical = (
            canonical_answer_request(
                payload["query"],
                tuple(payload.get("evidence_blocks", [])),
                str(payload.get("intent") or "REGULATION_CHECK"),
                str(payload.get("retrieval_request_id") or "") or None,
                trace_id=str(payload["trace_id"]),
                actor_hash=str(payload["actor_hash"]),
            )
            if "evidence_blocks" in payload
            else canonical_search_request(
                payload["query"],
                int(payload["top_k"]),
                tuple(payload.get("recent_utterances", ())),
                tuple(payload.get("selected_document_ids", ())),
                trace_id=str(payload["trace_id"]),
                actor_hash=str(payload["actor_hash"]),
            )
        )
        signature = GatewayRequestAuthenticator.build_signature(
            self._config.gateway_secret, timestamp, request_id, self._config.role, canonical
        )
        return {"X-Verified-Role": self._config.role, "X-Request-Id": request_id, "X-Request-Timestamp": timestamp, "X-Request-Signature": signature}

    @staticmethod
    def _evidence_blocks(search: dict[str, Any]) -> list[dict[str, str]]:
        results = search.get("results")
        if search.get("no_evidence") or not isinstance(results, list) or not results:
            raise ManualRagE2EError("Manual RAG search returned no evidence")
        blocks: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for item in results:
            if not isinstance(item, dict):
                raise ManualRagE2EError("Search results must all be evidence objects")
            raw_evidence_id = item.get("evidence_id")
            raw_text = item.get("content")
            if raw_text is None:
                raw_text = item.get("snippet")
            raw_citation = item.get("citation")
            if (
                not isinstance(raw_evidence_id, str)
                or not raw_evidence_id.strip()
                or not isinstance(raw_text, str)
                or not raw_text.strip()
                or not isinstance(raw_citation, str)
                or not raw_citation.strip()
            ):
                raise ManualRagE2EError(
                    "Every search result must include string evidence_id, text, and citation"
                )
            block = {
                "evidence_id": raw_evidence_id.strip(),
                "text": raw_text.strip(),
                "title": str(item.get("title", "")).strip(),
                "manual_id": str(item.get("manual_id", "")).strip(),
                "version": str(item.get("version", "")).strip(),
                "document_type": str(item.get("document_type", "")).strip(),
                "owner_team": str(item.get("owner_team", "")).strip(),
                "section_title": str(item.get("section_title", "")).strip(),
                "citation": raw_citation.strip(),
            }
            if block["evidence_id"] in seen_ids:
                raise ManualRagE2EError("Search results contain duplicate evidence identity")
            seen_ids.add(block["evidence_id"])
            blocks.append(block)
        return blocks

    @staticmethod
    def _validate_answer(answer: dict[str, Any], evidence_blocks: list[dict[str, str]]) -> None:
        if answer.get("status") != "ANSWER" or not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
            detail = answer.get("error") or answer.get("message") or answer.get("detail") or answer.get("answer") or "no diagnostic detail"
            raise ManualRagE2EError(f"Answer service returned {answer.get('status', 'invalid')}: {detail}")
        citations = answer.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ManualRagE2EError("Answer service returned no citations")
        allowed = {
            item["evidence_id"]: item["citation"]
            for item in evidence_blocks
        }
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("evidence_id"), str)
            or not item["evidence_id"].strip()
            or not isinstance(item.get("citation"), str)
            or item["evidence_id"] not in allowed
            or item["citation"] != allowed[item["evidence_id"]]
            for item in citations
        ):
            raise ManualRagE2EError(
                "Answer citations do not exactly match evidence returned by the search"
            )
        cited = [item["evidence_id"] for item in citations]
        if len(cited) != len(set(cited)):
            raise ManualRagE2EError("Answer citations contain duplicate evidence identity")


def main(argv: list[str] | None = None) -> int:
    """환경 설정으로 배포 RAG E2E를 실행하고 성공·실패·설정 차단 종료 코드를 반환한다."""

    parser = argparse.ArgumentParser(description="Run the deployed Manual/Policy RAG E2E contract")
    parser.add_argument("--print-report", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        config = ManualRagE2EConfig.from_environment()
    except ManualRagE2EError as error:
        print(json.dumps({"final_stage": "BLOCKED", "error": str(error)}, ensure_ascii=False))
        return 2
    orchestrator = ManualRagE2EOrchestrator(config)
    report = orchestrator.run()
    output = orchestrator.persist(report)
    payload = report.to_dict() | {"report_path": str(output)}
    if arguments.print_report:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"final_stage": report.final_stage, "report_path": str(output)}, ensure_ascii=False))
    return 0 if report.final_stage == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
