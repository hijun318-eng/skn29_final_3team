"""한글·영문 혼합 문서 후보에 결정론적 Okapi BM25 lexical 점수를 부여한다."""

from __future__ import annotations

from collections import Counter
import math
import re


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z_]+|[가-힣]+")


def tokenize(text: str) -> list[str]:
    """BM25 검색에 사용할 한글·영문·숫자 토큰을 만든다."""
    return [token.casefold() for token in TOKEN_PATTERN.findall(text)]


def bm25_scores(
    query: str,
    documents: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Okapi BM25 점수를 동일 후보군 안에서 0~1로 정규화한다."""
    query_terms = tuple(dict.fromkeys(tokenize(query)))
    tokenized = [tokenize(document) for document in documents]
    if not query_terms or not tokenized:
        return [0.0] * len(documents)

    average_length = sum(map(len, tokenized)) / len(tokenized) or 1.0
    frequencies = [Counter(tokens) for tokens in tokenized]
    document_frequencies = {
        term: sum(1 for frequency in frequencies if frequency.get(term, 0) > 0)
        for term in query_terms
    }
    raw_scores: list[float] = []
    document_count = len(tokenized)
    for tokens, frequency in zip(tokenized, frequencies, strict=True):
        score = 0.0
        length_factor = 1 - b + b * len(tokens) / average_length
        for term in query_terms:
            term_frequency = frequency.get(term, 0)
            if not term_frequency:
                continue
            inverse_frequency = math.log(
                1
                + (document_count - document_frequencies[term] + 0.5)
                / (document_frequencies[term] + 0.5)
            )
            score += inverse_frequency * (
                term_frequency * (k1 + 1)
                / (term_frequency + k1 * length_factor)
            )
        raw_scores.append(score)

    maximum = max(raw_scores, default=0.0)
    return [score / maximum if maximum else 0.0 for score in raw_scores]
