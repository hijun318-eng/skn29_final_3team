"""사용자 발화 라우팅 정확도 측정 하니스.

[핵심 목적]
자연어 요청이 올바른 대화 라우트(ANALYSIS / PRESENTATION / REPORT_ACTION)로 해석되는지를
고정된 발화 세트로 반복 측정한다. 목적은 "동작한다"가 아니라 수치로 회귀를 잡는 것이다.

[두 해석기 비교]
- ``contract``: 현재 운영 경로. Node1이 typed route 신호를 반환하고 서버가 확정한다.
- ``lexicon``: 계약 도입 이전 방식의 재현. 질문 문구를 정규식 키워드로 분기한다.

계약 경로 측정에는 실제 모델을 호출하지 않고, 각 발화에 대해 모델이 의도를 정확히 식별한
경우의 신호를 주입한다. 따라서 이 수치는 **서버 라우팅 계약의 상한**을 뜻하며 모델 자체의
분류 정확도가 아니다. 모델 정확도는 live 평가에서 따로 측정해야 한다.

[사용]
    python evals/nlu_route_accuracy.py            # 두 방식 비교표
    python evals/nlu_route_accuracy.py --json     # 기계 판독용 요약
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
# backend 패키지와 저장소 root를 함께 올린다. context 계층이 `src.ai` 계약 모듈을
# 참조하므로 둘 중 하나만 올리면 import가 끊긴다.
for entry in (str(BACKEND), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.services.conversation.slot_resolver import ConversationSlotResolver  # noqa: E402

AS_OF = date(2026, 8, 18)

# 계약 도입 이전에 production에 있던 정규식. 비교 기준선으로만 보존하며 운영 경로는
# 더 이상 이 사전을 사용하지 않는다.
_LEXICON_REPORT = re.compile(r"(?:보고서|리포트)\s*(?:에|으로)?\s*(?:담아|추가|넣어|반영|생성|작성|포함)")
_LEXICON_VIEW = re.compile(
    r"(?:그래프|차트|표|테이블|라인|바차트|막대|선\s*그래프|영역|가로\s*막대|원형|파이)"
    r"\s*(?:로|으로|도|로도|형태로|로는|으론)?\s*"
    r"(?:보여|나타내|바꿔|띄워|표시|변환|그려|뽑아|출력|해줘)"
)
_LEXICON_VIEW_ALT = re.compile(r"다른\s*(?:차트|그래프|모양|형식|뷰)")
_LEXICON_VIEW_SHORT = re.compile(
    r"^(?:표|그래프|차트|라인|바차트|막대)(?:로|으로|도|로도)?\s*(?:보여줘|나타내줘|해줘)?$"
)


@dataclass(frozen=True)
class Utterance:
    """평가 발화 한 건.

    Attributes:
        text: 사용자 발화 원문
        expected_route: 사람이 판단한 정답 라우트
        note: 해당 발화가 무엇을 검증하는지에 대한 짧은 설명
    """

    text: str
    expected_route: str
    note: str


# 평가 세트는 정규식이 이미 담고 있던 표현(대조군)과, 같은 의도를 다르게 말한 표현
# (동의어·완곡어법·구어체)을 함께 포함한다. 특정 호텔·지표 같은 업무 값은 넣지 않는다.
UTTERANCES: tuple[Utterance, ...] = (
    Utterance("그래프로 나타내줘", "PRESENTATION", "정규식이 담고 있던 표준 표현"),
    Utterance("표로 보여줘", "PRESENTATION", "정규식이 담고 있던 표준 표현"),
    Utterance("꺾은선으로 보여줘", "PRESENTATION", "사전에 없는 차트 명칭"),
    Utterance("시각화해줘", "PRESENTATION", "차트 명칭 없는 상위 표현"),
    Utterance("그림으로 보여줘", "PRESENTATION", "구어체 동의어"),
    Utterance("추이 좀 보게 해줘", "PRESENTATION", "의도만 있고 명칭 없음"),
    Utterance("이거 표 형태가 나을듯", "PRESENTATION", "서술어 없는 완곡 표현"),
    Utterance("한눈에 들어오게 바꿔줘", "PRESENTATION", "명칭·서술어 모두 사전 밖"),
    Utterance("보고서에 담아줘", "REPORT_ACTION", "정규식이 담고 있던 표준 표현"),
    Utterance("현재 내용을 보고서에 담아줘", "REPORT_ACTION", "정규식이 담고 있던 표준 표현"),
    Utterance("이거 리포트로 정리해줘", "REPORT_ACTION", "사전에 없는 서술어"),
    Utterance("문서로 남겨줘", "REPORT_ACTION", "사전에 없는 명사·서술어"),
    Utterance("보고서 초안 만들어줘", "REPORT_ACTION", "어순 변형"),
    Utterance("결재 올릴 수 있게 정리해줘", "REPORT_ACTION", "업무 맥락 완곡 표현"),
    Utterance("2025년 8월 객실 매출 보여줘", "ANALYSIS", "신규 측정 요청"),
    Utterance("작년 대비 얼마나 늘었어?", "ANALYSIS", "비교 측정 요청"),
    Utterance("식음 매출도 선 그래프로 보여줘", "ANALYSIS", "표현 요청이 섞여도 새 측정이 우선"),
    Utterance("호텔별로 나눠서 알려줘", "ANALYSIS", "차원 추가 측정 요청"),
)


def route_by_lexicon(utterance: Utterance, previous_turns: list[dict]) -> str:
    """계약 도입 이전 정규식 방식으로 라우트를 판정합니다.

    Args:
        utterance: 평가 발화
        previous_turns: 직전 턴 목록(정규식 방식은 사용하지 않으나 서명을 맞춘다)

    Returns:
        판정된 라우트 문자열
    """
    text = utterance.text
    if _LEXICON_REPORT.search(text):
        return "REPORT_ACTION"
    if _LEXICON_VIEW.search(text) or _LEXICON_VIEW_ALT.search(text) or _LEXICON_VIEW_SHORT.search(text):
        # 원본 구현은 새 지표 후보가 없을 때만 PRESENTATION으로 승격했다.
        return "PRESENTATION"
    return "ANALYSIS"


def route_by_contract(utterance: Utterance, previous_turns: list[dict]) -> str:
    """현재 운영 경로(Node1 typed 신호 + 서버 확정)로 라우트를 판정합니다.

    모델이 발화의 의도를 정확히 식별했을 때의 신호를 주입해, 서버 라우팅 계약이 그 신호를
    올바르게 확정하는지를 측정한다.

    Args:
        utterance: 평가 발화
        previous_turns: 직전 턴 목록

    Returns:
        서버가 확정한 라우트 문자열
    """
    signal: dict[str, object] = {}
    if utterance.expected_route == "PRESENTATION":
        signal = {"requested_route": "PRESENTATION", "selected_metric_id": None}
    elif utterance.expected_route == "REPORT_ACTION":
        signal = {"requested_route": "REPORT_ACTION", "selected_metric_id": None}
    else:
        # 새 측정 요청에서는 모델이 지표를 함께 식별한다. "식음 매출도 선 그래프로"처럼
        # 표현 요청이 섞인 경우까지 포함해 서버가 측정 우선으로 닫는지 확인한다.
        signal = {"requested_route": "PRESENTATION", "selected_metric_id": "some_metric"}

    return ConversationSlotResolver.resolve(
        user_message=utterance.text,
        node1_output=signal,
        previous_turns=previous_turns,
        as_of=AS_OF,
    ).route


def _previous_turns() -> list[dict]:
    """재사용 가능한 선행 분석이 존재하는 대화 상태를 만든다."""
    return [
        {
            "turn_id": "turn-1",
            "route": "ANALYSIS",
            "artifact_id": "artifact-1",
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
    ]


def evaluate() -> dict[str, object]:
    """두 해석 방식의 라우팅 정확도를 계산합니다.

    Returns:
        방식별 정확도와 발화별 판정을 담은 요약 딕셔너리
    """
    previous_turns = _previous_turns()
    rows: list[dict[str, object]] = []
    hits = {"lexicon": 0, "contract": 0}

    for utterance in UTTERANCES:
        lexicon = route_by_lexicon(utterance, previous_turns)
        contract = route_by_contract(utterance, previous_turns)
        hits["lexicon"] += lexicon == utterance.expected_route
        hits["contract"] += contract == utterance.expected_route
        rows.append(
            {
                "utterance": utterance.text,
                "expected": utterance.expected_route,
                "lexicon": lexicon,
                "contract": contract,
                "note": utterance.note,
            }
        )

    total = len(UTTERANCES)
    return {
        "total": total,
        "lexicon_correct": hits["lexicon"],
        "contract_correct": hits["contract"],
        "lexicon_accuracy": round(hits["lexicon"] / total, 4),
        "contract_accuracy": round(hits["contract"] / total, 4),
        "rows": rows,
    }


def main() -> int:
    """평가를 실행하고 결과를 출력합니다.

    Returns:
        계약 경로가 정규식 경로보다 나쁘면 1, 그 외 0
    """
    parser = argparse.ArgumentParser(description="사용자 발화 라우팅 정확도 측정")
    parser.add_argument("--json", action="store_true", help="기계 판독용 JSON으로 출력")
    args = parser.parse_args()

    summary = evaluate()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"{'발화':<26} {'정답':<14} {'정규식':<14} {'계약':<14}")
        print("-" * 70)
        for row in summary["rows"]:
            lex = f"{row['lexicon']}{'' if row['lexicon'] == row['expected'] else ' X'}"
            con = f"{row['contract']}{'' if row['contract'] == row['expected'] else ' X'}"
            print(f"{row['utterance']:<26} {row['expected']:<14} {lex:<14} {con:<14}")
        print("-" * 70)
        print(
            f"정규식 {summary['lexicon_correct']}/{summary['total']}"
            f" ({summary['lexicon_accuracy']:.1%})   "
            f"계약 {summary['contract_correct']}/{summary['total']}"
            f" ({summary['contract_accuracy']:.1%})"
        )

    return 0 if summary["contract_correct"] >= summary["lexicon_correct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
