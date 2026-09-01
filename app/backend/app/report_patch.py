"""검증된 Artifact 별칭과 제한된 모델 patch를 실제 draft block 변경으로 변환한다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import uuid4

from app.report_contracts import REPORT_MAX_BLOCKS, ReportAssistantPatch
from src.report.domain import (
    BlockType,
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionVersion,
    normalize_report_block_content,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ATOMIC_ARTIFACT_VIEWS = frozenset({"summary", "kpi", "chart", "table"})
_ARTIFACT_VIEW_LABELS = {
    "summary": "요약",
    "kpi": "핵심 지표",
    "chart": "차트",
    "table": "표",
}
_DEFAULT_HEIGHT = {
    BlockType.TEXT: 4,
    BlockType.CHART: 7,
    BlockType.TABLE: 5,
    BlockType.ARTIFACT: 12,
    BlockType.PAGE_BREAK: 1,
}
_ATOMIC_DEFAULT_HEIGHT = {
    "summary": 5,
    "kpi": 6,
    "chart": 7,
    "table": 5,
}


def artifact_view_title(source_title: str, view: str) -> str:
    """서버 소유 Artifact 제목과 한국어 view 역할로 변경 불가 block 제목을 만든다."""

    normalized = str(source_title).strip()
    label = _ARTIFACT_VIEW_LABELS.get(view)
    if not normalized or label is None:
        raise ValueError("검증 Artifact view 제목을 만들 수 없습니다.")
    suffix = f" · {label}"
    return f"{normalized[:255 - len(suffix)].rstrip()}{suffix}"


def artifact_view_default_height(view: str) -> int:
    """신규 원자 Artifact view의 renderer 최소 높이를 단일 계약으로 반환한다."""

    try:
        return _ATOMIC_DEFAULT_HEIGHT[view]
    except KeyError as error:
        raise ValueError("지원하지 않는 원자 Artifact view입니다.") from error


class ReportPatchNoChangesError(ValueError):
    """검증된 patch가 현재 Report와 의미상 같아 Revision이 불필요함을 나타낸다."""


@dataclass(frozen=True, slots=True)
class VerifiedArtifactBinding:
    """상류 repository가 owner·request·approval·query로 검증한 Artifact 참조를 고정한다."""

    artifact_id: str
    query_id: str
    checksum: str
    source_title: str
    available_views: frozenset[str]

    def __post_init__(self) -> None:
        normalized_title = str(self.source_title).strip()
        normalized_views = frozenset(self.available_views)
        if (
            not self.artifact_id
            or not self.query_id
            or not _SHA256.fullmatch(self.checksum)
            or not normalized_title
            or len(normalized_title) > 255
            or not normalized_views.issubset(ATOMIC_ARTIFACT_VIEWS)
        ):
            raise ValueError("검증 Artifact binding이 완전하지 않습니다.")
        object.__setattr__(self, "source_title", normalized_title)
        object.__setattr__(self, "available_views", normalized_views)


def validate_report_patch_operation_dependencies(patch: ReportAssistantPatch) -> None:
    """삭제 대상과 같은 block을 동시에 사용하거나 반복 변경하는 모순 patch를 거부한다.

    선택 조합의 권위는 모델 설명이 아니라 typed operation의 기존 block·anchor 참조다. 실제
    block ID는 오류에 포함하지 않으며 최종 구조 유효성은 적용기의 dry-run이 이어서 확인한다.
    """

    removed = {
        operation.block_id
        for operation in patch.operations
        if operation.op == "remove_block"
    }
    used_targets = {
        operation.block_id
        for operation in patch.operations
        if operation.op in {
            "update_text", "update_block_title", "resize_block", "reposition_block",
            "duplicate_block", "update_chart_settings", "update_table_settings",
            "set_block_size_mode",
        }
    }
    anchors: set[str] = set()
    for operation in patch.operations:
        if operation.op == "reposition_block" and operation.after_block_id:
            anchors.add(operation.after_block_id)
        elif (
            operation.op in {"add_text", "add_artifact_view"}
            and operation.placement.after_block_id
        ):
            anchors.add(operation.placement.after_block_id)
    if removed & (used_targets | anchors):
        raise ValueError("Report patch operation 선택에 서로 충돌하는 block 변경이 있습니다.")

    unique_targets: set[tuple[str, str]] = set()
    for operation in patch.operations:
        if operation.op in {
            "set_report_title", "set_report_orientation", "set_currency_display_unit",
            "compact_report_layout",
        }:
            key = (operation.op, "report")
        elif operation.op in {
            "update_text", "update_block_title", "resize_block", "reposition_block",
            "remove_block", "update_chart_settings", "update_table_settings",
            "set_block_size_mode",
        }:
            key = (operation.op, operation.block_id)
        else:
            continue
        if key in unique_targets:
            raise ValueError("Report patch가 같은 대상을 중복 변경합니다.")
        unique_targets.add(key)


def report_patch_operation_dependencies(
    patch: ReportAssistantPatch,
) -> tuple[tuple[int, ...], ...]:
    """ordered typed operation에서 서버 소유의 backward-only page 의존성을 계산한다.

    모델은 dependency를 입력할 수 없다. 뒤에 추가되는 각 페이지는 직전 추가 페이지를,
    명시적 anchor 없이 그 페이지 뒤에 놓이는 신규 content와 이동은 가장 최근 페이지를
    의존한다. 따라서 반환 그래프는 구성상 forward edge와 cycle을 만들 수 없다.
    """

    dependencies: list[tuple[int, ...]] = []
    latest_page_index: int | None = None
    for index, operation in enumerate(patch.operations):
        dependency: tuple[int, ...] = ()
        if operation.op == "add_report_page":
            if latest_page_index is not None:
                dependency = (latest_page_index,)
            latest_page_index = index
        elif latest_page_index is not None:
            if (
                operation.op in {"add_text", "add_artifact_view"}
                and operation.placement.after_block_id is None
            ) or (
                operation.op == "reposition_block"
                and operation.after_block_id is None
            ):
                dependency = (latest_page_index,)
        if any(item >= index for item in dependency):
            raise ValueError("Report patch operation 의존성이 이전 operation만 참조하지 않습니다.")
        dependencies.append(dependency)
    return tuple(dependencies)


def validate_report_patch_dependency_selection(
    patch: ReportAssistantPatch,
    selected_indexes: tuple[int, ...],
) -> None:
    """부분 승인 선택이 서버 계산 dependency를 모두 포함할 때만 저장을 허용한다."""

    if (
        not selected_indexes
        or tuple(sorted(set(selected_indexes))) != selected_indexes
        or any(index < 0 or index >= len(patch.operations) for index in selected_indexes)
    ):
        raise ValueError("Report patch operation 선택 범위가 올바르지 않습니다.")
    selected = set(selected_indexes)
    dependencies = report_patch_operation_dependencies(patch)
    if any(
        dependency not in selected
        for index in selected_indexes
        for dependency in dependencies[index]
    ):
        raise ValueError("Report patch operation 선택이 필요한 선행 변경을 포함하지 않습니다.")


def _replace_block(block: ReportBlock, **changes: object) -> ReportBlock:
    """한 block의 지정 필드만 바꾼 새 불변 값을 만들고 lineage 필드는 그대로 유지한다."""

    values = {
        "block_id": block.block_id, "title": block.title,
        "artifact_id": block.artifact_id, "columns": block.columns,
        "query_id": block.query_id, "type": block.type, "x": block.x, "y": block.y,
        "w": block.w, "h": block.h, "content": block.content,
        "evidence_refs": block.evidence_refs, "view_spec_id": block.view_spec_id,
    }
    values.update(changes)
    return ReportBlock(**values)


def _block_settings(block: ReportBlock) -> dict[str, object]:
    """비-text block의 JSON 설정만 객체로 읽고 손상된 값은 빈 설정으로 닫는다."""

    if block.type is BlockType.TEXT or not block.content:
        return {}
    try:
        value = json.loads(block.content)
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _with_settings(block: ReportBlock, changes: dict[str, object]) -> ReportBlock:
    """typed 허용값만 기존 renderer 설정에 병합해 결정적 JSON으로 저장한다."""

    settings = {**_block_settings(block), **changes}
    content = json.dumps(
        settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _replace_block(
        block,
        content=normalize_report_block_content(block.type, content),
    )


def _minimum_block_height(block: ReportBlock) -> int:
    """원자 Artifact block과 legacy 합본의 서로 다른 최소 높이를 결정한다."""

    if block.type is BlockType.ARTIFACT:
        visible_views = _block_settings(block).get("visibleViews")
        if (
            isinstance(visible_views, list)
            and len(visible_views) == 1
            and visible_views[0] in {"summary", "kpi"}
        ):
            return _ATOMIC_DEFAULT_HEIGHT[visible_views[0]]
    return _DEFAULT_HEIGHT[block.type]


def _compact_blocks(blocks: list[ReportBlock]) -> list[ReportBlock]:
    """시각 순서·폭과 명시적 페이지 경계를 유지하며 빈 세로 공간을 제거한다."""

    ordered = sorted(enumerate(blocks), key=lambda item: (item[1].y, item[1].x, item[0]))
    placed: dict[str, ReportBlock] = {}
    row: list[ReportBlock] = []
    row_y = row_x = row_height = 0

    def finish_row() -> None:
        nonlocal row, row_y, row_x, row_height
        for item in row:
            placed[item.block_id] = _replace_block(item, h=row_height)
        row_y += row_height
        row, row_x, row_height = [], 0, 0

    for _, block in ordered:
        if block.type is BlockType.PAGE_BREAK:
            if row:
                finish_row()
            placed[block.block_id] = _replace_block(
                block, columns=12, x=0, y=row_y, w=12, h=1,
            )
            row_y += 1
            continue
        if row_x and block.w > 12 - row_x:
            finish_row()
        item = _replace_block(block, columns=block.w, x=row_x, y=row_y, w=block.w)
        row.append(item)
        row_x += block.w
        row_height = max(row_height, block.h)
        if row_x == 12:
            finish_row()
    if row:
        finish_row()
    return [placed[item.block_id] for item in blocks]


def _blocks_overlap(left: ReportBlock, right: ReportBlock) -> bool:
    """두 block의 현재 12열 grid 사각형이 실제로 겹치는지 확인한다."""

    return (
        left.x < right.x + right.w
        and left.x + left.w > right.x
        and left.y < right.y + right.h
        and left.y + left.h > right.y
    )


def _resolve_block_collisions(
    blocks: list[ReportBlock],
    anchor_id: str,
) -> list[ReportBlock]:
    """anchor 좌표는 유지하고 충돌하는 block만 아래로 이동한다."""

    anchor = next((item for item in blocks if item.block_id == anchor_id), None)
    if anchor is None:
        return blocks
    order = {item.block_id: index for index, item in enumerate(blocks)}
    ordered = sorted(
        (item for item in blocks if item.block_id != anchor_id),
        key=lambda item: (item.y, item.x, order[item.block_id]),
    )
    placed = [anchor]
    resolved = {anchor.block_id: anchor}
    for block in ordered:
        candidate = block
        while True:
            collisions = [item for item in placed if _blocks_overlap(candidate, item)]
            if not collisions:
                break
            candidate = _replace_block(
                candidate,
                y=max(item.y + item.h for item in collisions),
            )
        placed.append(candidate)
        resolved[candidate.block_id] = candidate
    return [resolved[item.block_id] for item in blocks]


def _insert_block(
    blocks: list[ReportBlock],
    block: ReportBlock,
    after_block_id: str | None,
) -> None:
    """새 block을 상대 위치에 고정하고 실제 충돌 block만 아래로 이동한다."""

    if after_block_id is None:
        insert_y = max((item.y + item.h for item in blocks), default=0)
    else:
        target = next((item for item in blocks if item.block_id == after_block_id), None)
        if target is None:
            raise ValueError("Report patch의 기준 block을 찾을 수 없습니다.")
        insert_y = target.y + target.h
        while True:
            crossing_bottoms = [
                item.y + item.h
                for item in blocks
                if item.x < block.w
                and item.x + item.w > 0
                and item.y < insert_y
                and item.y + item.h > insert_y
            ]
            if not crossing_bottoms:
                break
            insert_y = max(crossing_bottoms)
    candidate = ReportBlock(
            block.block_id,
            block.title,
            block.artifact_id,
            block.columns,
            block.query_id,
            block.type,
            0,
            insert_y,
            block.w,
            block.h,
            block.content,
            block.evidence_refs,
            block.view_spec_id,
        )
    blocks.append(candidate)
    blocks[:] = _resolve_block_collisions(blocks, candidate.block_id)


def apply_report_assistant_patch(
    definition: ReportDefinitionVersion,
    patch: ReportAssistantPatch,
    artifact_bindings: dict[str, VerifiedArtifactBinding],
    previous_definition: ReportDefinitionVersion | None = None,
) -> ReportDefinitionVersion:
    """모델 patch를 draft에 적용하되 ID·Artifact·block type·layout 권위는 서버가 유지한다.

    모델은 기존 block ID와 서버가 제공한 Artifact 별칭만 참조할 수 있다. 임의 Artifact ID,
    query ID, checksum, 좌표는 입력받지 않으며 어느 연산이 실패해도 원본 definition은 바뀌지 않는다.
    """

    if definition.status is not DefinitionStatus.DRAFT:
        raise ValueError("Report Assistant patch는 draft에만 적용할 수 있습니다.")
    validate_report_patch_operation_dependencies(patch)
    if patch.operations[0].op == "restore_previous_revision":
        if (
            previous_definition is None
            or previous_definition.definition_id != definition.definition_id
            or previous_definition.version != definition.version - 1
        ):
            raise ValueError("복원할 직전 Report revision을 찾을 수 없습니다.")
        restored = definition.replace_blocks(
            previous_definition.blocks,
            title=previous_definition.title,
            orientation=previous_definition.orientation,
            currency_display_unit=previous_definition.currency_display_unit,
        )
        if restored == definition:
            raise ReportPatchNoChangesError("Report patch가 실제 변경을 만들지 않습니다.")
        return restored
    blocks = list(definition.blocks)
    title = definition.title
    orientation = definition.orientation
    currency_display_unit = definition.currency_display_unit
    latest_insert_for_anchor: dict[str, str] = {}
    for operation in patch.operations:
        target_block_id = getattr(operation, "block_id", None)
        target_block = next(
            (item for item in blocks if item.block_id == target_block_id),
            None,
        )
        if target_block is not None and target_block.type is BlockType.PAGE_BREAK:
            raise ValueError("페이지 경계 수정은 현재 지원하지 않습니다.")
        if operation.op == "set_report_title":
            if title == operation.title:
                raise ReportPatchNoChangesError("보고서 제목 operation이 실제 변경을 만들지 않습니다.")
            title = operation.title
            continue
        if operation.op == "set_report_orientation":
            if orientation == operation.orientation:
                raise ReportPatchNoChangesError("보고서 방향 operation이 실제 변경을 만들지 않습니다.")
            orientation = operation.orientation
            continue
        if operation.op == "set_currency_display_unit":
            if currency_display_unit == operation.currency_display_unit:
                raise ReportPatchNoChangesError("통화 단위 operation이 실제 변경을 만들지 않습니다.")
            currency_display_unit = operation.currency_display_unit
            continue
        if operation.op == "compact_report_layout":
            blocks = _compact_blocks(blocks)
            continue
        if operation.op == "add_report_page":
            _insert_block(
                blocks,
                ReportBlock(
                    str(uuid4()), "새 페이지", None, 12, None,
                    BlockType.PAGE_BREAK, 0, 0, 12, 1, "",
                ),
                None,
            )
            continue
        if operation.op in {
            "update_block_title", "resize_block", "update_chart_settings",
            "update_table_settings", "set_block_size_mode",
        }:
            index = next(
                (position for position, item in enumerate(blocks) if item.block_id == operation.block_id),
                None,
            )
            if index is None:
                raise ValueError("Report patch의 설정 대상 block을 찾을 수 없습니다.")
            source = blocks[index]
            if operation.op == "update_block_title":
                if source.type is not BlockType.TEXT:
                    raise ValueError("분석 Artifact view block 제목은 변경할 수 없습니다.")
                if source.title == operation.title:
                    raise ReportPatchNoChangesError("블록 제목 operation이 실제 변경을 만들지 않습니다.")
                blocks[index] = _replace_block(source, title=operation.title)
            elif operation.op == "resize_block":
                minimum_width = 4 if source.type is BlockType.TEXT else 6
                minimum_height = _minimum_block_height(source)
                if operation.block_width < minimum_width or operation.block_height < minimum_height:
                    raise ValueError("Report block 크기가 유형별 최소 범위보다 작습니다.")
                resized = _replace_block(
                    source, columns=operation.block_width, w=operation.block_width,
                    h=operation.block_height,
                    x=min(source.x, 12 - operation.block_width),
                )
                blocks[index] = (
                    _with_settings(resized, {"sizeMode": "manual"})
                    if source.type is not BlockType.TEXT else resized
                )
                blocks = _resolve_block_collisions(blocks, source.block_id)
            elif operation.op == "update_chart_settings":
                if source.type is not BlockType.CHART:
                    raise ValueError("chart 설정은 chart block에만 적용할 수 있습니다.")
                changes = {
                    key: value for key, value in {
                        "chartType": operation.chart_type,
                        "showLegend": operation.show_legend,
                        "sizeMode": operation.size_mode,
                    }.items() if value is not None
                }
                blocks[index] = _with_settings(source, changes)
            elif operation.op == "update_table_settings":
                if source.type is not BlockType.TABLE:
                    raise ValueError("table 설정은 table block에만 적용할 수 있습니다.")
                changes = {
                    key: value for key, value in {
                        "density": operation.density,
                        "showRowNumbers": operation.show_row_numbers,
                        "sizeMode": operation.size_mode,
                    }.items() if value is not None
                }
                blocks[index] = _with_settings(source, changes)
            else:
                if source.type not in {BlockType.CHART, BlockType.TABLE, BlockType.ARTIFACT}:
                    raise ValueError("자동 크기 모드는 분석 view block에만 적용할 수 있습니다.")
                blocks[index] = _with_settings(source, {"sizeMode": operation.size_mode})
            continue
        if operation.op == "remove_block":
            if len(blocks) == 1:
                raise ValueError("Report의 마지막 block은 제거할 수 없습니다.")
            index = next(
                (position for position, item in enumerate(blocks) if item.block_id == operation.block_id),
                None,
            )
            if index is None:
                raise ValueError("Report patch의 삭제 대상 block을 찾을 수 없습니다.")
            blocks.pop(index)
            continue
        if operation.op == "duplicate_block":
            source = next(
                (item for item in blocks if item.block_id == operation.block_id),
                None,
            )
            if source is None:
                raise ValueError("Report patch의 복제 대상 block을 찾을 수 없습니다.")
            _insert_block(
                blocks,
                ReportBlock(
                    str(uuid4()),
                    source.title,
                    source.artifact_id,
                    source.columns,
                    source.query_id,
                    source.type,
                    0,
                    0,
                    source.w,
                    source.h,
                    source.content,
                    source.evidence_refs,
                    source.view_spec_id,
                ),
                source.block_id,
            )
            continue
        if operation.op == "reposition_block":
            index = next(
                (position for position, item in enumerate(blocks) if item.block_id == operation.block_id),
                None,
            )
            if index is None:
                raise ValueError("Report patch의 이동 대상 block을 찾을 수 없습니다.")
            width = 6 if operation.width == "half" else 12
            source = blocks[index]
            ordered_ids = [
                item.block_id
                for item in sorted(blocks, key=lambda item: (item.y, item.x, item.block_id))
            ]
            ordered_index = ordered_ids.index(source.block_id)
            current_anchor = ordered_ids[ordered_index - 1] if ordered_index else None
            already_at_end = ordered_index == len(ordered_ids) - 1
            if source.w == width and (
                (operation.after_block_id is None and already_at_end)
                or operation.after_block_id == current_anchor
            ):
                continue
            blocks.pop(index)
            _insert_block(
                blocks,
                ReportBlock(
                    source.block_id,
                    source.title,
                    source.artifact_id,
                    width,
                    source.query_id,
                    source.type,
                    0,
                    0,
                    width,
                    source.h,
                    source.content,
                    source.evidence_refs,
                    source.view_spec_id,
                ),
                operation.after_block_id,
            )
            continue
        if operation.op == "update_text":
            index = next(
                (position for position, item in enumerate(blocks) if item.block_id == operation.block_id),
                None,
            )
            if index is None or blocks[index].type is not BlockType.TEXT:
                raise ValueError("Report patch의 수정 대상 text block을 찾을 수 없습니다.")
            source = blocks[index]
            blocks[index] = ReportBlock(
                source.block_id,
                operation.title or source.title,
                None,
                source.columns,
                None,
                BlockType.TEXT,
                source.x,
                source.y,
                source.w,
                source.h,
                operation.content or source.content,
                operation.evidence_refs if operation.content is not None else source.evidence_refs,
                source.view_spec_id,
            )
            continue
        width = 6 if operation.placement.width == "half" else 12
        if operation.op == "add_text":
            block_type = BlockType.TEXT
            artifact_id = None
            query_id = None
            content = operation.content
        else:
            binding = artifact_bindings.get(operation.artifact_ref)
            if binding is None:
                raise ValueError("Report patch가 허용되지 않은 Artifact 별칭을 참조했습니다.")
            if operation.view in ATOMIC_ARTIFACT_VIEWS:
                if operation.view not in binding.available_views:
                    raise ValueError("요청한 Artifact view를 검증된 결과에서 사용할 수 없습니다.")
                expected_title = artifact_view_title(binding.source_title, operation.view)
                if operation.title != expected_title:
                    raise ValueError("Artifact view 제목이 서버 검증 제목과 일치하지 않습니다.")
            block_type = (
                BlockType.ARTIFACT
                if operation.view in {"summary", "kpi"}
                else BlockType(operation.view)
            )
            artifact_id = binding.artifact_id
            query_id = binding.query_id
            settings: dict[str, object] = {"sizeMode": operation.size_mode}
            if operation.view in {"summary", "kpi"}:
                settings.update({
                    "schemaVersion": "ANSWER-ARTIFACT-BLOCK-v1",
                    "presentationMode": "standard",
                    "visibleViews": [operation.view],
                })
            elif operation.view == "chart":
                settings.update({
                    "visibleViews": ["chart"],
                    "showLegend": True if operation.show_legend is None else operation.show_legend,
                    **({"chartType": operation.chart_type} if operation.chart_type else {}),
                })
            elif operation.view == "table":
                settings.update({
                    "visibleViews": ["table"],
                    "density": operation.density or "comfortable",
                    "showRowNumbers": bool(operation.show_row_numbers),
                })
            content = json.dumps(
                settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        requested_anchor = operation.placement.after_block_id
        effective_anchor = (
            latest_insert_for_anchor.get(requested_anchor, requested_anchor)
            if requested_anchor is not None
            else None
        )
        new_block_id = str(uuid4())
        _insert_block(
            blocks,
            ReportBlock(
                new_block_id,
                operation.title,
                artifact_id,
                width,
                query_id,
                block_type,
                0,
                0,
                width,
                (
                    _ATOMIC_DEFAULT_HEIGHT[operation.view]
                    if operation.op == "add_artifact_view"
                    and operation.view in ATOMIC_ARTIFACT_VIEWS
                    else _DEFAULT_HEIGHT[block_type]
                ),
                content,
                operation.evidence_refs if operation.op == "add_text" else (),
                None,
            ),
            effective_anchor,
        )
        if requested_anchor is not None:
            latest_insert_for_anchor[requested_anchor] = new_block_id
    if len(blocks) > REPORT_MAX_BLOCKS:
        raise ValueError("Report block은 최대 100개까지 저장할 수 있습니다.")
    patched = definition.replace_blocks(
        tuple(blocks), title=title, orientation=orientation,
        currency_display_unit=currency_display_unit,
    )
    if patched == definition:
        raise ReportPatchNoChangesError("Report patch가 실제 변경을 만들지 않습니다.")
    return patched
