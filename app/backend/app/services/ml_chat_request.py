"""자연어 객실 수요 예측 질문을 런타임 capability 기반 요청으로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any


@dataclass(frozen=True)
class MLChatResolution:
    """자연어 질문을 예측 입력 또는 추가 질문 안내로 변환한 결과다."""

    payload: dict[str, Any] | None
    message: str | None = None
    options: tuple[dict[str, str], ...] = ()
    supported_properties: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        """실행 가능한 구조화 예측 입력이 만들어졌는지 반환한다."""

        return self.payload is not None

    def clarification_response(self) -> dict[str, Any]:
        """대화 화면이 표시할 추가 조건 질문 응답을 만든다."""

        return {
            "status": "NEEDS_CLARIFICATION",
            "answer_text": self.message or "예측 조건을 확인해 주세요.",
            "clarification_options": list(self.options),
            "supported_properties": list(self.supported_properties),
            "provenance": {"source": "ML_RUNTIME_CAPABILITIES", "rag_called": False},
        }


class MLChatRequestResolver:
    """호텔을 하드코딩하지 않고 runtime capability에서 예측 입력을 찾는다."""

    _DATE_PATTERN = re.compile(
        r"(?:(?P<year>\d{4})\s*(?:년|[-./])\s*)?"
        r"(?P<month>\d{1,2})\s*(?:월|[-./])\s*(?P<day>\d{1,2})\s*일?"
    )
    _HOTEL_PATTERN = re.compile(r"([A-Za-z0-9가-힣_-]+)\s*호텔", re.IGNORECASE)
    _HORIZON_PATTERNS = (
        re.compile(r"(?:향후|앞으로|다음)\s*(\d{1,2})\s*일"),
        re.compile(r"(\d{1,2})\s*일(?:간|동안)\s*(?:객실\s*)?(?:수요\s*)?(?:예측|전망)"),
    )

    def resolve(
        self,
        question: str,
        capabilities: dict[str, Any],
        *,
        conversation_id: str | None,
    ) -> MLChatResolution:
        """질문과 runtime capability를 호텔·기준일·예측기간 입력으로 변환한다."""

        properties = tuple(
            item for item in capabilities.get("properties", [])
            if isinstance(item, dict) and str(item.get("property_id") or "").strip()
        )
        supported = tuple(str(item["property_id"]).upper() for item in properties)
        if not properties:
            return MLChatResolution(None, "현재 ML 런타임에서 예측 가능한 호텔을 확인할 수 없습니다.")

        selected = self._select_property(question, properties)
        if selected is None:
            candidate = self._explicit_hotel(question)
            message = (
                f"'{candidate}' 호텔은 현재 모델의 예측 대상이 아닙니다. 지원 호텔: {', '.join(supported)}"
                if candidate else "예측할 호텔을 지정해 주세요."
            )
            options = tuple(
                {"label": f"{property_id} 호텔 예측", "value": f"{property_id} 호텔의 향후 7일 객실 수요를 예측해줘"}
                for property_id in supported
            )
            return MLChatResolution(None, message, options, supported)

        property_id = str(selected["property_id"]).upper()
        try:
            min_as_of = date.fromisoformat(str(selected["min_as_of"]))
            max_as_of = date.fromisoformat(str(selected["max_as_of"]))
        except (KeyError, TypeError, ValueError):
            return MLChatResolution(None, f"{property_id} 호텔의 예측 가능 날짜 메타데이터가 올바르지 않습니다.", supported_properties=supported)

        parsed_dates = self._extract_dates(question, max_as_of.year)
        as_of = parsed_dates[0] if parsed_dates else max_as_of
        max_horizon = max(
            1,
            int(
                capabilities.get("max_horizon_days")
                or capabilities.get("max_horizon")
                or 7
            ),
        )
        horizon = self._extract_horizon(question)
        if horizon is None and len(parsed_dates) > 1:
            horizon = (parsed_dates[1] - as_of).days
        horizon = horizon or min(7, max_horizon)
        if as_of < min_as_of or as_of > max_as_of:
            return MLChatResolution(None, f"{property_id} 호텔은 기준일 {min_as_of.isoformat()}부터 {max_as_of.isoformat()}까지만 예측할 수 있습니다.", supported_properties=supported)
        if horizon < 1 or horizon > max_horizon:
            return MLChatResolution(None, f"예측 기간은 1일부터 {max_horizon}일까지 지정해 주세요.", supported_properties=supported)

        payload: dict[str, Any] = {"property_id": property_id, "as_of": as_of, "horizon": horizon}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return MLChatResolution(payload, supported_properties=supported)

    @classmethod
    def _select_property(cls, question: str, properties: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
        normalized = cls._normalize_name(question)
        for item in properties:
            if any(cls._contains_alias(normalized, cls._normalize_name(alias)) for alias in cls._aliases(item)):
                return item
        return properties[0] if cls._explicit_hotel(question) is None and len(properties) == 1 else None

    @staticmethod
    def _aliases(metadata: dict[str, Any]) -> tuple[str, ...]:
        aliases = [str(metadata[key]).strip() for key in ("property_id", "property_name", "display_name", "name") if isinstance(metadata.get(key), str) and str(metadata[key]).strip()]
        if isinstance(metadata.get("aliases"), list):
            aliases.extend(str(value).strip() for value in metadata["aliases"] if str(value).strip())
        return tuple(dict.fromkeys(aliases))

    @staticmethod
    def _normalize_name(value: str) -> str:
        return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())

    @staticmethod
    def _contains_alias(question: str, alias: str) -> bool:
        return bool(alias) and re.search(rf"(?<![0-9a-z가-힣]){re.escape(alias)}(?![0-9a-z가-힣])", question, re.IGNORECASE) is not None

    @classmethod
    def _explicit_hotel(cls, question: str) -> str | None:
        match = cls._HOTEL_PATTERN.search(question)
        return match.group(1).strip() if match else None

    @classmethod
    def _extract_dates(cls, question: str, fallback_year: int) -> tuple[date, ...]:
        parsed: list[date] = []
        for match in cls._DATE_PATTERN.finditer(question):
            try:
                value = date(int(match.group("year") or fallback_year), int(match.group("month")), int(match.group("day")))
            except ValueError:
                continue
            if value not in parsed:
                parsed.append(value)
        return tuple(parsed)

    @classmethod
    def _extract_horizon(cls, question: str) -> int | None:
        for pattern in cls._HORIZON_PATTERNS:
            if match := pattern.search(question):
                return int(match.group(1))
        return None
