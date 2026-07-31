"""Versioned prompts with stable hashes for request tracing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256


@dataclass(frozen=True)
class PromptRecord:
    prompt_id: str
    version: str
    node: str
    environment: str
    model_profile: str
    adapter: str | None
    model_version: str
    text: str

    def metadata(self) -> dict[str, str | None]:
        result = asdict(self)
        result.pop("text")
        result["fixture_version"] = None
        result["hash"] = sha256(self.text.encode("utf-8")).hexdigest()
        return result


_PROMPTS = {
    "node1.normalize": PromptRecord(
        "node1.normalize",
        "PROMPT-v1.0.0",
        "node1",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "질문에서 intent, metric, dimension, 절대 기간 후보와 최소 재질문만 추출한다. "
        "자산·권한·Gate·SQL을 결정하지 않는다.",
    ),
    "node2.sql": PromptRecord(
        "node2.sql",
        "PROMPT-v1.0.0",
        "node2",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "승인 Context Package 안의 자산·컬럼·JOIN만 사용해 단일 read-only Trino SQL 후보를 만든다. "
        "실행과 정책 통과를 판정하지 않는다.",
    ),
    "node2.repair": PromptRecord(
        "node2.repair",
        "PROMPT-v1.0.0",
        "node2_repair",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "동일 Context와 정규화 오류 코드로 SQL을 한 번만 수정한다. "
        "원문 오류를 해석하거나 반복 호출하지 않는다.",
    ),
    "node3.explain": PromptRecord(
        "node3.explain",
        "PROMPT-v1.0.0",
        "node3",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "G3 pass shaped result의 조건·기간·단위·출처·제한만 설명한다. "
        "수치를 재계산하거나 원인을 단정하지 않는다.",
    ),
}


def get_prompt(prompt_id: str, environment: str = "development") -> PromptRecord:
    prompt = _PROMPTS[prompt_id]
    if prompt.environment != environment:
        raise KeyError(f"{prompt_id!r} is not registered for {environment!r}")
    return prompt


def list_prompt_metadata() -> list[dict[str, str | None]]:
    return [_PROMPTS[prompt_id].metadata() for prompt_id in sorted(_PROMPTS)]
