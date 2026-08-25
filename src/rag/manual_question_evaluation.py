from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean

from .access_policy import SearchAccessPolicy
from .pgvector_repository import PgVectorRepository
from .qwen_embedding import QwenEmbeddingProvider
from .retrieval_service import VectorRetrievalService
from .vector_settings import VectorSettings
from .contextual_query import ContextualQueryBuilder
from .manual_evaluation_metrics import ManualEvaluationMetrics

@dataclass(frozen=True)
class ManualQuestion:
    question_id: str
    query_type: str
    difficulty: str
    query: str
    expected_manual_id: str | None
    allowed_manual_ids: tuple[str, ...]
    expected_behavior: str | None = None
    expected_page_start: int | None = None
    expected_page_end: int | None = None

    @property
    def is_follow_up(self) -> bool:
        return self.query_type == "후속 대화"

    @property
    def is_strict_out_of_scope(self) -> bool:
        return self.expected_manual_id is None and self.query_type == "범위 밖"


class MarkdownQuestionSuite:
    @staticmethod
    def load(path: Path) -> list[ManualQuestion]:
        questions: list[ManualQuestion] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = MarkdownQuestionSuite._cells(line)
            if not cells:
                continue
            if cells[0].startswith("P") and len(cells) in (8, 9):
                allowed = tuple(
                    value.strip() for value in cells[5].split(",")
                    if value.strip() and value.strip() != "-"
                )
                questions.append(
                    ManualQuestion(
                        question_id=cells[0], query_type=cells[1], difficulty=cells[2],
                        query=cells[3], expected_manual_id=cells[4],
                        allowed_manual_ids=allowed,
                        **MarkdownQuestionSuite._gold_page(cells[6] if len(cells) == 9 else ""),
                    )
                )
            elif cells[0].startswith("N") and len(cells) == 7:
                questions.append(
                    ManualQuestion(
                        question_id=cells[0], query_type=cells[1], difficulty=cells[2],
                        query=cells[3], expected_manual_id=None, allowed_manual_ids=(),
                        expected_behavior=cells[4],
                    )
                )
        if not questions:
            raise ValueError(f"No evaluation questions found: {path}")
        return questions

    @staticmethod
    def version(path: Path) -> str:
        match = re.search(
            r"\|\s*문서 버전\s*\|\s*`?([^|`]+)`?\s*\|",
            path.read_text(encoding="utf-8"),
        )
        return match.group(1).strip() if match else "UNVERSIONED"

    @staticmethod
    def _gold_page(value: str) -> dict[str, int | None]:
        match = re.fullmatch(r"(?:p\.?\s*)?(\d+)(?:\s*[-~]\s*(\d+))?", value.strip())
        if not match:
            return {"expected_page_start": None, "expected_page_end": None}
        start = int(match.group(1))
        return {
            "expected_page_start": start,
            "expected_page_end": int(match.group(2) or start),
        }

    @staticmethod
    def _cells(line: str) -> list[str]:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return []
        return [cell.strip().replace("\\|", "|") for cell in stripped[1:-1].split("|")]


class ManualQuestionEvaluationService:
    def __init__(self, project_root: Path) -> None:
        self._settings = VectorSettings.load(project_root)
        repository = PgVectorRepository(self._settings.database_url)
        self._retrieval = VectorRetrievalService(repository)
        self._policy = SearchAccessPolicy.load(
            self._settings.config_dir / "access_policy.json"
        )
        self._embedding = QwenEmbeddingProvider(
            self._settings.model_path, self._settings.device,
            self._settings.dimension, self._settings.max_sequence_length,
            self._settings.query_prompt_name,
        )

    def evaluate(self, question_path: Path) -> dict[str, object]:
        evaluation_started = time.perf_counter()
        questions = MarkdownQuestionSuite.load(question_path)
        decision = self._policy.decide("MANAGER", 10)
        effective_queries = self._effective_queries(questions)
        embedding_started = time.perf_counter()
        vectors = self._embedding.embed_queries(effective_queries)
        embedding_seconds = time.perf_counter() - embedding_started
        details: list[dict[str, object]] = []
        retrieval_latencies_ms: list[float] = []
        for question, effective_query, vector in zip(
            questions, effective_queries, vectors, strict=True
        ):
            retrieval_started = time.perf_counter()
            results = self._retrieval.retrieve(effective_query, vector, decision)
            retrieval_latencies_ms.append((time.perf_counter() - retrieval_started) * 1000)
            retrieved = [result.manual_id for result in results]
            complete_citations = sum(
                result.manual_id in result.citation
                and f"v{result.version}" in result.citation
                and result.page_start > 0
                and result.page_end >= result.page_start
                for result in results
            )
            details.append(
                {
                    "question_id": question.question_id,
                    "query_type": question.query_type,
                    "difficulty": question.difficulty,
                    "query": question.query,
                    "context_applied": effective_query != question.query,
                    "expected_manual_id": question.expected_manual_id,
                    "allowed_manual_ids": list(question.allowed_manual_ids),
                    "expected_behavior": question.expected_behavior,
                    "retrieved_manual_ids": retrieved,
                    "scores": [result.score for result in results],
                    "retrieved_page_ranges": [
                        [result.page_start, result.page_end] for result in results
                    ],
                    "primary_rank": self._rank(question.expected_manual_id, retrieved),
                    "allowed_rank": self._allowed_rank(question, retrieved),
                    "expected_page_start": question.expected_page_start,
                    "expected_page_end": question.expected_page_end,
                    "gold_page_hit": self._gold_page_hit(question, results),
                    "citation_count": len(results),
                    "complete_citation_count": complete_citations,
                }
            )
        report = self._build_report(
            questions, details, decision.minimum_score, question_path,
            {
                "batch_total_seconds": round(time.perf_counter() - evaluation_started, 4),
                "embedding_batch_seconds": round(embedding_seconds, 4),
                "retrieval_request_count": len(retrieval_latencies_ms),
                "retrieval_mean_ms": round(mean(retrieval_latencies_ms), 4),
                "retrieval_p95_ms": round(
                    ManualEvaluationMetrics.percentile(retrieval_latencies_ms, 0.95), 4
                ),
                "online_concurrency_p95": "NOT_MEASURED_USE_LOAD_TEST",
            },
        )
        output = self._settings.evidence_dir / "rag_questions_v2_1_evaluation.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    @staticmethod
    def _effective_queries(questions: list[ManualQuestion]) -> list[str]:
        previous_by_group: dict[str, str] = {}
        effective: list[str] = []
        for question in questions:
            group = question.question_id.split("-", 1)[0]
            recent = (
                (previous_by_group[group],)
                if question.is_follow_up and group in previous_by_group
                else ()
            )
            effective.append(ContextualQueryBuilder.build(question.query, recent))
            previous_by_group[group] = question.query
        return effective

    def _build_report(
        self, questions: list[ManualQuestion], details: list[dict[str, object]],
        minimum_score: float, question_path: Path, timing: dict[str, object],
    ) -> dict[str, object]:
        positive = [item for item in details if item["expected_manual_id"] is not None]
        stateless = [
            item for item in positive if item["query_type"] != "후속 대화"
        ]
        follow_up = [item for item in positive if item["query_type"] == "후속 대화"]
        negative = [item for item in details if item["expected_manual_id"] is None]
        strict_negative = [
            item for item in negative if item["query_type"] == "범위 밖"
        ]
        safety = [item for item in negative if item["query_type"] != "범위 밖"]
        return {
            "status": "SUCCESS",
            "executed_at": datetime.now().astimezone().isoformat(),
            "question_file": str(question_path),
            "question_file_sha256": hashlib.sha256(question_path.read_bytes()).hexdigest(),
            "question_suite_version": MarkdownQuestionSuite.version(question_path),
            "model_id": self._settings.model_id,
            "model_revision": self._settings.model_revision,
            "device": self._embedding.device,
            "minimum_score": minimum_score,
            "question_count": len(details),
            "positive_count": len(positive),
            "stateless_positive_count": len(stateless),
            "follow_up_diagnostic_count": len(follow_up),
            "negative_count": len(negative),
            "strict_out_of_scope_count": len(strict_negative),
            "safety_diagnostic_count": len(safety),
            "stateless_metrics": ManualEvaluationMetrics.retrieval(stateless),
            "follow_up_evaluation_mode": "PREVIOUS_SAME_GROUP_UTTERANCE",
            "follow_up_contextual_metrics": ManualEvaluationMetrics.retrieval(follow_up),
            "follow_up_diagnostic_metrics": ManualEvaluationMetrics.retrieval(follow_up),
            "metrics_by_type": ManualEvaluationMetrics.grouped_retrieval(
                stateless, "query_type"
            ),
            "metrics_by_difficulty": ManualEvaluationMetrics.grouped_retrieval(
                stateless, "difficulty"
            ),
            "negative_metrics_by_type": ManualEvaluationMetrics.negative_by_type(negative),
            "strict_out_of_scope_no_evidence_accuracy": (
                ManualEvaluationMetrics.no_evidence_accuracy(strict_negative)
            ),
            "safety_diagnostic": {
                "no_evidence_count": sum(not item["retrieved_manual_ids"] for item in safety),
                "evidence_returned_count": sum(bool(item["retrieved_manual_ids"]) for item in safety),
                "end_to_end_answer_safety": "NOT_TESTED_NO_GENERATION_LLM",
            },
            "citation_metadata_completeness": ManualEvaluationMetrics.citation_completeness(
                details
            ),
            "citation_location_accuracy": ManualEvaluationMetrics.gold_page_accuracy(details),
            "timing": timing,
            "stateless_primary_top3_failures": [
                item for item in stateless if item["primary_rank"] is None
                or int(item["primary_rank"]) > 3
            ],
            "stateless_allowed_top3_failures": [
                item for item in stateless if item["allowed_rank"] is None
                or int(item["allowed_rank"]) > 3
            ],
            "details": details,
        }

    @staticmethod
    def _rank(expected: str | None, retrieved: list[str]) -> int | None:
        return retrieved.index(expected) + 1 if expected in retrieved else None

    @staticmethod
    def _allowed_rank(question: ManualQuestion, retrieved: list[str]) -> int | None:
        accepted = {question.expected_manual_id, *question.allowed_manual_ids}
        ranks = [index + 1 for index, value in enumerate(retrieved) if value in accepted]
        return min(ranks) if ranks else None

    @staticmethod
    def _gold_page_hit(question: ManualQuestion, results: list[object]) -> bool | None:
        if question.expected_page_start is None or question.expected_page_end is None:
            return None
        for result in results:
            if result.manual_id != question.expected_manual_id:
                continue
            return (
                result.page_start <= question.expected_page_end
                and result.page_end >= question.expected_page_start
            )
        return False

def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Markdown RAG question suite")
    parser.add_argument("questions", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    report = ManualQuestionEvaluationService(arguments.root).evaluate(arguments.questions)
    verbose_keys = {
        "details", "stateless_primary_top3_failures", "stateless_allowed_top3_failures"
    }
    print(json.dumps({key: value for key, value in report.items() if key not in verbose_keys}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
