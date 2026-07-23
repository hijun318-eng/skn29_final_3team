---
name: update-project-wbs
description: Update and validate this repository's execution WBS, schedule views, and work log when completed work changes a mapped task's schedule, status, owner, deliverable, or evidence, or when the user explicitly requests a WBS update. Do not use for routine code, document, or configuration edits with no execution-schedule impact; read-only investigation; report-only changes; Git integration; or speculative schedule changes.
---

# Update Project WBS

Keep `docs/markdown/02_WBS.md` aligned with completed repository work without inventing progress, dates, owners, or scope.

## Decide whether to run

Run this skill when verified work changes the schedule, status, owner, deliverable, or evidence of an execution WBS task, or when the user explicitly requests a WBS update. Skip it when:

- no repository file changed;
- only a personal daily report, date-based team summary, or weekly report changed;
- the requested work is investigation or explanation only.
- a routine document, code, or configuration change has no effect on an execution WBS task.

This skill updates WBS content only. It does not stage, commit, push, merge, or update project reports.

## Workflow

1. Confirm the repository root, current branch, and working tree. Preserve unrelated changes.
2. Read `docs/markdown/02_WBS.md` and the relevant active contract or changed files.
3. Apply `.agents/skills/manage-project-documents/SKILL.md` because the WBS is a numbered deliverable document.
4. Map the completed work to the narrowest existing execution WBS row. Add a row only when no existing task represents the work, following the document's current phase and ID scheme.
5. Record only verified status, actual dates, evidence, and deliverables. Do not mark a task complete merely because documentation changed.
6. Add one concise work-log entry with the applicable WBS ID and changed paths.
7. When a task row, date, or status changes, synchronize every affected view: execution WBS, phase summary and total count, eight-week schedule, Mermaid Gantt, and deliverable schedule. A work-log-only change does not require artificial schedule changes.
8. Update the common metadata header and bottom change history with the actual editor and current Asia/Seoul time.
9. Run the document-policy validator on `docs/markdown/02_WBS.md`, then run `git diff --check` and review the final diff.

## Guardrails

- Treat `docs/markdown/02_WBS.md` as the schedule source of truth; do not duplicate its task table inside this skill.
- Keep template-required structure intact and inspect the mapped WBS template when structural fields change.
- Do not infer an author, owner, completion percentage, schedule shift, or deliverable state.
- Treat `docs/markdown/ai_docs/` as reference material and do not use it to override the active WBS; do not edit protected originals under `docs/templates/`.
- Avoid recursive records: WBS updates caused solely by report maintenance are excluded.

## Completion report

Report the updated WBS ID, whether schedule views changed, validation results, and any unresolved schedule decision. When skipped, state `WBS 갱신 제외(영향 없음/보고 전용/읽기 전용)` with the applicable reason instead of editing the WBS.
