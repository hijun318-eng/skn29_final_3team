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
    ChangeOperation,
    SlotChange,
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
    metric_ids: tuple[str, ...] = ()
    analysis_operation: str | None = None
    result_limit: int | None = None
    comparison_time_range: ResolvedTimeRange | None = None
    analysis_time_bucket: str | None = None


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

        # 이전 확정 ANALYSIS 턴 역추적. route만 ANALYSIS인 실패·명확화 턴은 실행된
        # 분석 상태가 아니므로 상속 원본이 될 수 없다.
        eligible_analyses = [
            turn for turn in previous_turns if cls.is_resolved_analysis_turn(turn)
        ]
        last_analysis = eligible_analyses[-1] if eligible_analyses else None
        last_analysis_slots = last_analysis.get("resolved_slots", {}) if last_analysis else {}
        # OUT_OF_DATA_RANGE는 실행된 Analysis가 아니므로 source Turn이나 focus가 될 수
        # 없다. 다만 사용자가 바로 다음 Turn에서 가용 절대 기간만 고치면, 차단된 요청의
        # 확정 Metric·filter·dimension intent는 한 번만 재사용할 수 있어야 한다. 이
        # pending intent는 성공 Artifact 상속과 분리하고 즉시 직전 Turn에만 한정한다.
        pending_range_slots = (
            last_slots
            if last_turn is not None
            and last_turn.get("route") == "ANALYSIS"
            and last_turn.get("terminal_status") == "BLOCKED"
            and last_turn.get("reason_code") == "OUT_OF_DATA_RANGE"
            and bool(last_slots.get("metric_id") or last_slots.get("metric_ids"))
            else {}
        )
        analysis_inheritance_slots = last_analysis_slots or pending_range_slots

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
                        source_turn_ids=(
                            (str(last_analysis["turn_id"]),)
                            if last_analysis is not None
                            else ()
                        ),
                        is_inherited_metric=False,
                        is_inherited_dimension=True if last_analysis_slots.get("dimension_fields") else False,
                        is_inherited_period=is_inherited_period,
                        analysis_operation=last_slots.get("analysis_operation"),
                        analysis_time_bucket=last_slots.get("analysis_time_bucket"),
                        result_limit=last_slots.get("result_limit"),
                        comparison_time_range=cls._parse_stored_time_range(
                            last_slots.get("comparison_time_range")
                        ),
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
                        source_turn_ids=(
                            (str(last_analysis["turn_id"]),)
                            if last_analysis is not None
                            else ()
                        ),
                        is_inherited_metric=True if not node1_output.get("selected_metric_id") and resolved_metric else False,
                        is_inherited_dimension=True if last_analysis_slots.get("dimension_fields") else False,
                        is_inherited_period=False,
                        analysis_operation=last_slots.get("analysis_operation"),
                        analysis_time_bucket=last_slots.get("analysis_time_bucket"),
                        result_limit=last_slots.get("result_limit"),
                        comparison_time_range=cls._parse_stored_time_range(
                            last_slots.get("comparison_time_range")
                        ),
                    )

        # -------------------------------------------------------------
        # 1. REPORT_ACTION 라우트 감지 (보고서 담기/추가 서술어 의도)
        # -------------------------------------------------------------
        # Node1이 제시한 route는 후보다. 서버는 계약 enum 안의 값만 받아들이고, 각
        # 라우트가 요구하는 선행 상태(재사용할 Artifact 등)를 아래에서 다시 확인한다.
        requested_route = node1_output.get("requested_route")
        if requested_route not in cls.CONVERSATION_ROUTES:
            requested_route = None

        # Node1이 표현 종류는 명확히 구조화했지만 route enum만 누락하는 경우가 있다.
        # 문장을 키워드로 다시 해석하지 않고, 선행 Artifact가 있는 상태에서 모델이
        # 명시적 표현 변경을 반환한 경우에만 PRESENTATION 후보로 복구한다. 아래의
        # query-shape 비교가 새 지표·차원·필터·기간 요청을 다시 ANALYSIS로 닫는다.
        if (
            requested_route is None
            and last_analysis is not None
            and node1_output.get("presentation_explicit") is True
            and node1_output.get("presentation_type") in cls.ALLOWED_CHART_TYPES
        ):
            requested_route = "PRESENTATION"

        if requested_route == "REPORT_ACTION":
            source_turn_ids: list[str] = []
            seen_artifacts: set[str] = set()
            for turn in reversed(eligible_analyses):
                artifact = str(turn["artifact_id"])
                if artifact in seen_artifacts:
                    continue
                seen_artifacts.add(artifact)
                source_turn_ids.insert(0, str(turn["turn_id"]))
                if len(source_turn_ids) >= 2:
                    break
            return ResolvedTurnSlots(
                route="REPORT_ACTION",
                metric_id=None,
                dimension_fields=(),
                user_filters=(),
                time_range=None,
                target_chart_type=None,
                source_turn_ids=tuple(source_turn_ids),
                is_inherited_metric=False,
                is_inherited_dimension=False,
                is_inherited_period=False,
            )

        # -------------------------------------------------------------
        # 2. PRESENTATION 라우트 감지 (표현/시각화 전환 서술어 의도)
        # -------------------------------------------------------------
        raw_candidate_metrics = node1_output.get("selected_metric_ids")
        candidate_metric_ids = tuple(
            item
            for item in (
                raw_candidate_metrics
                if isinstance(raw_candidate_metrics, (list, tuple))
                else ()
            )
            if isinstance(item, str) and item
        )
        candidate_metric = (
            candidate_metric_ids[0]
            if len(candidate_metric_ids) == 1
            else node1_output.get("selected_metric_id")
            if not candidate_metric_ids
            else None
        )
        if not candidate_metric_ids and isinstance(candidate_metric, str):
            candidate_metric_ids = (candidate_metric,)
        stored_analysis_metric_ids = tuple(
            item
            for item in (
                analysis_inheritance_slots.get("metric_ids")
                or (
                    [analysis_inheritance_slots.get("metric_id")]
                    if analysis_inheritance_slots.get("metric_id")
                    else []
                )
            )
            if isinstance(item, str) and item
        )

        operations = {
            "aggregate",
            "breakdown",
            "time_trend",
            "top_n",
            "bottom_n",
            "period_comparison",
        }
        candidate_operation = node1_output.get("analysis_operation")
        if candidate_operation not in operations:
            candidate_operation = None
        candidate_time_bucket = node1_output.get("analysis_time_bucket")
        if candidate_time_bucket not in {"day", "week", "month", "quarter", "year"}:
            candidate_time_bucket = None

        # PRESENTATION은 저장된 Artifact를 다시 그릴 뿐 질의를 재실행하지 않는다. 따라서
        # 무엇을 측정할지(metric), 어떻게 나눌지(dimension), 어떤 행을 볼지(filter),
        # 어떤 집계 형태·시간 버킷을 쓸지 중 하나라도 바뀌면 재사용으로 답할 수 없다.
        # 이 중 하나라도 후보가 오면 신호와 무관하게 모든 게이트를 거치는 ANALYSIS로
        # 보낸다. 그러지 않으면 사용자가 요청한 재집계가 조용히 사라진다.
        candidate_changes_metric = bool(candidate_metric_ids) and (
            frozenset(candidate_metric_ids) != frozenset(stored_analysis_metric_ids)
        )
        candidate_changes_dimensions = cls._collection_slot_changes_query_shape(
            node1_output.get("dimension_fields"),
            analysis_inheritance_slots.get("dimension_fields"),
        )
        candidate_changes_filters = cls._collection_slot_changes_query_shape(
            node1_output.get("filter_fields"),
            analysis_inheritance_slots.get("user_filters"),
        )
        candidate_changes_period = cls._period_candidates_change_query_shape(
            node1_output.get("period_candidates"),
            analysis_inheritance_slots,
        )
        changes_query_shape = bool(
            candidate_changes_metric
            or candidate_changes_dimensions
            or candidate_changes_filters
            or candidate_changes_period
            or (
                candidate_operation is not None
                and candidate_operation
                != analysis_inheritance_slots.get("analysis_operation")
            )
            or (
                candidate_time_bucket is not None
                and candidate_time_bucket
                != analysis_inheritance_slots.get("analysis_time_bucket")
            )
            or (
                isinstance(node1_output.get("result_limit"), int)
                and not isinstance(node1_output.get("result_limit"), bool)
                and node1_output.get("result_limit")
                != analysis_inheritance_slots.get("result_limit")
            )
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
                source_turn_ids=(
                    (str(last_analysis["turn_id"]),)
                    if last_analysis is not None
                    else ()
                ),
                is_inherited_metric=last_analysis is not None,
                is_inherited_dimension=last_analysis is not None,
                is_inherited_period=last_analysis is not None,
                change_set=(
                    SlotChange(
                        "target_chart_type",
                        ChangeOperation.SET,
                        target_view,
                    ),
                ),
                metric_ids=stored_analysis_metric_ids,
                analysis_operation=last_analysis_slots.get("analysis_operation"),
                analysis_time_bucket=last_analysis_slots.get("analysis_time_bucket"),
                result_limit=last_analysis_slots.get("result_limit"),
                comparison_time_range=cls._parse_stored_time_range(
                    last_analysis_slots.get("comparison_time_range")
                ),
            )

        # -------------------------------------------------------------
        # 3. ANALYSIS 라우트: 슬롯 상속 & Delta 병합
        # -------------------------------------------------------------
        is_followup = (
            cls._is_followup_question(node1_output)
            # Node 1이 PRESENTATION으로 판정한 요청이 재집계를 요구하면 ANALYSIS로
            # 승격된다. 이 전환 자체가 선행 결과를 수정하는 후속 의도이므로 모델의
            # is_elliptical 누락만으로 확정된 지표·기간을 버리지 않는다.
            or (
                requested_route == "PRESENTATION"
                and last_analysis is not None
            )
            or bool(pending_range_slots)
            and not candidate_metric_ids
            and bool(node1_output.get("period_candidates"))
        )
        has_current_analysis_delta = cls.has_executable_analysis_delta(
            node1_output,
            analysis_inheritance_slots,
        )

        # 3-1. 단일 지표 ChangeSet 호환성을 유지하면서 복수 지표 묶음을 원자적으로 적용한다.
        inherited_metric_id = (
            stored_analysis_metric_ids[0]
            if len(stored_analysis_metric_ids) == 1
            else last_slots.get("metric_id")
        )
        metric_changes: tuple[Any, ...] = ()
        if len(candidate_metric_ids) > 1:
            metric_ids = candidate_metric_ids
            metric_id = None
            is_inherited_metric = False
        elif not candidate_metric_ids and is_followup and len(stored_analysis_metric_ids) > 1:
            metric_ids = stored_analysis_metric_ids
            metric_id = None
            is_inherited_metric = True
        else:
            metric_change = derive_metric_change(
                candidate_metric,
                is_followup,
                inherited_metric_id,
            )
            metric_id, is_inherited_metric = apply_metric_change(metric_change)
            metric_ids = (metric_id,) if metric_id else ()
            metric_changes = (metric_change,)

        analysis_operation = candidate_operation or (
            analysis_inheritance_slots.get("analysis_operation")
            if is_followup
            else None
        )
        analysis_time_bucket = (
            candidate_time_bucket
            if candidate_operation == "time_trend"
            else analysis_inheritance_slots.get("analysis_time_bucket")
            if is_followup and analysis_operation == "time_trend"
            else None
        )
        candidate_result_limit = node1_output.get("result_limit")
        result_limit = (
            candidate_result_limit
            if candidate_operation in {"top_n", "bottom_n"}
            and isinstance(candidate_result_limit, int)
            and not isinstance(candidate_result_limit, bool)
            else analysis_inheritance_slots.get("result_limit")
            if is_followup and analysis_operation in {"top_n", "bottom_n"}
            else None
        )
        # 3-2. dimension_fields 변경분 계산 및 적용
        candidate_dims = tuple(
            dict(d) for d in (node1_output.get("dimension_fields") or ()) if isinstance(d, dict)
        )
        inherited_dims = (
            tuple(dict(d) for d in analysis_inheritance_slots["dimension_fields"])
            if analysis_inheritance_slots.get("dimension_fields")
            else tuple(dict(d) for d in last_slots.get("dimension_fields", ()))
        )
        # Node 1은 결과 형태를 생략한 후속 질문에서 operation을 null로 보내므로 기존
        # 차원을 보존한다. 반대로 명시적인 aggregate와 빈 차원 목록은 전체값으로의
        # 전환이며, 이전 GROUP BY를 CLEAR해야 한다. 질문 문자열은 다시 파싱하지 않는다.
        preserve_dimensions = not (
            is_followup
            and candidate_operation == "aggregate"
            and not candidate_dims
        )
        dimension_changes = derive_dimension_changes(
            candidate_dims,
            inherited_dims,
            is_followup and preserve_dimensions,
        )
        dimension_fields, is_inherited_dimension = apply_dimension_changes(
            dimension_changes, inherited_dims
        )

        # 3-3. user_filters 변경분 계산 및 적용
        candidate_filters = tuple(
            dict(f) for f in (node1_output.get("filter_fields") or ()) if isinstance(f, dict)
        )
        inherited_filters = (
            tuple(dict(f) for f in analysis_inheritance_slots["user_filters"])
            if analysis_inheritance_slots.get("user_filters")
            else tuple(dict(f) for f in last_slots.get("user_filters", ()))
        )
        filter_changes = derive_dimension_changes(
            candidate_filters, inherited_filters, is_followup, field="user_filters"
        )
        user_filters, _is_inherited_filter = apply_dimension_changes(
            filter_changes, inherited_filters, field="user_filters"
        )
        change_set = (*metric_changes, *dimension_changes, *filter_changes)

        # 3-4. 시간 범위 해석 (TimeAlgebraEngine 적용)
        last_time_range = (
            (
                cls._parse_stored_time_range(last_analysis_slots.get("time_range"))
                or (
                    cls._parse_stored_time_range(last_slots.get("time_range"))
                    if not pending_range_slots
                    else None
                )
            )
            if previous_turns and (not is_followup or has_current_analysis_delta)
            else None
        )

        # latest_snapshot은 source time의 서버 기준일 전 MAX를 선택하므로 질문이나
        # 직전 턴의 range를 물려받지 않는다. 이 mode는 DataHub 후보를 고른 뒤
        # MetricResolver가 확정한 typed 신호이며, 문장 패턴으로 추측하지 않는다.
        if node1_output.get("time_mode") == "latest_snapshot":
            time_range = None
            is_inherited_period = False
            comparison_time_range = None
        else:
            time_range, is_inherited_period = TimeAlgebraEngine.resolve_time(
                user_message=msg,
                node1_output=node1_output,
                last_time_range=last_time_range,
                as_of=as_of_date,
            )
            comparison_time_range = TimeAlgebraEngine.resolve_comparison_time(
                node1_output,
                as_of_date,
            )
        if (
            comparison_time_range is None
            and is_followup
            and analysis_operation == "period_comparison"
            and node1_output.get("time_mode") != "latest_snapshot"
        ):
            prior_ranges = [
                (turn, cls._parse_stored_time_range(
                    turn.get("resolved_slots", {}).get("time_range")
                ))
                for turn in eligible_analyses[-2:]
            ]
            prior_ranges = [item for item in prior_ranges if item[1] is not None]
            if len(prior_ranges) == 2:
                time_range = prior_ranges[-1][1]
                comparison_time_range = prior_ranges[-2][1]
                is_inherited_period = True
            else:
                comparison_time_range = cls._parse_stored_time_range(
                    last_analysis_slots.get("comparison_time_range")
                )
        if analysis_operation != "period_comparison":
            comparison_time_range = None

        # Metric·dimension과 동일하게 기간 변경도 durable ChangeSet에 남긴다. Node 1의
        # typed period candidate가 있으면 SET, 직전 범위를 그대로 썼으면 PRESERVE이며,
        # 비교 범위를 새로 붙이는 전이는 ADD_VALUE다. 질문 문구를 다시 해석하지 않는다.
        period_changes: list[SlotChange] = []
        if time_range is not None:
            period_changes.append(
                SlotChange(
                    "time_range",
                    (
                        ChangeOperation.PRESERVE
                        if is_inherited_period
                        else ChangeOperation.SET
                    ),
                    {
                        "start": time_range.start.isoformat(),
                        "end_exclusive": time_range.end_exclusive.isoformat(),
                        "source_text": time_range.source_text,
                    },
                )
            )
        elif last_time_range is not None:
            period_changes.append(
                SlotChange("time_range", ChangeOperation.CLEAR, None)
            )

        last_comparison_time_range = cls._parse_stored_time_range(
            last_analysis_slots.get("comparison_time_range")
        )
        if comparison_time_range is not None:
            comparison_is_preserved = (
                last_comparison_time_range is not None
                and comparison_time_range.start == last_comparison_time_range.start
                and comparison_time_range.end_exclusive
                == last_comparison_time_range.end_exclusive
            )
            period_changes.append(
                SlotChange(
                    "comparison_time_range",
                    (
                        ChangeOperation.PRESERVE
                        if comparison_is_preserved
                        else ChangeOperation.ADD_VALUE
                        if last_comparison_time_range is None
                        else ChangeOperation.SET
                    ),
                    {
                        "start": comparison_time_range.start.isoformat(),
                        "end_exclusive": comparison_time_range.end_exclusive.isoformat(),
                        "source_text": comparison_time_range.source_text,
                    },
                )
            )
        elif last_comparison_time_range is not None:
            period_changes.append(
                SlotChange("comparison_time_range", ChangeOperation.CLEAR, None)
            )
        change_set = (*change_set, *period_changes)

        # 3-5. 초기 시각화 선호도 판별
        target_chart_type = cls._resolve_initial_chart_type(msg, node1_output)

        return ResolvedTurnSlots(
            route="ANALYSIS",
            metric_id=metric_id,
            dimension_fields=dimension_fields,
            user_filters=user_filters,
            time_range=time_range,
            target_chart_type=target_chart_type,
            source_turn_ids=(
                tuple(str(turn["turn_id"]) for turn in eligible_analyses[-2:])
                if analysis_operation == "period_comparison"
                and len(eligible_analyses) >= 2
                else (str(last_analysis["turn_id"]),)
                if last_analysis is not None
                and (
                    is_inherited_metric
                    or is_inherited_period
                    or is_inherited_dimension
                )
                else ()
            ),
            is_inherited_metric=is_inherited_metric,
            is_inherited_dimension=is_inherited_dimension,
            is_inherited_period=is_inherited_period,
            change_set=change_set,
            metric_ids=metric_ids,
            analysis_operation=analysis_operation,
            result_limit=result_limit,
            comparison_time_range=comparison_time_range,
            analysis_time_bucket=analysis_time_bucket,
        )

    @classmethod
    def _is_followup_question(
        cls,
        node1_output: dict[str, Any],
    ) -> bool:
        """이번 발화가 직전 턴의 슬롯을 상속할 생략문인지 판정합니다.

        생략 여부는 우선 Node1의 `is_elliptical`로 해석한다. 모델이 이 신호를 놓쳐도
        측정 대상 없이 분석 연산만 확정된 typed 구조는 그 자체로 이전 Metric이 필요한
        요청이므로 같은 문맥 의존 상태로 취급한다. 새 지표 후보가 있으면 아래 ChangeSet이
        교체하고, 생략된 기간·차원·필터만 호환 범위에서 이어간다.

        Args:
            node1_output: Node 1 정규화 결과

        Returns:
            직전 턴 슬롯을 상속할 후속 질의인지 여부
        """
        return cls.is_context_dependent_followup(node1_output)

    @classmethod
    def is_context_dependent_followup(
        cls,
        node1_output: dict[str, Any],
    ) -> bool:
        """typed Node 1 구조만으로 이전 분석 상태가 필요한 요청인지 판정한다.

        모델의 명시적 ``is_elliptical`` 신호가 우선이다. 다만 측정 대상은 없고
        결과 연산만 명시된 요청은 그 연산을 적용할 Metric이 현재 발화에 없으므로
        구조적으로도 문맥 의존적이다. 이는 질문 문구나 업무 값 목록을 해석하지 않는다.
        실제 상속 가능 여부는 이전 확정 분석 슬롯 존재 여부가 별도로 결정한다.
        """

        if node1_output.get("is_elliptical") is True:
            return True
        operations = {
            "aggregate",
            "breakdown",
            "time_trend",
            "top_n",
            "bottom_n",
            "period_comparison",
        }
        return (
            node1_output.get("metric_resolution") == "missing"
            and not node1_output.get("measurement_source_texts")
            and node1_output.get("analysis_operation") in operations
        )

    @classmethod
    def has_executable_analysis_delta(
        cls,
        node1_output: dict[str, Any],
        previous_analysis_slots: dict[str, Any] | None = None,
    ) -> bool:
        """현재 발화에서 서버가 실행에 반영할 수 있는 typed 변경이 있는지 판정한다.

        생략형이라는 모델 신호만으로 지표·기간·차원·필터를 모두 상속하면 기간 해석에
        실패한 발화도 직전 요청과 같은 쿼리로 실행될 수 있다. 질문 문자열을 다시 파싱하지
        않고 Node 1이 현재 발화에서 확정한 실행 슬롯만 확인한다. 연산·버킷·행 제한은 직전
        값과 실제로 다를 때만 변경으로 인정해, 모델이 직전 연산을 반복 출력한 것만으로
        이전 기간 전체가 재실행되지 않게 한다.
        """

        previous = previous_analysis_slots or {}
        raw_metric_ids = node1_output.get("selected_metric_ids")
        has_metric = bool(
            isinstance(node1_output.get("selected_metric_id"), str)
            and node1_output["selected_metric_id"]
        ) or bool(
            isinstance(raw_metric_ids, (list, tuple))
            and any(isinstance(item, str) and item for item in raw_metric_ids)
        )
        operations = {
            "aggregate",
            "breakdown",
            "time_trend",
            "top_n",
            "bottom_n",
            "period_comparison",
        }
        candidate_operation = node1_output.get("analysis_operation")
        candidate_time_bucket = node1_output.get("analysis_time_bucket")
        candidate_result_limit = node1_output.get("result_limit")
        return bool(
            has_metric
            or node1_output.get("dimension_fields")
            or node1_output.get("filter_fields")
            or node1_output.get("period_candidates")
            or node1_output.get("time_mode") == "latest_snapshot"
            or (
                candidate_operation in operations
                and candidate_operation != previous.get("analysis_operation")
            )
            or (
                candidate_time_bucket in {"day", "week", "month", "quarter", "year"}
                and candidate_time_bucket != previous.get("analysis_time_bucket")
            )
            or (
                isinstance(candidate_result_limit, int)
                and not isinstance(candidate_result_limit, bool)
                and candidate_result_limit != previous.get("result_limit")
            )
        )

    @staticmethod
    def has_grounded_analysis_slot_delta(node1_output: dict[str, Any]) -> bool:
        """오류로 거부된 Metric을 상속해도 되는 현재 발화의 독립 실행 근거를 확인한다.

        연산 종류 하나는 모델의 기본 출력일 수 있어 ``INVALID_METRIC``을 무시할 근거가
        되지 않는다. 현재 발화에서 별도로 확정된 Metric·기간·차원·필터·snapshot만
        preflight 오류를 해제할 수 있다.
        """

        raw_metric_ids = node1_output.get("selected_metric_ids")
        return bool(
            (
                isinstance(node1_output.get("selected_metric_id"), str)
                and node1_output["selected_metric_id"]
            )
            or (
                isinstance(raw_metric_ids, (list, tuple))
                and any(isinstance(item, str) and item for item in raw_metric_ids)
            )
            or node1_output.get("dimension_fields")
            or node1_output.get("filter_fields")
            or node1_output.get("period_candidates")
            or node1_output.get("time_mode") == "latest_snapshot"
        )

    @staticmethod
    def is_resolved_analysis_turn(turn: dict[str, Any]) -> bool:
        """실패·명확화 상태가 아닌 확정 Metric 분석 턴만 상속 원본으로 허용한다."""

        if turn.get("route") != "ANALYSIS":
            return False
        terminal_status = turn.get("terminal_status")
        if terminal_status is not None and terminal_status != "SUCCEEDED":
            return False
        if terminal_status is not None and not turn.get("artifact_id"):
            return False
        slots = turn.get("resolved_slots")
        if not isinstance(slots, dict):
            return False
        if slots.get("ambiguity_status") == "NEEDS_CLARIFICATION":
            return False
        return bool(slots.get("metric_id") or slots.get("metric_ids"))

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

        표현을 지목하지 않은 질문은 결과에 집중하도록 요약 뷰로 시작한다. 표현 요청은
        질문 문구를 서버에서 다시 파싱하지 않고 Node1의 typed 신호만 사용한다.

        Args:
            msg: 사용자 발화(현재 분기 판단에는 쓰지 않으며 추적용으로 유지)
            node1_output: Node1 정규화 결과

        Returns:
            허용 목록에 속하는 뷰 타입
        """
        # 연산 종류만으로 차트를 추정하지 않는다. Node1이 표현 타입뿐 아니라 현재
        # 질문에 그 표현이 명시됐다는 typed 증거까지 반환한 경우에만 초기 뷰로 쓴다.
        if not node1_output or node1_output.get("presentation_explicit") is not True:
            return "SUMMARY"
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
    def _collection_slot_changes_query_shape(
        candidate_value: object,
        stored_value: object,
    ) -> bool:
        """현재 후보 차원·필터가 저장된 쿼리 형태와 실제로 다른지 비교한다.

        Node 1은 표현만 바꾸는 요청에서도 앞선 차원이나 필터를 반복 출력할 수 있다.
        후보의 존재만 변경으로 간주하면 동일 Artifact를 다시 조회하게 되므로, durable
        ChangeSet과 같은 식별 키로 집합을 비교한다. 후보가 없으면 생략으로 보고 변경하지
        않으며, 형식이 깨진 비어 있지 않은 후보는 안전하게 변경으로 닫는다.
        """

        if not candidate_value:
            return False
        if not isinstance(candidate_value, (list, tuple)):
            return True

        candidate_items = tuple(item for item in candidate_value if isinstance(item, dict))
        if len(candidate_items) != len(candidate_value):
            return True
        stored_items = tuple(
            item
            for item in (
                stored_value if isinstance(stored_value, (list, tuple)) else ()
            )
            if isinstance(item, dict)
        )

        def identity(item: dict[str, Any]) -> tuple[str, str, str, str]:
            return (
                str(item.get("asset_fqn", "")),
                str(item.get("column", "")),
                str(item.get("operator", "")),
                str(item.get("value_text", "")),
            )

        return {identity(item) for item in candidate_items} != {
            identity(item) for item in stored_items
        }

    @classmethod
    def _period_candidates_change_query_shape(
        cls,
        candidate_value: object,
        stored_slots: dict[str, Any],
    ) -> bool:
        """typed 기간 후보가 저장된 주·비교 기간과 실제로 다른지 비교한다.

        ``source_text``는 같은 기간을 표현한 자연어가 달라질 수 있으므로 쿼리 경계에
        포함하지 않는다. 후보가 저장 범위의 선두와 모두 같으면 모델의 반복 출력으로
        보고, 새 경계·추가 비교 기간·깨진 후보는 재조회가 필요한 변경으로 처리한다.
        """

        if not candidate_value:
            return False
        candidates = TimeAlgebraEngine._valid_candidates(candidate_value)
        if not candidates:
            return True

        stored_ranges = tuple(
            item
            for item in (
                cls._parse_stored_time_range(stored_slots.get("time_range")),
                cls._parse_stored_time_range(stored_slots.get("comparison_time_range")),
            )
            if item is not None
        )
        if len(candidates) > len(stored_ranges):
            return True
        return any(
            candidate.start != stored.start
            or candidate.end_exclusive != stored.end_exclusive
            for candidate, stored in zip(candidates, stored_ranges)
        )

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
