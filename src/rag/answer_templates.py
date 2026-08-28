from __future__ import annotations

import re
from enum import StrEnum

from .manual_article_formatter import ManualArticleFormatter


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
        risk_criteria = (
            self._contains(text, "위험", "긴급 장애", "긴급 상황", "중대 사안", "중대 상황")
            and self._contains(text, "판단", "기준", "구분", "분류", "보는")
        )
        if risk_criteria:
            selected.append(AnswerType.CRITERIA)
        if self._contains(text, "지금", "즉시", "긴급", "사고", "위험", "쓰러", "누출", "노출", "유출", "잘못 전달", "위생 문제", "개인정보 문제"):
            selected.append(AnswerType.IMMEDIATE)
        if self._contains(text, "요약", "핵심", "주요 내용", "간단히", "전체적으로"):
            selected.append(AnswerType.SUMMARY)
        if self._contains(text, "어떻게", "순서", "절차", "처리 방법", "진행", "먼저 뭘"):
            selected.append(AnswerType.PROCEDURE)
        if self._contains(text, "판단 기준", "어떤 기준", "어떤 경우", "기준이 뭐", "구분 기준", "보고 시점", "보고 상황", "남길 기록", "업무 종료", "종료 기준", "완료 기준"):
            selected.append(AnswerType.CRITERIA)
        if self._contains(text, "규정", "가능", "환불", "취소", "보상", "조건", "예외", "금지사항", "하면 안", "해서는 안"):
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

    _ARTICLE_FORMATTER = ManualArticleFormatter()
    _FOOTER = "내부 업무지침 · 현장 실행형 · 의미전달 검증완료본"
    _BOILERPLATE = re.compile(
        r"(?:"
        r"(?:현장\s*확인내용|객실\s*[·ㆍ]\s*설비)?\s*"
        r"내부\s*업무지침\s*[·ㆍ]\s*현장\s*실행형\s*[·ㆍ]\s*"
        r"의미전달\s*검증완료본"
        r"|현장\s*실행형\s*내부\s*업무지침"
        r")"
    )
    _RELATED_DOCUMENTS_BLOCK = re.compile(
        r"이\s*영역의\s*문서.*?이\s*영역에서\s*공통으로\s*지킬\s*기준",
        re.DOTALL,
    )

    _ACTION_TERMS = (
        "해야", "한다", "확인", "차단", "중단", "보존", "보고", "연락", "요청", "안내",
        "기록", "판단", "조치", "통제", "확보", "금지", "처리", "점검", "인계",
    )
    _CRITERIA_TERMS = (
        "위험", "가능성", "중단", "지속", "필요", "불명", "이상", "사고", "피해",
        "고립", "화재", "감전", "가스", "누수", "응급", "장애",
    )
    _REPORT_TERMS = ("책임자", "관리자", "보고", "전달", "연락", "긴급기관", "전문기관")
    _CONTROL_TERMS = (
        "통제", "중단", "접근", "해제", "분해", "훼손", "우회", "안전 확인",
        "추측", "확정적으로", "금지",
    )
    _RECORD_TERMS = ("기록", "시각", "인계", "종료", "재점검", "확인 결과")
    _ADMIN_PREFIXES = (
        "담당", "적용 범위", "문서 성격", "이 지침을 사용하는 상황", "사용 상황", "총괄 주관",
        "현장 확인내용", "객실·설비",
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
        structured = self._ARTICLE_FORMATTER.format(
            body,
            question,
            selected_types[0].value,
        )
        if structured:
            return structured
        points = self._points(body)
        if not points:
            return "현재 확인된 문서에서는 질문에 답할 수 있는 구체적인 기준을 확인하지 못했습니다."
        if selected_types == (AnswerType.SUMMARY,):
            return self._render_section("핵심 요약", points[:4])

        if selected_types[0] is AnswerType.IMMEDIATE:
            groups = self._immediate_groups(points)
            order = (
                ("즉시 보고 기준", "criteria", False),
                ("즉시 조치 절차", "actions", True),
                ("상급자 보고 및 인계", "reports", False),
                ("현장 통제 및 종료", "controls", False),
            ) if "보고" in question and "기준" in question else (
                ("즉시 조치 절차", "actions", True),
                ("즉시 보고 기준", "criteria", False),
                ("상급자 보고 및 인계", "reports", False),
                ("현장 통제 및 종료", "controls", False),
            )
            return "\n\n".join(
                self._render_section(title, groups[key], numbered)
                for title, key, numbered in order
                if groups[key]
            )

        heading = {
            AnswerType.PROCEDURE: "처리 절차",
            AnswerType.CRITERIA: "판단 기준",
            AnswerType.POLICY: "적용 조건 및 예외",
            AnswerType.COMPARE: "구분 및 비교",
        }[selected_types[0]]
        numbered = selected_types[0] is AnswerType.PROCEDURE
        return self._render_section(heading, points, numbered)

    @classmethod
    def _immediate_groups(cls, points: list[str]) -> dict[str, list[str]]:
        groups = {"criteria": [], "actions": [], "reports": [], "controls": []}
        for point in points:
            complete = point.endswith(cls._COMPLETE_ENDINGS)
            if not complete:
                key = "controls" if any(term in point for term in cls._RECORD_TERMS) else "criteria"
            elif any(term in point for term in cls._REPORT_TERMS):
                key = "reports"
            elif any(term in point for term in (*cls._CONTROL_TERMS, *cls._RECORD_TERMS)):
                key = "controls"
            else:
                key = "actions"
            groups[key].append(point)
        return groups

    @staticmethod
    def _render_section(title: str, points: list[str], numbered: bool = False) -> str:
        items = "\n\n".join(
            f"{index}. {point}" if numbered else f"- {point}"
            for index, point in enumerate(points, start=1)
        )
        return f"[{title}]\n\n{items}"

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
            points = self._points(item.get("body", ""))
            sections.append(f"{label}\n" + "\n".join(f"- {point}" for point in points))
        return "\n\n".join(sections)

    def _points(self, body: str) -> list[str]:
        # 관련 문서 목록은 검색·도움말용 메타데이터다. 답변에는 목록을 숨기고,
        # 앞의 문서 요약과 뒤의 실제 공통 기준 및 본문만 사용한다.
        cleaned_body = self._RELATED_DOCUMENTS_BLOCK.sub(" • ", body)
        cleaned_body = self._BOILERPLATE.sub(" • ", cleaned_body)
        cleaned_body = (
            cleaned_body
            .replace("이 영역의 문서", " • ")
            .replace("이 영역에서 공통으로 지킬 기준", " • ")
        )
        cleaned = " ".join(cleaned_body.replace(self._FOOTER, "").split())
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
        parts = re.split(r"\s*•\s*|(?<=[.!?])\s+|(?=\d+[.)]\s+)", cleaned)
        normalized = [
            re.sub(r"^\d+[.)]\s*", "", " ".join(part.strip(" .-:").split()))
            for part in parts
        ]
        points = []
        for point in normalized:
            actionable = any(term in point for term in self._ACTION_TERMS)
            criterion = any(term in point for term in self._CRITERIA_TERMS)
            complete = point.endswith(self._COMPLETE_ENDINGS)
            if (
                len(point) >= 8
                and not point.startswith(self._ADMIN_PREFIXES)
                and not any(
                    label in point
                    for label in ("주관 담당", "협조 담당", "적용 범위", "문서 성격", "총괄 주관")
                )
                and (actionable or criterion)
                and (complete or len(point) <= 100)
            ):
                points.append(point)
        return list(dict.fromkeys(points))

    @staticmethod
    def _query_terms(question: str) -> set[str]:
        terms = {term for term in re.findall(r"[가-힣A-Za-z0-9]+", question) if len(term) >= 2}
        domains = {term for term in ("안전", "시설", "객실", "개인정보", "환불", "보상", "예약", "취소", "위생", "고객") if term in question}
        return terms | domains
