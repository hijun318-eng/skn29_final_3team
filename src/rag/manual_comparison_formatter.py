"""여러 매뉴얼의 동일 조문을 문서별로 정렬하고 실제 공통 문장만 비교한다."""

from __future__ import annotations

from typing import Any

from .manual_article_formatter import ManualArticleFormatter, ManualClaim, ManualSection


class ManualComparisonFormatter:
    """요청된 동일 조문만 문서별로 비교하고 근거에 없는 공통 주제를 만들지 않는다."""

    def __init__(self) -> None:
        self._articles = ManualArticleFormatter()

    def build_sections(
        self,
        groups: list[list[dict[str, Any]]],
        query: str,
    ) -> list[tuple[dict[str, Any], ManualSection]]:
        """문서별 근거 그룹에서 요청 조문을 만들고 대표 근거와 함께 반환한다."""

        target = self.target_number(query)
        answer_type = "PROCEDURE" if target == 4 else "CRITERIA"
        built: list[tuple[dict[str, Any], ManualSection]] = []
        for group in groups:
            if not group:
                continue
            for section in self._articles.build_sections(group, query, answer_type):
                built.append((group[0], section))
        return built

    def common_section(
        self,
        sections: list[tuple[dict[str, Any], ManualSection]],
    ) -> ManualSection | None:
        """둘 이상 문서에 정규화된 문장이 모두 있을 때만 공통점 절을 구성한다."""

        by_document: dict[str, dict[str, ManualClaim]] = {}
        for item, section in sections:
            key = f"{item.get('manual_id') or item.get('title')}:{item.get('version') or ''}"
            claims = by_document.setdefault(key, {})
            for claim in section.claims:
                claims[self._normalize(claim.text)] = claim
        if len(by_document) < 2:
            return None
        common_keys = set.intersection(*(set(claims) for claims in by_document.values()))
        common_claims = []
        for key in sorted(common_keys):
            matched = [claims[key] for claims in by_document.values()]
            common_claims.append(ManualClaim(
                text=matched[0].text,
                evidence_ids=tuple(dict.fromkeys(
                    evidence_id for claim in matched for evidence_id in claim.evidence_ids
                )),
            ))
        return ManualSection(0, "공통점", tuple(common_claims)) if common_claims else None

    def select_documents(self, evidence: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """근거를 문서·버전별로 묶어 원문 순서의 단일 비교 본문으로 합친다."""

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in evidence:
            key = (
                str(item.get("manual_id") or item.get("title") or ""),
                str(item.get("version") or ""),
            )
            if key[0]:
                grouped.setdefault(key, []).append(item)
        selected = []
        for group in grouped.values():
            ordered = sorted(group, key=self._articles.evidence_order)
            aggregated = dict(ordered[0])
            aggregated["body"] = "\n\n[[CHUNK_BOUNDARY]]\n\n".join(
                str(item.get("body") or "") for item in ordered if item.get("body")
            )
            selected.append(aggregated)
        return selected

    def sections(self, items: list[dict[str, Any]], query: str) -> list[str]:
        """문서별 비교 항목을 제목과 파싱된 조문이 포함된 표시 문자열로 반환한다."""

        built = self.build_sections([[item] for item in items], query)
        return [
            f"[{item.get('title') or '확인 불가'}]\n\n{self._articles.render_section(section)}"
            for item, section in built
        ]

    def target_number(self, query: str) -> int:
        """질문에 명시된 첫 조 번호를 선택하고 없으면 판단 기준인 제3조를 사용한다."""

        specific = self._articles.specific_numbers(query)
        return specific[0] if specific else 3

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(text.lower().split()).rstrip(".!?")
