---
name: manage-project-documents
description: Apply this repository's document placement, protected-folder, template, filename, metadata-header, change-history, and validation rules. Use when an AI agent creates, edits, moves, renames, or reviews files under docs/, especially numbered deliverable Markdown or official artifacts. Do not use for report-only updates handled by update-project-reports.
---

# Manage Project Documents

Use `docs/문서관리규칙.md` as the canonical policy. Keep policy tables there; keep only the execution workflow here.

## Workflow

1. Read `docs/문서관리규칙.md` before deciding a document path, number, template, or header. For an artifact numbered 01 through 21, read only its matching section in `docs/markdown/document_specs/산출물작성규격.md` when creating it or changing, reviewing, converting, or validating its structure, fields, or headings.
2. Classify the target as a Markdown working document, official deliverable, source template, or auxiliary file.
3. Treat `docs/markdown/ai_docs/` as auxiliary AI/external-reference material, not an official deliverable or current implementation fact. Refuse writes under `docs/templates/`; use an editable working document or `docs/deliverables/` instead.
4. For a filename beginning with two digits and `_`, inspect the mapped template when the task can affect structure, fields, headings, conversion, or submission. Preserve its top-level title order and hierarchy. Skip this step only for a text-only edit that cannot affect template structure; if the mapping is ambiguous, stop for direction.
5. Before editing an existing document, inspect its current header, version, basis date, change history, links, and referenced contracts.
6. Apply the smallest coherent change. When moving or renaming, update repository links in the same task.
7. For an edited `docs/**/*.md` file outside the exempt paths, update the metadata header and recent change history according to the canonical rule. Record the actual human editor; never invent a name.
8. From the repository root, run `<python> .agents/skills/manage-project-documents/scripts/check_document_policy.py <changed paths>` and `git diff --check`.
9. Follow `AGENTS.md` for WBS and personal-report updates. Do not stage, commit, or push without authorization.

## Validation boundaries

- Treat `docs/문서관리규칙.md` as policy, not duplicated Skill content.
- Treat templates and `docs/markdown/ai_docs/` as references, not current project facts.
- Do not claim an artifact is synchronized with Markdown unless both were compared.
- Do not bulk-add headers to untouched legacy documents.
