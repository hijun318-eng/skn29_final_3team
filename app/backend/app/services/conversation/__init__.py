"""Bounded Governed 멀티턴 대화 서비스 패키지.

[주요 구성 모듈]
- orchestrator.py: 대화방 수명주기, CAS 동시성 제어 및 3대 라우트(ANALYSIS, PRESENTATION, REPORT_ACTION) 총괄
- slot_resolver.py: 지표/차원/필터/기간 슬롯 해석 및 모호성 해소(Disambiguation)
- change_set.py: 5대 ChangeSet 연산(SET, CLEAR, ADD_VALUE, REMOVE_VALUE, PRESERVE) 기반 상태 전이
- time_algebra.py: 상대/절대 기간 및 캘린더 연산을 처리하는 시간 대수 엔진
- report_actions.py: 분석 결과(Artifact)를 리포트 초안(Draft)으로 컴파일 및 저장
"""

from app.services.conversation.change_set import (
    AnalysisChangeSet,
    ChangeOperation,
    SlotChange,
    apply_dimension_changes,
    apply_metric_change,
    derive_dimension_changes,
    derive_metric_change,
)
from app.services.conversation.orchestrator import ConversationOrchestrator
from app.services.conversation.reconciler import (
    ConversationReconciler,
    ConversationRecoveryWorker,
    conversation_recovery_worker,
)
from app.services.conversation.report_actions import execute_report_action
from app.services.conversation.slot_resolver import (
    ConversationSlotResolver,
    ResolvedTimeRange,
    ResolvedTurnSlots,
)
from app.services.conversation.time_algebra import TimeAlgebraEngine

# 하위 호환성을 위한 별칭
SlotResolver = ConversationSlotResolver

__all__ = [
    "ConversationOrchestrator",
    "ConversationReconciler",
    "ConversationRecoveryWorker",
    "conversation_recovery_worker",
    "ConversationSlotResolver",
    "SlotResolver",
    "ResolvedTurnSlots",
    "ResolvedTimeRange",
    "TimeAlgebraEngine",
    "AnalysisChangeSet",
    "ChangeOperation",
    "SlotChange",
    "derive_metric_change",
    "apply_metric_change",
    "derive_dimension_changes",
    "apply_dimension_changes",
    "execute_report_action",
]
