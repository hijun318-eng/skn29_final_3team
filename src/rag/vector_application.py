"""immutable corpus 적재·검색·답변·증적 생명주기를 조정하는 RAG application이다."""

from __future__ import annotations

import json
import hashlib
import os
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
from .document_ingestion import CorpusDocumentParser
from .embedding_input import EmbeddingInputBuilder
from .pgvector_repository import PgVectorRepository
from .quality_evaluation import SyntheticQualitySuite
from .source_bytes import read_bounded_source_bytes
from .retrieval_service import VectorRetrievalService
from .vector_settings import VectorSettings
from .p2_contracts import P2GateStatus, RagToolContract
from .contextual_query import ContextualQueryBuilder
from .corpus_manifest import CORPUS_MANIFEST_VERSION_V2, CorpusManifest
from .processing_profile import processing_profile_sha256
from .vector_search_payload import build_search_payload, hash_search_input
from .manual_article_formatter import ManualArticleFormatter


class VectorRagApplication:
    """설정·접근 정책·embedding·pgvector를 release 단위 실행 경계로 결합한다."""

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

    @staticmethod
    def _answer_evidence_from_result(result: object) -> dict[str, str]:
        """서버 소유 검색 결과 하나를 서명 대상 답변 evidence 계약으로 투영한다."""

        def value(name: str) -> str:
            raw = getattr(result, name, None)
            return "" if raw is None else str(raw)

        return {
            "evidence_id": value("evidence_id"),
            "text": value("content"),
            "document_id": value("manual_id"),
            "title": value("title"),
            "manual_id": value("manual_id"),
            "version": value("version"),
            "document_type": value("document_type"),
            "owner_team": value("owner_team"),
            "section_title": value("section_title"),
            "article_number": "",
            "page_start": value("page_start"),
            "chunk_id": value("chunk_id"),
            "chunk_index": value("chunk_index"),
            "score": value("score"),
            "vector_score": value("vector_score"),
            "lexical_score": value("lexical_score"),
            "document_status": value("document_status"),
            "approval_status": value("approval_status"),
            "validity_status": value("validity_status"),
            "effective_from": value("effective_from"),
            "effective_to": value("expires_at"),
            "citation": value("citation"),
        }

    @staticmethod
    def _validated_answer_evidence(
        evidence_blocks: list[dict],
    ) -> list[dict[str, str]]:
        fields = {
            "approval_status",
            "article_number",
            "chunk_id",
            "chunk_index",
            "document_id",
            "document_status",
            "effective_from",
            "effective_to",
            "evidence_id",
            "lexical_score",
            "manual_id",
            "document_type",
            "owner_team",
            "page_start",
            "score",
            "section_title",
            "text",
            "title",
            "validity_status",
            "vector_score",
            "version",
            "citation",
        }
        if (
            not evidence_blocks
            or len(evidence_blocks) > 50
            or any(
                not isinstance(block, dict)
                or set(block) != fields
                or any(not isinstance(value, str) for value in block.values())
                or not block["evidence_id"].strip()
                or not block["text"].strip()
                for block in evidence_blocks
            )
        ):
            raise ValueError("RAG answer evidence contract is invalid")
        normalized = [{key: block[key] for key in sorted(fields)} for block in evidence_blocks]
        evidence_ids = [item["evidence_id"] for item in normalized]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("RAG answer evidence contains duplicate identity")
        return normalized

    def __init__(self, project_root: Path) -> None:
        self._settings = VectorSettings.load(project_root)
        self._policy = SearchAccessPolicy.load(
            self._settings.config_dir / "access_policy.json"
        )
        self._corpus_manifest = CorpusManifest.load(
            self._settings.corpus_manifest_path,
            self._settings.manuals_dir,
        )
        self._validate_manifest_access_policy(self._corpus_manifest)
        self._processing_profile_sha256 = processing_profile_sha256(
            self._settings.chunk_max_tokens,
            self._settings.chunk_overlap_tokens,
        )
        self._repository = PgVectorRepository(
            self._settings.database_url,
            self._embedding_metadata(),
            self._corpus_manifest.manifest_sha256,
            self._corpus_manifest.included_document_checksums,
            self._processing_profile_sha256,
        )

        self._retrieval = VectorRetrievalService(self._repository)
        self._evidence_repository = RagEvidenceRepository(
            self._settings.database_url,
            self._embedding_metadata(),
            self._corpus_manifest.manifest_sha256,
            self._corpus_manifest.included_document_checksums,
            self._processing_profile_sha256,
        )
        self._embedding: QwenEmbeddingProvider | OpenAIEmbeddingProvider | None = None
        self._embedding_init_lock = threading.Lock()
        self._evidence_lock = threading.Lock()

    @property
    def database_url(self) -> str:
        """migration과 운영 점검이 사용할 검증 완료 PostgreSQL 연결 문자열을 반환한다."""

        return self._settings.database_url

    def migrate(self) -> dict[str, object]:
        """정렬된 RAG migration을 적용하고 실행 파일과 DB 상태를 receipt로 반환한다."""

        migrations = sorted(self._settings.migrations_dir.glob("*.sql"))
        for migration in migrations:
            self._repository.migrate(migration)
        return {
            "status": "SUCCESS",
            "migrations": [str(path) for path in migrations],
            **self._repository.status(),
        }

    def ingest(self, limit: int | None = None) -> dict[str, object]:
        """manifest 전체를 파싱·embedding·staging해 atomic corpus release로 발행한다."""

        if limit is not None:
            raise ValueError("Partial RAG ingestion cannot publish a corpus release")
        corpus_manifest = CorpusManifest.load(
            self._settings.corpus_manifest_path,
            self._settings.manuals_dir,
        )
        self._validate_manifest_access_policy(corpus_manifest)
        if corpus_manifest.manifest_sha256 != self._corpus_manifest.manifest_sha256:
            raise ValueError("RAG corpus manifest changed after runtime startup")
        embedding_provider = self._get_embedding()
        embedding_metadata = self._embedding_metadata()
        run_id = uuid4()
        entries = corpus_manifest.included_documents
        processed_documents = 0
        created_chunks = 0
        staged_chunks = 0
        skipped_documents = 0
        warnings: list[str] = []
        inspections: list[dict[str, object]] = []
        self._repository.start_run(
            run_id,
            embedding_metadata,
            corpus_manifest.manifest_sha256,
            self._processing_profile_sha256,
        )
        try:
            from .token_chunker import TokenChunker
            chunker = TokenChunker(
                provider=embedding_provider,
                max_tokens=self._settings.chunk_max_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
            )
            parser = CorpusDocumentParser(chunker=chunker)
            provider_token_counter = getattr(
                embedding_provider,
                "count_tokens",
                None,
            )
            embedding_input = EmbeddingInputBuilder(
                self._settings.max_sequence_length,
                provider_token_counter if callable(provider_token_counter) else None,
            )
            for entry in entries:
                path = CorpusManifest.source_path(self._settings.manuals_dir, entry)
                document, chunks, parser_warnings, inspection_manifest = parser.parse(
                    path,
                    entry,
                )
                warnings.extend(parser_warnings)
                if self._repository.unchanged(
                    document,
                    embedding_metadata,
                    self._processing_profile_sha256,
                ):
                    staged_chunks += self._repository.copy_active_document(
                        run_id,
                        document,
                        chunks,
                        embedding_metadata,
                        self._processing_profile_sha256,
                    )
                    skipped_documents += 1
                    inspections.append(
                        {
                            "manual_id": document.manual_id,
                            "status": "UNCHANGED",
                            "chunks": len(chunks),
                            "manifest": inspection_manifest,
                        }
                    )
                    continue
                vectors = self._get_embedding().embed_documents(
                    [embedding_input.build(document, chunk) for chunk in chunks],
                    self._settings.batch_size,
                )
                written = self._repository.stage_document(
                    run_id,
                    document,
                    chunks,
                    vectors,
                    embedding_metadata,
                )
                created_chunks += written
                staged_chunks += written
                processed_documents += 1
                inspections.append(
                    {
                        "manual_id": document.manual_id,
                        "status": "SUCCESS",
                        "chunks": len(chunks),
                        "manifest": inspection_manifest,
                    }
                )
            publish_manifest = CorpusManifest.load(
                self._settings.corpus_manifest_path,
                self._settings.manuals_dir,
            )
            self._validate_manifest_access_policy(publish_manifest)
            if publish_manifest != self._corpus_manifest:
                raise ValueError("RAG corpus manifest changed during corpus staging")
            active_release = self._repository.publish_release(
                run_id,
                expected_document_count=len(entries),
                expected_chunk_count=staged_chunks,
                metadata=embedding_metadata,
                corpus_manifest_sha256=self._corpus_manifest.manifest_sha256,
                processing_profile_sha256=self._processing_profile_sha256,
            )
        except Exception as error:
            self._repository.finish_run(
                run_id,
                "FAILED",
                processed_documents + skipped_documents,
                staged_chunks,
                str(error),
            )
            raise
        report = {
            "run_id": str(run_id),
            "status": "SUCCESS",
            "source_document_count": len(entries),
            "source_pdf_count": sum(entry.source_format == "pdf" for entry in entries),
            "source_docx_count": sum(entry.source_format == "docx" for entry in entries),
            "excluded_reference_document_count": len(corpus_manifest.documents) - len(entries),
            "processed_documents": processed_documents,
            "skipped_unchanged_documents": skipped_documents,
            "created_chunks": created_chunks,
            "staged_chunks": staged_chunks,
            "model_id": self._settings.model_id,
            "embedding_provider": self._settings.embedding_provider,
            "model_revision": self._settings.model_revision,
            "embedding_dimension": self._settings.dimension,
            "processing_profile_sha256": self._processing_profile_sha256,
            "device": self._get_embedding().device if processed_documents else "NOT_LOADED",
            "warnings": warnings,
            "documents": inspections,
            "active_release": active_release,
        }
        self._write_evidence("vector_ingestion_manifest.json", report)
        return report

    def _validate_manifest_access_policy(self, manifest: CorpusManifest) -> None:
        """v2 문서 역할을 활성 접근 정책에 결합하되 v1 재실행 호환은 유지한다."""

        if manifest.schema_version == CORPUS_MANIFEST_VERSION_V2:
            manifest.validate_access_policy(self._policy.known_roles)

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
        """서명 문맥·역할·release를 검증하고 hybrid 검색 evidence와 receipt를 반환한다."""

        active_release = self._require_active_release()
        decision = self._policy.decide(role, top_k)
        if (
            actor_hash is None
            or len(actor_hash) != 64
            or any(character not in "0123456789abcdef" for character in actor_hash)
        ):
            raise ValueError("RAG search requires a valid actor receipt")
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
        report_periods = ContextualQueryBuilder.report_periods(effective_query)
        if results and report_periods and not selected_ids:
            target_period = max(report_periods)
            period_candidates = [
                item
                for item in results
                if item.document_type == "INTERNAL_REPORT"
                and item.version == target_period
            ]
            if period_candidates:
                target_document = max(
                    period_candidates,
                    key=lambda item: (item.score, item.vector_score, item.lexical_score),
                )
                focused_results = self._retrieval.retrieve(
                    effective_query,
                    vector,
                    decision,
                    (target_document.manual_id,),
                    retrieval_mode=retrieval_mode,
                    maximum_chunks_per_document=min(decision.top_k, 10),
                )
                if focused_results:
                    results = focused_results
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
        answer_evidence = [
            self._answer_evidence_from_result(item) for item in results
        ]
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
            corpus_release_id=str(active_release["release_id"]),
            answer_query_sha256=hashlib.sha256(
                effective_query.encode("utf-8")
            ).hexdigest(),
            answer_intent=intent,
            answer_evidence=answer_evidence,
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
            model_revision=self._settings.model_revision,
            embedding_dimension=self._settings.dimension,
            corpus_release_id=str(active_release["release_id"]),
            corpus_manifest_sha256=self._corpus_manifest.manifest_sha256,
            processing_profile_sha256=self._processing_profile_sha256,
            answer_query=effective_query,
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
        """활성 release·embedding 계약·DB·tool Gate 상태를 side effect 없이 조회한다."""

        active_release = self._repository.active_release_receipt(
            self._embedding_metadata(),
            self._corpus_manifest.manifest_sha256,
            self._processing_profile_sha256,
        )
        return {
            "status": "healthy" if active_release is not None else "not_ready",
            "database": self._repository.status(),
            "model_id": self._settings.model_id,
            "embedding_provider": self._settings.embedding_provider,
            "model_revision": self._settings.model_revision,
            "embedding_api_configured": bool(self._settings.embedding_api_key) if self._settings.embedding_provider == "openai" else True,
            "expected_dimension": self._settings.dimension,
            "corpus_manifest_sha256": self._corpus_manifest.manifest_sha256,
            "processing_profile_sha256": self._processing_profile_sha256,
            "active_corpus_release": active_release,
            "search_policy": "SERVER_CONTROLLED",
            "execution_state": asdict(P2GateStatus()),
            "tool": RagToolContract().public_metadata(),
        }

    def evaluate_smoke(self) -> dict[str, object]:
        """legacy smoke 질문을 활성 release에 실행해 재현 가능한 평가 report를 만든다."""

        self._require_active_release()
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
        """활성 문서에서 합성 suite를 구성하고 retrieval 품질 report를 생성한다."""

        self._require_active_release()
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
        """immutable release에서 지원하지 않는 mutation 검증 요청을 명시적으로 거부한다."""

        raise RuntimeError(
            "RAG lifecycle validation is unsupported for immutable corpus releases"
        )

    def write_runtime_evidence(self) -> dict[str, object]:
        """혼합 source inventory와 DB ingestion 상태를 checksum 가능한 증적 파일로 쓴다."""

        active_release = self._require_active_release()
        inventory = self._evidence_repository.source_inventory()
        source_report = {
            "status": "SUCCESS",
            "source_type": "MIXED_IMMUTABLE_CORPUS",
            "document_count": len(inventory),
            "document_type_counts": {
                document_type: sum(
                    1 for item in inventory
                    if item["document_type"] == document_type
                )
                for document_type in sorted(
                    {str(item["document_type"]) for item in inventory}
                )
            },
            "total_pages": sum(
                int(item["location_count"] or 0)
                for item in inventory
                if item["locator_kind"] == "PAGE"
            ),
            "total_explicit_segments": sum(
                int(item["location_count"] or 0)
                for item in inventory
                if item["locator_kind"] == "EXPLICIT_BREAK_SEGMENT"
            ),
            "documents": inventory,
        }
        database_report = {
            "status": "SUCCESS",
            "database": self._repository.status(),
            "model_id": self._settings.model_id,
            "model_revision": self._settings.model_revision,
            "active_corpus_release": active_release,
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

    def _require_active_release(self) -> dict[str, object]:
        receipt = self._repository.active_release_receipt(
            self._embedding_metadata(),
            self._corpus_manifest.manifest_sha256,
            self._processing_profile_sha256,
        )
        if receipt is None:
            raise RuntimeError("Active RAG corpus release is not ready")
        return receipt

    def catalog(self, role: str) -> list[dict[str, object]]:
        """활성 release와 역할 Gate를 통과한 문서 catalog만 반환한다."""

        self._require_active_release()
        decision = self._policy.decide(role, 1)
        return self._repository.catalog(role, decision.allow_unresolved_validity)

    def source_document(self, manual_id: str, role: str) -> tuple[bytes, str, str]:
        """권한과 checksum을 재검증한 PDF 또는 DOCX 원본 bytes·이름·media type을 반환한다."""

        self._require_active_release()
        decision = self._policy.decide(role, 1)
        source, expected_sha256 = self._repository.source_receipt(
            manual_id,
            role,
            decision.allow_unresolved_validity,
        )
        source = source.resolve()
        manuals_root = self._settings.manuals_dir.resolve()
        media_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        media_type = media_types.get(source.suffix.lower())
        if media_type is None or manuals_root not in source.parents or not source.is_file():
            raise FileNotFoundError(manual_id)
        try:
            content = read_bounded_source_bytes(
                source,
                expected_suffix=source.suffix.lower(),
            )
        except (OSError, ValueError) as error:
            raise FileNotFoundError(manual_id) from error
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise FileNotFoundError(manual_id)
        return content, source.name, media_type

    def source_pdf(self, manual_id: str, role: str) -> tuple[bytes, str]:
        """legacy PDF 전용 계약을 유지하고 DOCX를 PDF로 오표시하지 않도록 거부한다."""

        content, filename, media_type = self.source_document(manual_id, role)
        if media_type != "application/pdf":
            raise FileNotFoundError(manual_id)
        return content, filename

    def answer(
        self,
        request_id: str,
        trace_id: str,
        query: str,
        evidence_blocks: list[dict],
        role: str,
        intent: str = "REGULATION_CHECK",
        retrieval_request_id: str | None = None,
        actor_hash: str | None = None,
    ) -> dict:
        """소비 전 retrieval receipt와 evidence identity를 검증해 근거 제한 답변을 생성한다."""

        from .answer_contracts import AnswerRequest
        from .answer_service import AnswerService

        self._require_active_release()
        decision = self._policy.decide(role, 1)
        if retrieval_request_id is None:
            raise ValueError("RAG answer requires a retrieval request receipt")
        if (
            actor_hash is None
            or len(actor_hash) != 64
            or any(character not in "0123456789abcdef" for character in actor_hash)
        ):
            raise ValueError("RAG answer requires a valid actor receipt")
        normalized_query = ContextualQueryBuilder.build(query)
        caller_evidence = self._validated_answer_evidence(evidence_blocks)
        bound_evidence = self._repository.load_answer_evidence(
            retrieval_request_id=retrieval_request_id,
            role=decision.role,
            query=normalized_query,
            answer_intent=intent,
            trace_id=trace_id,
            actor_hash=actor_hash,
            caller_evidence=caller_evidence,
        )

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
        answer_model = os.getenv("RAG_ANSWER_MODEL", "").strip()
        if not api_key or not endpoint or not answer_model:
            raise RuntimeError("RAG answer transport is not configured")
        answer_config = {**answer_config, "model": answer_model}

        answer_service = AnswerService(answer_config, api_key, endpoint)

        req = AnswerRequest(
            request_id=request_id,
            trace_id=trace_id,
            query=normalized_query,
            evidence_blocks=bound_evidence,
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
            query_hash=hashlib.sha256(normalized_query.encode("utf-8")).hexdigest(),
            status=response.status,
            latency_ms=latency_ms,
            model_id=answer_model,
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
