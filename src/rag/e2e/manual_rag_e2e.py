from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from src.rag.request_auth import (
    GatewayRequestAuthenticator,
    canonical_answer_request,
    canonical_search_request,
)


class ManualRagE2EError(RuntimeError):
    """Manual/Policy RAG E2E contract violation."""


@dataclass(frozen=True)
class ManualRagE2EConfig:
    base_url: str
    gateway_secret: str
    role: str
    query: str
    top_k: int
    timeout_seconds: float
    artifact_dir: Path
    intent: str = "REGULATION_CHECK"

    @classmethod
    def from_environment(cls) -> "ManualRagE2EConfig":
        config = cls(os.getenv("RAG_E2E_BASE_URL", "").strip().rstrip("/"), os.getenv("RAG_E2E_GATEWAY_HMAC_SECRET", "").strip(), os.getenv("RAG_E2E_ROLE", "MANAGER").strip().upper(), os.getenv("RAG_E2E_QUERY", "").strip(), int(os.getenv("RAG_E2E_TOP_K", "3")), float(os.getenv("RAG_E2E_TIMEOUT_SECONDS", "20")), Path(os.getenv("RAG_E2E_ARTIFACT_DIR", "evals/runs/rag")), os.getenv("RAG_E2E_INTENT", "REGULATION_CHECK").strip().upper())
        if not config.base_url or len(config.gateway_secret) < 32:
            raise ManualRagE2EError("RAG_E2E_BASE_URL and a 32+ character gateway secret are required")
        if len(config.role) < 2 or len(config.query) < 2 or not 1 <= config.top_k <= 10:
            raise ManualRagE2EError("Invalid Manual RAG E2E role, query, or top_k")
        if config.intent not in {
            "PROCESS", "IMMEDIATE_ACTION", "DECISION_CRITERIA",
            "REGULATION_CHECK", "COMPARISON", "SUMMARY",
        }:
            raise ManualRagE2EError("Invalid Manual RAG E2E intent")
        return config


@dataclass
class ManualRagE2EReport:
    request_id: str
    trace_id: str
    started_at: str
    final_stage: str = "STARTED"
    stages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def record(self, stage: str, payload: dict[str, Any]) -> None:
        self.final_stage = stage
        self.stages.append({"stage": stage, "payload": payload})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonHttpClient:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def get(self, url: str) -> dict[str, Any]:
        return self._request(url, "GET", None, {})

    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        response = self._request(url, "POST", payload, headers)
        response["gateway_request_id"] = headers.get("X-Request-Id", "")
        return response
    def _request(self, url: str, method: str, payload: dict[str, Any] | None, headers: dict[str, str]) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"} | headers)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                decoded = response.read().decode("utf-8")
        except HTTPError as error:
            raise ManualRagE2EError(f"HTTP {error.code} from {url}") from error
        except URLError as error:
            raise ManualRagE2EError(f"Network failure for {url}: {error.reason}") from error
        try:
            result = json.loads(decoded)
        except json.JSONDecodeError as error:
            raise ManualRagE2EError(f"Non-JSON response from {url}") from error
        if not isinstance(result, dict):
            raise ManualRagE2EError(f"JSON object response required from {url}")
        return result


class ManualRagE2EOrchestrator:
    def __init__(self, config: ManualRagE2EConfig, http_client: JsonHttpClient | None = None) -> None:
        self._config = config
        self._http = http_client or JsonHttpClient(config.timeout_seconds)

    def run(self) -> ManualRagE2EReport:
        trace_id = str(uuid4())
        report = ManualRagE2EReport(str(uuid4()), trace_id, datetime.now(timezone.utc).isoformat())
        try:
            self._verify_health(report, "/health/live", "LIVE_READY")
            self._verify_health(report, "/health/ready", "READY")
            search_payload = {
                "query": self._config.query,
                "top_k": self._config.top_k,
                "recent_utterances": [],
                "selected_document_ids": [],
                "intent": self._config.intent,
            }
            search = self._http.post(f"{self._config.base_url}/v1/tools/internal-manual-search", search_payload, self._signed_headers(search_payload, trace_id))
            evidence_blocks = self._evidence_blocks(search)
            retrieval_request_id = str(
                search.get("request_id") or search.get("gateway_request_id") or ""
            ) or None
            report.record("SEARCHED", {"evidence_count": len(search.get("results", [])), "gateway_request_id": search.get("gateway_request_id", ""), "intent": self._config.intent})
            answer_payload = {
                "query": self._config.query,
                "evidence_blocks": evidence_blocks,
                "intent": self._config.intent,
                "retrieval_request_id": retrieval_request_id,
            }
            answer = self._http.post(f"{self._config.base_url}/v1/tools/internal-manual-answer", answer_payload, self._signed_headers(answer_payload, trace_id))
            self._validate_answer(answer, evidence_blocks)
            report.record("ANSWERED", {"status": answer["status"], "citation_count": len(answer["citations"]), "gateway_request_id": answer.get("gateway_request_id", "")})
            report.record("SUCCEEDED", {"contract": "manual-policy-rag-v1"})
        except ManualRagE2EError as error:
            report.error = str(error)
            report.record("FAILED", {"error": report.error})
        return report

    def persist(self, report: ManualRagE2EReport) -> Path:
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
                str(payload.get("intent", "REGULATION_CHECK")),
                payload.get("retrieval_request_id"),
            )
            if "evidence_blocks" in payload
            else canonical_search_request(
                payload["query"],
                int(payload["top_k"]),
                tuple(payload.get("recent_utterances", ())),
                tuple(payload.get("selected_document_ids", ())),
                payload.get("resolved_question"),
                tuple(payload.get("domains", ())),
                str(payload.get("intent", "REGULATION_CHECK")),
            )
        )
        signature = GatewayRequestAuthenticator.build_signature(
            self._config.gateway_secret, timestamp, request_id, self._config.role, canonical
        )
        return {"X-Verified-Role": self._config.role, "X-Request-Id": request_id, "X-Request-Timestamp": timestamp, "X-Request-Signature": signature, "X-Trace-Id": trace_id}

    @staticmethod
    def _evidence_blocks(search: dict[str, Any]) -> list[dict[str, Any]]:
        results = search.get("results")
        if search.get("no_evidence") or not isinstance(results, list) or not results:
            raise ManualRagE2EError("Manual RAG search returned no evidence")
        blocks: list[dict[str, Any]] = []
        metadata_fields = (
            "title", "manual_id", "version", "section_title", "page_start",
            "chunk_id", "chunk_index", "score", "vector_score", "lexical_score",
            "document_status", "approval_status", "validity_status",
            "effective_from", "expires_at", "citation", "ranking_stage",
        )
        for item in results:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id", "")).strip()
            content = str(item.get("content") or item.get("snippet") or "").strip()
            if not evidence_id or not content:
                continue
            block = {field: item.get(field) for field in metadata_fields}
            block.update({
                "evidence_id": evidence_id,
                "document_id": str(item.get("manual_id", "")).strip(),
                "content": content,
            })
            blocks.append(block)
        if not blocks:
            raise ManualRagE2EError("Search results did not contain usable evidence blocks")
        return blocks

    @staticmethod
    def _validate_answer(answer: dict[str, Any], evidence_blocks: list[dict[str, Any]]) -> None:
        if answer.get("status") != "ANSWER" or not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
            detail = answer.get("error") or answer.get("message") or answer.get("detail") or answer.get("answer") or "no diagnostic detail"
            raise ManualRagE2EError(f"Answer service returned {answer.get('status', 'invalid')}: {detail}")
        citations = answer.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ManualRagE2EError("Answer service returned no citations")
        allowed = {item["evidence_id"] for item in evidence_blocks}
        cited = {str(item.get("evidence_id", "")) for item in citations if isinstance(item, dict)}
        if not cited <= allowed:
            raise ManualRagE2EError("Answer citations reference evidence not returned by the search")


def main(argv: list[str] | None = None) -> int:
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
