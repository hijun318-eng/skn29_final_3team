---
name: draft-commit-message
description: >-
  Inspect staged Git changes and draft one evidence-based Korean commit message. Use for "draft a commit message" or 사용자의 "커밋 메시지 작성", "커밋 제목·본문 작성", "staged diff 요약" 요청. Do not stage, commit, push, or invent a message when nothing is staged.
---

# 커밋 메시지 초안

`docs/markdown/collaboration/README.md`의 `변경 확인과 commit` 절을 commit message 형식의 단일 기준으로 사용한다.

## 절차

1. 전체 diff를 읽기 전에 `git diff --cached --name-status`, `git diff --cached --numstat`, `git diff --cached --check`, `git log -5 --pretty=format:%s`를 실행한다.
2. staged diff가 비어 있거나 unmerged path가 있으면 중단한다. binary, 과대 파일, secret 의심 파일, 생성 data, 보호 template 또는 무관한 staged path가 있으면 경고한다.
3. staged 범위가 안전한지 확인한 뒤에만 `git diff --cached`를 실행한다. staged 변경만 설명한다.
4. 단일 기준 형식에 따라 staged 근거만으로 주된 의도, type, scope, 변경 bullet, 검증 note를 정한다.
5. 가장 적합한 message 하나를 작성한다.

## 출력 규칙

- 권장 multi-line commit message 하나를 code block으로 반환한다.
- staged 변경에 사용자 확인이 필요할 때만 경고를 code block 밖에 둔다.
- 사용자가 별도로 승인하지 않으면 파일을 stage하거나 `git commit`, `git push`를 실행하지 않는다.
