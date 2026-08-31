from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .clients import (
    AnalysisCoreClient,
    JsonHttpClient,
    MlRuntimeClient,
    RagGatewayClient,
    RuntimeHealthClient,
    RuntimeRequestError,
)
from .contracts import DynamicE2EConfig, DynamicE2EReport, E2EStage, StageEvidence


class DynamicE2EOrchestrator:
    """Runs the full path only through configured, real runtime endpoints."""

    def __init__(self, config: DynamicE2EConfig) -> None:
        self._config = config
        http = JsonHttpClient(config.timeout_seconds)
        self._analysis_health = RuntimeHealthClient(config.analysis, http)
        self._rag_health = RuntimeHealthClient(config.rag, http)
        self._analysis = AnalysisCoreClient(config, http)
        self._rag = RagGatewayClient(config, http)
        self._ml = MlRuntimeClient(config, http)

    def run(self) -> DynamicE2EReport:
        report = DynamicE2EReport(
            request_id=self._config.request_id,
            trace_id=self._config.trace_id,
        )
        try:
            self._record_health(report, E2EStage.ANALYSIS, self._analysis_health, "analysis-core")
            analysis = self._record_call(report, E2EStage.ANALYSIS, self._analysis.analyze)

            self._record_health(report, E2EStage.RAG_SEARCH, self._rag_health, "rag")
            search = self._record_call(report, E2EStage.RAG_SEARCH, self._rag.search)
            evidence_blocks = self._extract_evidence_blocks(search.payload)
            answer_query = search.payload.get("answer_query")
            if (
                not isinstance(answer_query, str)
                or answer_query != self._config.rag_query
            ):
                raise RuntimeRequestError(
                    code="RAG_ANSWER_QUERY_INVALID",
                    message="RAG search did not return its normalized answer query",
                    response=search.payload,
                )
            retrieval_request_id = str(search.payload.get("request_id") or "")
            if not retrieval_request_id:
                raise RuntimeRequestError(
                    code="RAG_RETRIEVAL_RECEIPT_MISSING",
                    message="RAG search did not return its retrieval request receipt",
                    response=search.payload,
                )
            answer = self._record_call(
                report,
                E2EStage.RAG_ANSWER,
                lambda: self._rag.answer(
                    evidence_blocks,
                    retrieval_request_id,
                    answer_query,
                ),
            )
            if answer.payload.get("trace_id") != self._config.trace_id:
                raise RuntimeRequestError(
                    code="RAG_ANSWER_TRACE_INVALID",
                    message="RAG answer did not preserve the signed trace",
                    response=answer.payload,
                )
            self._validate_answer_uses_search_evidence(answer.payload, evidence_blocks)

            health = self._record_call(report, E2EStage.ML_HEALTH, self._ml.health)
            if self._is_model_approved(health.payload):
                self._record_call(
                    report,
                    E2EStage.ML_PREDICTION,
                    lambda: self._ml.prediction(analysis.payload),
                )
            else:
                report.record(
                    StageEvidence(
                        stage=E2EStage.ML_PREDICTION,
                        status="BLOCKED",
                        latency_ms=0.0,
                        details={"ml_health": health.payload},
                        error_code="ML_MODEL_BLOCKED",
                        error_message="The actual ML runtime reported no approved active model",
                    )
                )
                report.finish(E2EStage.BLOCKED)
                return report

            report.finish(E2EStage.SUCCEEDED)
            return report
        except RuntimeRequestError as error:
            report.record(
                StageEvidence(
                    stage=self._failure_stage(report),
                    status="FAILED",
                    latency_ms=0.0,
                    details=error.response,
                    error_code=error.code,
                    error_message=str(error),
                )
            )
            report.finish(E2EStage.FAILED)
            return report
        except ValueError as error:
            report.record(
                StageEvidence(
                    stage=self._failure_stage(report),
                    status="FAILED",
                    latency_ms=0.0,
                    details={},
                    error_code="INVALID_RUNTIME_CONTRACT",
                    error_message=str(error),
                )
            )
            report.finish(E2EStage.FAILED)
            return report

    def persist(self, report: DynamicE2EReport) -> Path:
        self._config.output_dir.mkdir(parents=True, exist_ok=True)
        destination = self._config.output_dir / f"dynamic-e2e-{report.request_id}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    @staticmethod
    def _is_model_approved(payload: dict[str, Any]) -> bool:
        approval = str(payload.get("approval_status", payload.get("status", ""))).upper()
        return payload.get("active") is True and approval in {"APPROVED", "HEALTHY", "READY"}

    def _record_health(
        self,
        report: DynamicE2EReport,
        stage: E2EStage,
        client: RuntimeHealthClient,
        runtime_name: str,
    ) -> None:
        response = self._record_call(report, stage, client.check)
        report.record(
            StageEvidence(
                stage=stage,
                status="HEALTHY",
                latency_ms=response.latency_ms,
                details={"runtime": runtime_name, "health": response.payload},
            )
        )

    @staticmethod
    def _record_call(
        report: DynamicE2EReport,
        stage: E2EStage,
        operation: Any,
    ) -> Any:
        started = time.perf_counter()
        response = operation()
        report.record(
            StageEvidence(
                stage=stage,
                status="SUCCEEDED",
                latency_ms=(time.perf_counter() - started) * 1000,
                details=response.payload,
            )
        )
        return response

    @staticmethod
    def _extract_evidence_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise RuntimeRequestError(
                code="RAG_SEARCH_EMPTY",
                message="The real RAG search runtime returned no evidence for the E2E request",
                response=payload,
            )
        evidence_blocks: list[dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                raise RuntimeRequestError(
                    code="RAG_RESULT_INVALID",
                    message="The real RAG runtime returned a non-object search result",
                    response=payload,
                )
            evidence_id = result.get("evidence_id")
            citation = result.get("citation")
            text = result.get("content") or result.get("snippet") or result.get("text")
            if not all(isinstance(value, str) and value.strip() for value in (evidence_id, citation, text)):
                raise RuntimeRequestError(
                    code="RAG_EVIDENCE_INCOMPLETE",
                    message="The real RAG result did not include evidence ID, citation and text",
                    response={"result": result},
                )
            evidence_blocks.append(
                {
                    "evidence_id": evidence_id,
                    "citation": citation,
                    "text": text,
                    "title": str(result.get("title") or ""),
                    "manual_id": str(result.get("manual_id") or ""),
                    "section_title": str(result.get("section_title") or ""),
                }
            )
        return evidence_blocks

    @staticmethod
    def _validate_answer_uses_search_evidence(
        answer_payload: dict[str, Any], evidence_blocks: list[dict[str, Any]]) -> None:
        status = str(answer_payload.get("status", "")).upper()
        if status != "ANSWER":
            raise RuntimeRequestError(
                code="RAG_ANSWER_NOT_AVAILABLE",
                message=f"The real RAG answer endpoint returned status {status or 'MISSING'}",
                response=answer_payload,
            )
        citations = answer_payload.get("citations")
        if not isinstance(citations, list) or not citations:
            raise RuntimeRequestError(
                code="RAG_ANSWER_UNCITED",
                message="The real RAG answer endpoint returned an answer without citations",
                response=answer_payload,
            )
        allowed_ids = {str(block["evidence_id"]) for block in evidence_blocks}
        for citation in citations:
            if not isinstance(citation, dict) or str(citation.get("evidence_id", "")) not in allowed_ids:
                raise RuntimeRequestError(
                    code="RAG_ANSWER_CITATION_MISMATCH",
                    message="The real RAG answer cited evidence not returned by this search request",
                    response=answer_payload,
                )

    @staticmethod
    def _failure_stage(report: DynamicE2EReport) -> E2EStage:
        if not report.stages:
            return E2EStage.INITIALIZED
        return report.stages[-1].stage
