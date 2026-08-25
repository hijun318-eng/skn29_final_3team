from __future__ import annotations

import re
from enum import StrEnum


class AnswerType(StrEnum):
    PROCEDURE = "PROCEDURE"
    CRITERIA = "CRITERIA"
    IMMEDIATE = "IMMEDIATE"
    POLICY = "POLICY"
    SUMMARY = "SUMMARY"
    COMPARE = "COMPARE"


class AnswerTemplateSelector:
    """질문 전체 표현을 우선순위에 따라 내부 답변 유형으로 분류한다."""

    def select(self, question: str) -> AnswerType:
        return self.select_all(question)[0]

    def select_all(self, question: str) -> tuple[AnswerType, ...]:
        """복합 질문은 우선순위가 높은 유형부터 최대 두 개까지 선택한다."""
        text = " ".join(question.lower().split())
        selected: list[AnswerType] = []
        if self._contains(text, "지금", "즉시", "긴급", "사고", "위험", "쓰러", "누출", "노출", "유출", "잘못 전달", "위생 문제", "개인정보 문제"):
            selected.append(AnswerType.IMMEDIATE)
        if self._contains(text, "어떻게", "순서", "절차", "처리 방법", "진행", "먼저 뭘"):
            selected.append(AnswerType.PROCEDURE)
        if self._contains(text, "판단 기준", "어떤 기준", "어떤 경우", "기준이 뭐", "구분 기준"):
            selected.append(AnswerType.CRITERIA)
        if self._contains(text, "규정", "가능", "환불", "취소", "보상", "조건", "예외"):
            selected.append(AnswerType.POLICY)
        if self._contains(text, "차이", "비교", "와 b", "과 b", "둘을 구분", "둘의 구분"):
            selected.append(AnswerType.COMPARE)
        return tuple(dict.fromkeys(selected))[:2] or (AnswerType.SUMMARY,)

    @staticmethod
    def _contains(text: str, *terms: str) -> bool:
        return any(term in text for term in terms)

    def clarification(self, question: str) -> str | None:
        text = " ".join(question.lower().split())
        broad = self._contains(text, "문서 주요 내용", "전체 규정", "관리자 보고 기준", "어떤 경우 예외")
        scoped = self._contains(
            text, "안전", "개인정보", "시설", "객실", "고객", "환불", "보상", "예약", "취소", "위생", "보고서"
        )
        if not broad or scoped:
            return None
        return (
            "어떤 업무 상황의 기준을 확인하시려는지 알려주세요.\n\n"
            "예: 안전사고, 개인정보 노출, 시설 장애, 고객 불만, 예약·취소, 환불·보상"
        )


class EvidenceAnswerFormatter:
    """LLM 장애 시에도 검색 근거 문구만 사용해 유형별 짧은 답변을 만든다."""

    _FOOTER = "내부 업무지침 · 현장 실행형 · 의미전달 검증완료본"

    _ACTION_TERMS = (
        "해야", "한다", "확인", "차단", "중단", "보존", "보고", "연락", "요청", "안내",
        "기록", "판단", "조치", "통제", "확보", "금지", "처리", "점검", "인계",
    )
    _ADMIN_PREFIXES = (
        "담당", "적용 범위", "문서 성격", "이 지침을 사용하는 상황", "사용 상황", "총괄 주관",
    )
    _COMPLETE_ENDINGS = (
        "한다", "된다", "않는다", "필요하다", "해야 한다", "할 수 있다", "할 수 없다",
        "합니다", "됩니다", "않습니다", "필요합니다", "해야 합니다", "입니다", "하세요", "하십시오",
    )

    def format(
        self,
        answer_types: AnswerType | tuple[AnswerType, ...],
        body: str,
        question: str = "",
        evidence: list[dict[str, str]] | None = None,
    ) -> str:
        selected_types = answer_types if isinstance(answer_types, tuple) else (answer_types,)
        if AnswerType.COMPARE in selected_types and evidence:
            return self._compare(evidence, question)
        points = self._ranked_points(body, question)
        if not points:
            return "현재 확인된 문서에서는 질문에 답할 수 있는 구체적인 기준을 확인하지 못했습니다."
        selected = points[:5]
        if selected_types == (AnswerType.SUMMARY,):
            return "\n\n".join(selected[:4])

        first, rest = selected[0], selected[1:]
        if selected_types[0] is AnswerType.IMMEDIATE:
            report_points = [point for point in selected if "보고" in point or "책임자" in point or "관리자" in point]
            action_points = [point for point in rest if point not in report_points][:3]
            sections = [first]
            if action_points:
                sections.append("다음 조치를 순서대로 진행합니다.\n\n" + "\n".join(
                    f"{index}. {point}" for index, point in enumerate(action_points, start=1)
                ))
            if AnswerType.CRITERIA in selected_types and report_points:
                sections.append("다음 조건에서는 즉시 책임자에게 보고합니다.\n\n" + "\n".join(
                    f"- {point}" for point in report_points[:3]
                ))
            return "\n\n".join(sections)

        heading = {
            AnswerType.PROCEDURE: "처리 순서는 다음과 같습니다.",
            AnswerType.CRITERIA: "주요 판단 기준은 다음과 같습니다.",
            AnswerType.POLICY: "적용 조건과 예외는 다음과 같습니다.",
            AnswerType.COMPARE: "주요 구분 기준은 다음과 같습니다.",
        }[selected_types[0]]
        if not rest:
            return first
        marker = "1." if selected_types[0] is AnswerType.PROCEDURE else "-"
        items = "\n".join(
            f"{index}. {point}" if marker == "1." else f"- {point}"
            for index, point in enumerate(rest, start=1)
        )
        return f"{first}\n\n{heading}\n\n{items}"

    def _compare(self, evidence: list[dict[str, str]], question: str) -> str:
        query_terms = self._query_terms(question)
        evidence = sorted(
            evidence,
            key=lambda item: (
                "전체안내" in item.get("title", ""),
                -sum(term in f"{item.get('title', '')} {item.get('section_title', '')}" for term in query_terms),
            ),
        )
        distinct: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in evidence:
            key = item.get("manual_id") or item.get("title") or item.get("evidence_id", "")
            if key and key not in seen:
                seen.add(key)
                distinct.append(item)
            if len(distinct) == 2:
                break
        if len(distinct) < 2:
            return "현재 확인된 근거만으로는 두 업무 기준을 각각 비교하기 어렵습니다. 비교할 두 대상을 더 구체적으로 알려주세요."
        sections = ["두 업무는 적용 상황과 우선 조치를 기준으로 구분해야 합니다."]
        for item in distinct:
            section = item.get("section_title", "")
            label = section if section and section not in {"페이지 본문", "본문"} else item.get("title", "")
            label = label or item.get("manual_id") or "구분 기준"
            points = self._points(item.get("body", ""))[:4]
            sections.append(f"{label}\n" + "\n".join(f"- {point}" for point in points))
        return "\n\n".join(sections)

    def _ranked_points(self, body: str, question: str) -> list[str]:
        points = self._points(body)
        query_terms = self._query_terms(question)
        indexed = list(enumerate(points))
        indexed.sort(
            key=lambda item: (
                -sum(term in item[1] for term in query_terms),
                -sum(term in item[1] for term in self._ACTION_TERMS),
                item[0],
            )
        )
        ranked = [point for _, point in indexed]
        domain_terms = [
            term
            for term in ("안전", "시설", "객실", "개인정보", "환불", "보상", "예약", "취소", "위생", "고객")
            if term in question
        ]
        relevant = [point for point in ranked if any(term in point for term in domain_terms)]
        return relevant or ranked

    def _points(self, body: str) -> list[str]:
        cleaned = " ".join(body.replace(self._FOOTER, "").split())
        cleaned = re.sub(
            r"(?<![이가은는을를과와의에로])\s+(과|와|을|를|은|는|이|가|의|에|로)(?=\s)",
            r"\1",
            cleaned,
        )
        cleaned = re.sub(
            r"(확인|보고|처리|점검|통제|보존|요청|제한|적용)\s+한다\b",
            r"\1한다",
            cleaned,
        )
        cleaned = re.sub(
            r"(?:사용 상황|시작 전 확인|판단 기준|처리 순서|즉시 보고 조건|기록\s*/\s*마무리|제\d+\s*조)",
            " • ",
            cleaned,
        )
        parts = re.split(r"\s*•\s*|(?<=[.!?])\s+", cleaned)
        normalized = [" ".join(part.strip(" .-:").split()) for part in parts]
        return [
            point for point in normalized
            if len(point) >= 8
            and not point.startswith(self._ADMIN_PREFIXES)
            and not any(
                label in point
                for label in ("주관 담당", "협조 담당", "적용 범위", "문서 성격", "총괄 주관")
            )
            and any(term in point for term in self._ACTION_TERMS)
            and point.endswith(self._COMPLETE_ENDINGS)
        ]

    @staticmethod
    def _query_terms(question: str) -> set[str]:
        terms = {term for term in re.findall(r"[가-힣A-Za-z0-9]+", question) if len(term) >= 2}
        domains = {term for term in ("안전", "시설", "객실", "개인정보", "환불", "보상", "예약", "취소", "위생", "고객") if term in question}
        return terms | domains
