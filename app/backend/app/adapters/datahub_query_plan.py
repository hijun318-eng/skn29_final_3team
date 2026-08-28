"""사용자 질문을 DataHub Core 검색이 실제로 받을 수 있는 bounded query 계획으로 변환한다.

권위 있는 입력은 요청 원문과 호출자가 active release에서 투영한 승인 label·alias뿐이다.
이 모듈은 지표별 정적 사전을 소유하지 않는다. DataHub Core 검색은 자연어 전체 질의나
명시적 ``OR`` 문법의 동작을 API 계약으로 보장하지 않으므로, 언어 중립 변형과 release-bound
exact phrase 힌트만 bounded 계획으로 만든다. 각 변형은 예약문자를 escape해 DataHub query
문법 injection을 차단한다.

외부 경계: 이 모듈은 I/O를 하지 않는다. 생성한 문자열은 ``DataHubCatalogClient``가
``searchAcrossEntities`` 입력으로만 사용한다.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable

from app.adapters.query_search_evidence import unicode_tokens


# Lucene query_string이 연산자로 해석하는 문자 전체. escape하지 않으면 사용자 질문이
# field 지정(`urn:...`)이나 boolean 절로 승격돼 검색 범위를 벗어날 수 있다.
# Lucene의 boolean ampersand 연산자는 ``&&``이고 단일 ``&``는 업무 약어
#(``F&B``)의 실제 색인 문자다. tokenizer가 ``&&``를 보존하지 않으므로 단일 ``&``를
# 다시 escape해 검색 불능으로 만들지 않는다.
_RESERVED_CHARACTERS = frozenset('+-=|><!(){}[]^"~*?:\\/')
_MAX_TOKENS = 8
_MAX_VARIANTS = 3
_MAX_QUERY_CHARACTERS = 256
_MAX_QUESTION_CHARACTERS = 2048
_TERMINAL = ""
_BOOLEAN_OPERATOR_TOKENS = frozenset({"and", "or", "not"})


class DataHubQueryPlanError(ValueError):
    """질문에서 검색 가능한 token을 얻지 못해 bounded 계획을 만들 수 없음을 알린다."""


@dataclass(frozen=True)
class DataHubQueryVariant:
    """검색 요청 하나의 label과 escape된 질의를 불변으로 보존한다.

    ``label``은 관측용 식별자이며 사용자 원문을 포함하지 않는다. ``query``는 이미 escape가
    끝난 값이므로 호출자가 다시 가공하면 안 된다.
    """

    label: str
    query: str
    token_count: int


class GovernedPhraseIndex:
    """active release의 승인 문구를 질문 부분문자열 검색용 trie로 한 번 컴파일한다.

    매 질문마다 전체 Glossary를 순회하지 않도록 공백 보존형과 무공백 복합어형 trie를
    함께 만든다. 반환값은 후보 순위가 아니라 DataHub에 보낼 고정밀 query hint이며,
    최종 후보는 반드시 DataHub 반환 rank와 snapshot membership으로 다시 검증해야 한다.
    """

    def __init__(self, phrases: Iterable[str]) -> None:
        self._roots: tuple[dict[str, object], dict[str, object]] = ({}, {})
        self._phrase_tokens: dict[str, frozenset[str]] = {}
        seen: set[tuple[int, str]] = set()
        for raw_phrase in phrases:
            if not isinstance(raw_phrase, str) or not raw_phrase.strip():
                raise ValueError("governed search phrase must be non-empty text")
            normalized = _normalized_search_text(raw_phrase)
            self._phrase_tokens.setdefault(normalized, unicode_tokens(normalized))
            if len(normalized) > _MAX_QUERY_CHARACTERS:
                raise ValueError("governed search phrase exceeds the query bound")
            forms = (normalized, normalized.replace(" ", ""))
            for root_index, form in enumerate(forms):
                if not form or (root_index, form) in seen:
                    continue
                seen.add((root_index, form))
                node = self._roots[root_index]
                for character in form:
                    child = node.setdefault(character, {})
                    if not isinstance(child, dict):  # pragma: no cover - trie 불변식이다.
                        raise RuntimeError("governed phrase trie is corrupt")
                    node = child
                terminal = node.setdefault(_TERMINAL, [])
                if not isinstance(terminal, list):  # pragma: no cover - trie 불변식이다.
                    raise RuntimeError("governed phrase trie terminal is corrupt")
                terminal.append((normalized, form))

    def match(self, question: str, *, max_hints: int = 2) -> tuple[str, ...]:
        """질문에 실제로 포함된 가장 긴 승인 문구를 bounded DataHub hint로 반환한다.

        Latin 식별자는 ASCII 단어 경계를 강제해 ``ADR``이 ``address``에 매치되는 일을
        막는다. 한국어는 조사와 무공백 복합어가 이어질 수 있어 Unicode 전체 단어 경계를
        강제하지 않는다.
        """

        if max_hints < 1:
            raise ValueError("governed search hint bound must be positive")
        normalized = _normalized_search_text(question)
        if len(normalized) > _MAX_QUESTION_CHARACTERS:
            raise DataHubQueryPlanError("the request exceeds the question length bound")
        representations = (normalized, normalized.replace(" ", ""))
        matches: dict[str, tuple[int, int, str]] = {}
        for representation_rank, (text, root) in enumerate(
            zip(representations, self._roots, strict=True)
        ):
            for start in range(len(text)):
                node: dict[str, object] = root
                for end in range(start, min(len(text), start + _MAX_QUERY_CHARACTERS)):
                    child = node.get(text[end])
                    if not isinstance(child, dict):
                        break
                    node = child
                    terminal = node.get(_TERMINAL)
                    if not isinstance(terminal, list):
                        continue
                    for entry in terminal:
                        if (
                            not isinstance(entry, tuple)
                            or len(entry) != 2
                            or not all(isinstance(item, str) for item in entry)
                        ):  # pragma: no cover - trie 불변식이다.
                            continue
                        canonical, form = entry
                        if _requires_ascii_boundary(form) and not _ascii_boundaries(
                            text, start, end + 1
                        ):
                            continue
                        candidate = (representation_rank, -(end + 1 - start), form)
                        current = matches.get(canonical)
                        if current is None or candidate < current:
                            matches[canonical] = candidate
        exact = tuple(
            evidence[2]
            for _canonical, evidence in sorted(
                matches.items(), key=lambda item: (item[1][1], item[0])
            )[:max_hints]
        )
        if exact:
            return exact

        # Exact alias가 없는 자연어 표현은 phrase 전체를 무제한 scan하거나 업무별
        # synonym map을 두지 않는다. 미리 컴파일한 승인 phrase token과 질문 token 사이에
        # 독립적인 두 개 이상의 Unicode 부분-token 증거가 있을 때만 원래 승인 phrase를
        # bounded query hint로 사용한다. 예: ``식음료 순매출`` → ``식음료 매출``.
        question_tokens = unicode_tokens(normalized)
        fuzzy: list[tuple[int, int, str]] = []
        for phrase, phrase_tokens in self._phrase_tokens.items():
            related = sum(
                any(_related_unicode_token(token, candidate) for candidate in question_tokens)
                for token in phrase_tokens
            )
            if related >= 2:
                fuzzy.append((related, len(phrase.replace(" ", "")), phrase))
        return tuple(
            phrase
            for _score, _size, phrase in sorted(
                fuzzy,
                key=lambda item: (-item[0], -item[1], item[2]),
            )[:max_hints]
        )


def escape_search_text(value: str) -> str:
    """Lucene 예약문자를 backslash로 중화해 질문 문자열이 검색 문법으로 승격되지 못하게 한다."""

    return "".join(
        f"\\{character}" if character in _RESERVED_CHARACTERS else character
        for character in value
    )


def ordered_query_tokens(question: str, *, max_tokens: int = _MAX_TOKENS) -> tuple[str, ...]:
    """질문 어순을 유지한 채 NFKC·casefold 정규화 token을 상한까지 잘라 반환한다.

    모든 token이 한 글자인 입력은 닫되, 더 긴 문맥과 함께 나온 한 글자 업무 명사는 보존한다.
    """

    normalized = unicodedata.normalize("NFKC", question).casefold()
    if len(normalized) > _MAX_QUESTION_CHARACTERS:
        raise DataHubQueryPlanError("the request exceeds the question length bound")
    tokens: list[str] = []
    current: list[str] = []
    for index, character in enumerate(normalized):
        if unicodedata.category(character)[:1] in {"L", "N", "M"} or character == "_":
            current.append(character)
            continue
        # ``F&B``처럼 한 글자 구성요소를 ``&``로 잇는 업무 약어는 각 글자를
        # noise로 버리면 검색 증거가 사라진다. 양쪽이 실제 문자·숫자인 connector만
        # token 안에 보존하고, 최종 query에서는 예약문자로 escape한다.
        if (
            character == "&"
            and current
            and index + 1 < len(normalized)
            and unicodedata.category(normalized[index + 1])[:1] in {"L", "N", "M"}
        ):
            current.append(character)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    # 모든 token이 한 글자면 조사·단위 파편으로 간주해 닫는다. 반면 ``룸 매출``처럼
    # 더 긴 문맥 안의 한 글자 명사는 언어 중립적으로 보존해야 등록 alias를 잃지 않는다.
    if not any(len(token) > 1 for token in tokens):
        return ()
    return tuple(tokens)[:max_tokens]


def plan_search_queries(
    question: str,
    *,
    max_variants: int = _MAX_VARIANTS,
    max_tokens: int = _MAX_TOKENS,
    governed_phrases: tuple[str, ...] = (),
) -> tuple[DataHubQueryVariant, ...]:
    """질문 하나를 최대 ``max_variants``개의 DataHub 검색 질의로 계획한다.

    변형은 세 가지 언어 중립 전략만 사용한다.

    ``phrase``
        정규화된 전체 질문을 인용부호로 감싼 고정밀 질의다. 등록된 alias가 질문에
        그대로 들어있는 경우에만 맞고, 아니면 0건이므로 recall을 대신할 수 없다.
    ``tokens``
        예약문자가 제거된 token을 서버 소유 ``OR``로 결합하는 bounded fallback이다.
        사용자 입력이 boolean 연산자와 같을 때만 literal로 인용한다. DataHub GraphQL은
        이 query-string 의미를 공개 계약으로 보장하지 않으므로 exact governed hint가
        없을 때만 사용하며, 전환은 실제 Core benchmark를 통과해야 한다.
    ``compounds``
        인접 token을 붙인 복합어를 인용해 결합한다. 한국어의 띄어쓰기 차이를 특정 지표
        사전 없이 흡수하는 fallback이며 역시 API 보장이 아니라 측정 대상이다.

    반환 순서가 곧 요청 순서이며 호출자는 상한을 그대로 요청 수 상한으로 쓸 수 있다.
    ``DataHubQueryPlanError``는 검색 가능한 token이 하나도 없을 때만 발생한다.
    """

    if max_variants < 1 or max_tokens < 1:
        raise ValueError("query plan bounds must be positive")
    tokens = ordered_query_tokens(question, max_tokens=max_tokens)
    if not tokens:
        raise DataHubQueryPlanError("the request has no searchable tokens")
    # 조사가 붙은 token까지 함께 요구하면 색인된 원형을 놓치므로, 기존 runtime과 같은
    # 조사 분리 규칙으로 얻은 원형만 추가한다.
    stems = tuple(
        sorted(
            stem
            for stem in unicode_tokens(" ".join(tokens))
            if len(stem) > 1 and stem not in tokens
        )
    )[:max_tokens]
    phrase = " ".join(tokens)
    compounds = tuple(
        f"{first}{second}" for first, second in zip(tokens, tokens[1:])
    )[:max_tokens]
    planned: list[DataHubQueryVariant] = [
        DataHubQueryVariant(
            f"governed-{index}",
            f'"{escape_search_text(phrase)}"',
            max(1, len(ordered_query_tokens(phrase, max_tokens=max_tokens))),
        )
        for index, phrase in enumerate(governed_phrases, start=1)
        if isinstance(phrase, str) and phrase.strip()
    ]
    planned.append(
        DataHubQueryVariant("phrase", f'"{escape_search_text(phrase)}"', len(tokens))
    )
    # exact governed hint가 하나라도 있으면 해당 질의가 가장 강한 증거다. 같은 질문에
    # OR/compound 변형까지 모두 보내지 않고, 아직 hint로 포착되지 않은 표현을 위한 전체
    # phrase 한 건만 보조한다. hint가 없을 때만 언어 중립 fallback 변형을 모두 사용한다.
    if not governed_phrases:
        planned.append(
            DataHubQueryVariant(
                "tokens",
                _or_query((*tokens, *stems)),
                len(tokens) + len(stems),
            )
        )
    if compounds and not governed_phrases:
        planned.append(
            DataHubQueryVariant("compounds", _or_query(compounds), len(compounds))
        )
    seen: set[str] = set()
    result: list[DataHubQueryVariant] = []
    for variant in planned:
        if variant.query in seen or len(variant.query) > _MAX_QUERY_CHARACTERS:
            continue
        seen.add(variant.query)
        result.append(variant)
        if len(result) == max_variants:
            break
    if not result:
        raise DataHubQueryPlanError("the request exceeds the DataHub query plan bounds")
    return tuple(result)


def _or_query(values: tuple[str, ...]) -> str:
    # tokenizer가 field·wildcard·grouping 문자를 이미 제거했으므로 일반 token은 DataHub
    # Core의 analyzed lexical 검색에 그대로 전달한다. 사용자 token 자체가 boolean
    # 연산자일 때만 literal phrase로 묶고, 절 사이의 대문자 OR만 서버가 소유한다.
    return " OR ".join(
        (
            f'"{escape_search_text(value)}"'
            if value.casefold() in _BOOLEAN_OPERATOR_TOKENS
            else escape_search_text(value)
        )
        for value in values
    )


def _normalized_search_text(value: str) -> str:
    """trie와 query planner가 공유하는 NFKC·casefold·공백 정규형을 만든다."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _requires_ascii_boundary(value: str) -> bool:
    """ASCII 업무 식별자만 더 긴 영문 단어 내부 매치를 금지한다."""

    return bool(value) and all(
        ord(character) < 128
        for character in value
        if not character.isspace()
    )


def _ascii_boundaries(value: str, start: int, end: int) -> bool:
    """부분문자열 앞뒤가 ASCII 문자·숫자·underscore가 아닌지 확인한다."""

    def is_word(character: str) -> bool:
        return ord(character) < 128 and (character.isalnum() or character == "_")

    return (start == 0 or not is_word(value[start - 1])) and (
        end == len(value) or not is_word(value[end])
    )


def _related_unicode_token(left: str, right: str) -> bool:
    """두 token의 exact 또는 안전한 비-ASCII 부분어 관계만 fuzzy hint 증거로 인정한다."""

    if left == right:
        return True
    if min(len(left), len(right)) < 2:
        return False
    # ASCII 식별자의 부분문자열은 ADR/address 같은 오탐을 만들므로 exact만 허용한다.
    if all(ord(character) < 128 for character in (*left, *right)):
        return False
    common_prefix = 0
    for first, second in zip(left, right):
        if first != second:
            break
        common_prefix += 1
    return left in right or right in left or common_prefix >= 2
