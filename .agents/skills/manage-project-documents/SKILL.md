---
name: manage-project-documents
description: >-
  Apply repository document rules to create, edit, move, rename, or review docs/. Use for "create/edit a project document", "문서 작성·수정·이동·이름 변경·검토", or "산출물 작성"; report-only work uses update-project-reports.
---

# 프로젝트 문서 관리

세부 정책은 `docs/문서관리규칙.md`에 두고 이 Skill에는 절차만 둔다.

## 절차

1. 문서 path, 번호, template, header를 정하기 전에 `docs/문서관리규칙.md`를 읽는다. 구조, field, heading, 변환 또는 제출에 영향을 주는 번호 산출물 작업이면 `docs/markdown/document_specs/산출물작성규격.md`의 해당 절과 매핑된 template을 읽고 필수 계층을 보존한다. 매핑이 모호하면 중단하며, 구조와 무관한 문구 수정이면 두 항목을 생략한다.
2. 기존 문서를 편집하기 전에 현재 header, version, 기준일, 변경 이력, link, 참조 contract를 확인한다.
3. 이동하거나 이름을 바꾸면 같은 작업에서 저장소 link도 갱신한다.
4. 단일 기준에 따라 적용 대상의 metadata header와 변경 이력을 갱신한다.
5. repository root에서 `<python> .agents/skills/manage-project-documents/scripts/check_document_policy.py <changed paths>`와 `git diff --check`를 실행한다.

## 검증 경계

- artifact와 Markdown을 모두 비교하지 않았다면 동기화되었다고 쓰지 않는다.
