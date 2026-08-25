"""보고서 Assistant V2 핵심 승인·lineage 전이의 실행 가능한 회귀 검사다."""

from datetime import datetime, timezone
import unittest

from workflow import (
    AnalysisRequest,
    Artifact,
    ChangeKind,
    Decision,
    Phase,
    apply_decision,
    attach_new_artifact,
    resolve_approval,
    revision_saved,
    select_artifact,
    start_session,
)


def artifact(
    artifact_id: str,
    day: int,
    *,
    approved: bool = True,
    request_id: str | None = None,
) -> Artifact:
    """테스트에서 승인 상태와 생성 순서가 명확한 Artifact를 만든다."""
    return Artifact(
        artifact_id,
        f"query-{artifact_id}",
        artifact_id,
        "a" * 64,
        approved,
        datetime(2026, 8, day, tzinfo=timezone.utc),
        request_id,
    )


class ReportAssistantWorkflowTests(unittest.TestCase):
    def test_manual_and_scheduled_source_selection(self) -> None:
        old = artifact("old", 1)
        latest = artifact("latest", 3)
        unapproved = artifact("unapproved", 4, approved=False)

        self.assertEqual("old", select_artifact((old, latest), selected_id="old").artifact_id)
        self.assertEqual("latest", select_artifact((old, latest, unapproved)).artifact_id)
        with self.assertRaisesRegex(ValueError, "승인되지 않은"):
            select_artifact((unapproved,), selected_id="unapproved")

    def test_existing_artifact_change_saves_revision_without_data_agent(self) -> None:
        session = start_session("session-1", artifact("base", 1))
        saving, effect = apply_decision(session, Decision(
            ChangeKind.EXISTING_ARTIFACT,
            "차트를 표보다 위로 이동해 줘",
        ))

        self.assertEqual(Phase.SAVING_REVISION, saving.phase)
        self.assertEqual("save_revision", effect.name)
        self.assertEqual(("base",), effect.payload["artifact_ids"])
        self.assertEqual(2, revision_saved(saving, 2).revision)

    def test_new_data_waits_for_approval_before_dispatch(self) -> None:
        session = start_session("session-2", artifact("base", 1))
        request = AnalysisRequest("request-1", "지난달과 비교해 줘", "현재 근거에 지난달이 없음")
        waiting, effect = apply_decision(session, Decision(
            ChangeKind.NEW_DATA,
            "지난달과 비교해 줘",
            request,
        ))

        self.assertEqual(Phase.WAITING_APPROVAL, waiting.phase)
        self.assertEqual("request_user_approval", effect.name)
        rejected, rejected_effect = resolve_approval(waiting, False)
        self.assertEqual(Phase.READY, rejected.phase)
        self.assertIsNone(rejected_effect)

    def test_approved_new_artifact_preserves_plan_lineage(self) -> None:
        session = start_session("session-3", artifact("base", 1))
        request = AnalysisRequest("request-2", "채널별 매출을 추가해 줘", "현재 근거에 채널 차원이 없음")
        waiting, _ = apply_decision(session, Decision(ChangeKind.NEW_DATA, request.question, request))
        running, run_effect = resolve_approval(waiting, True)

        self.assertEqual("run_data_agent", run_effect.name)
        saving, save_effect = attach_new_artifact(
            running,
            artifact("channel", 2, request_id=request.request_id),
        )
        self.assertEqual(("base", "channel"), save_effect.payload["artifact_ids"])
        completed = revision_saved(saving, 2)
        self.assertEqual(Phase.READY, completed.phase)
        self.assertEqual(("base", "channel"), completed.artifact_ids)

    def test_unrelated_data_agent_artifact_is_rejected(self) -> None:
        session = start_session("session-4", artifact("base", 1))
        request = AnalysisRequest("approved-request", "비교", "근거 부족")
        waiting, _ = apply_decision(session, Decision(ChangeKind.NEW_DATA, "비교", request))
        running, _ = resolve_approval(waiting, True)

        with self.assertRaisesRegex(ValueError, "승인된 분석 계획"):
            attach_new_artifact(running, artifact("wrong", 2, request_id="other-request"))


if __name__ == "__main__":
    unittest.main()
