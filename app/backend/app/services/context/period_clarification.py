"""기간 후보를 사용자 재질의 선택지로 변환하는 모듈.

[핵심 목적]
Node1이 기간을 단일 구간으로 좁히지 못했을 때, 서버가 사용자에게 제시할 결정론적
선택지와 추천 문구를 만든다. 새 기간을 추측해 만들어내지 않고 이미 해석된 후보만
사용자 선택지로 승격한다.
"""

from __future__ import annotations

from typing import Any

from app.contracts import ClarificationType, DisambiguationOption


def period_suggestions(candidates: object) -> tuple[str, ...]:
    """기간 후보에서 사용자에게 보여줄 원문 표현만 뽑아냅니다.

    Args:
        candidates: Node1 기간 후보 목록(비목록이면 빈 결과)

    Returns:
        후보의 `source_text` 튜플
    """
    if not isinstance(candidates, (list, tuple)):
        return ()
    return tuple(
        str(candidate["source_text"])
        for candidate in candidates
        if isinstance(candidate, dict)
        and isinstance(candidate.get("source_text"), str)
    )


def disambiguation_options_for_metrics(
    metric_ids: list[str],
    metric_terms: dict[str, dict[str, Any]],
) -> tuple[DisambiguationOption, ...]:
    """승인된 지표 후보를 typed 사용자 선택지로 변환합니다."""
    options: list[DisambiguationOption] = []
    for mid in metric_ids:
        term = metric_terms.get(mid, {})
        label = str(term.get("label") or mid)
        definition = str(term.get("definition") or f"{label} 지표 분석")
        options.append(
            DisambiguationOption(
                label=label,
                metric_id=mid,
                description=definition,
                clarification_type=ClarificationType.METRIC,
                value=mid,
            )
        )
    return tuple(options)


def disambiguation_options_for_periods(
    candidates: object,
) -> tuple[DisambiguationOption, ...]:
    """기간 후보를 재질의용 typed 선택지로 변환합니다.

    Args:
        candidates: Node1 기간 후보 목록(비목록이면 빈 결과)

    Returns:
        시작·종료 경계가 모두 있는 후보만 담은 선택지 튜플
    """
    if not isinstance(candidates, (list, tuple)):
        return ()
    options: list[DisambiguationOption] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            source_text = str(candidate.get("source_text") or "")
            start = str(candidate.get("start") or "")
            end = str(candidate.get("end_exclusive") or "")
            if start and end:
                options.append(
                    DisambiguationOption(
                        label=source_text or f"{start} ~ {end}",
                        period_start=start,
                        period_end_exclusive=end,
                        description=f"{source_text or start} 기간으로 분석",
                        clarification_type=ClarificationType.PERIOD,
                        value=f"{start}:{end}",
                    )
                )
    return tuple(options)
