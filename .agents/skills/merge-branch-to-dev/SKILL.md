---
name: merge-branch-to-dev
description: Integrate one recognized personal team branch into dev using this repository's guarded workflow, including authorized branch push, exact local/remote checks, merge, post-merge team-report integration, an optional report-only commit, and final dev push. Use only when the user explicitly asks to merge or apply a personal branch to dev. Do not use for merely updating dev, syncing dev into a personal branch, dev-to-main integration, generic Git help, or commit-message drafting.
---

# Merge Branch To Dev

Apply `docs/markdown/collaboration/README.md` as the Git-policy source. Load and follow `.agents/skills/update-project-reports/SKILL.md` for report integration. Never copy report rules into this Skill.

## Authorization boundary

An explicit personal-branch-to-`dev` request authorizes only the target branch push, `dev` fetch/pull/merge/push, and a report-only commit containing the `team_summaries/` files returned by the report workflow. It does not authorize unrelated files, force push, rebase, reset, stash, or history rewriting.

## Workflow

1. Resolve the repository root with `git rev-parse --show-toplevel` and use it as the working directory for every command. Require Git and a Python 3.10+ launcher (`python` or `python3`).
2. Resolve exactly one source from `junhee`, `minji`, `seung`, `daesung`, or `jaehong`. If the user did not name it, use the current branch only when it is one of those five; otherwise stop.
3. Confirm the source work is committed and the working tree is clean. Push the source, fetch origin, then run:
   `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase source`
4. Switch to `dev`, require a clean tree, fetch origin, and run `git pull --ff-only origin dev`.
5. Require exact local/remote `dev` equality and record the pre-merge commit. Run the preflight script with `--phase dev`.
6. Merge `origin/<branch>`. On any conflict, stop before report generation or push and report the conflicted paths. Do not resolve without a new explicit instruction.
7. Load `.agents/skills/update-project-reports/SKILL.md` and apply its post-merge mode. Validate the affected date summaries and cumulative weekly reports.
8. Stage only the returned `docs/markdown/daily_reports/team_summaries/` paths. Review the staged diff. If it is non-empty, create one report-only team-format commit; otherwise skip it.
9. Recheck `git diff --check`, working-tree state, report limits, and that `origin/dev` is still an ancestor of local `dev` after a final fetch.
10. Push `dev`, then verify `dev` and `origin/dev` resolve to the same commit.

## Stop conditions

Stop without cleanup when the tree is dirty, source or `dev` differs unexpectedly from origin, local `dev` is ahead/diverged before integration, a merge conflicts, report validation fails, or report changes cannot be isolated. Preserve evidence and ask for direction.
