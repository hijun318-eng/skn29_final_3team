---
name: manage-project-documents
description: Apply this repository's document placement, protected-folder, template, filename, metadata-header, change-history, and validation rules. Use when an AI agent creates, edits, moves, renames, or reviews files under docs/, especially numbered deliverable Markdown or official artifacts. Do not use for report-only updates handled by update-project-reports.
---

# Manage Project Documents

Use `docs/문서관리규칙.md` as the canonical policy. Keep policy tables there; keep only the execution workflow here.

## Workflow

1. Run `git rev-parse --show-toplevel`, make that repository root the working directory for every later command, then run `git status --short` and `git branch --show-current`. Require Git and a Python 3.10+ launcher (`python` or `python3`) before using bundled scripts.
2. Read `docs/문서관리규칙.md` before deciding a document path, number, template, or header.
3. Classify the target as a Markdown working document, official deliverable, source template, or auxiliary file.
4. Refuse writes under `docs/markdown/final_project/` and `docs/templates/`. Report the required correction and use an editable working document or `docs/deliverables/` instead.
5. For a filename beginning with two digits and `_`, inspect the mapped template directly before editing. Preserve its top-level title order and hierarchy. If the mapping is ambiguous, stop for direction.
6. Before editing an existing document, inspect its current header, version, basis date, change history, links, and referenced contracts.
7. Apply the smallest coherent change. When moving or renaming, update repository links in the same task.
8. For an edited `docs/**/*.md` file outside the exempt paths, update the metadata header and recent change history according to the canonical rule. Record the actual human editor; never invent a name.
9. From the repository root, run `<python> .agents/skills/manage-project-documents/scripts/check_document_policy.py <changed paths>` and `git diff --check`.
10. Follow `AGENTS.md` for WBS and personal-report updates. Do not stage, commit, or push without authorization.

## Validation boundaries

- Treat `docs/문서관리규칙.md` as policy, not duplicated Skill content.
- Treat templates as structure references, not current project facts.
- Do not claim an artifact is synchronized with Markdown unless both were compared.
- Do not bulk-add headers to untouched legacy documents.
