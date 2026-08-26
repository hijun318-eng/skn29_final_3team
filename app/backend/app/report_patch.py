"""검증된 Artifact 별칭과 제한된 모델 patch를 실제 draft block 변경으로 변환한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from app.report_contracts import ReportAssistantPatch
from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_HEIGHT = {
    BlockType.TEXT: 4,
    BlockType.CHART: 7,
    BlockType.TABLE: 5,
    BlockType.ARTIFACT: 12,
}


@dataclass(frozen=True, slots=True)
class VerifiedArtifactBinding:
    """상류 repository가 owner·request·approval·query로 검증한 Artifact 참조를 고정한다."""

    artifact_id: str
    query_id: str
    checksum: str

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.query_id or not _SHA256.fullmatch(self.checksum):
            raise ValueError("검증 Artifact binding이 완전하지 않습니다.")


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
        if operation.op in {"update_text", "reposition_block", "duplicate_block"}
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
        if operation.op == "set_report_title":
            key = (operation.op, "report")
        elif operation.op in {"update_text", "reposition_block", "remove_block"}:
            key = (operation.op, operation.block_id)
        else:
            continue
        if key in unique_targets:
            raise ValueError("Report patch가 같은 대상을 중복 변경합니다.")
        unique_targets.add(key)


def _insert_block(
    blocks: list[ReportBlock],
    block: ReportBlock,
    after_block_id: str | None,
) -> None:
    """상대 위치를 현재 block ID로 검증하고 기존 layout을 아래로 이동해 삽입한다."""

    if after_block_id is None:
        insert_y = max((item.y + item.h for item in blocks), default=0)
    else:
        target = next((item for item in blocks if item.block_id == after_block_id), None)
        if target is None:
            raise ValueError("Report patch의 기준 block을 찾을 수 없습니다.")
        insert_y = target.y + target.h
    shifted = [
        ReportBlock(
            item.block_id,
            item.title,
            item.artifact_id,
            item.columns,
            item.query_id,
            item.type,
            item.x,
            item.y + block.h if item.y >= insert_y else item.y,
            item.w,
            item.h,
            item.content,
            item.evidence_refs,
        )
        for item in blocks
    ]
    blocks[:] = shifted
    blocks.append(
        ReportBlock(
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
        )
    )


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
        return definition.replace_blocks(
            previous_definition.blocks,
            title=previous_definition.title,
            orientation=previous_definition.orientation,
            currency_display_unit=previous_definition.currency_display_unit,
        )
    blocks = list(definition.blocks)
    title = definition.title
    latest_insert_for_anchor: dict[str, str] = {}
    for operation in patch.operations:
        if operation.op == "set_report_title":
            title = operation.title
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
            source = blocks.pop(index)
            width = 6 if operation.width == "half" else 12
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
            block_type = BlockType(operation.view)
            artifact_id = binding.artifact_id
            query_id = binding.query_id
            content = ""
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
                _DEFAULT_HEIGHT[block_type],
                content,
                operation.evidence_refs if operation.op == "add_text" else (),
            ),
            effective_anchor,
        )
        if requested_anchor is not None:
            latest_insert_for_anchor[requested_anchor] = new_block_id
    return definition.replace_blocks(tuple(blocks), title=title)
