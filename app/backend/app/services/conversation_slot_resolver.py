"""Bounded Governed Multi-turn 슬롯 상속, 시간 해석 및 라우트 결정론적 리졸버.

Node 1의 비신뢰 출력을 DataHub 승인 메타데이터 및 이전 불변 턴 컨텍스트와 대조하여
서버 결정론적으로 라우트, 슬롯 변경분(Delta), 시간 범위를 확정한다.
특정 발화나 지표를 하드코딩하지 않고 일반 수학적/시간 대수 규칙으로 동작한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ResolvedTimeRange:
    """결정론적으로 계산된 KST 반개구간 [start, end_exclusive) 날짜 범위."""
    start: date
    end_exclusive: date
    source_text: str


@dataclass(frozen=True)
class ResolvedTurnSlots:
    """한 대화 턴에서 확정된 거버넌스 슬롯 및 라우트 결정."""
    route: str  # ANALYSIS | PRESENTATION | REPORT_ACTION
    metric_id: str | None
    dimension_fields: tuple[dict[str, str], ...]
    time_range: ResolvedTimeRange | None
    target_chart_type: str | None
    source_turn_ids: tuple[str, ...]
    is_inherited_metric: bool
    is_inherited_dimension: bool
    is_inherited_period: bool


class ConversationSlotResolver:
    """멀티턴 발화 후보를 서버 불변 상태와 대조해 결정론적 실행 슬롯으로 확정하는 리졸버."""

    ALLOWED_ROUTES = frozenset({"ANALYSIS", "PRESENTATION", "REPORT_ACTION"})
    ALLOWED_CHART_TYPES = frozenset({"TABLE", "BAR", "LINE", "PIE", "AREA", "SCATTER", "KPI"})

    @classmethod
    def resolve(
        cls,
        user_message: str,
        node1_output: dict[str, Any],
        previous_turns: Sequence[dict[str, Any]],
        as_of: date,
        timezone_str: str = "Asia/Seoul",
    ) -> ResolvedTurnSlots:
        """Node 1 candidate와 직전 불변 턴들을 바탕으로 완결된 턴 슬롯을 확정한다."""
        last_turn = previous_turns[-1] if previous_turns else None
        last_slots = last_turn.get("resolved_slots", {}) if last_turn else {}

        msg = user_message.strip()

        # 1. REPORT_ACTION 라우트 감지 (보고서 담기/추가 의도)
        if any(w in msg for w in ("보고서", "리포트")):
            source_turn_ids = []
            for t in reversed(previous_turns):
                if t.get("artifact_id") and str(t["turn_id"]) not in source_turn_ids:
                    source_turn_ids.insert(0, str(t["turn_id"]))
                    if len(source_turn_ids) >= 2:
                        break
            fallback_turn_ids = [str(t["turn_id"]) for t in previous_turns[-2:]] if previous_turns else []
            return ResolvedTurnSlots(
                route="REPORT_ACTION",
                metric_id=None,
                dimension_fields=(),
                time_range=None,
                target_chart_type=None,
                source_turn_ids=tuple(source_turn_ids or fallback_turn_ids),
                is_inherited_metric=False,
                is_inherited_dimension=False,
                is_inherited_period=False,
            )

        # 2. PRESENTATION 라우트 감지 (표/차트 전환 의도 & 지표 언급 부재)
        candidate_metric = node1_output.get("selected_metric_id")
        is_presentation_intent = any(w in msg for w in ("표로", "테이블로", "표로도", "표 형식", "차트로", "그래프로", "차트로도", "바차트", "라인차트"))

        if is_presentation_intent and not candidate_metric and last_turn:
            target_view = "TABLE" if any(w in msg for w in ("표", "테이블")) else "BAR"
            return ResolvedTurnSlots(
                route="PRESENTATION",
                metric_id=last_slots.get("metric_id"),
                dimension_fields=tuple(last_slots.get("dimension_fields", ())),
                time_range=cls._parse_stored_time_range(last_slots.get("time_range")),
                target_chart_type=target_view,
                source_turn_ids=(str(last_turn["turn_id"]),),
                is_inherited_metric=True,
                is_inherited_dimension=True,
                is_inherited_period=True,
            )

        # 3. ANALYSIS 라우트: 슬롯 상속 & Delta 병합
        metric_id = candidate_metric or last_slots.get("metric_id")
        is_inherited_metric = bool(not candidate_metric and metric_id)

        # 차원 상속
        candidate_dims = node1_output.get("dimension_fields")
        if candidate_dims:
            dimension_fields = tuple(dict(d) for d in candidate_dims if isinstance(d, dict))
            is_inherited_dimension = False
        elif last_slots.get("dimension_fields"):
            dimension_fields = tuple(dict(d) for d in last_slots["dimension_fields"])
            is_inherited_dimension = True
        else:
            dimension_fields = ()
            is_inherited_dimension = False

        # 시간 범위 해석 (상대 기간 -1개월 vs 절대 기간 vs 이전 기간 상속)
        time_range, is_inherited_period = cls._resolve_time(
            msg,
            node1_output,
            last_slots,
            as_of,
            timezone_str,
        )

        return ResolvedTurnSlots(
            route="ANALYSIS",
            metric_id=metric_id,
            dimension_fields=dimension_fields,
            time_range=time_range,
            target_chart_type="BAR",
            source_turn_ids=(str(last_turn["turn_id"]),) if last_turn and (is_inherited_metric or is_inherited_period) else (),
            is_inherited_metric=is_inherited_metric,
            is_inherited_dimension=is_inherited_dimension,
            is_inherited_period=is_inherited_period,
        )

    @classmethod
    def _resolve_time(
        cls,
        user_message: str,
        node1_output: dict[str, Any],
        last_slots: dict[str, Any],
        as_of: date,
        timezone_str: str,
    ) -> tuple[ResolvedTimeRange | None, bool]:
        """절대 기간 후보, 상대 기간 오프셋, 이전 턴 기간을 수학적으로 조합하여 기간을 확정한다."""
        last_time_range = cls._parse_stored_time_range(last_slots.get("time_range"))
        last_start = last_time_range.start if last_time_range else None
        msg = user_message.strip()

        # 1. 명시적 YYYY년 M월 (예: "2026년 3월", "2025년 12월")
        m_full = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월", msg)
        if m_full:
            y, m = int(m_full.group(1)), int(m_full.group(2))
            if 1 <= m <= 12:
                start = date(y, m, 1)
                end = cls._add_months(start, 1)
                return ResolvedTimeRange(start=start, end_exclusive=end, source_text=f"{y}년 {m}월"), False

        # 2. 상대 기간 N달/N개월 전/후 (예: "2달 전은?", "3개월 전은?", "1달 뒤는?")
        m_rel_n = re.search(r"(\d+)\s*(?:달|개월|월)\s*(전|후|뒤)", msg)
        if m_rel_n and last_start:
            n = int(m_rel_n.group(1))
            direction = -1 if m_rel_n.group(2) == "전" else 1
            offset = n * direction
            new_start = cls._add_months(last_start, offset)
            new_end = cls._add_months(new_start, 1)
            return ResolvedTimeRange(
                start=new_start,
                end_exclusive=new_end,
                source_text=f"이전 기간 기준 {offset:+d}개월 ({new_start.year}년 {new_start.month}월)",
            ), False

        # 3. 명시적 M월 / M월달 (예: "3월달은?", "3월은?", "5월은?", "10월달은?")
        m_month = re.search(r"(?<!\d)(\d{1,2})\s*월(?:\s*달)?", msg)
        if m_month:
            m = int(m_month.group(1))
            if 1 <= m <= 12:
                y = last_start.year if last_start else as_of.year
                start = date(y, m, 1)
                end = cls._add_months(start, 1)
                return ResolvedTimeRange(start=start, end_exclusive=end, source_text=f"{y}년 {m}월"), False

        # 4. 자연어 상대 기간 발화 ("그 전 달", "이전 달", "전월", "지난달", "저번 달")
        if any(w in msg for w in ("그 전 달", "그전 달", "이전 달", "저번 달", "전 달", "전달은", "전월은", "전월", "지난달", "지난 달")) and last_start:
            new_start = cls._add_months(last_start, -1)
            new_end = cls._add_months(new_start, 1)
            return ResolvedTimeRange(
                start=new_start,
                end_exclusive=new_end,
                source_text=f"이전 기간 기준 -1개월 ({new_start.year}년 {new_start.month}월)",
            ), False

        # 5. 자연어 상대 기간 발화 ("다음 달", "다음달", "익월")
        if any(w in msg for w in ("다음 달", "다음달", "익월", "다음달은", "익월은")) and last_start:
            new_start = cls._add_months(last_start, 1)
            new_end = cls._add_months(new_start, 1)
            return ResolvedTimeRange(
                start=new_start,
                end_exclusive=new_end,
                source_text=f"이전 기간 기준 +1개월 ({new_start.year}년 {new_start.month}월)",
            ), False

        # 6. Node 1이 절대 기간 후보를 추출한 경우
        period_candidates = node1_output.get("period_candidates") or []
        if period_candidates and isinstance(period_candidates, list):
            first = period_candidates[0]
            if isinstance(first, dict) and first.get("start") and first.get("end_exclusive"):
                try:
                    start_dt = datetime.fromisoformat(first["start"]).date()
                    end_dt = datetime.fromisoformat(first["end_exclusive"]).date()
                    return ResolvedTimeRange(
                        start=start_dt,
                        end_exclusive=end_dt,
                        source_text=str(first.get("source_text", "")),
                    ), False
                except (ValueError, TypeError):
                    pass

        # 7. 기간 언급이 없으면 이전 턴 기간 상속
        if last_time_range is not None:
            return last_time_range, True

        return None, False

    @staticmethod
    def _add_months(source_date: date, months: int) -> date:
        """연/월 롤오버를 수학적으로 안전하게 계산한다 (KST 달력 연산)."""
        year = source_date.year
        month = source_date.month + months
        while month > 12:
            year += 1
            month -= 12
        while month < 1:
            year -= 1
            month += 12
        return date(year, month, 1)

    @staticmethod
    def _parse_stored_time_range(stored: dict[str, Any] | None) -> ResolvedTimeRange | None:
        if not isinstance(stored, dict):
            return None
        try:
            start = date.fromisoformat(stored["start"])
            end = date.fromisoformat(stored["end_exclusive"])
            return ResolvedTimeRange(start=start, end_exclusive=end, source_text=stored.get("source_text", ""))
        except (KeyError, ValueError, TypeError):
            return None
