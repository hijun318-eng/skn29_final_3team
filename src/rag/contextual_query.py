"""현재 질문과 제한된 최근 발화를 검색용 문맥으로 정규화한다."""

from __future__ import annotations

import re


class ContextualQueryBuilder:
    """mult-turn 발화와 선택 문서 ID의 개수·형식 경계를 한곳에서 검증한다."""

    MAX_RECENT_UTTERANCES = 3
    MAX_SELECTED_DOCUMENTS = 10
    _REPORT_PERIOD_PATTERN = re.compile(
        r"(?:(?P<year>20\d{2})\s*년\s*)?(?P<month>1[0-2]|0?[1-9])\s*월"
    )

    @classmethod
    def build(cls, query: str, recent_utterances: tuple[str, ...] = ()) -> str:
        """최대 세 최근 발화 뒤에 현재 질문을 붙인 검색 문자열을 반환한다."""

        normalized_query = cls._normalize(query, "query")
        history = tuple(
            cls._normalize(item, "recent_utterance")
            for item in recent_utterances[-cls.MAX_RECENT_UTTERANCES :]
        )
        if not history:
            return normalized_query
        return "\n".join((*history, normalized_query))

    @classmethod
    def validate_document_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """선택 문서 ID를 정규화하고 허용 개수·대문자 식별자 형식을 검사한다."""

        if len(values) > cls.MAX_SELECTED_DOCUMENTS:
            raise ValueError("Too many selected document IDs")
        normalized = tuple(
            cls._normalize(value, "selected_document_id") for value in values
        )
        if any(not re.fullmatch(r"[A-Z][A-Z0-9-]{1,99}", value) for value in normalized):
            raise ValueError("Invalid selected document ID")
        return normalized

    @classmethod
    def report_periods(cls, value: str) -> tuple[str, ...]:
        """`2026년 7월과 8월`처럼 연도가 생략된 연속 월도 보고 월로 정규화한다."""

        normalized = cls._normalize(value, "query")
        current_year: int | None = None
        periods: list[str] = []
        for match in cls._REPORT_PERIOD_PATTERN.finditer(normalized):
            raw_year = match.group("year")
            if raw_year is not None:
                current_year = int(raw_year)
            if current_year is None:
                continue
            period = f"{current_year:04d}-{int(match.group('month')):02d}"
            if period not in periods:
                periods.append(period)
        return tuple(periods)

    @staticmethod
    def _normalize(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()
