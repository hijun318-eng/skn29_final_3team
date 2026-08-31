from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .evidence_repository import RagEvidenceRepository
from .quality_evaluation import QualityQuery, SyntheticQualitySuite
from .vector_settings import VectorSettings
from .corpus_manifest import CorpusManifest
from .processing_profile import processing_profile_sha256


class EvaluationQuestionReportWriter:
    TYPE_LABELS = {
        "TITLE_BASELINE": "제목 기준",
        "DISTINCT_BODY_SCENARIO": "본문 상황",
        "DISTINCT_BODY_CONTEXT": "본문 문맥",
        "OUT_OF_SCOPE": "범위 밖",
    }

    def __init__(self, project_root: Path) -> None:
        self._settings = VectorSettings.load(project_root)
        manifest = CorpusManifest.load(
            self._settings.corpus_manifest_path,
            self._settings.manuals_dir,
        )
        self._repository = RagEvidenceRepository(
            self._settings.database_url,
            {
                "provider": self._settings.embedding_provider,
                "model": self._settings.model_id,
                "dimensions": self._settings.dimension,
                "version": self._settings.model_revision,
            },
            manifest.manifest_sha256,
            manifest.included_document_checksums,
            processing_profile_sha256(
                self._settings.chunk_max_tokens,
                self._settings.chunk_overlap_tokens,
            ),
        )

    def write(self) -> dict[str, object]:
        suite = SyntheticQualitySuite()
        questions = suite.build(self._repository.evaluation_sources())
        evidence_path = self._settings.evidence_dir / "vector_quality_evaluation.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        details = {item["query_id"]: item for item in evidence["details"]}
        self._validate_alignment(questions, details)
        output_path = self._settings.evidence_dir / "RAG_검증용_검색질문_목록_20260804.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self._render(questions, details, evidence, suite), encoding="utf-8"
        )
        return {
            "status": "SUCCESS",
            "output": str(output_path),
            "question_count": len(questions),
            "positive_count": sum(item.expected_manual_id is not None for item in questions),
            "negative_count": sum(item.expected_manual_id is None for item in questions),
        }

    def _render(
        self,
        questions: list[QualityQuery],
        details: dict[str, dict[str, object]],
        evidence: dict[str, object],
        suite: SyntheticQualitySuite,
    ) -> str:
        positive = [item for item in questions if item.expected_manual_id is not None]
        negative = [item for item in questions if item.expected_manual_id is None]
        failed = [item for item in positive if self._verdict(item, details[item.query_id]) == "실패"]
        lines = [
            "# RAG 검증용 검색 질문 목록",
            "",
            "| 항목 | 내용 |",
            "|---|---|",
            f"| 생성 일시 | {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} |",
            f"| 평가 상태 | `{evidence['evaluation_set_status']}` |",
            f"| schema·seed | `{suite.SCHEMA_VERSION}` · `{suite.SEED}` |",
            f"| 전체 질문 | {len(questions)}개 |",
            f"| 긍정·범위 밖 | {len(positive)}개 · {len(negative)}개 |",
            f"| Recall@1·Recall@3 | {evidence['recall_at_1']:.4f} · {evidence['recall_at_3']:.4f} |",
            "| 운영 승인 | 담당자 검수 전 DRAFT |",
            "",
            "이 문서는 실제 평가에 사용한 질문을 사람이 확인하기 위한 목록이다. 질문은 합성 자동 생성본이며 실제 직원 질문이나 운영 승인 정답으로 간주하지 않는다.",
            "",
            "## 판정 기준",
            "",
            "| 표시 | 의미 |",
            "|---|---|",
            "| Top1 | 예상 문서가 첫 번째 결과 |",
            "| Top3 | 예상 문서가 상위 3개 안에 포함 |",
            "| 실패 | 예상 문서가 상위 3개에 없음 |",
            "| 차단 정상 | 범위 밖 질문의 검색 결과가 0건 |",
            "",
            f"## 우선 검토가 필요한 실패 질문 {len(failed)}개",
            "",
            self._table(failed, details),
            "",
            f"## 긍정 질문 전체 {len(positive)}개",
            "",
            self._table(positive, details),
            "",
            f"## 범위 밖·차단 질문 {len(negative)}개",
            "",
            self._table(negative, details),
            "",
            "## 담당자 검수 항목",
            "",
            "| 확인 항목 | 기록 방법 |",
            "|---|---|",
            "| 질문이 실제 업무 표현과 비슷한가 | 적합·수정·제외 |",
            "| 예상 문서가 유일한 정답인가 | 적합·복수정답·오답 |",
            "| 검색 결과가 업무상 안전한가 | 안전·주의·차단 필요 |",
            "| 문서 권한과 유효기간이 확정됐는가 | 확정·미확정 |",
            "",
            "## 변경 내역",
            "",
            "| 버전 | 일자 | 내용 |",
            "|---|---|---|",
            "| v1.0 | 2026-08-04 | 합성 평가 120문항과 실제 검색 결과를 검수용 표로 생성 |",
            "",
        ]
        return "\n".join(lines)

    def _table(
        self, questions: list[QualityQuery], details: dict[str, dict[str, object]]
    ) -> str:
        lines = [
            "| ID | 유형 | 검색 질문 | 예상 문서 | 실제 상위 문서 | 판정 |",
            "|---|---|---|---|---|---|",
        ]
        for question in questions:
            detail = details[question.query_id]
            retrieved = detail["retrieved_manual_ids"]
            lines.append(
                "| "
                + " | ".join(
                    (
                        question.query_id,
                        self.TYPE_LABELS[question.query_type],
                        self._escape(question.query),
                        question.expected_manual_id or "없음",
                        " → ".join(str(item) for item in retrieved) or "0건",
                        self._verdict(question, detail),
                    )
                )
                + " |"
            )
        return "\n".join(lines)

    @staticmethod
    def _verdict(question: QualityQuery, detail: dict[str, object]) -> str:
        retrieved = list(detail["retrieved_manual_ids"])
        if question.expected_manual_id is None:
            return "차단 정상" if not retrieved else "오탐"
        if retrieved and retrieved[0] == question.expected_manual_id:
            return "Top1"
        return "Top3" if question.expected_manual_id in retrieved else "실패"

    @staticmethod
    def _escape(value: str) -> str:
        return " ".join(value.split()).replace("|", "\\|")

    @staticmethod
    def _validate_alignment(
        questions: list[QualityQuery], details: dict[str, dict[str, object]]
    ) -> None:
        if len(questions) != len(details):
            raise ValueError("Question suite and evaluation evidence counts differ")
        for question in questions:
            detail = details.get(question.query_id)
            if detail is None:
                raise ValueError(f"Missing evaluation detail: {question.query_id}")
            if detail["query_type"] != question.query_type:
                raise ValueError(f"Query type mismatch: {question.query_id}")
            if detail["expected_manual_id"] != question.expected_manual_id:
                raise ValueError(f"Expected manual mismatch: {question.query_id}")
