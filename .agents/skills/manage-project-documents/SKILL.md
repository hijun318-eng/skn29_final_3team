---
name: manage-project-documents
description: >-
  Apply this repository's document rules when creating, editing, moving, renaming, or reviewing docs/. Use for "create or edit a project document" or "문서 작성·수정·이동·이름 변경·검토", "산출물 작성" requests, especially numbered deliverables and official artifacts. 보고서만 갱신할 때는 update-project-reports를 사용한다.
---

# 프로젝트 문서 관리

`docs/문서관리규칙.md`를 정책의 단일 기준으로 사용한다. 정책 표는 해당 문서에 두고 이 Skill에는 실행 절차만 둔다.

## 절차

1. 문서 path, 번호, template, header를 정하기 전에 `docs/문서관리규칙.md`를 읽는다. 구조, field, heading, 변환 또는 제출에 영향을 주는 번호 산출물 작업이면 `docs/markdown/document_specs/산출물작성규격.md`의 해당 절과 매핑된 template을 읽고 필수 계층을 보존한다. 매핑이 모호하면 중단하며, 구조와 무관한 문구 수정이면 두 항목을 생략한다.
2. 대상을 Markdown 작업 문서, 공식 deliverable, 원본 template 또는 보조 파일로 분류한다.
3. `docs/markdown/ai_docs/`는 공식 deliverable이나 현재 구현 사실이 아닌 AI·외부 참고자료로 취급한다. `docs/templates/` 쓰기는 거부하고 편집 가능한 작업 문서 또는 `docs/deliverables/`를 사용한다.
4. 기존 문서를 편집하기 전에 현재 header, version, 기준일, 변경 이력, link, 참조 contract를 확인한다.
5. 가장 작은 일관된 변경을 적용한다. 이동하거나 이름을 바꾸면 같은 작업에서 저장소 link도 갱신한다.
6. 제외 path 밖의 `docs/**/*.md`를 편집하면 단일 기준에 따라 metadata header와 최근 변경 이력을 갱신한다. 실제 사람 편집자를 기록하고 이름을 추정하지 않는다.
7. repository root에서 `<python> .agents/skills/manage-project-documents/scripts/check_document_policy.py <changed paths>`와 `git diff --check`를 실행한다.
8. WBS와 개인 보고서 갱신은 `AGENTS.md`를 따른다.

## 검증 경계

- artifact와 Markdown을 모두 비교하지 않았다면 동기화되었다고 쓰지 않는다.
- 수정하지 않은 legacy 문서에 header를 일괄 추가하지 않는다.
