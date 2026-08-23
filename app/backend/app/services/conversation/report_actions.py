"""REPORT_ACTION 라우트의 실데이터 Report Draft 조립 및 영속화 모듈.

[핵심 목적]
대화 오케스트레이터가 확정한 REPORT_ACTION 라우트에서 사용자가 요청한 대화 결과들을
공식 보고서 블록(TEXT, CHART, TABLE)으로 조립하고, 기존 초안(Draft)에 이어붙이거나 신규 초안을 생성합니다.

[보안 및 데이터 신뢰성 원칙]
1. 채팅 문구나 캡처 이미지를 임의로 보고서에 넣지 않습니다.
2. `report_repo.get_transfer_artifact`가 검증하고 반환하는 신뢰된 Artifact(내러티브 마크다운,
   차트 스펙 JSON, 정량 데이터 스냅샷 JSON)의 실데이터만을 사용하여 보고서 블록을 생성합니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class ReportActionPlan:
    """종결 트랜잭션 전에 준비하는 불변 Report 변경 계획."""

    report_definition_id: UUID
    artifact_id: UUID
    draft: ReportDefinitionVersion | None = None
    replacement_version: int | None = None
    replacement_blocks: tuple[ReportBlock, ...] = ()


def _select_target_turns(previous_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이전 대화 턴들 중 가장 최근의 최대 2개 고유 Artifact 턴을 시간순(Turn 순서)으로 정렬해 반환합니다.

    Args:
        previous_turns: 이전 대화 턴들의 목록

    Returns:
        최대 2개의 고유 Artifact를 가진 턴 목록 (시간 오름차순)
    """
    current_artifact = next(
        (
            str(turn["artifact_id"])
            for turn in reversed(previous_turns)
            if turn.get("route") == "ANALYSIS"
            and turn.get("terminal_status", "SUCCEEDED") == "SUCCEEDED"
            and turn.get("artifact_id")
        ),
        None,
    )
    visible_views: list[dict[str, Any]] = []
    seen_view_types: set[str] = set()
    for turn in reversed(previous_turns):
        view_type = str(
            turn.get("view_type")
            or turn.get("resolved_slots", {}).get("target_chart_type")
            or ""
        ).upper()
        if (
            turn.get("view_spec_id")
            and turn.get("terminal_status", "SUCCEEDED") == "SUCCEEDED"
            and str(turn.get("artifact_id")) == current_artifact
            and view_type not in seen_view_types
        ):
            visible_views.insert(0, turn)
            seen_view_types.add(view_type)
            if len(visible_views) >= 2:
                break
    if visible_views:
        return visible_views

    distinct_target_turns: list[dict[str, Any]] = []
    seen_artifacts: set[UUID] = set()

    for turn in reversed(previous_turns):
        art_id = turn.get("artifact_id")
        if art_id and art_id not in seen_artifacts:
            seen_artifacts.add(art_id)
            distinct_target_turns.append(turn)
            if len(distinct_target_turns) >= 2:
                break

    distinct_target_turns.reverse()
    return distinct_target_turns


async def _blocks_for_turn(
    report_repo: Any,
    turn_item: dict[str, Any],
    current_y: int,
    multi_source: bool,
) -> tuple[list[ReportBlock], int, str]:
    """선택된 단일 Artifact 턴의 실데이터로부터 TEXT(내러티브), CHART(차트), TABLE(스냅샷) 블록을 조립합니다.

    Args:
        report_repo: 보고서 영속성 저장소 인스턴스
        turn_item: 처리 대상 턴 딕셔너리
        current_y: 현재 그리드 레이아웃의 Y 좌표 시작점
        multi_source: 여러 턴의 결과를 함께 조립하는 멀티 소스 여부

    Returns:
        tuple[조립된 ReportBlock 리스트, 다음 블록 시작 Y 좌표, 턴 제목 문자열]
    """
    art_id = turn_item["artifact_id"]
    turn_msg = turn_item.get("user_message", "")
    artifact = await report_repo.get_transfer_artifact(str(art_id))
    art_id_str = str(artifact.get("artifact_id") or art_id)
    query_id_str = str(artifact.get("trino_query_id") or "")
    art_title = str(artifact.get("title") or turn_msg or "분석").strip()

    blocks: list[ReportBlock] = []

    if turn_item.get("view_spec_id"):
        view_type = str(
            turn_item.get("view_type")
            or turn_item.get("resolved_slots", {}).get("target_chart_type")
            or "TABLE"
        ).upper()
        block_type = BlockType.TABLE if view_type == "TABLE" else BlockType.CHART
        title_suffix = "표" if block_type is BlockType.TABLE else "차트"
        height = 5 if block_type is BlockType.TABLE else 7
        blocks.append(
            ReportBlock(
                block_id=str(uuid4()),
                title=f"{art_title} {title_suffix}" if multi_source else title_suffix,
                artifact_id=art_id_str,
                columns=12,
                query_id=query_id_str,
                type=block_type,
                x=0,
                y=current_y,
                w=12,
                h=height,
                content="",
                view_spec_id=str(turn_item["view_spec_id"]),
            )
        )
        return blocks, current_y + height, (
            turn_msg[:40].strip() if turn_msg else ""
        )

    # 1. TEXT 블록: 생성된 내러티브 마크다운 요약
    narrative = str(artifact.get("narrative_markdown") or "").strip()
    if narrative:
        blocks.append(
            ReportBlock(
                block_id=str(uuid4()),
                title=f"{art_title} 요약" if multi_source else "분석 요약",
                artifact_id=None,
                columns=12,
                query_id=None,
                type=BlockType.TEXT,
                x=0,
                y=current_y,
                w=12,
                h=4,
                content=narrative,
            )
        )
        current_y += 4

    # 2. CHART 블록: 차트 스펙 JSON
    chart_spec = artifact.get("chart_spec_json")
    if chart_spec and isinstance(chart_spec, dict) and chart_spec.get("y_fields"):
        blocks.append(
            ReportBlock(
                block_id=str(uuid4()),
                title=f"{art_title} 차트" if multi_source else "데이터 시각화",
                artifact_id=art_id_str,
                columns=12,
                query_id=query_id_str,
                type=BlockType.CHART,
                x=0,
                y=current_y,
                w=12,
                h=7,
                content="",
            )
        )
        current_y += 7

    # 3. TABLE 블록: 데이터 스냅샷 테이블
    snapshot = artifact.get("data_snapshot_json")
    has_snapshot = isinstance(snapshot, dict) and bool(snapshot.get("rows"))
    if has_snapshot or not chart_spec:
        blocks.append(
            ReportBlock(
                block_id=str(uuid4()),
                title=f"{art_title} 데이터" if multi_source else "상세 데이터",
                artifact_id=art_id_str,
                columns=12,
                query_id=query_id_str,
                type=BlockType.TABLE,
                x=0,
                y=current_y,
                w=12,
                h=5,
                content="",
            )
        )
        current_y += 5

    return blocks, current_y, (turn_msg[:40].strip() if turn_msg else "")


async def plan_report_action(
    report_repo: Any,
    previous_turns: list[dict[str, Any]],
) -> ReportActionPlan:
    """Validate sources and prepare a report mutation without writing state.

    [처리 흐름]
    1. 선행 분석 결과(Artifact)가 존재하는지 검증 (없으면 ValueError)
    2. 최대 2개 Artifact로부터 TEXT/CHART/TABLE 블록 목록 생성
    3. 기존 대화방에 연결된 DRAFT 보고서가 있는지 확인:
       - 이미 존재하면: 중복 블록을 제외하고 기존 그리드 하단에 새 블록 추가
       - 존재하지 않으면: 새로운 ReportDefinitionVersion (DRAFT) 생성 및 저장
    4. (report_definition_id, artifact_id) 튜플 반환

    Args:
        report_repo: 보고서 저장소 인스턴스
        previous_turns: 이전 대화 턴 목록

    Returns:
        tuple[생성/갱신된 report_definition_id, 참조된 주 artifact_id]

    Raises:
        ValueError: 보고서에 담을 선행 Artifact가 존재하지 않을 때
    """
    target_turns = [t for t in reversed(previous_turns) if t.get("artifact_id")]
    if not target_turns:
        raise ValueError("보고서에 추가할 선행 분석 결과(Artifact)가 없습니다.")

    distinct_target_turns = _select_target_turns(previous_turns)
    multi_source = len(distinct_target_turns) > 1

    blocks: list[ReportBlock] = []
    current_y = 0
    primary_title = ""

    for turn_item in distinct_target_turns:
        turn_blocks, current_y, title = await _blocks_for_turn(
            report_repo, turn_item, current_y, multi_source
        )
        blocks.extend(turn_blocks)
        if not primary_title and title:
            primary_title = title

    # 블록이 생성되지 않은 경우 최소 1개의 TABLE 블록을 fallback으로 추가
    if not blocks:
        first_art = distinct_target_turns[0]
        first_artifact = await report_repo.get_transfer_artifact(str(first_art["artifact_id"]))
        blocks.append(
            ReportBlock(
                block_id=str(uuid4()),
                title="상세 데이터",
                artifact_id=str(first_art["artifact_id"]),
                columns=12,
                query_id=str(first_artifact.get("trino_query_id") or ""),
                type=BlockType.TABLE,
                x=0,
                y=0,
                w=12,
                h=5,
                content="",
            )
        )

    # 이전 턴들 중 이미 생성된 report_definition_id가 있는지 확인
    existing_report_def_id = None
    for turn in reversed(previous_turns):
        if turn.get("report_definition_id"):
            existing_report_def_id = turn["report_definition_id"]
            break

    report_def_id = None
    replacement_version = None
    replacement_blocks: tuple[ReportBlock, ...] = ()
    if existing_report_def_id:
        try:
            existing_ver = await report_repo.get_version(str(existing_report_def_id), 1)
            if existing_ver.status == DefinitionStatus.DRAFT:
                existing_blocks = list(existing_ver.blocks)
                existing_art_ids = {b.artifact_id for b in existing_blocks if b.artifact_id}
                new_unique_blocks = [b for b in blocks if not b.artifact_id or b.artifact_id not in existing_art_ids]
                if not new_unique_blocks:
                    new_unique_blocks = blocks

                max_y = max((b.y + b.h for b in existing_blocks), default=0)
                adjusted_new_blocks = []
                curr_y = max_y + 1 if max_y > 0 else 0
                for block in new_unique_blocks:
                    adjusted_new_blocks.append(
                        ReportBlock(
                            block_id=block.block_id,
                            title=block.title,
                            artifact_id=block.artifact_id,
                            columns=block.columns,
                            query_id=block.query_id,
                            type=block.type,
                            x=block.x,
                            y=curr_y,
                            w=block.w,
                            h=block.h,
                            content=block.content,
                            view_spec_id=block.view_spec_id,
                        )
                    )
                    curr_y += block.h

                combined_blocks = tuple(existing_blocks + adjusted_new_blocks)
                replacement_version = existing_ver.version
                replacement_blocks = combined_blocks
                report_def_id = existing_report_def_id
        except Exception as update_err:
            logger.info("기존 draft %s 갱신 실패, 새 draft 생성으로 대체: %s", existing_report_def_id, update_err)
            existing_report_def_id = None

    # 기존 draft가 없거나 갱신에 실패한 경우 새 DRAFT 보고서 생성
    if not existing_report_def_id:
        report_def_id = uuid4()
        report_title = f"{primary_title} 보고서" if primary_title else "대화형 분석 보고서"
        draft_def = ReportDefinitionVersion(
            definition_id=str(report_def_id),
            version=1,
            status=DefinitionStatus.DRAFT,
            title=report_title,
            blocks=tuple(blocks),
            orientation="portrait",
            currency_display_unit="auto",
        )
    else:
        draft_def = None

    return ReportActionPlan(
        report_definition_id=UUID(str(report_def_id)),
        artifact_id=UUID(str(distinct_target_turns[-1]["artifact_id"])),
        draft=draft_def,
        replacement_version=replacement_version,
        replacement_blocks=replacement_blocks,
    )


async def apply_report_action_plan(
    report_repo: Any,
    plan: ReportActionPlan,
    session: Any | None = None,
) -> None:
    """준비된 Report 변경을 가능하면 호출자 세션의 트랜잭션 안에서 적용한다."""

    if plan.draft is not None:
        writer = getattr(report_repo, "add_draft_in_session", None)
        if session is not None and callable(writer):
            await writer(session, plan.draft)
        else:
            await report_repo.add_draft(plan.draft)
        return
    if plan.replacement_version is None:
        raise ValueError("Report action plan has no terminal mutation")
    writer = getattr(report_repo, "replace_draft_blocks_in_session", None)
    if session is not None and callable(writer):
        await writer(
            session,
            str(plan.report_definition_id),
            plan.replacement_version,
            plan.replacement_blocks,
        )
    else:
        await report_repo.replace_draft_blocks(
            definition_id=str(plan.report_definition_id),
            version=plan.replacement_version,
            blocks=plan.replacement_blocks,
        )


async def execute_report_action(
    report_repo: Any,
    previous_turns: list[dict[str, Any]],
) -> tuple[UUID, UUID]:
    """Conversation 밖의 호출자를 위해 계획과 적용을 연속 수행하는 호환 래퍼."""

    plan = await plan_report_action(report_repo, previous_turns)
    await apply_report_action_plan(report_repo, plan)
    return plan.report_definition_id, plan.artifact_id
