"""멀티턴 슬롯 해석, 시간 대수 엔진, 라우트 및 뷰 타입 결정론적 분기 테스트."""

from datetime import date
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.conversation.slot_resolver import (
    ConversationSlotResolver,
    ResolvedTimeRange,
)
from app.services.conversation.time_algebra import TimeAlgebraEngine


def _node1_period(start: str, end_exclusive: str, source_text: str) -> dict:
    """Node 1이 반환하는 typed period_candidates 형태의 응답 조각을 만든다.

    운영 경로에서 질문 문장의 시간 해석은 Node 1이 소유하고 서버는 그 결과를 확정만
    하므로, 시간 대수 테스트도 문자열 파싱이 아니라 이 typed 후보로 구동한다.
    """
    return {
        "period_candidates": [
            {"start": start, "end_exclusive": end_exclusive, "source_text": source_text}
        ],
        "period_relationship": "single",
    }


def test_time_algebra_confirms_node1_typed_period():
    """Node 1이 해석한 반개구간 후보를 서버가 재해석 없이 그대로 확정하는지 검증."""
    as_of = date(2026, 8, 18)

    resolved, inherited = TimeAlgebraEngine.resolve_time(
        "2025년 8월 1일 ~ 8월 15일 객실 매출 보여줘",
        _node1_period("2025-08-01T00:00:00+09:00", "2025-08-16T00:00:00+09:00", "2025년 8월 1일 ~ 8월 15일"),
        None,
        as_of,
    )
    assert not inherited
    assert resolved is not None
    assert resolved.start == date(2025, 8, 1)
    assert resolved.end_exclusive == date(2025, 8, 16)

    # 멀티턴 fast-path는 타임존 없는 날짜 문자열을 싣는다. 두 형태 모두 확정돼야 한다.
    naive, _ = TimeAlgebraEngine.resolve_time(
        "2025년 3분기 매출",
        _node1_period("2025-07-01", "2025-10-01", "2025년 3분기"),
        None,
        as_of,
    )
    assert naive is not None
    assert naive.start == date(2025, 7, 1)
    assert naive.end_exclusive == date(2025, 10, 1)


def test_time_algebra_caps_every_current_interval_before_today():
    """문구와 무관하게 현재 구간은 완료된 영업일 ``date < as_of``만 포함한다."""

    resolved, inherited = TimeAlgebraEngine.resolve_time(
        "8월 비스타 호텔 매출",
        _node1_period(
            "2026-08-01T00:00:00+09:00",
            "2026-09-01T00:00:00+09:00",
            "8월",
        ),
        None,
        date(2026, 8, 20),
    )

    assert inherited is False
    assert resolved is not None
    assert resolved.start == date(2026, 8, 1)
    assert resolved.end_exclusive == date(2026, 8, 20)


def test_time_algebra_rejects_malformed_candidate_without_synthesizing_period():
    """반개구간 불변식을 깨는 후보는 채택하지 않고, 기본 기간을 합성하지도 않는지 검증.

    기간을 확정하지 못하면 상위 MetricResolver가 PERIOD_REQUIRED로 닫아야 하므로
    이 단계에서 임의의 당월 기간을 만들어내면 안 된다.
    """
    as_of = date(2026, 8, 18)

    resolved, inherited = TimeAlgebraEngine.resolve_time(
        "매출 보여줘",
        _node1_period("2025-09-01", "2025-08-01", "역전된 구간"),
        None,
        as_of,
    )
    assert resolved is None
    assert not inherited

    empty, _ = TimeAlgebraEngine.resolve_time("매출 보여줘", {}, None, as_of)
    assert empty is None


def test_time_algebra_confirms_anchor_resolved_by_node1():
    """대화 앵커가 필요한 표현도 서버가 재파싱하지 않고 Node 1 후보를 확정하는지 검증.

    node1_request에 `previous_period`가 실려 나가므로 "그 전 달"의 기준점은 Node 1이
    이미 반영한다. 서버가 같은 표현을 별도 어휘로 다시 파싱하면 승인된 해석을 덮어쓴다.
    """
    as_of = date(2026, 8, 18)
    last = ResolvedTimeRange(date(2025, 8, 1), date(2025, 9, 1), "2025년 8월")

    resolved, inherited = TimeAlgebraEngine.resolve_time(
        "그 전 달은?",
        _node1_period("2025-07-01", "2025-08-01", "그 전 달"),
        last,
        as_of,
    )
    assert not inherited
    assert resolved is not None
    assert resolved.start == date(2025, 7, 1)
    assert resolved.end_exclusive == date(2025, 8, 1)


def test_time_algebra_does_not_reparse_relative_expressions_itself():
    """상대 기간 표현을 서버가 자체 계산하지 않는지 검증.

    후보 없이 상대 표현만 들어오면 직전 기간을 그대로 상속할 뿐, 개월·분기 오프셋을
    서버가 만들어내면 안 된다.
    """
    as_of = date(2026, 8, 18)
    base = ResolvedTimeRange(date(2025, 6, 1), date(2025, 7, 1), "2025년 6월")

    for message in ("2개월 전 매출은?", "3달 뒤는?", "지난달은?", "다음 달은?"):
        resolved, inherited = TimeAlgebraEngine.resolve_time(message, {}, base, as_of)
        assert inherited is True, message
        assert resolved == base, message


def test_conversation_slot_resolver_routes_and_views():
    """ANALYSIS / PRESENTATION / REPORT_ACTION 라우트 및 점진적 뷰 타입 결정론적 검증."""
    as_of = date(2026, 8, 18)

    # Turn 1: 일반 질의 (지표/요약 기본 SUMMARY)
    turn1_slots = ConversationSlotResolver.resolve(
        user_message="2025년 8월 1일 ~ 8월 15일 객실 매출 보여줘",
        node1_output={
            "selected_metric_id": "room_revenue",
            **_node1_period(
                "2025-08-01T00:00:00+09:00",
                "2025-08-16T00:00:00+09:00",
                "2025년 8월 1일 ~ 8월 15일",
            ),
        },
        previous_turns=[],
        as_of=as_of,
    )
    assert turn1_slots.route == "ANALYSIS"
    assert turn1_slots.target_chart_type == "SUMMARY"
    assert turn1_slots.time_range.start == date(2025, 8, 1)
    assert turn1_slots.time_range.end_exclusive == date(2025, 8, 16)

    prev_turn1 = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-1",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-08-16",
                "source_text": "2025년 8월 1일 ~ 8월 15일",
            },
        },
    }

    # Turn 2: "그래프로 나타내줘" (PRESENTATION -> BAR)
    turn2_slots = ConversationSlotResolver.resolve(
        user_message="그래프로 나타내줘",
        node1_output={"requested_route": "PRESENTATION", "presentation_type": "BAR"},
        previous_turns=[prev_turn1],
        as_of=as_of,
    )
    assert turn2_slots.route == "PRESENTATION"
    assert turn2_slots.target_chart_type == "BAR"
    assert turn2_slots.is_inherited_metric is True

    prev_turn2 = {
        "turn_id": "turn-2",
        "route": "PRESENTATION",
        "artifact_id": "art-1",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "target_chart_type": "BAR",
            "time_range": prev_turn1["resolved_slots"]["time_range"],
        },
    }

    # Turn 3: 표현을 지목하지 않은 전환 요청은 허용 목록을 순환한다 (BAR -> LINE)
    turn3_slots = ConversationSlotResolver.resolve(
        user_message="다른 차트로 나타내줘",
        node1_output={"requested_route": "PRESENTATION", "presentation_type": None},
        previous_turns=[prev_turn1, prev_turn2],
        as_of=as_of,
    )
    assert turn3_slots.route == "PRESENTATION"
    assert turn3_slots.target_chart_type == "LINE"

    # Turn 4: "표로도 보여줘" (PRESENTATION -> TABLE)
    turn4_slots = ConversationSlotResolver.resolve(
        user_message="표로도 보여줘",
        node1_output={"requested_route": "PRESENTATION", "presentation_type": "TABLE"},
        previous_turns=[prev_turn1, prev_turn2],
        as_of=as_of,
    )
    assert turn4_slots.route == "PRESENTATION"
    assert turn4_slots.target_chart_type == "TABLE"

    # Turn 5: "현재 내용을 보고서에 담아줘" (REPORT_ACTION)
    turn5_slots = ConversationSlotResolver.resolve(
        user_message="현재 내용을 보고서에 담아줘",
        node1_output={"requested_route": "REPORT_ACTION"},
        previous_turns=[prev_turn1, prev_turn2],
        as_of=as_of,
    )
    assert turn5_slots.route == "REPORT_ACTION"
    assert turn5_slots.source_turn_ids == ("turn-1", "turn-2")


def test_conversation_slot_resolver_metric_and_period_inheritance():
    """지표 및 기간 상속 상태 머신 검증."""
    as_of = date(2026, 8, 18)

    prev_turn = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-100",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [{"column": "property_id"}],
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-05-01",
                "end_exclusive": "2025-06-01",
                "source_text": "2025년 5월",
            },
        },
    }

    # 지표는 상속받고 기간만 "6월은?"으로 변경한 질의.
    # "6월"의 연도는 대화 맥락(직전 턴 2025년)에 의존하므로 Node 1이 그 앵커를 받은 뒤
    # 반환하는 typed 후보를 서버가 확정한다.
    turn_slots = ConversationSlotResolver.resolve(
        user_message="6월은?",
        node1_output={**_node1_period("2025-06-01", "2025-07-01", "6월"), "is_elliptical": True},
        previous_turns=[prev_turn],
        as_of=as_of,
    )
    assert turn_slots.route == "ANALYSIS"
    assert turn_slots.metric_id == "room_revenue"
    assert turn_slots.is_inherited_metric is True
    assert turn_slots.is_inherited_dimension is True
    assert turn_slots.is_inherited_period is False
    assert turn_slots.time_range.start == date(2025, 6, 1)
    assert turn_slots.time_range.end_exclusive == date(2025, 7, 1)


def test_conversation_slot_resolver_disambiguation_metric_selection():
    """모호한 지표 선택지(CLARIFICATION)가 주어졌을 때 후속 턴 선택 발화로 지표 슬롯이 해소되는지 검증."""
    as_of = date(2026, 8, 18)

    prev_turn_clarification = {
        "turn_id": "turn-ambiguous-1",
        "route": "ANALYSIS",
        "user_message": "2025년 8월 매출 보여줘",
        "resolved_slots": {
            "ambiguity_status": "NEEDS_CLARIFICATION",
            "clarification_type": "metric",
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-09-01",
                "source_text": "2025년 8월",
            },
            "disambiguation_options": [
                {
                    "label": "객실 매출",
                    "metric_id": "room_revenue",
                    "description": "판매된 객실의 총 숙박 매출",
                    "clarification_type": "metric",
                    "value": "room_revenue",
                },
                {
                    "label": "식음 매출",
                    "metric_id": "fnb_revenue",
                    "description": "레스토랑 및 연회 식음 매출",
                    "clarification_type": "metric",
                    "value": "fnb_revenue",
                },
            ],
        },
    }

    # 사용자 2차 발화: "객실 매출"
    turn2_slots = ConversationSlotResolver.resolve(
        user_message="객실 매출",
        node1_output={},
        previous_turns=[prev_turn_clarification],
        as_of=as_of,
    )

    assert turn2_slots.route == "ANALYSIS"
    assert turn2_slots.metric_id == "room_revenue"
    assert turn2_slots.is_inherited_metric is False  # 모호성 해소로 새로 확정됨
    assert turn2_slots.is_inherited_period is True  # 1턴의 2025년 8월 기간을 상속
    assert turn2_slots.time_range is not None
    assert turn2_slots.time_range.start == date(2025, 8, 1)
    assert turn2_slots.time_range.end_exclusive == date(2025, 9, 1)


def test_conversation_slot_resolver_disambiguation_period_selection():
    """모호한 기간 선택지(CLARIFICATION)가 주어졌을 때 후속 턴 선택 발화로 기간 슬롯이 해소되는지 검증."""
    as_of = date(2026, 8, 18)

    prev_turn_clarification = {
        "turn_id": "turn-ambiguous-2",
        "route": "ANALYSIS",
        "user_message": "객실 매출 보여줘",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "ambiguity_status": "NEEDS_CLARIFICATION",
            "clarification_type": "period",
            "disambiguation_options": [
                {
                    "label": "2025-08-01 ~ 2025-08-16",
                    "period_start": "2025-08-01",
                    "period_end_exclusive": "2025-08-16",
                    "description": "8월 상반기 기간으로 분석",
                    "clarification_type": "period",
                    "value": "2025-08-01:2025-08-16",
                },
                {
                    "label": "2025-08-16 ~ 2025-09-01",
                    "period_start": "2025-08-16",
                    "period_end_exclusive": "2025-09-01",
                    "description": "8월 하반기 기간으로 분석",
                    "clarification_type": "period",
                    "value": "2025-08-16:2025-09-01",
                },
            ],
        },
    }

    # 사용자 2차 발화: "2025-08-01 ~ 2025-08-16"
    turn2_slots = ConversationSlotResolver.resolve(
        user_message="2025-08-01 ~ 2025-08-16",
        node1_output={},
        previous_turns=[prev_turn_clarification],
        as_of=as_of,
    )

    assert turn2_slots.route == "ANALYSIS"
    assert turn2_slots.metric_id == "room_revenue"
    assert turn2_slots.is_inherited_metric is True
    assert turn2_slots.is_inherited_period is False
    assert turn2_slots.time_range is not None
    assert turn2_slots.time_range.start == date(2025, 8, 1)
    assert turn2_slots.time_range.end_exclusive == date(2025, 8, 16)


def test_conversation_slot_resolver_dimension_followup_is_value_agnostic():
    """차원/필터 후속 질의 판별이 특정 호텔·객실명 리터럴 없이 일반 문법 패턴만으로 동작하는지 검증.

    AGENTS.md는 특정 호텔·고객 등급 같은 업무 값을 정규식에 하드코딩하는 것을 금지한다.
    이 테스트는 코드에 등장한 적 없는 임의의 명사(예: 신규로 추가된 호텔 "선셋")도 동일한
    "명사+만/은/는/도" 문법 형태면 후속 질의로 인식되는지 확인해 값 목록에 의존하지 않음을 증명한다.
    """
    as_of = date(2026, 8, 18)
    prev_turn = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-100",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [{"column": "hotel_code"}],
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-05-01",
                "end_exclusive": "2025-06-01",
                "source_text": "2025년 5월",
            },
        },
    }

    # 코드에 하드코딩된 적 없는 임의의 호텔명("선셋")도 동일 문법으로 후속 질의 인식돼야 함
    turn_slots = ConversationSlotResolver.resolve(
        user_message="선셋만 보여줘",
        node1_output={"is_elliptical": True},
        previous_turns=[prev_turn],
        as_of=as_of,
    )
    assert turn_slots.route == "ANALYSIS"
    assert turn_slots.metric_id == "room_revenue"
    assert turn_slots.is_inherited_metric is True

    # 조사 없는 완전한 새 문장은 후속 질의로 오인하면 안 됨 (지표 후보 불일치로 신규 분석 처리)
    fresh_slots = ConversationSlotResolver.resolve(
        user_message="선셋 호텔의 전체 예약 취소 사유를 분석해줘",
        node1_output={"is_elliptical": False, "metric_candidates": ["cancellation_rate"]},
        previous_turns=[prev_turn],
        as_of=as_of,
    )
    assert fresh_slots.is_inherited_metric is False


def test_conversation_slot_resolver_dimension_add_value_via_change_set():
    """Node 1이 이전 차원에 하나를 더한 후보를 내면 AnalysisChangeSet이 ADD_VALUE로 좁혀지고
    최종 dimension_fields는 기존 것을 유지한 채 새 차원만 추가되는지 검증."""
    as_of = date(2026, 8, 18)
    prev_turn = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-1",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [{"asset_fqn": "serving.room_daily", "column": "hotel_code"}],
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-08-16",
                "source_text": "2025년 8월",
            },
        },
    }

    slots = ConversationSlotResolver.resolve(
        user_message="객실타입도 보여줘",
        node1_output={
            "is_elliptical": True,
            "dimension_fields": [
                {"asset_fqn": "serving.room_daily", "column": "hotel_code"},
                {"asset_fqn": "serving.room_daily", "column": "room_type"},
            ]
        },
        previous_turns=[prev_turn],
        as_of=as_of,
    )

    assert slots.route == "ANALYSIS"
    assert {d["column"] for d in slots.dimension_fields} == {"hotel_code", "room_type"}
    dim_changes = [c for c in slots.change_set if c.field == "dimension_fields"]
    assert len(dim_changes) == 1
    assert dim_changes[0].op.value == "ADD_VALUE"
    assert dim_changes[0].value["column"] == "room_type"


def test_conversation_slot_resolver_user_filter_exclude_via_change_set():
    """Node 1이 낸 filter_fields 후보가 이전 턴에 없는 배제(neq) 필터면 ADD_VALUE로 좁혀지고
    최종 user_filters에 반영되는지 검증. 값 자체는 아직 검증되지 않은 value_text 그대로다."""
    as_of = date(2026, 8, 18)
    prev_turn = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-1",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [],
            "user_filters": [],
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-08-16",
                "source_text": "2025년 8월",
            },
        },
    }

    slots = ConversationSlotResolver.resolve(
        user_message="선셋은 빼줘",
        node1_output={
            "filter_fields": [
                {
                    "asset_fqn": "serving.room_daily",
                    "column": "hotel_code",
                    "operator": "neq",
                    "value_text": "선셋",
                },
            ]
        },
        previous_turns=[prev_turn],
        as_of=as_of,
    )

    assert slots.route == "ANALYSIS"
    assert len(slots.user_filters) == 1
    assert slots.user_filters[0]["operator"] == "neq"
    assert slots.user_filters[0]["value_text"] == "선셋"
    filter_changes = [c for c in slots.change_set if c.field == "user_filters"]
    assert len(filter_changes) == 1
    assert filter_changes[0].op.value == "SET"


def test_conversation_slot_resolver_user_filter_preserved_across_followup():
    """이전 턴에서 확정된 user_filters는 후속 단답형 질의에서 candidate가 비어도 유지된다."""
    as_of = date(2026, 8, 18)
    prev_turn = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-1",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [],
            "user_filters": [
                {
                    "asset_fqn": "serving.room_daily",
                    "column": "hotel_code",
                    "operator": "neq",
                    "value_text": "선셋",
                }
            ],
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-08-16",
                "source_text": "2025년 8월",
            },
        },
    }

    slots = ConversationSlotResolver.resolve(
        user_message="4월은?",
        node1_output={"is_elliptical": True, "metric_candidates": ["room_revenue"]},
        previous_turns=[prev_turn],
        as_of=as_of,
    )

    assert slots.route == "ANALYSIS"
    assert len(slots.user_filters) == 1
    assert slots.user_filters[0]["value_text"] == "선셋"


def test_time_algebra_does_not_reimplement_as_of_anchored_expressions():
    """롤링 윈도우·캘린더 별칭은 서버가 문장에서 재해석하지 않는지 검증.

    "최근 3개월간", "올해", "작년"은 질문과 as_of만으로 계산 가능한 표현이므로 Node 1의
    권위 범위다. 서버가 같은 표현을 자체 lexicon으로 다시 파싱하면 거버넌스를 통과한
    Node 1 후보를 덮어쓰게 되므로, 후보 없이 호출하면 기간이 확정되지 않아야 한다.
    """
    as_of = date(2026, 8, 18)

    for message in ("최근 3개월간 객실 매출", "올해 초부터 지금까지 매출", "작년 매출 보여줘"):
        resolved, _ = TimeAlgebraEngine.resolve_time(message, {}, None, as_of)
        assert resolved is None, f"서버가 '{message}'를 자체 파싱했습니다."

    # Node 1이 현재 날짜를 포함하는 미완료 구간을 반환해도 데이터 경계는
    # [start, as_of)로 제한된다.
    rolling, _ = TimeAlgebraEngine.resolve_time(
        "최근 3개월간 객실 매출",
        _node1_period("2026-06-01", "2026-09-01", "최근 3개월간"),
        None,
        as_of,
    )
    assert rolling is not None
    assert rolling.start == date(2026, 6, 1)
    assert rolling.end_exclusive == as_of


def test_conversation_slot_resolver_backtracking_across_presentation_turn():
    """PRESENTATION 턴을 거친 후에도 1턴 전 ANALYSIS의 지표/차원이 유실 없이 역추적 상속되는지 검증."""
    as_of = date(2026, 8, 18)

    turn1_analysis = {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-100",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [{"column": "property_id", "asset_fqn": "pms.rooms"}],
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-05-01",
                "end_exclusive": "2025-06-01",
                "source_text": "2025년 5월",
            },
        },
    }

    turn2_presentation = {
        "turn_id": "turn-2",
        "route": "PRESENTATION",
        "artifact_id": "art-100",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "target_chart_type": "BAR",
            "time_range": turn1_analysis["resolved_slots"]["time_range"],
        },
    }

    # Turn 3: "다음 달은?" (Turn 2가 PRESENTATION이지만 Turn 1의 dimension_fields와 metric_id를 완벽히 상속)
    turn3_slots = ConversationSlotResolver.resolve(
        user_message="다음 달은?",
        node1_output={
            "is_elliptical": True,
            **_node1_period("2025-06-01", "2025-07-01", "다음 달"),
        },
        previous_turns=[turn1_analysis, turn2_presentation],
        as_of=as_of,
    )

    assert turn3_slots.route == "ANALYSIS"
    assert turn3_slots.metric_id == "room_revenue"
    assert turn3_slots.is_inherited_metric is True
    assert turn3_slots.is_inherited_dimension is True
    assert len(turn3_slots.dimension_fields) == 1
    assert turn3_slots.dimension_fields[0]["column"] == "property_id"
    assert turn3_slots.time_range.start == date(2025, 6, 1)
    assert turn3_slots.time_range.end_exclusive == date(2025, 7, 1)




def _prior_analysis_turn() -> dict:
    """재사용 가능한 Artifact를 가진 직전 ANALYSIS 턴을 만든다."""
    return {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "artifact_id": "art-1",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "target_chart_type": "SUMMARY",
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-09-01",
                "source_text": "2025년 8월",
            },
        },
    }


def test_route_is_decided_by_contract_signal_not_question_wording():
    """라우트가 문장 표현이 아니라 Node1의 typed route 신호로 결정되는지 검증.

    같은 발화라도 신호가 다르면 라우트가 달라지고, 신호가 없으면 모든 게이트를 거치는
    ANALYSIS로 진행해야 한다. 이로써 동의어·오타·새로운 표현이 조용히 오분류되지 않는다.
    """
    as_of = date(2026, 8, 18)
    prev = [_prior_analysis_turn()]

    # 정규식에 존재한 적 없는 표현이라도 신호만 있으면 정확히 라우팅된다.
    for message in ("꺾은선으로 보여줘", "그림으로 보여줘", "추이 좀 보게 해줘"):
        slots = ConversationSlotResolver.resolve(
            user_message=message,
            node1_output={"requested_route": "PRESENTATION", "presentation_type": "LINE"},
            previous_turns=prev,
            as_of=as_of,
        )
        assert slots.route == "PRESENTATION", message
        assert slots.target_chart_type == "LINE"

    for message in ("문서로 남겨줘", "이거 리포트로 정리해줘"):
        slots = ConversationSlotResolver.resolve(
            user_message=message,
            node1_output={"requested_route": "REPORT_ACTION"},
            previous_turns=prev,
            as_of=as_of,
        )
        assert slots.route == "REPORT_ACTION", message

    # 신호가 없으면 라우트를 추측하지 않고 ANALYSIS로 닫는다.
    assert ConversationSlotResolver.resolve(
        user_message="보고서에 담아줘",
        node1_output={},
        previous_turns=prev,
        as_of=as_of,
    ).route == "ANALYSIS"


def test_unknown_route_signal_is_not_trusted():
    """계약 enum 밖의 route 값은 신호로 승격되지 않고 ANALYSIS로 닫히는지 검증."""
    as_of = date(2026, 8, 18)
    prev = [_prior_analysis_turn()]

    for bogus in ("FORECAST", "report_action", "", "DROP TABLE"):
        slots = ConversationSlotResolver.resolve(
            user_message="보고서에 담아줘",
            node1_output={"requested_route": bogus},
            previous_turns=prev,
            as_of=as_of,
        )
        assert slots.route == "ANALYSIS", bogus


def test_presentation_signal_yields_to_a_new_measurement_request():
    """새 지표 조회가 함께 오면 PRESENTATION 신호가 있어도 ANALYSIS로 진행하는지 검증.

    재사용으로 답할 수 없는 요청을 Artifact 재사용 경로로 보내면 사용자가 요청한 새 측정이
    조용히 사라지므로, 서버가 신호를 그대로 따르지 않고 전제조건으로 다시 판단해야 한다.
    """
    slots = ConversationSlotResolver.resolve(
        user_message="식음 매출도 선 그래프로 보여줘",
        node1_output={
            "requested_route": "PRESENTATION",
            "presentation_type": "LINE",
            "selected_metric_id": "fnb_revenue",
        },
        previous_turns=[_prior_analysis_turn()],
        as_of=date(2026, 8, 18),
    )

    assert slots.route == "ANALYSIS"
    assert slots.metric_id == "fnb_revenue"


def test_presentation_type_outside_allowlist_is_rejected():
    """허용 목록 밖 표현 타입은 채택하지 않고 순환 기본값으로 닫는지 검증."""
    slots = ConversationSlotResolver.resolve(
        user_message="영역 차트로 보여줘",
        node1_output={"requested_route": "PRESENTATION", "presentation_type": "AREA"},
        previous_turns=[_prior_analysis_turn()],
        as_of=date(2026, 8, 18),
    )

    assert slots.route == "PRESENTATION"
    assert slots.target_chart_type in ConversationSlotResolver.ALLOWED_CHART_TYPES
    assert slots.target_chart_type != "AREA"


def test_slot_inheritance_requires_an_explicit_elliptical_signal():
    """생략문 신호가 없으면 직전 슬롯을 상속하지 않는지 검증.

    상속 여부를 문장 형태로 추측하면 새 질문이 이전 지표를 조용히 물려받아 사용자가
    요청하지 않은 분석이 나간다. 신호가 없을 때는 상속하지 않고 슬롯을 비워, 상위
    단계가 재질의로 닫도록 한다.
    """
    prev = [_prior_analysis_turn()]

    inherited = ConversationSlotResolver.resolve(
        user_message="6월은?",
        node1_output={"is_elliptical": True},
        previous_turns=prev,
        as_of=date(2026, 8, 18),
    )
    assert inherited.metric_id == "room_revenue"
    assert inherited.is_inherited_metric is True

    for absent in ({}, {"is_elliptical": False}, {"is_elliptical": None}):
        slots = ConversationSlotResolver.resolve(
            user_message="6월은?",
            node1_output=absent,
            previous_turns=prev,
            as_of=date(2026, 8, 18),
        )
        assert slots.metric_id is None, absent
        assert slots.is_inherited_metric is False, absent


def test_elliptical_signal_does_not_override_server_state_check():
    """생략문 신호가 있어도 이번 턴 후보가 직전 지표를 포함하지 않으면 상속하지 않는지 검증.

    이 판단은 대화 상태를 아는 서버만 할 수 있으므로 모델 신호가 이를 덮어써서는 안 된다.
    """
    slots = ConversationSlotResolver.resolve(
        user_message="취소율은?",
        node1_output={"is_elliptical": True, "metric_ids": ["cancellation_rate"]},
        previous_turns=[_prior_analysis_turn()],
        as_of=date(2026, 8, 18),
    )

    assert slots.is_inherited_metric is False


def test_presentation_yields_when_the_question_changes_the_query_shape():
    """분해·필터가 바뀌면 PRESENTATION 신호가 있어도 ANALYSIS로 가는지 검증.

    Artifact 재사용은 측정 대상·분해 기준·포함 행이 모두 그대로일 때만 성립한다.
    live 검증에서 모델이 "호텔별로도 나눠서 보여줘"를 PRESENTATION으로 분류한 사례가
    있었고, 그대로 따랐다면 사용자가 요청한 차원 분해가 조용히 사라졌다.
    """
    prev = [_prior_analysis_turn()]
    base = {"requested_route": "PRESENTATION", "presentation_type": "BAR"}

    # 차원 분해가 추가되면 재사용으로 답할 수 없다.
    by_dimension = ConversationSlotResolver.resolve(
        user_message="호텔별로도 나눠서 보여줘",
        node1_output={
            **base,
            "dimension_fields": [{"asset_fqn": "serving.room_daily", "column": "hotel_code"}],
        },
        previous_turns=prev,
        as_of=date(2026, 8, 18),
    )
    assert by_dimension.route == "ANALYSIS"

    # 행을 제한하는 필터가 추가돼도 마찬가지다.
    by_filter = ConversationSlotResolver.resolve(
        user_message="선셋만 빼고 보여줘",
        node1_output={
            **base,
            "filter_fields": [
                {
                    "asset_fqn": "serving.room_daily",
                    "column": "hotel_code",
                    "operator": "neq",
                    "value_text": "선셋",
                }
            ],
        },
        previous_turns=prev,
        as_of=date(2026, 8, 18),
    )
    assert by_filter.route == "ANALYSIS"

    # 표현만 바뀌는 요청은 그대로 재사용 경로를 탄다.
    render_only = ConversationSlotResolver.resolve(
        user_message="꺾은선으로 보여줘",
        node1_output=base,
        previous_turns=prev,
        as_of=date(2026, 8, 18),
    )
    assert render_only.route == "PRESENTATION"
