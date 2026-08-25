"""보고서 Assistant V2의 승인·Artifact lineage 상태 전이를 검증하는 독립 프로토타입이다."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import re


CHECKSUM = re.compile(r"^[0-9a-f]{64}$")


class Phase(str, Enum):
    """서버가 소유해야 하는 보고서 Assistant 세션 단계다."""

    READY = "ready"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING_DATA_AGENT = "running_data_agent"
    SAVING_REVISION = "saving_revision"


class ChangeKind(str, Enum):
    """모델이 제안할 수 있지만 직접 실행할 수는 없는 변경 분류다."""

    EXISTING_ARTIFACT = "existing_artifact"
    NEW_DATA = "new_data"


@dataclass(frozen=True)
class Artifact:
    """승인 상태와 checksum을 포함한 Assistant 입력 Artifact의 최소 계약이다."""

    artifact_id: str
    query_id: str
    title: str
    checksum: str
    approved: bool
    created_at: datetime
    request_id: str | None = None


@dataclass(frozen=True)
class AnalysisRequest:
    """사용자 승인 화면에 노출할 새 데이터 분석 계획이다."""

    request_id: str
    question: str
    reason: str


@dataclass(frozen=True)
class Decision:
    """보고서 모델의 비신뢰 출력에서 검증을 마친 변경 제안이다."""

    kind: ChangeKind
    instruction: str
    analysis_request: AnalysisRequest | None = None


@dataclass(frozen=True)
class Effect:
    """상태 전이 뒤 외부 adapter가 수행해야 할 명령이다."""

    name: str
    payload: object


@dataclass(frozen=True)
class Session:
    """보고서 한 편집 세션의 단계, revision, 근거 Artifact와 대기 계획을 보존한다."""

    session_id: str
    phase: Phase
    revision: int
    artifact_ids: tuple[str, ...]
    pending_request: AnalysisRequest | None = None
    pending_instruction: str | None = None


def _validate_artifact(artifact: Artifact) -> None:
    if not artifact.approved:
        raise ValueError("승인되지 않은 Artifact는 보고서 근거로 사용할 수 없습니다.")
    if not CHECKSUM.fullmatch(artifact.checksum):
        raise ValueError("Artifact checksum 형식이 올바르지 않습니다.")


def select_artifact(
    artifacts: tuple[Artifact, ...],
    *,
    selected_id: str | None = None,
) -> Artifact:
    """수동 선택 ID 또는 스케줄 실행용 최신 승인 Artifact를 결정한다.

    ``selected_id``가 없으면 승인 Artifact 중 ``created_at``이 가장 최근인 항목을 사용한다.
    후보가 없거나 수동 대상이 승인되지 않았으면 성공처럼 대체하지 않고 실패한다.
    """
    if selected_id is not None:
        artifact = next(
            (item for item in artifacts if item.artifact_id == selected_id),
            None,
        )
        if artifact is None:
            raise ValueError("선택한 Artifact를 찾을 수 없습니다.")
    else:
        approved = tuple(item for item in artifacts if item.approved)
        if not approved:
            raise ValueError("스케줄 실행에 사용할 승인 Artifact가 없습니다.")
        artifact = max(approved, key=lambda item: item.created_at)
    _validate_artifact(artifact)
    return artifact


def start_session(session_id: str, artifact: Artifact, revision: int = 1) -> Session:
    """검증된 최초 Artifact와 저장된 초안 revision으로 편집 세션을 연다."""
    _validate_artifact(artifact)
    if revision < 1:
        raise ValueError("revision은 1 이상이어야 합니다.")
    return Session(session_id, Phase.READY, revision, (artifact.artifact_id,))


def apply_decision(session: Session, decision: Decision) -> tuple[Session, Effect]:
    """변경 제안을 기존 근거 편집 또는 사용자 승인 대기로만 전이한다."""
    if session.phase is not Phase.READY:
        raise ValueError("진행 중인 작업이 끝난 뒤 새 지시를 제출할 수 있습니다.")
    if not decision.instruction.strip():
        raise ValueError("편집 지시는 비어 있을 수 없습니다.")
    if decision.kind is ChangeKind.EXISTING_ARTIFACT:
        if decision.analysis_request is not None:
            raise ValueError("기존 Artifact 편집에는 새 분석 계획을 포함할 수 없습니다.")
        saving = replace(
            session,
            phase=Phase.SAVING_REVISION,
            pending_instruction=decision.instruction.strip(),
        )
        return saving, Effect("save_revision", {
            "base_revision": session.revision,
            "instruction": saving.pending_instruction,
            "artifact_ids": session.artifact_ids,
        })
    if decision.analysis_request is None:
        raise ValueError("새 데이터 변경에는 승인 가능한 분석 계획이 필요합니다.")
    waiting = replace(
        session,
        phase=Phase.WAITING_APPROVAL,
        pending_request=decision.analysis_request,
        pending_instruction=decision.instruction.strip(),
    )
    return waiting, Effect("request_user_approval", decision.analysis_request)


def resolve_approval(session: Session, approved: bool) -> tuple[Session, Effect | None]:
    """사용자 승인만 Data Agent 실행 명령으로 바꾸며 거절 시 안전하게 편집 상태로 복귀한다."""
    if session.phase is not Phase.WAITING_APPROVAL or session.pending_request is None:
        raise ValueError("승인 대기 중인 분석 계획이 없습니다.")
    if not approved:
        return replace(
            session,
            phase=Phase.READY,
            pending_request=None,
            pending_instruction=None,
        ), None
    return replace(session, phase=Phase.RUNNING_DATA_AGENT), Effect(
        "run_data_agent",
        session.pending_request,
    )


def attach_new_artifact(session: Session, artifact: Artifact) -> tuple[Session, Effect]:
    """승인 계획과 일치하는 새 Artifact만 lineage에 추가하고 revision 저장을 요청한다."""
    if session.phase is not Phase.RUNNING_DATA_AGENT or session.pending_request is None:
        raise ValueError("Data Agent 결과를 기다리는 세션이 아닙니다.")
    _validate_artifact(artifact)
    if artifact.request_id != session.pending_request.request_id:
        raise ValueError("Artifact가 승인된 분석 계획에서 생성되지 않았습니다.")
    if artifact.artifact_id in session.artifact_ids:
        raise ValueError("이미 연결된 Artifact입니다.")
    artifact_ids = (*session.artifact_ids, artifact.artifact_id)
    saving = replace(session, phase=Phase.SAVING_REVISION, artifact_ids=artifact_ids)
    return saving, Effect("save_revision", {
        "base_revision": session.revision,
        "instruction": session.pending_instruction,
        "artifact_ids": artifact_ids,
    })


def revision_saved(session: Session, revision: int) -> Session:
    """CAS 저장 성공으로 받은 다음 revision만 적용하고 세션을 입력 가능 상태로 되돌린다."""
    if session.phase is not Phase.SAVING_REVISION:
        raise ValueError("저장 중인 revision이 없습니다.")
    if revision != session.revision + 1:
        raise ValueError("저장된 revision이 예상한 CAS 순서와 다릅니다.")
    return replace(
        session,
        phase=Phase.READY,
        revision=revision,
        pending_request=None,
        pending_instruction=None,
    )
