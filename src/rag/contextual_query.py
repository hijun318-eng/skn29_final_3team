from __future__ import annotations

import re


class ContextualQueryBuilder:
    MAX_RECENT_UTTERANCES = 3
    MAX_SELECTED_DOCUMENTS = 10

    @classmethod
    def build(cls, query: str, recent_utterances: tuple[str, ...] = ()) -> str:
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
        if len(values) > cls.MAX_SELECTED_DOCUMENTS:
            raise ValueError("Too many selected document IDs")
        normalized = tuple(
            cls._normalize(value, "selected_document_id") for value in values
        )
        if any(not re.fullmatch(r"[A-Z][A-Z0-9-]{1,99}", value) for value in normalized):
            raise ValueError("Invalid selected document ID")
        return normalized

    @staticmethod
    def _normalize(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()
