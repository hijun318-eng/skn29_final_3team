"""외부 의존성 port의 공개 비동기 계약을 정의한다."""

from __future__ import annotations

from typing import Any, Protocol


class ModelAdapter(Protocol):
    """모델 추론 기능만 노출하며 권한과 SQL 실행 결정은 허용하지 않는다."""

    async def generate(
        self,
        node: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """노드별 typed payload를 추론하고 active response 계약을 만족하는 mapping을 반환한다.

        구현체는 transport·timeout 오류를 숨겨 성공값으로 대체하지 않고 명시적 모델 예외로
        전달해야 한다.
        """
        ...

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다."""
        ...
