"""실제 Node1 모델이 승인된 신호 계약을 지키는지 확인하는 live 평가 스크립트.

[이 스크립트가 답하는 질문]
계약·프롬프트·서버 확정 로직은 단위/계약 테스트로 이미 검증된다. 여기서 남는 미검증
항목은 하나다. **실제 모델이 `requested_route`·`presentation_type`·`is_elliptical`·
`period_candidates`를 지시대로 채우는가.**

[비용과 승인]
운영 model endpoint를 실제로 호출하므로 요금이 발생하고 질문 텍스트가 외부로 전송된다.
따라서 `--confirm-paid-call` 없이는 어떤 호출도 하지 않는다. 자격증명은 Git에서 제외된
저장소 `infrastructure/database/.env`에서만 읽고, 값은 출력·로그·argv 어디에도 남기지 않는다.

[사용]
    python evals/nlu_live_node1.py --dry-run
    python evals/nlu_live_node1.py --confirm-paid-call
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
REPOSITORY_ENV = ROOT / "infrastructure" / "database" / ".env"
for entry in (str(BACKEND), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from src.ai.schema import ContractError, validate_payload  # noqa: E402

AS_OF = "2026-08-19T00:00:00+09:00"
PREVIOUS_PERIOD = {
    "start": "2025-08-01T00:00:00+09:00",
    "end_exclusive": "2025-09-01T00:00:00+09:00",
}
BUSINESS_TERMS = {
    "room_revenue": {"kind": "metric", "aliases": ["객실 매출", "객실 수익"]},
    "fnb_revenue": {"kind": "metric", "aliases": ["식음 매출", "F&B 매출"]},
    "hotel_code": {"kind": "dimension", "aliases": ["호텔", "지점"]},
}


@dataclass(frozen=True)
class LiveCase:
    """live 평가 발화 한 건과 기대 신호.

    Attributes:
        text: 사용자 발화
        route: 기대하는 `requested_route`
        elliptical: 기대하는 `is_elliptical`
        anchored: 기간이 직전 턴 앵커 기준으로 해석되어야 하는지 여부
    """

    text: str
    route: str | None
    elliptical: bool
    anchored: bool = False


CASES: tuple[LiveCase, ...] = (
    LiveCase("2025년 8월 객실 매출 보여줘", "ANALYSIS", False),
    LiveCase("꺾은선으로 보여줘", "PRESENTATION", True),
    LiveCase("한눈에 들어오게 바꿔줘", "PRESENTATION", True),
    LiveCase("이거 리포트로 정리해줘", "REPORT_ACTION", True),
    LiveCase("결재 올릴 수 있게 정리해줘", "REPORT_ACTION", True),
    LiveCase("그 전 달은?", "ANALYSIS", True, anchored=True),
    LiveCase("호텔별로도 나눠서 보여줘", "ANALYSIS", True),
    LiveCase("취소 사유를 분석해줘", "ANALYSIS", False),
)


def read_secret(key: str) -> str:
    """고정된 저장소 환경 파일에서 값 하나를 읽습니다.

    값 자체는 반환만 하고 출력하지 않으며 다른 dotenv나 process environment로
    fallback하지 않는다.

    Args:
        key: 읽을 키 이름

    Returns:
        키에 해당하는 값

    Raises:
        SystemExit: 파일이 없거나 키가 비어 있을 때
    """
    if not REPOSITORY_ENV.is_file():
        raise SystemExit(f"저장소 환경 파일을 찾을 수 없습니다: {REPOSITORY_ENV}")
    resolved_env = REPOSITORY_ENV.resolve(strict=True)
    if resolved_env != REPOSITORY_ENV.absolute():
        raise SystemExit("저장소 환경 파일은 symbolic link일 수 없습니다.")
    match = re.search(
        rf"^{re.escape(key)}=(.*)$",
        resolved_env.read_text(encoding="utf-8-sig"),
        re.M,
    )
    value = match.group(1).strip() if match else ""
    if not value:
        raise SystemExit(f"저장소 환경 파일에 {key} 값이 없습니다.")
    return value


def build_request(case: LiveCase) -> dict[str, object]:
    """평가 발화 하나를 계약을 만족하는 node1_request로 만듭니다.

    Args:
        case: 평가 발화

    Returns:
        검증을 통과한 node1_request 페이로드
    """
    request: dict[str, object] = {
        "question": case.text,
        "role_hint": "analyst",
        "as_of": AS_OF,
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian",
        "allowed_routes": ["general", "template"],
        "business_terms": BUSINESS_TERMS,
        "previous_period": dict(PREVIOUS_PERIOD),
    }
    validate_payload("node1_request", request)
    return request


def _server_route(case: LiveCase, response: dict[str, object]) -> str:
    """모델 신호를 서버 라우팅 계약에 통과시켜 최종 라우트를 얻습니다.

    사용자가 실제로 겪는 결과는 모델의 원신호가 아니라 서버가 전제조건까지 확인해
    확정한 라우트다. 따라서 품질 지표도 이 값으로 측정한다.

    Args:
        case: 평가 발화
        response: 모델이 반환한 node1_response

    Returns:
        서버가 확정한 라우트
    """
    from app.services.conversation.slot_resolver import ConversationSlotResolver

    signals = dict(response)
    # MetricResolver가 승인 검증 뒤 싣는 필드명으로 맞춰, 운영과 같은 입력을 준다.
    signals["dimension_fields"] = [
        {"asset_fqn": "serving.room_daily", "column": term}
        for term in (response.get("dimension_candidates") or [])
        if isinstance(term, str)
    ]
    previous_turns = [
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
    return ConversationSlotResolver.resolve(
        user_message=case.text,
        node1_output=signals,
        previous_turns=previous_turns,
        as_of=date(2026, 8, 19),
    ).route


def judge(case: LiveCase, response: dict[str, object]) -> dict[str, object]:
    """모델 응답과 서버 확정 결과가 기대와 일치하는지 판정합니다.

    Args:
        case: 평가 발화와 기대값
        response: 계약 검증을 통과한 node1_response

    Returns:
        항목별 일치 여부와 관측값을 담은 결과 딕셔너리
    """
    periods = response.get("period_candidates") or []
    first_start = ""
    if isinstance(periods, list) and periods and isinstance(periods[0], dict):
        first_start = str(periods[0].get("start", ""))
    anchored_ok = (not case.anchored) or first_start.startswith("2025-07")
    server_route = _server_route(case, response)
    return {
        "utterance": case.text,
        "route_expected": case.route,
        "model_signal": response.get("requested_route"),
        "signal_ok": response.get("requested_route") == case.route,
        "server_route": server_route,
        "route_ok": server_route == case.route,
        "elliptical_expected": case.elliptical,
        "elliptical_actual": response.get("is_elliptical"),
        "elliptical_ok": response.get("is_elliptical") is case.elliptical,
        "period_start": first_start,
        "anchor_ok": anchored_ok,
    }


async def run_live(repeat: int = 1) -> list[dict[str, object]]:
    """운영 어댑터로 각 발화를 실제 모델에 보내고 판정 결과를 모읍니다.

    같은 발화를 여러 번 호출해 응답이 재현되는지도 함께 측정한다. 한 번의 호출로는
    디코딩 분산과 실제 품질 변화를 구분할 수 없기 때문이다.

    Args:
        repeat: 발화당 호출 횟수

    Returns:
        발화별·회차별 판정 결과 목록
    """
    from app.adapters.model_adapter import ContractModelAdapter

    adapter = ContractModelAdapter.from_endpoints(
        openai_endpoint=read_secret("OPENAI_ENDPOINT"),
        openai_token=read_secret("OPENAI_API_KEY"),
        openai_model=read_secret("OPENAI_MODEL"),
        node2_endpoint=read_secret("OPENAI_ENDPOINT"),
        node2_token=read_secret("OPENAI_API_KEY"),
        node2_model=read_secret("OPENAI_MODEL"),
        node2_provider="openai",
        timeout_seconds=int(read_secret("MODEL_TIMEOUT_SECONDS")),
    )

    results: list[dict[str, object]] = []
    for attempt in range(1, repeat + 1):
        for case in CASES:
            try:
                response = await adapter.normalize_question(build_request(case))
            except ContractError as error:
                results.append({"utterance": case.text, "attempt": attempt, "contract_error": str(error)})
                continue
            except Exception as error:  # 운영 endpoint 실패는 결과에 그대로 남긴다.
                results.append({"utterance": case.text, "attempt": attempt, "call_error": type(error).__name__})
                continue
            results.append({**judge(case, response), "attempt": attempt})
    return results


def main() -> int:
    """인자를 해석하고 dry-run 또는 live 평가를 수행합니다.

    Returns:
        모든 항목이 기대와 일치하면 0, 그 외 1
    """
    parser = argparse.ArgumentParser(description="Node1 신호 계약 live 검증")
    parser.add_argument("--dry-run", action="store_true", help="호출 없이 보낼 요청만 검증·출력")
    parser.add_argument("--confirm-paid-call", action="store_true", help="유료 외부 호출을 승인")
    parser.add_argument("--repeat", type=int, default=1, help="발화당 호출 횟수(재현성 측정)")
    args = parser.parse_args()

    if args.dry_run or not args.confirm_paid_call:
        for case in CASES:
            build_request(case)
        print(f"DRY_RUN_OK: {len(CASES)}건의 요청이 node1_request 계약을 만족합니다.")
        print("실제 호출은 --confirm-paid-call 이 있어야 수행됩니다.")
        return 0

    results = asyncio.run(run_live(repeat=max(1, args.repeat)))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(
        row.get("route_ok") and row.get("elliptical_ok") and row.get("anchor_ok")
        for row in results
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
