from __future__ import annotations

import json
import hashlib
import threading
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .qwen_embedding import QwenEmbeddingProvider
from .embedding_provider import OpenAIEmbeddingProvider
from .access_policy import SearchAccessPolicy
from .evidence_repository import RagEvidenceRepository
from .evaluation_service import QualityEvaluator
from .lifecycle_repository import DocumentLifecycleRepository
from .lifecycle_fixture import build_lifecycle_fixture
from .pdf_ingestion import PdfManualParser
from .pgvector_repository import PgVectorRepository
from .quality_evaluation import SyntheticQualitySuite
from .retrieval_service import VectorRetrievalService
from .vector_settings import VectorSettings
from .p2_contracts import P2GateStatus, RagToolContract
from .contextual_query import ContextualQueryBuilder
from .vector_search_payload import build_search_payload, hash_search_input
from .manual_article_formatter import ManualArticleFormatter


class VectorRagApplication:
    @staticmethod
    def answer_document_limit(
        intent: str,
        selected_document_ids: tuple[str, ...],
    ) -> int:
        """명시적 비교와 승인된 두 문서 후속 문맥을 hydration에서 유지한다."""
        return 2 if intent == "COMPARISON" or len(selected_document_ids) > 1 else 1

    @staticmethod
    def answer_document_ids(
        selected_document_ids: tuple[str, ...],
        retrieved_document_ids: tuple[str, ...],
        limit: int,
    ) -> tuple[str, ...]:
        """서버가 저장한 문서 snapshot을 새 벡터 순위보다 우선한다."""
        return (selected_document_ids or retrieved_document_ids)[:limit]

    def __init__(self, project_root: Path) -> None:
        self._settings = VectorSettings.load(project_root)
        self._repository = PgVectorRepository(self._settings.database_url)

        reranker = None
        if self._settings.reranker_path:
            from .reranker import RerankerProvider
            # Just initialize reranker right away or lazy load? Lazy load is better but for now let's just do it
            reranker = RerankerProvider(self._settings.reranker_path, self._settings.device)

        self._retrieval = VectorRetrievalService(self._repository, reranker=reranker)
        self._evidence_repository = RagEvidenceRepository(self._settings.database_url)
        self._lifecycle = DocumentLifecycleRepository(self._settings.database_url)
        self._policy = SearchAccessPolicy.load(
            self._settings.config_dir / "access_policy.json"
        )
        self._embedding: QwenEmbeddingProvider | OpenAIEmbeddingProvider | None = None
        self._embedding_init_lock = threading.Lock()
        self._evidence_lock = threading.Lock()

    @property
    def database_url(self) -> str:
        return self._settings.database_url
    def migrate(self) -> dict[str, object]:
        migrations = sorted(self._settings.migrations_dir.glob("*.sql"))
        for migration in migrations:
            self._repository.migrate(migration)
        return {
            "status": "SUCCESS",
            "migrations": [str(path) for path in migrations],
            **self._repository.status(),
        }
    def ingest(self, limit: int | None = None) -> dict[str, object]:
        embedding_provider = self._get_embedding()
        embedding_metadata = self._embedding_metadata()
        run_id = uuid4()
        self._repository.start_run(run_id, embedding_metadata)
        from .token_chunker import TokenChunker
        chunker = TokenChunker(
            provider=embedding_provider,
            max_tokens=self._settings.chunk_max_tokens,
            overlap_tokens=self._settings.chunk_overlap_tokens
        )
        parser = PdfManualParser(chunker=chunker)
        all_files = sorted(self._settings.manuals_dir.glob("*.pdf"))
        files = [path for path in all_files if "내부업무매뉴얼_통합본" not in path.name]
        files = files[:limit] if limit else files
        processed_documents = 0
        created_chunks = 0
        skipped_documents = 0
        warnings: list[str] = []
        inspections: list[dict[str, object]] = []
        try:
            for path in files:
                document, chunks, parser_warnings, manifest = parser.parse(path)
                warnings.extend(parser_warnings)
                if self._repository.unchanged(document, embedding_metadata):
                    skipped_documents += 1
                    inspections.append({"manual_id": document.manual_id, "status": "UNCHANGED"})
                    continue
                vectors = self._get_embedding().embed_documents(
                    [chunk.content for chunk in chunks], self._settings.batch_size
                )
                created_chunks += self._repository.replace_document(document, chunks, vectors, embedding_metadata)
                processed_documents += 1
                inspections.append(
                    {"manual_id": document.manual_id, "status": "SUCCESS", "chunks": len(chunks), "manifest": manifest}
                )
            self._repository.finish_run(run_id, "SUCCESS", processed_documents, created_chunks)
        except Exception as error:
            self._repository.finish_run(
                run_id, "FAILED", processed_documents, created_chunks, str(error)
            )
            raise
        report = {
            "run_id": str(run_id),
            "status": "SUCCESS",
            "source_pdf_count": len(files),
            "excluded_reference_pdf_count": len(all_files) - len(files),
            "processed_documents": processed_documents,
            "skipped_unchanged_documents": skipped_documents,
            "created_chunks": created_chunks,
            "model_id": self._settings.model_id,
            "embedding_provider": self._settings.embedding_provider,
            "model_revision": self._settings.model_revision,
            "embedding_dimension": self._settings.dimension,
            "device": self._get_embedding().device if processed_documents else "NOT_LOADED",
            "warnings": warnings,
            "documents": inspections,
        }
        self._write_evidence("vector_ingestion_manifest.json", report)
        return report
    def search(
        self,
        query: str,
        role: str,
        top_k: int = 5,
        request_id: str | None = None,
        trace_id: str | None = None,
        as_of: str | None = None,
        session_id: str | None = None,
        actor_hash: str | None = None,
        router_decision_id: str | None = None,
        parent_artifact_id: str | None = None,
        report_run_id: str | None = None,
        recent_utterances: tuple[str, ...] = (),
        selected_document_ids: tuple[str, ...] = (),
        retrieval_mode: str = "HYBRID",
        maximum_chunks_per_document: int = 1,
        resolved_question: str | None = None,
        domains: tuple[str, ...] = (),
        intent: str = "REGULATION_CHECK",
    ) -> dict[str, object]:
        decision = self._policy.decide(role, top_k)
        effective_query = ContextualQueryBuilder.build(
            resolved_question or query,
            () if resolved_question else recent_utterances,
        )
        selected_ids = ContextualQueryBuilder.validate_document_ids(
            selected_document_ids
        )
        document_limit = self.answer_document_limit(intent, selected_ids)
        effective_maximum_chunks = (
            max(2, maximum_chunks_per_document)
            if document_limit > 1
            else max(min(decision.top_k, 10), maximum_chunks_per_document)
            if selected_ids
            else maximum_chunks_per_document
        )
        started = time.perf_counter()
        vector = self._get_embedding().embed_query(effective_query)
        results = self._retrieval.retrieve(
            effective_query, vector, decision, selected_ids,
            retrieval_mode=retrieval_mode,
            maximum_chunks_per_document=effective_maximum_chunks
        )
        if results:
            answer_type = {
                "PROCESS": "PROCEDURE",
                "IMMEDIATE_ACTION": "IMMEDIATE",
                "DECISION_CRITERIA": "CRITERIA",
                "REGULATION_CHECK": "POLICY",
                "COMPARISON": "COMPARE",
                "SUMMARY": "SUMMARY",
            }.get(intent, "POLICY")
            formatter = ManualArticleFormatter()
            article_numbers = formatter.target_numbers(query, answer_type)
            manual_ids = self.answer_document_ids(
                selected_ids,
                tuple(dict.fromkeys(item.manual_id for item in results)),
                document_limit,
            )
            article_context = self._repository.article_context(
                manual_ids,
                article_numbers,
                decision.role,
                decision.allow_unresolved_validity,
                maximum_chunks_per_document=24 if document_limit > 1 else 48,
            )
            hydrated = []
            seen_evidence_ids: set[str] = set()
            for item in (*article_context, *results):
                if item.evidence_id in seen_evidence_ids:
                    continue
                seen_evidence_ids.add(item.evidence_id)
                hydrated.append(item)
            results = hydrated[:50]
        latency_ms = (time.perf_counter() - started) * 1000
        query_hash = hash_search_input(query, recent_utterances, selected_ids, resolved_question, domains, intent)
        resolved_request_id = request_id or str(uuid4())
        self._repository.audit_search(
            query_hash,
            decision.role,
            len(results),
            latency_ms,
            request_id=resolved_request_id,
            trace_id=trace_id or resolved_request_id,
            tool_code=RagToolContract().tool_code,
            tool_version=RagToolContract().semantic_version,
            as_of=as_of,
            session_id=session_id,
            actor_hash=actor_hash,
            router_decision_id=router_decision_id,
            parent_artifact_id=parent_artifact_id,
            report_run_id=report_run_id,
        )
        payload = build_search_payload(
            query_hash=query_hash,
            decision=decision,
            results=[asdict(result) for result in results],
            latency_ms=latency_ms,
            request_id=resolved_request_id,
            trace_id=trace_id or resolved_request_id,
            as_of=as_of,
            recent_utterance_count=len(recent_utterances),
            selected_document_ids=selected_ids,
            retrieval_mode=retrieval_mode,
            domains=domains,
            intent=intent,
            resolved_with_context=bool(resolved_question and resolved_question.strip() != query.strip()),
        )
        payload["agent"] = "INTERNAL_GUIDELINE"
        payload["processing_steps"] = [
            "DOCUMENT_SEARCHED",
            "ACCESS_VERIFIED",
            "EVIDENCE_VALIDATED",
        ]
        self._write_evidence("vector_search_latest.json", payload)
        return payload
    def status(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "database": self._repository.status(),
            "model_id": self._settings.model_id,
            "embedding_provider": self._settings.embedding_provider,
            "model_revision": self._settings.model_revision,
            "embedding_api_configured": bool(self._settings.embedding_api_key) if self._settings.embedding_provider == "openai" else True,
            "expected_dimension": self._settings.dimension,
            "search_policy": "SERVER_CONTROLLED",
            "execution_state": asdict(P2GateStatus()),
            "tool": RagToolContract().public_metadata(),
        }

    def evaluate_smoke(self) -> dict[str, object]:
        path = self._settings.smoke_queries_path
        suite = json.loads(path.read_text(encoding="utf-8"))
        return self._evaluate_queries(
            [
                {
                    "query_id": f"S{index:03d}",
                    "query": item["query"],
                    "expected_manual_id": item["expected_manual_id"],
                    "query_type": "LEGACY_SMOKE",
                }
                for index, item in enumerate(suite["queries"], start=1)
            ],
            "vector_smoke_evaluation.json",
            suite["status"],
            "legacy-smoke-v1",
        )

    def evaluate_quality(self) -> dict[str, object]:
        suite = SyntheticQualitySuite()
        queries = [asdict(item) for item in suite.build(self._evidence_repository.evaluation_sources())]
        return self._evaluate_queries(
            queries,
            "vector_quality_evaluation.json",
            "SYNTHETIC_DRAFT_NOT_HUMAN_APPROVED",
            suite.SCHEMA_VERSION,
            suite.SEED,
        )

    def validate_lifecycle(self) -> dict[str, object]:
        manual_id = "SYNTHETIC-LIFECYCLE-001"
        try:
            first = build_lifecycle_fixture(manual_id, "1.0", "첫 번째 안전 점검 절차")
            second = build_lifecycle_fixture(manual_id, "2.0", "개정된 안전 점검 및 보고 절차")
            for document, chunk in (first, second):
                vector = self._get_embedding().embed_documents([chunk.content], 1)
                self._repository.replace_document(document, [chunk], vector, self._embedding_metadata())
            before_delete = self._lifecycle.snapshot(manual_id)
            deleted = self._lifecycle.soft_delete(
                manual_id, "SYSTEM_ADMIN", "SYNTHETIC_LIFECYCLE_VALIDATION"
            )
            after_delete = self._lifecycle.snapshot(manual_id)
            restored = self._lifecycle.restore(
                manual_id, "SYSTEM_ADMIN", "SYNTHETIC_LIFECYCLE_VALIDATION"
            )
            after_restore = self._lifecycle.snapshot(manual_id)
            passed = (
                before_delete["archived_version_count"] == 1
                and before_delete["current_version"] == "2.0"
                and deleted == 1
                and after_delete["soft_deleted"] is True
                and restored == 1
                and after_restore["soft_deleted"] is False
            )
            report = {
                "status": "SUCCESS" if passed else "FAILED",
                "fixture": "synthetic",
                "seed": 20260803,
                "schema_version": "1.0",
                "version_transition": before_delete,
                "soft_delete": after_delete,
                "restore": after_restore,
            }
            self._write_evidence("document_lifecycle_validation.json", report)
            return report
        finally:
            self._lifecycle.remove_synthetic_fixture(manual_id)

    def write_runtime_evidence(self) -> dict[str, object]:
        inventory = self._evidence_repository.source_inventory()
        source_report = {
            "status": "SUCCESS",
            "source_type": "INDIVIDUAL_MANUAL_PDF",
            "document_count": len(inventory),
            "total_pages": sum(int(item["page_count"] or 0) for item in inventory),
            "documents": inventory,
        }
        database_report = {
            "status": "SUCCESS",
            "database": self._repository.status(),
            "model_id": self._settings.model_id,
            "model_revision": self._settings.model_revision,
            "ingestion_history": self._evidence_repository.ingestion_history(),
        }
        self._write_evidence("source_inspection_report.json", source_report)
        self._write_evidence("vector_database_status.json", database_report)
        return {"source": source_report, "runtime": database_report}

    def _evaluate_queries(
        self,
        queries: list[dict[str, object]],
        filename: str,
        status: str,
        schema_version: str,
        seed: int | None = None,
    ) -> dict[str, object]:
        report = QualityEvaluator(
            self._policy, self._retrieval, self._get_embedding()
        ).evaluate(queries, status, schema_version, seed)
        self._write_evidence(filename, report)
        return report

    def _get_embedding(self) -> QwenEmbeddingProvider | OpenAIEmbeddingProvider:
        if self._embedding is None:
            with self._embedding_init_lock:
                if self._embedding is None:
                    if self._settings.embedding_provider == "openai":
                        self._embedding = OpenAIEmbeddingProvider(
                            self._settings.embedding_api_key,
                            self._settings.model_id,
                            self._settings.dimension,
                            self._settings.embedding_endpoint,
                            self._settings.embedding_timeout_seconds,
                            self._settings.embedding_maximum_attempts,
                        )
                    elif self._settings.embedding_provider == "qwen":
                        self._embedding = QwenEmbeddingProvider(
                            self._settings.model_path,
                            self._settings.device,
                            self._settings.dimension,
                            self._settings.max_sequence_length,
                            self._settings.query_prompt_name,
                        )
                    else:
                        raise ValueError(f"Unsupported RAG_EMBEDDING_PROVIDER: {self._settings.embedding_provider}")
        return self._embedding

    def _embedding_metadata(self) -> dict[str, object]:
        return {"provider": self._settings.embedding_provider, "model": self._settings.model_id, "dimensions": self._settings.dimension, "version": self._settings.model_revision}

    def catalog(self, role: str) -> list[dict[str, object]]:
        decision = self._policy.decide(role, 1)
        return self._repository.catalog(role, decision.allow_unresolved_validity)

    def source_pdf(self, manual_id: str, role: str) -> tuple[bytes, str]:
        decision = self._policy.decide(role, 1)
        source = self._repository.source_path(
            manual_id,
            role,
            decision.allow_unresolved_validity,
        ).resolve()
        manuals_root = self._settings.manuals_dir.resolve()
        if source.suffix.lower() != ".pdf" or manuals_root not in source.parents or not source.is_file():
            raise FileNotFoundError(manual_id)
        return source.read_bytes(), source.name

    def answer(
        self,
        request_id: str,
        trace_id: str,
        query: str,
        evidence_blocks: list[dict],
        intent: str = "REGULATION_CHECK",
        retrieval_request_id: str | None = None,
    ) -> dict:
        import os
        from .answer_contracts import AnswerRequest
        from .answer_service import AnswerService

        # We need to construct an answer config. Let's load it from answer.json
        import json
        answer_config_path = self._settings.config_dir / "answer.json"
        if answer_config_path.exists():
            answer_config = json.loads(answer_config_path.read_text(encoding="utf-8"))
        else:
            answer_config = {}

        # Also, check answer endpoint and api key from ENV
        api_key = os.getenv("RAG_ANSWER_API_KEY", "").strip()
        endpoint = os.getenv("RAG_ANSWER_ENDPOINT", "").strip()
        if not api_key or not endpoint:
            raise RuntimeError("RAG answer transport is not configured")

        answer_service = AnswerService(answer_config, api_key, endpoint)

        req = AnswerRequest(
            request_id=request_id,
            trace_id=trace_id,
            query=query,
            evidence_blocks=evidence_blocks,
            intent=intent,
            retrieval_request_id=retrieval_request_id,
        )

        started = time.perf_counter()
        response = answer_service.generate(req)
        latency_ms = (time.perf_counter() - started) * 1000

        self._repository.record_answer_trace(
            request_id=request_id,
            trace_id=trace_id,
            retrieval_request_id=retrieval_request_id,
            query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            status=response.status,
            latency_ms=latency_ms,
            model_id=str(answer_config.get("model") or "gpt-4o-mini"),
            answer_hash=hashlib.sha256(response.answer.encode("utf-8")).hexdigest(),
            answer_type=response.answer_type,
            citation_evidence_ids=[item.evidence_id for item in response.citations],
        )

        report = response.model_dump(mode="json")
        self._write_evidence("vector_answer_latest.json", report)
        return report

    def _write_evidence(self, filename: str, payload: dict[str, object]) -> None:
        path = self._settings.evidence_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._evidence_lock:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
