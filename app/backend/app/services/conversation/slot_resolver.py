"""멀티턴 대화의 슬롯 상속 및 라우트 결정론적 리졸버 모듈.

[핵심 설계 원칙]
1. 비신뢰 LLM 출력 통제: Node 1(LLM)이 추출한 후보를 맹신하지 않고, DataHub 승인 메타데이터와
   이전 대화 턴의 불변 상태를 대조하여 서버 사이드에서 결정론적으로 라우트와 슬롯(지표/차원/필터/기간)을 확정합니다.
2. 3대 라우트 분류:
   - ANALYSIS: 새로운 데이터 집계/조회 쿼리가 필요한 분석 라우트 (슬롯 Delta 연산 적용)
   - PRESENTATION: 동일한 쿼리 결과 스냅샷을 다른 시각화 형태(차트/테이블/뷰)로 즉시 전환
   - REPORT_ACTION: 분석 결과를 공식 보고서 초안(Draft)으로 컴파일하여 저장
3. 모호성 해소(Disambiguation): 질문이 여러 지표/기간으로 해석될 때 사용자에게 선택지를 제시하고,
   선택 발화("1번", "객실 점유율" 등)를 번호/정확도/포함관계 규칙으로 즉각 매칭합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from app.services.conversation.change_set import (
    AnalysisChangeSet,
    apply_dimension_changes,
    apply_metric_change,
    derive_dimension_changes,
    derive_metric_change,
)
from app.services.conversation.time_algebra import ResolvedTimeRange, TimeAlgebraEngine

__all__ = [
    "ResolvedTimeRange",
    "TimeAlgebraEngine",
    "ResolvedTurnSlots",
    "ConversationSlotResolver",
]


@dataclass(frozen=True)
class ResolvedTurnSlots:
    """대화의 단일 턴에서 확정된 거버넌스 슬롯 및 라우트 결정 데이터 클래스.

    Attributes:
        route: 실행할 3대 라우트 ('ANALYSIS' | 'PRESENTATION' | 'REPORT_ACTION')
        metric_id: 확정된 분석 지표 ID (PRESENTATION/ANALYSIS 시)
        dimension_fields: 그룹화 차원 필드 튜플 (예: [{'asset_fqn': '...', 'column': 'hotel_id'}])
        user_filters: 사용자 지정 필터 튜플 (예: [{'asset_fqn': '...', 'column': 'hotel_name', 'operator': '=', 'value_text': '비스타'}])
        time_range: 확정된 반개구간 [start, end_exclusive) 기간 범위
        target_chart_type: 목표 뷰/시각화 타입 ('SUMMARY', 'TABLE', 'BAR', 'LINE', 'PIE' 등)
        source_turn_ids: 이번 턴 결정에 영향을 준 이전 참조 턴 ID 목록
        is_inherited_metric: 지표가 이전 턴에서 상속되었는지 여부
        is_inherited_dimension: 차원이 이전 턴에서 상속되었는지 여부
        is_inherited_period: 기간이 이전 턴에서 상속되었는지 여부
        change_set: 이번 턴에 적용된 typed 슬롯 변경 연산 목록 (ChangeSet)
    """

    route: str
    metric_id: str | None
    dimension_fields: tuple[dict[str, str], ...]
    user_filters: tuple[dict[str, str], ...]
    time_range: ResolvedTimeRange | None
    target_chart_type: str | None
    source_turn_ids: tuple[str, ...]
    is_inherited_metric: bool
    is_inherited_dimension: bool
    is_inherited_period: bool
    change_set: AnalysisChangeSet = ()


class ConversationSlotResolver:
    """멀티턴 대화 슬롯 해석 및 라우트 결정 상태 머신."""

    ALLOWED_CHART_TYPES = ("SUMMARY", "TABLE", "BAR", "LINE", "PIE", "HORIZONTAL_BAR", "DONUT")
    CHART_CYCLE_ALLOWLIST = ("BAR", "LINE", "HORIZONTAL_BAR")
    CONVERSATION_ROUTES = ("ANALYSIS", "PRESENTATION", "REPORT_ACTION")

    @classmethod
    def match_disambiguation_option(
        cls,
        user_message: str,
        options: Sequence[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """사용자의 선택 발화가 모호성 해소 후보(지표/기간 목록) 중 어느 항목에 해당하는지 매칭합니다.

        [매칭 알고리즘 단계]
        1. 완전 일치 (Exact match): value, metric_id, label과 대소문자 무관 완전 일치
        2. 서수 선택 (Ordinal match): 발화 맨 앞 정수를 선택지 순번으로 읽는다. 조사·수량사
           종류는 열거하지 않으며, 뒤에 다른 숫자가 오면 순번으로 보지 않는다.
        3. 부분 문자열 포함 (Substring/Token match): label이나 metric_id가 발화에 포함된 경우
        4. 기간 범위 일치 (Period range match): 시작일/종료일 또는 기간 텍스트 매칭

        Args:
            user_message: 사용자가 입력한 선택 발화
            options: 이전 턴에서 제시되었던 모호성 해소 후보 리스트

        Returns:
            매칭된 옵션 딕셔너리 (없으면 None)
        """
        if not options:
            return None
        msg = user_message.strip()
        msg_lower = msg.lower()

        # 1. 완전 일치 (value, metric_id, label)
        for opt in options:
            val = str(opt.get("value") or "").strip()
            mid = str(opt.get("metric_id") or "").strip()
            label = str(opt.get("label") or "").strip()
            if msg in (val, mid, label) or msg_lower in (val.lower(), mid.lower(), label.lower()):
                return opt

        # 2. 서수 선택 매칭. 선택지는 서버가 번호를 붙여 제시했으므로 발화 맨 앞의 정수만
        #    읽고 뒤따르는 조사·수량사는 종류를 열거하지 않는다. 한국어 단어 목록을 두면
        #    표현이 늘 때마다 사전을 고쳐야 하고, 그 자체가 문구 기반 분기가 된다.
        leading_digits = ""
        for character in msg:
            if not character.isdigit():
                break
            leading_digits += character
        if leading_digits and not any(character.isdigit() for character in msg[len(leading_digits):]):
            index = int(leading_digits) - 1
            if 0 <= index < len(options):
                return options[index]

        # 3. 부분 문자열 및 토큰 포함 매칭
        for opt in options:
            label = str(opt.get("label") or "").strip()
            mid = str(opt.get("metric_id") or "").strip()
            if label and (label in msg or msg in label):
                return opt
            if mid and mid.lower() in msg_lower:
                return opt

        # 4. 기간 범위 매칭 (ISO 날짜 문자열 포함 여부)
        for opt in options:
            if opt.get("clarification_type") == "period" or opt.get("period_start"):
                p_start = str(opt.get("period_start") or "")
                p_end = str(opt.get("period_end_exclusive") or "")
                if p_start in msg and (p_end in msg or not p_end):
                    return opt

        return None

    @classmethod
    def resolve(
        cls,
        user_message: str,
        node1_output: dict[str, Any],
        previous_turns: Sequence[dict[str, Any]],
        as_of: date | None = None,
        timezone_str: str = "Asia/Seoul",
    ) -> ResolvedTurnSlots:
        """대화 기록(히스토리)과 Node 1의 출력을 대조하여 이번 턴의 슬롯과 라우트를 결정론적으로 확정합니다.

        [처리 단계]
        0. Disambiguation 선택 처리: 이전 턴이 모호성 해소 대기 상태였는지 확인
        1. REPORT_ACTION 감지: "보고서에 담아줘", "리포트 생성" 등 의도 분석
        2. PRESENTATION 감지: "차트로 보여줘", "표로 바꿔줘" 등 쿼리 재실행 없는 뷰 전환 의도 분석
        3. ANALYSIS 슬롯 상속 & ChangeSet 적용: 단답형 후속 질의 여부를 판정하고 5대 연산으로 슬롯 확정

        Args:
            user_message: 사용자의 입력 발화
            node1_output: LLM Node 1의 분석 결과 딕셔너리
            previous_turns: 이전 턴들의 데이터 목록
            as_of: 기준 일자 (생략 시 오늘)
            timezone_str: 타임존 (기본 'Asia/Seoul')

        Returns:
            확정된 ResolvedTurnSlots 객체
        """
        msg = user_message.strip()
        as_of_date = as_of or date.today()

        last_turn = previous_turns[-1] if previous_turns else None
        last_slots = last_turn.get("resolved_slots", {}) if last_turn else {}
        last_chart_type = (last_slots.get("target_chart_type") or "SUMMARY").upper()

        # 이전 ANALYSIS 턴 역추적 (중간에 PRESENTATION/CLARIFICATION 턴이 끼어 있어도 원천 분석 지표/차원 보존)
        last_analysis = next((t for t in reversed(previous_turns) if t.get("route") == "ANALYSIS"), None)
        last_analysis_slots = last_analysis.get("resolved_slots", {}) if last_analysis else {}

        # -------------------------------------------------------------
        # 0. Disambiguation 후속 선택 처리
        # -------------------------------------------------------------
        if last_slots.get("ambiguity_status") == "NEEDS_CLARIFICATION":
            options = last_slots.get("disambiguation_options", [])
            pending_metric = last_slots.get("metric_id")
            pending_time = last_slots.get("time_range")
            pending_dimensions = tuple(
                last_slots.get("dimension_fields")
                or last_analysis_slots.get("dimension_fields", ())
            )
            pending_filters = tuple(
                last_slots.get("user_filters")
                or last_analysis_slots.get("user_filters", ())
            )
            opt_type = last_slots.get("clarification_type") or "metric"
            matched_option = cls.match_disambiguation_option(msg, options)

            if matched_option:
                if opt_type == "metric" or matched_option.get("metric_id"):
                    resolved_metric = matched_option.get("metric_id") or matched_option.get("value")
                    time_range, is_inherited_period = TimeAlgebraEngine.resolve_time(
                        user_message=last_slots.get("pending_user_message") or msg,
                        node1_output=node1_output,
                        last_time_range=cls._parse_stored_time_range(pending_time),
                        as_of=as_of_date,
                    )
                    target_chart_type = cls._resolve_initial_chart_type(msg, node1_output)
                    return ResolvedTurnSlots(
                        route="ANALYSIS",
                        metric_id=resolved_metric,
                        dimension_fields=pending_dimensions,
                        user_filters=pending_filters,
                        time_range=time_range,
                        target_chart_type=target_chart_type,
                        source_turn_ids=(str(last_turn["turn_id"]),) if last_turn else (),
                        is_inherited_metric=False,
                        is_inherited_dimension=True if last_analysis_slots.get("dimension_fields") else False,
                        is_inherited_period=is_inherited_period,
                    )
                elif opt_type == "period" or matched_option.get("period_start"):
                    p_start = date.fromisoformat(matched_option["period_start"])
                    p_end = date.fromisoformat(matched_option["period_end_exclusive"])
                    time_range = ResolvedTimeRange(
                        start=p_start,
                        end_exclusive=p_end,
                        source_text=matched_option.get("label", f"{p_start} ~ {p_end}"),
                    )
                    resolved_metric = node1_output.get("selected_metric_id") or pending_metric or last_analysis_slots.get("metric_id")
                    target_chart_type = cls._resolve_initial_chart_type(msg, node1_output)
                    return ResolvedTurnSlots(
                        route="ANALYSIS",
                        metric_id=resolved_metric,
                        dimension_fields=pending_dimensions,
                        user_filters=pending_filters,
                        time_range=time_range,
                        target_chart_type=target_chart_type,
                        source_turn_ids=(str(last_turn["turn_id"]),) if last_turn else (),
                        is_inherited_metric=True if not node1_output.get("selected_metric_id") and resolved_metric else False,
                        is_inherited_dimension=True if last_analysis_slots.get("dimension_fields") else False,
                        is_inherited_period=False,
                    )

        # -------------------------------------------------------------
        # 1. REPORT_ACTION 라우트 감지 (보고서 담기/추가 서술어 의도)
        # -------------------------------------------------------------
        # Node1이 제시한 route는 후보다. 서버는 계약 enum 안의 값만 받아들이고, 각
        # 라우트가 요구하는 선행 상태(재사용할 Artifact 등)를 아래에서 다시 확인한다.
        requested_route = node1_output.get("requested_route")
        if requested_route not in cls.CONVERSATION_ROUTES:
            requested_route = None

        if requested_route == "REPORT_ACTION":
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
                user_filters=(),
                time_range=None,
                target_chart_type=None,
                source_turn_ids=tuple(source_turn_ids or fallback_turn_ids),
                is_inherited_metric=False,
                is_inherited_dimension=False,
                is_inherited_period=False,
            )

        # -------------------------------------------------------------
        # 2. PRESENTATION 라우트 감지 (표현/시각화 전환 서술어 의도)
        # -------------------------------------------------------------
        candidate_metric = node1_output.get("selected_metric_id")

        # PRESENTATION은 저장된 Artifact를 다시 그릴 뿐 질의를 재실행하지 않는다. 따라서
        # 무엇을 측정할지(metric), 어떻게 나눌지(dimension), 어떤 행을 볼지(filter) 중 하나라도
        # 바뀌면 재사용으로 답할 수 없다. 이 중 하나라도 후보가 오면 신호와 무관하게 모든
        # 게이트를 거치는 ANALYSIS로 보낸다. 그러지 않으면 사용자가 요청한 분해·필터가
        # 조용히 사라지고 이전 결과가 다시 표시된다.
        changes_query_shape = bool(
            candidate_metric
            or node1_output.get("dimension_fields")
            or node1_output.get("filter_fields")
        )
        # 재사용할 선행 Artifact가 실제로 있는지는 오케스트레이터가 실행 직전에 확인해
        # 없으면 typed 실패로 닫는다(조용한 우회 금지).
        if requested_route == "PRESENTATION" and not changes_query_shape:
            target_view = cls._resolve_presentation_chart_type(msg, last_chart_type, node1_output)
            return ResolvedTurnSlots(
                route="PRESENTATION",
                metric_id=last_analysis_slots.get("metric_id") or last_slots.get("metric_id"),
                dimension_fields=tuple(last_analysis_slots.get("dimension_fields", ())) if last_analysis_slots else tuple(last_slots.get("dimension_fields", ())),
                user_filters=tuple(last_analysis_slots.get("user_filters", ())) if last_analysis_slots else tuple(last_slots.get("user_filters", ())),
                time_range=cls._parse_stored_time_range(last_analysis_slots.get("time_range")) or cls._parse_stored_time_range(last_slots.get("time_range")),
                target_chart_type=target_view,
                source_turn_ids=(str(last_turn["turn_id"]),) if last_turn else (),
                is_inherited_metric=True if last_turn else False,
                is_inherited_dimension=True if last_turn else False,
                is_inherited_period=True if last_turn else False,
            )

        # -------------------------------------------------------------
        # 3. ANALYSIS 라우트: 슬롯 상속 & Delta 병합
        # -------------------------------------------------------------
        is_followup = cls._is_followup_question(
            msg, node1_output, last_analysis_slots.get("metric_id") or last_slots.get("metric_id")
        )

        # 3-1. metric_id 변경분 계산 및 적용
        inherited_metric_id = last_analysis_slots.get("metric_id") or last_slots.get("metric_id")
        metric_change = derive_metric_change(candidate_metric, is_followup, inherited_metric_id)
        metric_id, is_inherited_metric = apply_metric_change(metric_change)

        # 3-2. dimension_fields 변경분 계산 및 적용
        candidate_dims = tuple(
            dict(d) for d in (node1_output.get("dimension_fields") or ()) if isinstance(d, dict)
        )
        inherited_dims = (
            tuple(dict(d) for d in last_analysis_slots["dimension_fields"])
            if last_analysis_slots.get("dimension_fields")
            else tuple(dict(d) for d in last_slots.get("dimension_fields", ()))
        )
        dimension_changes = derive_dimension_changes(candidate_dims, inherited_dims, is_followup)
        dimension_fields, is_inherited_dimension = apply_dimension_changes(
            dimension_changes, inherited_dims
        )

        # 3-3. user_filters 변경분 계산 및 적용
        candidate_filters = tuple(
            dict(f) for f in (node1_output.get("filter_fields") or ()) if isinstance(f, dict)
        )
        inherited_filters = (
            tuple(dict(f) for f in last_analysis_slots["user_filters"])
            if last_analysis_slots.get("user_filters")
            else tuple(dict(f) for f in last_slots.get("user_filters", ()))
        )
        filter_changes = derive_dimension_changes(
            candidate_filters, inherited_filters, is_followup, field="user_filters"
        )
        user_filters, _is_inherited_filter = apply_dimension_changes(
            filter_changes, inherited_filters, field="user_filters"
        )
        change_set = (metric_change, *dimension_changes, *filter_changes)

        # 3-4. 시간 범위 해석 (TimeAlgebraEngine 적용)
        last_time_range = (
            cls._parse_stored_time_range(last_analysis_slots.get("time_range"))
            or cls._parse_stored_time_range(last_slots.get("time_range"))
        ) if previous_turns else None

        time_range, is_inherited_period = TimeAlgebraEngine.resolve_time(
            user_message=msg,
            node1_output=node1_output,
            last_time_range=last_time_range,
            as_of=as_of_date,
        )

        # 3-5. 초기 시각화 선호도 판별
        target_chart_type = cls._resolve_initial_chart_type(msg, node1_output)

        return ResolvedTurnSlots(
            route="ANALYSIS",
            metric_id=metric_id,
            dimension_fields=dimension_fields,
            user_filters=user_filters,
            time_range=time_range,
            target_chart_type=target_chart_type,
            source_turn_ids=(str(last_turn["turn_id"]),) if last_turn and (is_inherited_metric or is_inherited_period or is_inherited_dimension) else (),
            is_inherited_metric=is_inherited_metric,
            is_inherited_dimension=is_inherited_dimension,
            is_inherited_period=is_inherited_period,
            change_set=change_set,
        )

    @classmethod
    def _is_followup_question(
        cls,
        msg: str,
        node1_output: dict[str, Any],
        last_metric_id: str | None,
    ) -> bool:
        """이번 발화가 직전 턴의 슬롯을 상속할 생략문인지 판정합니다.

        생략 여부는 질문 자체의 문법 판단이므로 Node1이 `is_elliptical`로 해석하고, 서버는
        그 신호를 대화 상태와 대조해 확정한다. 신호가 없으면 상속을 추측하지 않고 False로
        닫아, 슬롯이 비면 상위 단계가 재질의로 처리하게 한다(잘못된 상속보다 안전).

        Args:
            msg: 사용자 발화(현재 판단에는 쓰지 않으며 추적용으로 유지)
            node1_output: Node 1 정규화 결과
            last_metric_id: 직전 턴에서 확정된 지표 ID

        Returns:
            직전 턴 슬롯을 상속할 후속 질의인지 여부
        """
        if node1_output.get("is_elliptical") is not True:
            return False

        # MetricResolver는 승인 검증을 마친 지표 집합을 `metric_ids`로 싣고, 검증 전
        # 원본 Node1 응답은 `metric_candidates`를 쓴다. 두 생산자를 모두 읽지 않으면
        # 이 가드가 운영 경로에서 항상 통과해 새 지표 질문까지 후속 질의로 오인한다.
        metric_candidates = node1_output.get("metric_ids")
        if not isinstance(metric_candidates, list):
            metric_candidates = node1_output.get("metric_candidates")
        if (
            isinstance(metric_candidates, list)
            and metric_candidates
            and last_metric_id is not None
            and last_metric_id not in metric_candidates
        ):
            # 생략문이더라도 이번 턴 후보가 직전 지표를 포함하지 않으면 이어가는 분석이
            # 아니므로 상속하지 않는다. 이 판단은 대화 상태를 아는 서버만 할 수 있다.
            return False

        return True

    @classmethod
    def _resolve_presentation_chart_type(
        cls,
        msg: str,
        last_chart_type: str,
        node1_output: dict[str, Any] | None = None,
    ) -> str:
        """PRESENTATION 라우트에서 다음 목표 차트/표 뷰 타입을 확정합니다.

        어떤 표현을 요청했는지는 Node1이 `presentation_type`으로 해석한다. 질문이 특정
        표현을 지목하지 않아 신호가 없으면(예: "다른 걸로 보여줘") 허용 목록을 순환해
        직전과 다른 표현을 제시한다.

        Args:
            msg: 사용자 발화(현재 분기 판단에는 쓰지 않으며 추적용으로 유지)
            last_chart_type: 직전 턴에서 표시하던 뷰 타입
            node1_output: Node1 정규화 결과

        Returns:
            허용 목록에 속하는 뷰 타입
        """
        signal = cls._presentation_signal(node1_output)
        if signal is not None:
            return signal

        current = last_chart_type.upper()
        if current not in cls.CHART_CYCLE_ALLOWLIST:
            return cls.CHART_CYCLE_ALLOWLIST[0]
        index = cls.CHART_CYCLE_ALLOWLIST.index(current)
        return cls.CHART_CYCLE_ALLOWLIST[(index + 1) % len(cls.CHART_CYCLE_ALLOWLIST)]

    @classmethod
    def _resolve_initial_chart_type(
        cls,
        msg: str,
        node1_output: dict[str, Any] | None = None,
    ) -> str:
        """ANALYSIS 라우트에서 질문이 명시한 초기 시각화 타입을 확정합니다.

        표현을 지목하지 않은 질문은 표/차트를 강제하지 않고 요약(``SUMMARY``)으로 연다.

        Args:
            msg: 사용자 발화(현재 분기 판단에는 쓰지 않으며 추적용으로 유지)
            node1_output: Node1 정규화 결과

        Returns:
            허용 목록에 속하는 뷰 타입
        """
        return cls._presentation_signal(node1_output) or "SUMMARY"

    @classmethod
    def _presentation_signal(cls, node1_output: dict[str, Any] | None) -> str | None:
        """Node1이 제시한 표현 타입 후보를 허용 목록 안에서만 통과시킵니다.

        Args:
            node1_output: Node1 정규화 결과(없을 수 있음)

        Returns:
            허용된 뷰 타입, 신호가 없거나 허용 밖이면 None
        """
        if not node1_output:
            return None
        value = node1_output.get("presentation_type")
        if isinstance(value, str) and value.upper() in cls.ALLOWED_CHART_TYPES:
            return value.upper()
        return None

    @staticmethod
    def _parse_stored_time_range(stored: dict[str, Any] | None) -> ResolvedTimeRange | None:
        """저장소(DB)에 직렬화되어 있던 기간 딕셔너리를 ResolvedTimeRange 객체로 복원합니다."""
        if not isinstance(stored, dict):
            return None
        try:
            start = date.fromisoformat(stored["start"])
            end = date.fromisoformat(stored["end_exclusive"])
            return ResolvedTimeRange(start=start, end_exclusive=end, source_text=stored.get("source_text", ""))
        except (KeyError, ValueError, TypeError):
            return None
