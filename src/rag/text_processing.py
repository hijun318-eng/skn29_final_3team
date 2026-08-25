from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import Chunk


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WORD_PATTERN = re.compile(r"[가-힣A-Za-z0-9_]+")
SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
PII_PATTERNS = (
    re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)"),
    re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"),
)


@dataclass(frozen=True)
class ParsedSection:
    number: str
    title: str
    content: str


class SecurityScanner:
    def inspect(self, text: str) -> tuple[str, str]:
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            return "REJECTED_SECRET", text
        masked = text
        for pattern in PII_PATTERNS:
            masked = pattern.sub("[MASKED_PII]", masked)
        return ("MASKED_PII" if masked != text else "SAFE"), masked


class KoreanTokenizer:
    def tokenize(self, text: str) -> tuple[str, ...]:
        terms: list[str] = []
        for word in WORD_PATTERN.findall(text.lower()):
            terms.append(word)
            if any("가" <= char <= "힣" for char in word) and len(word) >= 2:
                terms.extend(word[index : index + 2] for index in range(len(word) - 1))
        return tuple(terms)


class MarkdownSectionParser:
    def parse(self, text: str) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        current_title = "문서 개요"
        current_number = "0"
        body: list[str] = []
        heading_count = 0

        for line in text.splitlines():
            match = HEADING_PATTERN.match(line)
            if match and len(match.group(1)) <= 3:
                if body and "\n".join(body).strip():
                    sections.append(ParsedSection(current_number, current_title, "\n".join(body).strip()))
                heading_count += 1
                current_title = match.group(2).strip()
                number_match = re.match(r"(\d+(?:\.\d+)*)[.)]?\s*(.*)", current_title)
                current_number = number_match.group(1) if number_match else str(heading_count)
                body = [line]
            else:
                body.append(line)

        if body and "\n".join(body).strip():
            sections.append(ParsedSection(current_number, current_title, "\n".join(body).strip()))
        return sections


class SectionChunker:
    def __init__(self, tokenizer: KoreanTokenizer, max_characters: int = 1600) -> None:
        self._tokenizer = tokenizer
        self._max_characters = max_characters

    def create_chunks(self, manual_id: str, sections: list[ParsedSection]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for section in sections:
            pieces = self._split(section.content)
            for index, content in enumerate(pieces, start=1):
                digest = hashlib.sha256(
                    f"{manual_id}|{section.number}|{index}|{content}".encode("utf-8")
                ).hexdigest()[:20]
                chunks.append(
                    Chunk(
                        chunk_id=digest,
                        manual_id=manual_id,
                        section_number=section.number,
                        section_title=section.title,
                        content=content,
                        token_terms=self._tokenizer.tokenize(content),
                    )
                )
        return chunks

    def _split(self, content: str) -> list[str]:
        if len(content) <= self._max_characters:
            return [content]
        blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
        pieces: list[str] = []
        current = ""
        for block in blocks:
            candidate = f"{current}\n\n{block}".strip()
            if current and len(candidate) > self._max_characters:
                pieces.append(current)
                current = block
            else:
                current = candidate
        if current:
            pieces.append(current)
        return pieces
