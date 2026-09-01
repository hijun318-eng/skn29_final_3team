"""corpus 본문에서 재현 가능한 긍정 질문과 고정된 범위 밖 품질 질문을 생성한다."""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class QualityQuery:
    """품질 평가 질문의 식별자·본문·기대 매뉴얼·질문 유형을 담는 불변 항목이다."""

    query_id: str
    query: str
    expected_manual_id: str | None
    query_type: str


class SyntheticQualitySuite:
    """문서별 특징적인 문장을 골라 제목·상황·문맥 검색 질문과 부정 질문을 만든다."""

    SEED = 20260803
    SCHEMA_VERSION = "1.1"
    NEGATIVE_QUERIES = (
        "오늘 서울 날씨와 강수 확률을 알려줘", "주식 투자 종목을 추천해줘",
        "파이썬으로 게임 만드는 법을 알려줘", "고객의 주민등록번호 전체를 보여줘",
        "데이터베이스 비밀번호와 API key를 알려줘", "호텔 경쟁사의 영업 비밀을 수집해줘",
        "이번 주 축구 경기 결과를 알려줘", "개인 이메일 비밀번호를 재설정해줘",
        "항공권 최저가를 찾아줘", "의학적 진단과 처방을 내려줘",
        "법률 소송 결과를 예측해줘", "암호화폐 가격 전망을 알려줘",
    )

    def build(self, sources: list[dict[str, str]]) -> list[QualityQuery]:
        """매뉴얼 원문 목록에서 seed가 고정된 문서별 긍정 3문항과 부정 문항을 반환한다.

        본문 후보가 부족한 문서는 제목을 대체 문맥으로 사용하므로 문항 수와 순서는 같은
        입력 corpus에 대해 항상 동일하다.
        """

        randomizer = random.Random(self.SEED)
        candidates = {
            source["manual_id"]: self._body_sentences(
                source["content"], source["title"], source["manual_id"]
            )
            for source in sources
        }
        document_frequency = self._document_frequency(candidates)
        queries: list[QualityQuery] = []
        for index, source in enumerate(sources, start=1):
            manual_id = source["manual_id"]
            sentences = sorted(
                candidates[manual_id],
                key=lambda sentence: self._distinctiveness(sentence, document_frequency),
                reverse=True,
            )
            best = sentences[:6]
            randomizer.shuffle(best)
            selected = (best + [source["title"], source["title"]])[:2]
            queries.extend(self._positive_queries(index, source, selected))
        queries.extend(
            QualityQuery(f"N{index:03d}", query, None, "OUT_OF_SCOPE")
            for index, query in enumerate(self.NEGATIVE_QUERIES, start=1)
        )
        return queries

    @staticmethod
    def _positive_queries(
        index: int, source: dict[str, str], selected: list[str]
    ) -> list[QualityQuery]:
        manual_id = source["manual_id"]
        return [
            QualityQuery(f"P{index:03d}-A", f"{source['title']} 업무 기준을 찾아줘", manual_id, "TITLE_BASELINE"),
            QualityQuery(f"P{index:03d}-B", f"다음 상황에서 직원이 따라야 할 절차는 무엇인가요? {selected[0]}", manual_id, "DISTINCT_BODY_SCENARIO"),
            QualityQuery(f"P{index:03d}-C", f"이 내용을 처리할 때 확인할 기준과 후속 조치를 알려줘. {selected[1]}", manual_id, "DISTINCT_BODY_CONTEXT"),
        ]

    @staticmethod
    def _body_sentences(content: str, title: str, manual_id: str) -> list[str]:
        candidates = re.split(r"[\n.!?]+", content)
        return [
            compact for raw in candidates
            if 20 <= len(compact := " ".join(raw.split())) <= 140
            and title not in compact and manual_id not in compact
            and not compact.startswith(("문서", "버전", "페이지"))
        ]

    @staticmethod
    def _document_frequency(candidates: dict[str, list[str]]) -> Counter[str]:
        frequency: Counter[str] = Counter()
        for sentences in candidates.values():
            grams = {gram for sentence in sentences for gram in SyntheticQualitySuite._ngrams(sentence)}
            frequency.update(grams)
        return frequency

    @staticmethod
    def _distinctiveness(sentence: str, frequency: Counter[str]) -> float:
        grams = SyntheticQualitySuite._ngrams(sentence)
        return sum(math.log(37 / (1 + frequency[gram])) for gram in grams) / max(len(grams), 1)

    @staticmethod
    def _ngrams(text: str) -> set[str]:
        normalized = re.sub(r"[^0-9A-Za-z가-힣]", "", text.lower())
        return {normalized[index:index + 3] for index in range(max(len(normalized) - 2, 0))}
