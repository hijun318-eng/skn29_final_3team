---
name: update-project-reports
description: Update and validate plain-language personal daily reports, presentation-ready team daily summaries, and weekday-based weekly reports in this repository. Use after a file-changing task on a recognized personal branch, when the user requests reporting for a date or period, or when merge-branch-to-dev invokes post-merge report integration. Never infer an author on dev/main, perform Git integration actions, update WBS, or create recursive entries for report-only changes.
---

# Update Project Reports

Use `docs/markdown/daily_reports/README.md` as the canonical source for branch mapping, report evidence, formats, periods, and limits.

## Select the mode

- **Personal completion:** After a non-report repository change on a recognized personal branch, update only that branch's `일일보고.md`.
- **Requested period:** When the user specifies a date or period, update the applicable date summaries and weekly reports from the five personal reports.
- **Post-merge integration:** Accept the source branch, pre-merge `base` SHA, and post-merge `head` SHA from `merge-branch-to-dev`; update only affected `team_summaries/` files and return their paths plus validation results.

## Personal report workflow

1. Confirm the current branch and its mapped report file from the canonical README. On `main`, `dev`, or an unmapped branch, do not infer an author.
2. Use the current KST date unless the user explicitly supplies another date.
3. Record only repository results that remain after the task. Exclude investigation-only answers, commit-message drafting, Git operations, and report-only maintenance.
4. Add to the existing date block or create the newest block below the file notice. Use up to three short bullets labeled `오늘 한 일`, `결과`, and `공유할 내용`; omit an empty label rather than inventing content.
5. Write for a teammate who did not perform the work. Use one idea per sentence, explain necessary product names once, and replace internal English terms with ordinary Korean when the exact term is not needed.
6. From the repository root, validate the changed file with `<python> .agents/skills/update-project-reports/scripts/validate_reports.py --date <YYYYMMDD> <changed report path>` and `git diff --check`.

## Team and weekly workflow

1. In post-merge mode, require `source`, `base`, and `head`; verify that `base` is an ancestor of `head` and `head` is the current commit. Compare the source member's personal report at both SHAs and select dates whose complete blocks changed. Add dates with no team summary; honor an explicit user range first.
2. Read all five personal `일일보고.md` files directly. Do not use a date summary as the source of truth.
3. Resolve the official week from `docs/markdown/ai_docs/최종_프로젝트_산출물_및_전체_일정.md`.
4. For each target date, write a presentation-ready team summary with `오늘 팀 진행 상황` and `팀원별 발표 메모`. Include all five mapped members as headings, give each member at most two short bullets, use `보고 없음` when the source block is missing, and do not use a dense summary table.
5. Rebuild each affected weekly report with exactly three content sections: `이번 주 진행 상황`, `이번 주에 진행한 것`, and `앞으로 진행할 내용`. Under `이번 주에 진행한 것`, group source-backed results under `요일 (YYYYMMDD)` headings.
6. Keep the weekly status brief, and include future work only when a personal report explicitly records a remaining, blocked, or next task. Otherwise write `확인된 다음 작업 없음`.
7. Write all team and weekly content as speaking notes: one idea per sentence, ordinary Korean first, and no unexplained internal IDs or abbreviations. Preserve exact technical names only when teammates need them to identify a screen, service, or command.
8. Merge similar work without inventing status, owners, schedules, or completion. Remove branch synchronization, fetch, merge, commit, push, and commit-hash history while preserving actual work results.
9. Do not write a report entry about report integration itself and do not update WBS for report-only changes.
10. From the repository root, run `<python> .agents/skills/update-project-reports/scripts/validate_reports.py <changed report paths>` and `git diff --check`.
11. In post-merge mode, return `source`, `base`, `head`, changed `team_summaries/` paths, target dates, and validation results to `merge-branch-to-dev`; do not stage or commit them here.
