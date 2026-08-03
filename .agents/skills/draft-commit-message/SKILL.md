---
name: draft-commit-message
description: Inspect the current repository's staged Git changes and draft one detailed Korean commit message with a concise subject, concrete change body, and evidence-based validation or impact notes. Use when the user asks for a commit message, Korean commit title/body, or staged-diff summary. Do not stage, commit, push, or invent a message when no staged changes exist.
---

# Draft Commit Message

Use the `변경 확인과 commit` section of `docs/markdown/collaboration/README.md` as the canonical message format.

## Workflow

1. Run `git diff --cached --name-status`, `git diff --cached --numstat`, `git diff --cached --check`, and `git log -5 --pretty=format:%s` before loading the full diff.
2. Stop when the staged diff is empty or contains unmerged paths. Warn about binary, oversized, secret-like, generated-data, protected-template, or unrelated staged paths.
3. Run `git diff --cached` only after the staged scope is safe to inspect. Describe only staged changes.
4. Choose the primary intent, type, scope, change bullets, and validation notes from staged evidence only, following the canonical format.
5. Produce one best message.

## Output Rules

- Return one recommended multi-line commit message in a code block.
- Put warnings outside the code block only when staged changes need user attention.
- Do not stage files or run `git commit` or `git push` unless the user separately authorizes it.
