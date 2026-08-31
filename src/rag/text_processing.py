"""로컬 Markdown 검증 corpus의 보안 검사·한글 토큰화·절 단위 청킹을 수행한다."""

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
    """Markdown 제목에서 얻은 절 번호·제목과 해당 절 원문을 함께 보존한다."""

    number: str
    title: str
    content: str


class SecurityScanner:
    """텍스트의 비밀값 노출은 거부하고 주민번호·전화번호는 마스킹한다."""

    def inspect(self, text: str) -> tuple[str, str]:
        """보안 상태와 안전한 텍스트를 반환하며 비밀 패턴은 원문과 함께 거부 표시한다."""

        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            return "REJECTED_SECRET", text
        masked = text
        for pattern in PII_PATTERNS:
            masked = pattern.sub("[MASKED_PII]", masked)
        return ("MASKED_PII" if masked != text else "SAFE"), masked


class KoreanTokenizer:
    """검색용 영숫자·한글 단어와 한글 2-gram을 결정론적으로 생성한다."""

    def tokenize(self, text: str) -> tuple[str, ...]:
        """문자열을 소문자 단어 토큰과 한글 연속 2글자 토큰의 순서열로 변환한다."""

        terms: list[str] = []
        for word in WORD_PATTERN.findall(text.lower()):
            terms.append(word)
            if any("가" <= char <= "힣" for char in word) and len(word) >= 2:
                terms.extend(word[index : index + 2] for index in range(len(word) - 1))
        return tuple(terms)


class MarkdownSectionParser:
    """Markdown 1~3단계 제목을 경계로 본문을 검색 가능한 절 목록으로 나눈다."""

    def parse(self, text: str) -> list[ParsedSection]:
        """문서 순서를 유지한 절을 반환하고 명시 번호가 없으면 제목 등장 순번을 부여한다."""

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
    """절 본문을 빈 줄 블록 경계에서 묶고 내용 기반 식별자를 가진 청크로 변환한다.

    하나의 분리 불가능한 블록이 문자 한도를 넘는 경우에는 내용 손실을 피하기 위해
    해당 블록을 그대로 유지한다.
    """

    def __init__(self, tokenizer: KoreanTokenizer, max_characters: int = 1600) -> None:
        self._tokenizer = tokenizer
        self._max_characters = max_characters

    def create_chunks(self, manual_id: str, sections: list[ParsedSection]) -> list[Chunk]:
        """매뉴얼 식별자와 절 내용을 해시해 안정적인 식별자·검색 토큰을 가진 청크를 만든다."""

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
