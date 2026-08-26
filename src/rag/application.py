from __future__ import annotations

import hashlib
import os
import json
import math
from collections import Counter
from pathlib import Path

from .models import DocumentConfig, SearchResult
from .repository import SqliteRagRepository
from .text_processing import KoreanTokenizer, MarkdownSectionParser, SectionChunker, SecurityScanner


def _snippet_limit() -> int:
    try:
        return max(1, int(os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip() or "1800"))
    except ValueError:
        return 1800


class LocalRagApplication:
    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._repository = SqliteRagRepository(
            self._root / "evals" / "runs" / "rag" / "rag_validation.db"
        )
        self._tokenizer = KoreanTokenizer()
        self._parser = MarkdownSectionParser()
        self._chunker = SectionChunker(self._tokenizer)
        self._scanner = SecurityScanner()
        self._repository.initialize()

    def ingest(self) -> dict[str, object]:
        created_chunks = 0
        documents = self._load_allowlist()
        inspections: list[dict[str, object]] = []
        for config in documents:
            raw = config.source_path.read_text(encoding="utf-8-sig")
            security_status, safe_text = self._scanner.inspect(raw)
            if security_status == "REJECTED_SECRET":
                inspections.append({"manual_id": config.manual_id, "status": security_status})
                continue
            checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            sections = self._parser.parse(safe_text)
            chunks = self._chunker.create_chunks(config.manual_id, sections)
            created_chunks += self._repository.upsert_document(config, checksum, chunks)
            inspections.append(
                {
                    "manual_id": config.manual_id,
                    "status": security_status,
                    "checksum": checksum,
                    "sections": len(sections),
                    "chunks": len(chunks),
                }
            )
        report = {
            "run_status": "SUCCESS",
            "source_type": "REFERENCE_MARKDOWN_NOT_ACTUAL_MANUAL_PDF",
            "created_chunks": created_chunks,
            "database_counts": self._repository.counts(),
            "documents": inspections,
        }
        self._write_json("ingestion_manifest.json", report)
        return report

    def search(
        self,
        query: str,
        role: str,
        top_k: int = 3,
        allow_unresolved_validity: bool = False,
    ) -> list[SearchResult]:
        query_terms = Counter(self._tokenizer.tokenize(query))
        rows = self._repository.list_searchable_chunks(role, allow_unresolved_validity)
        ranked: list[tuple[float, object]] = []
        for row in rows:
            chunk_terms = Counter(json.loads(row["token_terms"]))
            overlap = sum(min(count, chunk_terms[term]) for term, count in query_terms.items())
            if overlap == 0:
                continue
            denominator = math.sqrt(sum(query_terms.values()) * sum(chunk_terms.values()))
            score = overlap / denominator if denominator else 0.0
            ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        results = [self._to_result(score, row) for score, row in ranked[:top_k]]
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        self._repository.record_search(query_hash, role, len(results))
        return results

    def status(self) -> dict[str, object]:
        return {
            "database": "SQLite local validation store",
            "search": "KEYWORD_NGRAM",
            "embedding": "NOT_RUN",
            "pgvector": "NOT_RUN",
            "actual_manual_pdf": "BLOCKED_MISSING_SOURCE",
            "counts": self._repository.counts(),
        }

    def _load_allowlist(self) -> list[DocumentConfig]:
        path = self._root / "config" / "document_allowlist.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            DocumentConfig(
                manual_id=item["manual_id"],
                title=item["title"],
                version=item["version"],
                source_path=(self._root / item["source_path"]).resolve(),
                role_scope=tuple(item["role_scope"]),
            )
            for item in payload["documents"]
        ]

    def _to_result(self, score: float, row: object) -> SearchResult:
        snippet = " ".join(str(row["content"]).split())[:_snippet_limit()]
        citation = f"[{row['manual_id']} v{row['version']} §{row['section_number']} {row['section_title']}]"
        return SearchResult(
            manual_id=row["manual_id"],
            manual_title=row["title"],
            manual_version=row["version"],
            section_number=row["section_number"],
            section_title=row["section_title"],
            score=round(score, 6),
            snippet=snippet,
            citation_label=citation,
        )

    def _write_json(self, filename: str, payload: dict[str, object]) -> None:
        path = self._root / "artifacts" / "rag" / "evidence" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
