"""대화 턴의 분석 기간을 확정하는 시간 대수(Time Algebra) 모듈.

[권위 경계]
질문 문장의 시간 표현 해석은 Node 1(LLM)이 소유한다. Node 1은 `as_of`·`timezone`·
`calendar_id`와 직전 턴 기간 앵커(`previous_period`)를 권위 시간 컨텍스트로 받아
반개구간 [start, end_exclusive) RFC 3339 `period_candidates`를 반환한다. 그 결과는 이
모듈에 도달하기 전에 `app.services.context.metric_resolver._model_periods`가 타임존
일치·start<end·source_text 존재를 이미 검증한다. 이 모듈은 검증된 후보를 **재해석하지
않고 확정**하며, 문장을 다시 파싱하지 않는다.

[문장 파싱을 두지 않는 이유]
"그 전 달"처럼 앵커가 직전 기간인 표현도 `previous_period`를 함께 받은 Node 1이 해석한다.
서버가 같은 표현을 별도 어휘로 다시 파싱하면 승인된 해석을 덮어쓰고, 동의어·오타·새로운
표현이 나올 때마다 사전을 고쳐야 한다.

[해석 실패 시]
기간을 확정하지 못하면 임의의 기본 기간을 합성하지 않고 ``None``을 반환한다. 상위
`metric_resolver`가 `PERIOD_REQUIRED` typed error와 재질의 선택지로 닫는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class ResolvedTimeRange:
    """확정된 KST 기준 반개구간 [start, end_exclusive) 날짜 범위.

    Attributes:
        start: 시작 일자 (이상, inclusive)
        end_exclusive: 종료 일자 (미만, exclusive)
        source_text: 기간의 근거가 된 질문 내 연속 구간 표현
    """

    start: date
    end_exclusive: date
    source_text: str


class TimeAlgebraEngine:
    """[책임] 질문의 시간 표현 후보를 검증하고 직전 턴 상속 여부와 영업일 기준 KST 기간을 확정하는 시간 대수 엔진.
    - 입출력: Node 1 출력 후보, 직전 턴 기간, 기준일 as_of 수신 → 확정된 ResolvedTimeRange 및 상속 플래그 반환
    - 주의조건: 기간 미특정 시 임의 기본값을 합성하지 않고 None을 반환하여 상위의 PERIOD_REQUIRED 재질의 유도
    """

    @classmethod
    def resolve_time(
        cls,
        user_message: str,
        node1_output: dict[str, Any],
        last_time_range: ResolvedTimeRange | None,
        as_of: date,
    ) -> tuple[ResolvedTimeRange | None, bool]:
        """[책임] Node 1 해석 후보 또는 직전 턴 상속 여부를 판단하여 이번 턴의 KST 반개구간 기간을 확정한다.
        - 입출력: user_message, node1_output, last_time_range, as_of 수신 → (ResolvedTimeRange | None, 상속여부) 튜플 반환
        - 주의조건: 기간 미특정 시 임의 기본값을 합성하지 않고 None을 반환하여 상위의 PERIOD_REQUIRED 재질의 유도
        """
        candidate = cls._first_valid_candidate(node1_output.get("period_candidates"))
        if candidate is not None:
            return cls.complete_data_range(candidate, as_of), False

        if last_time_range is not None:
            return cls.complete_data_range(last_time_range, as_of), True

        return None, False

    @classmethod
    def resolve_comparison_time(
        cls,
        node1_output: dict[str, Any],
        as_of: date,
    ) -> ResolvedTimeRange | None:
        """[책임] 명시적 2개 기간 비교 질의에서 두 번째 비교 대상 반개구간 [start, end)을 확정한다.
        - 입출력: node1_output 및 기준일 as_of 수신 → 두 번째 비교 대상 ResolvedTimeRange 반환 (비교 아닐 시 None)
        - 주의조건: period_relationship이 comparison이 아니거나 유효 후보가 2개가 아니면 None을 반환
        """
        if node1_output.get("period_relationship") != "comparison":
            return None
        candidates = cls._valid_candidates(node1_output.get("period_candidates"))
        if len(candidates) != 2:
            return None
        return cls.complete_data_range(candidates[1], as_of)

    @staticmethod
    def complete_data_range(
        resolved: ResolvedTimeRange,
        as_of: date,
    ) -> ResolvedTimeRange:
        """[책임] 완료된 영업일 기준 데이터만 공개하도록 진행 중인 기간을 as_of 기준일 미만으로 클램핑한다.
        - 입출력: 확정된 ResolvedTimeRange 및 기준일 as_of 수신 → 종료일이 as_of로 제한된 ResolvedTimeRange 반환
        - 주의조건: start < as_of < end_exclusive인 경우에만 end_exclusive를 as_of로 절단하며 과거 기간은 불변 유지
        """

        if resolved.start < as_of < resolved.end_exclusive:
            return ResolvedTimeRange(
                start=resolved.start,
                end_exclusive=as_of,
                source_text=resolved.source_text,
            )
        return resolved

    @classmethod
    def _first_valid_candidate(cls, candidates: object) -> ResolvedTimeRange | None:
        """Node 1 기간 후보 중 반개구간 규칙을 만족하는 첫 항목을 반환합니다.

        상류에서 이미 검증된 후보를 받지만, 멀티턴 fast-path는 타임존 없는 날짜 문자열을
        싣기 때문에 두 형태를 모두 수용하되 start < end_exclusive 불변식은 여기서도 다시
        확인한다. 형식이 깨진 후보만 건너뛰고, 쓸 수 있는 후보가 하나도 없으면 ``None``을
        반환해 상위 단계가 상속 또는 미확정으로 닫도록 한다.

        Args:
            candidates: Node 1 ``period_candidates`` 값(비리스트면 후보 없음으로 처리)

        Returns:
            확정 가능한 첫 기간 또는 None
        """
        values = cls._valid_candidates(candidates)
        return values[0] if values else None

    @classmethod
    def _valid_candidates(cls, candidates: object) -> tuple[ResolvedTimeRange, ...]:
        """형식과 반개구간 불변식을 만족하는 typed 기간 후보를 순서대로 반환한다."""

        if not isinstance(candidates, list):
            return ()
        values: list[ResolvedTimeRange] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            try:
                start = datetime.fromisoformat(str(candidate["start"])).date()
                end_exclusive = datetime.fromisoformat(str(candidate["end_exclusive"])).date()
            except (KeyError, TypeError, ValueError):
                continue
            if start >= end_exclusive:
                continue
            values.append(
                ResolvedTimeRange(
                    start=start,
                    end_exclusive=end_exclusive,
                    source_text=str(candidate.get("source_text") or ""),
                )
            )
        return tuple(values)

    @staticmethod
    def add_months(dt: date, months: int) -> date:
        """연도 롤오버를 반영해 N개월 이동한 달의 1일을 반환합니다.

        기간 해석에는 사용하지 않으며, 캘린더 경계 계산이 필요한 호출자를 위한 순수 함수다.

        Args:
            dt: 기준 날짜
            months: 가감할 개월 수(음수 허용)

        Returns:
            계산된 연/월의 1일
        """
        total = dt.month + months
        return date(dt.year + ((total - 1) // 12), ((total - 1) % 12) + 1, 1)
