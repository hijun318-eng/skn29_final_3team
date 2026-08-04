---
name: update-project-wbs
description: >-
  Update execution WBS, schedule views, and work log for verified mapped-task changes. Use for "update the WBS", "WBS 업데이트", or "일정·진척·담당자·산출물·근거 반영". Exclude no-impact, read-only/report-only, Git integration, and speculative updates.
---

# 프로젝트 WBS 갱신

## 절차

1. `docs/markdown/02_WBS.md`가 있는지 확인한다. 없으면 다시 만들지 않고 중단한다. 해당 문서와 관련 active contract 또는 변경 파일을 읽는다.
2. WBS는 번호 산출물 문서이므로 `.agents/skills/manage-project-documents/SKILL.md`를 적용한다.
3. 완료된 작업을 가장 좁은 기존 실행 WBS 행에 매핑한다. 기존 task가 작업을 나타내지 못할 때만 문서의 현재 phase와 ID 체계에 따라 행을 추가한다.
4. 검증된 상태, 실제 날짜, 근거, deliverable만 기록한다. 문서만 바뀌었다는 이유로 task를 완료 처리하지 않는다.
5. 해당 WBS ID와 변경 path를 포함한 간결한 work log 항목 하나를 추가한다.
6. task 행, 날짜 또는 상태가 바뀌면 영향받은 모든 view인 실행 WBS, phase 요약과 전체 count, 8주 일정, Mermaid Gantt, deliverable 일정을 동기화한다. work-log-only 변경에는 인위적인 일정 변경을 만들지 않는다.
7. 문서 Skill 검증 후 `<python> .agents/skills/update-project-wbs/scripts/validate_wbs.py docs/markdown/02_WBS.md`를 실행하고 최종 diff를 검토한다.

## 완료 보고

일정 view 변경 여부와 미해결 일정 결정을 `AGENTS.md`의 완료 보고에 추가한다.
