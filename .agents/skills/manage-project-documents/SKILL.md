---
name: manage-project-documents
description: Apply this repository's document placement, protected-folder, template, filename, metadata-header, change-history, and validation rules. Use when an AI agent creates, edits, moves, renames, or reviews files under docs/, especially numbered deliverable Markdown or official artifacts. Do not use for report-only updates handled by update-project-reports.
---

# Manage Project Documents

Use `docs/문서관리규칙.md` as the canonical policy. Keep policy tables there; keep only the execution workflow here.

## Workflow

1. Read `docs/문서관리규칙.md` before deciding a document path, number, template, or header. For a numbered artifact task that can affect structure, fields, headings, conversion, or submission, read its matching section in `docs/markdown/document_specs/산출물작성규격.md` and mapped template, preserve the required hierarchy, and stop if the mapping is ambiguous. Skip both for structure-neutral text edits.
2. Classify the target as a Markdown working document, official deliverable, source template, or auxiliary file.
3. Treat `docs/markdown/ai_docs/` as auxiliary AI/external-reference material, not an official deliverable or current implementation fact. Refuse writes under `docs/templates/`; use an editable working document or `docs/deliverables/` instead.
4. Before editing an existing document, inspect its current header, version, basis date, change history, links, and referenced contracts.
5. Apply the smallest coherent change. When moving or renaming, update repository links in the same task.
6. For an edited `docs/**/*.md` file outside the exempt paths, update the metadata header and recent change history according to the canonical rule. Record the actual human editor; never invent a name.
7. From the repository root, run `<python> .agents/skills/manage-project-documents/scripts/check_document_policy.py <changed paths>` and `git diff --check`.
8. Follow `AGENTS.md` for WBS and personal-report updates.

## Validation boundaries

- Do not claim an artifact is synchronized with Markdown unless both were compared.
- Do not bulk-add headers to untouched legacy documents.
