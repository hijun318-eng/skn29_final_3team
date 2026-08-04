---
name: draft-commit-message
description: >-
  Draft one evidence-based Korean commit message from staged Git changes. Use for "draft a commit message", "커밋 메시지 작성", "커밋 제목·본문", or "staged diff 요약"; do not trigger without staged changes.
---

# 커밋 메시지 초안

commit message 형식은 `docs/markdown/collaboration/README.md`의 `변경 확인과 commit` 절을 따른다.

## 절차

1. 전체 diff를 읽기 전에 `git diff --cached --name-status`, `git diff --cached --numstat`, `git diff --cached --check`를 실행한다.
2. staged diff가 비어 있거나 unmerged path가 있으면 중단한다. binary, 과대 파일, secret 의심 파일, 생성 data, 보호 template 또는 무관한 staged path가 있으면 경고한다.
3. staged 범위가 안전한지 확인한 뒤에만 `git diff --cached`를 실행한다. staged 변경만 설명한다.
4. staged 근거와 단일 기준만으로 type, scope, 변경, 검증 note를 정하고 가장 적합한 message 하나를 작성한다.

## 출력 규칙

- 권장 multi-line commit message 하나를 code block으로 반환하고, 확인이 필요한 staged 변경만 밖에서 경고한다.
- 별도 승인 없이 stage, `git commit`, `git push`를 실행하지 않는다.
