---
name: draft-commit-message
description: Inspect the current repository's staged Git changes and draft one Korean commit message that follows the team's format. Use when the user asks for a commit message, Korean commit title, or staged-diff summary. Do not stage, commit, push, or invent a message when no staged changes exist.
---

# Draft Commit Message

## Workflow

1. Run `git rev-parse --show-toplevel`, `git branch --show-current`, and `git status --short`.
2. Run `git diff --cached --name-status`, `git diff --cached --numstat`, `git diff --cached --check`, and `git log -5 --pretty=format:%s` before loading the full diff.
3. Stop when the staged diff is empty or contains unmerged paths. Warn about binary, oversized, secret-like, generated-data, protected-template, or unrelated staged paths.
4. Run `git diff --cached` only after the staged scope is safe to inspect. Describe only staged changes.
5. Choose the type and scope from the actual change, then produce one best message.

## Message Format

- Use `<type>(<scope>): <한국어 summary>`.
- Choose `type` from `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`, `perf`, `style`, `data`, or `eval`.
- Keep `type` and `scope` lowercase. Use a short repository component for `scope`.
- Include Korean in `summary`, keep the subject within 72 characters, and omit the final period.
- Add a short Korean body only when the reason, validation, or risk cannot be understood from the subject.

## Output Rules

- Return one recommended commit message in a code block.
- Put warnings outside the code block only when staged changes need user attention.
- Do not stage files or run `git commit` or `git push` unless the user separately authorizes it.
