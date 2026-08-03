---
name: update-project-reports
description: Update and validate plain-language personal daily reports, presentation-ready team daily summaries, and weekday-based weekly reports in this repository. Use after a non-report file-changing task on a recognized personal branch, when the user requests reporting for a date or period, or when merge-branch-to-dev invokes post-merge report integration. Never infer an author on dev/main, perform Git integration actions, update WBS, or create recursive entries for report-only changes.
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
3. Record only qualifying repository results and write the date block using the canonical README's format, wording, and limits.
4. From the repository root, validate the changed file with `<python> .agents/skills/update-project-reports/scripts/validate_reports.py --date <YYYYMMDD> <changed report path>` and `git diff --check`.

## Team and weekly workflow

1. In post-merge mode, require `source`, `base`, and `head`; verify that `base` is an ancestor of `head` and `head` is the current commit. Compare the source member's personal report at both SHAs and select dates whose complete blocks changed. Add dates with no team summary; honor an explicit user range first.
2. Read all five personal `일일보고.md` files directly. Do not use a date summary as the source of truth.
3. Resolve the official week using the canonical README.
4. Create target date summaries and rebuild affected weekly reports using the canonical README's source, format, wording, and limit rules.
5. Do not write a report entry about report integration itself and do not update WBS for report-only changes.
6. From the repository root, run `<python> .agents/skills/update-project-reports/scripts/validate_reports.py <changed report paths>` and `git diff --check`.
7. In post-merge mode, return `source`, `base`, `head`, changed `team_summaries/` paths, target dates, and validation results to `merge-branch-to-dev`; do not stage or commit them here.
