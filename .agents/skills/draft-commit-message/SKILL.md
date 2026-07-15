---
name: draft-commit-message
description: Draft one concise, factual commit message from the currently staged Git diff in the active repository. Use when the user asks for a commit message, asks to commit staged work, or requests a staged-diff summary. Do not use for release notes, PR descriptions, unstaged changes, or speculative future work.
---

# Draft Commit Message

## Workflow

1. Confirm the Git root and do not stage files.
2. Run `scripts/collect_context.ps1` from this skill directory.
3. If it reports no staged changes, stop and say that a staged diff is required.
4. Read `docs/engineering/COMMIT_CONVENTION.md` from the repository root.
5. Infer one primary intent from the staged paths and patch. If unrelated intents are mixed, recommend a split instead of hiding them in one message.
6. Draft `<type>(<scope>): <summary>` with a subject of at most 72 characters.
7. Add a body only when the reason, risk, migration, synthetic-data version, or validation is not obvious from the subject.
8. Mention only validation that actually ran. Do not infer tests, behavior, or data quality from filenames.
9. Return the proposed message for review. Do not commit, push, amend, or rewrite history unless the user explicitly authorizes that action.

## Output

Return one copy-ready message. When a split is required, return the proposed commit groups before any messages.

Use this optional body shape:

```text
type(scope): summary

Why:
- reason

Changes:
- material change

Validation:
- command or evidence
```

Omit empty sections.
