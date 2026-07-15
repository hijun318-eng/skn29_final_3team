---
name: draft-commit-message
description: Draft one factual commit message from the currently staged Git diff while following the repository commit convention.
---

# Shared Draft Commit Message

1. Read and follow `.agents/skills/draft-commit-message/SKILL.md` as the canonical workflow.
2. Use `.agents/skills/draft-commit-message/scripts/collect_context.ps1` to collect staged diff context.
3. Do not stage, commit, push, amend, or rewrite history unless the user explicitly requests it.
4. Do not include unstaged or untracked changes, and do not claim validation that did not run.
