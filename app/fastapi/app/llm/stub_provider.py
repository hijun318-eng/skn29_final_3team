"""Stub LLM provider — 결정론적 mock 응답."""

from __future__ import annotations

import hashlib
import time

from app.llm.base import LLMProvider, LLMResponse

# mock 응답 템플릿 5종: prompt 해시 → 고정 매핑
_TEMPLATES: list[str] = [
    "합성 데이터 분석 결과: 조식 시간대 혼잡도가 평균 대비 {pct}% 높습니다.",
    "이슈 브리프: 객실 청소 지연이 객실 VOC {count}건과 상관관계가 있습니다.",
    "보고서 요약: 이번 주 주요 이슈는 조식 대기시간 증가와 객실 청소 지연입니다.",
    "검토 의견: 해당 시그널은 합성 시나리오의 정상 범위 내에 있습니다.",
    "근거 설명: 관측된 수치는 dataset_version gw-synthetic-1.0.0 기준입니다.",
]


def _pick_template(prompt: str) -> str:
    """prompt 해시로 결정론적 템플릿 선택."""
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    idx = int(digest[:8], 16) % len(_TEMPLATES)
    template = _TEMPLATES[idx]
    # 간단한 템플릿 치환
    seed = int(digest[8:16], 16)
    return template.format(pct=15 + (seed % 40), count=3 + (seed % 10))


class StubProvider(LLMProvider):
    """결정론적 mock 응답을 반환하는 stub provider."""

    MODEL_NAME: str = "stub-v1"

    async def complete(self, prompt: str, **kwargs: object) -> LLMResponse:
        start = time.monotonic()
        text = _pick_template(prompt)
        latency = (time.monotonic() - start) * 1000
        return LLMResponse(
            text=text,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            model_name=self.MODEL_NAME,
            latency_ms=round(latency, 2),
        )
