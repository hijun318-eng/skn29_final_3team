from __future__ import annotations

from typing import Any

from .manual_article_formatter import ManualArticleFormatter, ManualClaim, ManualSection


class ManualComparisonFormatter:
    """Compare the same requested article without inventing shared themes."""

    def __init__(self) -> None:
        self._articles = ManualArticleFormatter()

    def build_sections(
        self,
        groups: list[list[dict[str, Any]]],
        query: str,
    ) -> list[tuple[dict[str, Any], ManualSection]]:
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
        built = self.build_sections([[item] for item in items], query)
        return [
            f"[{item.get('title') or '확인 불가'}]\n\n{self._articles.render_section(section)}"
            for item, section in built
        ]

    def target_number(self, query: str) -> int:
        specific = self._articles.specific_numbers(query)
        return specific[0] if specific else 3

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(text.lower().split()).rstrip(".!?")
