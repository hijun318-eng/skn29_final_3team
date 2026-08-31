"""검색 근거에서 제1조~제9조 항목을 추출하고 인용 가능한 답변 절로 구성한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManualArticle:
    """한 근거 청크에서 파싱한 조 번호·표준 제목·중복 제거된 문장들을 보존한다."""

    number: int
    title: str
    points: tuple[str, ...]


@dataclass(frozen=True)
class ManualClaim:
    """답변에 표시할 한 문장과 그 문장을 뒷받침하는 evidence 식별자를 묶는다."""

    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ManualSection:
    """같은 조 번호에 속한 근거 문장들을 출력 순서대로 담는 답변 절이다."""

    number: int
    title: str
    claims: tuple[ManualClaim, ...]


class ManualArticleFormatter:
    """청크별 조문을 먼저 파싱한 뒤 원문 순서와 evidence 연결을 유지해 병합한다."""

    _ARTICLE_PATTERN = re.compile(
        r"제\s*(\d+)\s*조\s*[.:·]?\s*(.*?)"
        r"(?=제\s*\d+\s*조\s*[.:·]?|\[\[CHUNK_BOUNDARY\]\]|$)",
        re.DOTALL,
    )
    _FOOTER_PATTERN = re.compile(
        r"내부\s*업무지침\s*[·ㆍ]\s*현장\s*실행형\s*[·ㆍ]\s*의미전달\s*검증완료본"
    )
    _TITLES = {
        1: "이 지침을 사용하는 상황",
        2: "시작 전에 확인할 사항",
        3: "구체적인 판단·처리 기준",
        4: "처리 순서",
        5: "책임자에게 바로 보고할 상황",
        6: "반드시 남길 기록",
        7: "담당자가 해서는 안 되는 행동",
        8: "상황별 적용 예시",
        9: "업무 종료 기준",
    }
    _TITLE_PATTERNS = {
        number: re.compile(r"\s*".join(re.escape(word) for word in title.split()))
        for number, title in _TITLES.items()
    }
    _ADMIN_LABELS = ("주관 담당", "협조 담당", "적용 범위", "문서 성격", "총괄 주관")
    _COMPLETE_ENDINGS = (
        "한다", "된다", "않는다", "필요하다", "해야 한다", "할 수 있다", "할 수 없다",
        "했는가", "있는가", "정했는가", "확인했는가", "안내했는가", "검토했는가",
        "합니다", "됩니다", "않습니다", "입니다", "하세요", "하십시오", ".", "?", "!",
    )

    def format(self, body: str, question: str, answer_type: str) -> str | None:
        """경계 표시가 포함된 본문을 질문 유형에 맞는 조문 답변 문자열로 변환한다.

        파싱 가능한 제1조~제9조 근거가 하나도 없으면 내용을 추정하지 않고 ``None``을
        반환한다.
        """

        chunks = [part.strip() for part in body.split("[[CHUNK_BOUNDARY]]") if part.strip()]
        evidence = [
            {
                "evidence_id": f"local:{index:04d}",
                "body": chunk,
                "page_start": index,
                "chunk_index": index,
                "section_title": "",
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
        sections = self.build_sections(evidence, question, answer_type)
        if not sections:
            return None
        rendered = "\n\n".join(self.render_section(section) for section in sections)
        return f"[문서 요약]\n\n{rendered}" if answer_type == "SUMMARY" else rendered

    def build_sections(
        self,
        evidence: list[dict[str, Any]],
        question: str,
        answer_type: str,
    ) -> tuple[ManualSection, ...]:
        """근거 목록을 출처 순으로 합치고 질문이 요구한 조문만 evidence와 함께 반환한다."""

        merged: dict[int, dict[str, list[str]]] = {}
        for item in sorted(evidence, key=self.evidence_order):
            evidence_id = str(item.get("evidence_id") or "").strip()
            if not evidence_id:
                continue
            for article in self._parse_articles(
                str(item.get("body") or item.get("content") or item.get("text") or ""),
                str(item.get("section_title") or ""),
            ):
                points = merged.setdefault(article.number, {})
                for point in article.points:
                    points.setdefault(point, [])
                    if evidence_id not in points[point]:
                        points[point].append(evidence_id)

        targets = self.target_numbers(question, answer_type)
        return tuple(
            ManualSection(
                number=number,
                title=self._TITLES[number],
                claims=tuple(
                    ManualClaim(text=point, evidence_ids=tuple(evidence_ids))
                    for point, evidence_ids in merged.get(number, {}).items()
                ),
            )
            for number in targets
            if merged.get(number)
        )

    def available_numbers(self, evidence: list[dict[str, Any]]) -> set[int]:
        """제공된 근거에서 실제로 파싱된 제1조~제9조 번호 집합을 반환한다."""

        return {
            article.number
            for item in evidence
            for article in self._parse_articles(
                str(item.get("body") or item.get("content") or item.get("text") or ""),
                str(item.get("section_title") or ""),
            )
        }

    def claim_segments(self, body: str, section_title: str = "") -> tuple[str, ...]:
        """조문 parser가 분리한 전체 불릿·문장을 외부 답변 claim 검증 단위로 반환한다."""

        return tuple(
            dict.fromkeys(
                point
                for article in self._parse_articles(body, section_title)
                for point in article.points
            )
        )

    def target_numbers(self, question: str, answer_type: str) -> tuple[int, ...]:
        """질문에 명시된 조 번호를 우선하고 없으면 답변 유형의 기본 조 번호를 선택한다."""

        return self.specific_numbers(question) or self._default_numbers(answer_type)

    def _parse_articles(self, body: str, section_title: str = "") -> tuple[ManualArticle, ...]:
        articles: list[ManualArticle] = []
        for match in self._ARTICLE_PATTERN.finditer(body):
            number = int(match.group(1))
            if number not in self._TITLES:
                continue
            payload = self._FOOTER_PATTERN.sub(" • ", match.group(2))
            payload = self._TITLE_PATTERNS[number].sub("", payload, count=1)
            points = self._points(payload)
            if points:
                articles.append(ManualArticle(number, self._TITLES[number], points))
        if articles:
            return tuple(articles)
        inferred = re.search(r"제\s*(\d+)\s*조", section_title)
        if inferred and int(inferred.group(1)) in self._TITLES:
            number = int(inferred.group(1))
            points = self._points(self._TITLE_PATTERNS[number].sub("", body, count=1))
            if points:
                return (ManualArticle(number, self._TITLES[number], points),)
        return ()

    def _points(self, payload: str) -> tuple[str, ...]:
        cleaned = " ".join(payload.split())
        parts = re.split(r"\s*•\s*|(?=\d+[.)]\s+)", cleaned)
        points: list[str] = []
        for part in parts:
            point = re.sub(r"^\d+[.)]\s*", "", part).strip(" .-:")
            point = re.split(
                r"(?:주관\s*담당|협조\s*담당|적용\s*범위|문서\s*성격|총괄\s*주관)",
                point,
                maxsplit=1,
            )[0].strip()
            if len(point) < 3 or point.startswith(self._ADMIN_LABELS):
                continue
            if len(point) >= 80 and not point.endswith(self._COMPLETE_ENDINGS):
                continue
            if point not in points:
                points.append(point)
        return tuple(points)

    @staticmethod
    def specific_numbers(question: str) -> tuple[int, ...]:
        """질문에 등장한 유효 조 번호를 최초 등장 순서대로 중복 없이 추출한다."""

        return tuple(
            dict.fromkeys(
                number
                for raw in re.findall(r"제\s*(\d+)\s*조", question)
                if (number := int(raw)) in ManualArticleFormatter._TITLES
            )
        )

    @staticmethod
    def _default_numbers(answer_type: str) -> tuple[int, ...]:
        return {
            "PROCEDURE": (4,),
            "CRITERIA": (3,),
            "IMMEDIATE": (4,),
            "POLICY": (3,),
            "SUMMARY": (1, 3, 4, 9),
            "COMPARE": tuple(range(1, 10)),
        }.get(str(answer_type), (3,))

    @staticmethod
    def evidence_order(item: dict[str, Any]) -> tuple[int, int, str]:
        """근거를 페이지·청크·evidence 식별자 순으로 안정 정렬할 키를 만든다."""

        def number(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        return (
            number(item.get("page_start"), 1_000_000),
            number(item.get("chunk_index"), 1_000_000),
            str(item.get("evidence_id") or ""),
        )

    @staticmethod
    def render_section(section: ManualSection) -> str:
        """절차 조문은 번호 목록으로, 다른 조문은 글머리표 목록으로 렌더링한다."""

        numbered = section.number == 4
        lines = [
            f"{index}. {claim.text}" if numbered else f"- {claim.text}"
            for index, claim in enumerate(section.claims, start=1)
        ]
        return f"[제{section.number}조 {section.title}]\n\n" + "\n\n".join(lines)
