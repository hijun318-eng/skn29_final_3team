---
name: update-project-reports
description: Update and validate personal daily reports, date-based team summaries, and weekly reports in this repository. Use after a file-changing task on a recognized personal branch, when the user requests reporting for a date or period, or when merge-branch-to-dev invokes post-merge report integration. Never infer an author on dev/main, perform Git integration actions, update WBS, or create recursive entries for report-only changes.
---

# Update Project Reports

Use `docs/markdown/daily_reports/README.md` as the canonical source for branch mapping, report evidence, formats, periods, and limits.

Resolve the repository root with `git rev-parse --show-toplevel` and use it as the working directory for every command. Require Git and a Python 3.10+ launcher (`python` or `python3`) before using bundled scripts.

## Select the mode

- **Personal completion:** After a non-report repository change on a recognized personal branch, update only that branch's `일일보고.md`.
- **Requested period:** When the user specifies a date or period, update the applicable date summaries and weekly reports from the five personal reports.
- **Post-merge integration:** Accept the source branch, pre-merge `base` SHA, and post-merge `head` SHA from `merge-branch-to-dev`; update only affected `team_summaries/` files and return their paths plus validation results.

## Personal report workflow

1. Confirm the current branch and its mapped report file from the canonical README. On `main`, `dev`, or an unmapped branch, do not infer an author.
2. Use the current KST date unless the user explicitly supplies another date.
3. Record only repository results that remain after the task. Exclude investigation-only answers, commit-message drafting, Git operations, and report-only maintenance.
4. Add to the existing date block or create the newest block below the file notice. Consolidate related work rather than duplicating entries.
5. From the repository root, validate the changed file with `<python> .agents/skills/update-project-reports/scripts/validate_reports.py --date <YYYYMMDD> <changed report path>` and `git diff --check`.

## Team and weekly workflow

1. In post-merge mode, require `source`, `base`, and `head`; verify that `base` is an ancestor of `head` and `head` is the current commit. Compare the source member's personal report at both SHAs and select dates whose complete blocks changed. Add dates with no team summary; honor an explicit user range first.
2. Read all five personal `일일보고.md` files directly. Do not use a date summary as the source of truth.
3. Resolve the official week from `docs/markdown/ai_docs/최종_프로젝트_산출물_및_전체_일정.md`.
4. For each target date, preserve the existing team-summary structure, include all five mapped members, and mark missing source blocks as `보고 없음`.
5. Rebuild each affected weekly report from all source dates in its applicable range. Merge similar work without inventing status, owners, schedules, or completion.
6. Remove branch synchronization, fetch, merge, commit, push, and commit-hash history while preserving actual work results.
7. Do not write a report entry about report integration itself and do not update WBS for report-only changes.
8. From the repository root, run `<python> .agents/skills/update-project-reports/scripts/validate_reports.py <changed report paths>` and `git diff --check`.
9. In post-merge mode, return `source`, `base`, `head`, changed `team_summaries/` paths, target dates, and validation results to `merge-branch-to-dev`; do not stage or commit them here.
