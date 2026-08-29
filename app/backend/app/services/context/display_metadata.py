"""승인된 Glossary metadata에서 한국어 사용자 표시값을 결정한다."""

from __future__ import annotations

import re
from typing import Any, Iterable


_HANGUL = re.compile(r"[가-힣]")


def preferred_display_text(primary: object, aliases: Iterable[object] = ()) -> str:
    """원본 label을 보존하되 승인 aliases에 한국어가 있으면 그 값을 표시명으로 쓴다."""

    primary_text = str(primary or "").strip()
    if _HANGUL.search(primary_text):
        return primary_text
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if _HANGUL.search(alias_text):
            return alias_text
    return primary_text


def metric_display_label(term: Any) -> str:
    """DataHub Glossary Term의 label·aliases만 사용해 지표 표시명을 반환한다."""

    return preferred_display_text(
        getattr(term, "label", ""),
        getattr(term, "aliases", ()),
    )


def metric_display_unit(unit: object) -> str:
    """계산용 단위 코드를 바꾸지 않고 한국어 화면에 사용할 단위만 반환한다."""

    raw = str(unit or "").strip()
    normalized = raw.casefold()
    if normalized == "ratio" or raw == "%":
        return "%"
    if normalized == "krw" or normalized.startswith("krw_per_"):
        return "원"
    if normalized in {"room_night", "room_nights"}:
        return "객실박"
    if normalized in {"room", "rooms"}:
        return "실"
    if normalized in {"hour", "hours"}:
        return "시간"
    if normalized in {"point", "points"}:
        return "점"
    if normalized == "count":
        return "건"
    return raw
