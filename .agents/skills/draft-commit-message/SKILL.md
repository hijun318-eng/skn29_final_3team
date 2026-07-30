---
name: draft-commit-message
description: Inspect the current repository's staged Git changes and draft one detailed Korean commit message with a concise subject, concrete change body, and evidence-based validation or impact notes. Use when the user asks for a commit message, Korean commit title/body, or staged-diff summary. Do not stage, commit, push, or invent a message when no staged changes exist.
---

# Draft Commit Message

## Workflow

1. Run `git rev-parse --show-toplevel`, `git branch --show-current`, and `git status --short`.
2. Run `git diff --cached --name-status`, `git diff --cached --numstat`, `git diff --cached --check`, and `git log -5 --pretty=format:%s` before loading the full diff.
3. Stop when the staged diff is empty or contains unmerged paths. Warn about binary, oversized, secret-like, generated-data, protected-template, or unrelated staged paths.
4. Run `git diff --cached` only after the staged scope is safe to inspect. Describe only staged changes.
5. Group the staged diff into one to five distinct work items without splitting one change into repetitive bullets. Use verified test results from the current context only; otherwise record validation as `미실행`.
6. Choose the type and scope from the primary intent, then produce one best message.

## Message Format

- Use `<type>: <한국어 summary>` or `<type>(<scope>): <한국어 summary>`.
- Choose `type` from `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`, `perf`, `style`, `data`, or `eval`.
- Add a short lowercase repository component as `scope` when the staged change is centered on one clear component. Omit `scope` for cross-cutting, repository-wide, or naturally unscoped changes.
- Include Korean in `summary`, keep the subject within 72 characters, and omit the final period.
- Add a Korean body by default. Keep one blank line between the subject and body.
- Start the body with `변경:` and add one to five distinct `-` bullets that name the changed contract, behavior, path group, or decision. Do not repeat the subject or list filenames without explaining what changed.
- Add `검증:` with commands or result summaries confirmed in the current context. When no verification evidence exists, write `- 미실행` instead of guessing.
- Add `영향:` only for compatibility, migration, Gate/status, deployment, security, or remaining-risk information that materially affects consumers.
- Keep each bullet concise and describe only staged changes.

Examples:

```text
docs(gate): R2·R4 I1 제출 재검토 결과 반영

변경:
- R2 service fragment 제출을 REVIEW로 전환하고 소비자 검증 조건 기록
- R4 clean handoff와 container readiness 증거 및 cleanup 보완 범위 반영
- WBS와 일일보고에 R1 판정 근거 동기화

검증:
- 문서 정책·WBS·보고서 검사 통과
- 전체 테스트 26건 통과
```

## Output Rules

- Return one recommended multi-line commit message in a code block.
- Put warnings outside the code block only when staged changes need user attention.
- Do not stage files or run `git commit` or `git push` unless the user separately authorizes it.
