---
name: update-project-wbs
description: Update and validate this repository's execution WBS, schedule views, and work log when completed work changes a mapped task's schedule, status, owner, deliverable, or evidence, or when the user explicitly requests a WBS update. Do not use for routine code, document, or configuration edits with no execution-schedule impact; read-only investigation; report-only changes; Git integration; or speculative schedule changes.
---

# Update Project WBS

Keep `docs/markdown/02_WBS.md` aligned with completed repository work without inventing progress, dates, owners, or scope.

This skill updates WBS content only. It does not stage, commit, push, merge, or update project reports.

## Workflow

1. Require `docs/markdown/02_WBS.md` to exist. If it is missing, stop instead of recreating it. Read it and the relevant active contract or changed files.
2. Apply `.agents/skills/manage-project-documents/SKILL.md` because the WBS is a numbered deliverable document.
3. Map the completed work to the narrowest existing execution WBS row. Add a row only when no existing task represents the work, following the document's current phase and ID scheme.
4. Record only verified status, actual dates, evidence, and deliverables. Do not mark a task complete merely because documentation changed.
5. Add one concise work-log entry with the applicable WBS ID and changed paths.
6. When a task row, date, or status changes, synchronize every affected view: execution WBS, phase summary and total count, eight-week schedule, Mermaid Gantt, and deliverable schedule. A work-log-only change does not require artificial schedule changes.
7. Update the common metadata header and bottom change history with the actual editor and current Asia/Seoul time.
8. After the document Skill validations, run `<python> .agents/skills/update-project-wbs/scripts/validate_wbs.py docs/markdown/02_WBS.md` and review the final diff.

## Completion report

Report the updated WBS ID, whether schedule views changed, validation results, and any unresolved schedule decision. When skipped, state `WBS 갱신 제외(영향 없음/보고 전용/읽기 전용)` with the applicable reason instead of editing the WBS.
