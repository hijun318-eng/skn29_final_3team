<!-- PR title은 <type>(<scope>): <summary> 형식과 72자 제한을 따릅니다. -->

## 연결 작업

- Issue: <!-- 예: #12 -->
- Target branch: <!-- 개인 branch는 dev, main은 dev에서만 -->

## 변경 목적

<!-- 왜 필요한 변경인지 작성 -->

## 변경 내용

<!-- 핵심 변경을 작은 목록으로 작성 -->

## 범위

- In scope:
- Out of scope:

## 검증

<!-- 실제 실행한 command와 결과만 작성 -->

- [ ] 관련 unit/integration test를 실행했다.
- [ ] 실행하지 못한 검증과 이유를 적었다.
- [ ] 수동 확인이 필요한 항목을 적었다.

## AI 작업 근거

- 사용한 AI/Skill:
- AI가 변경한 범위:
- 사람이 확인한 diff와 결정:
- [ ] staged diff와 commit message가 일치한다.
- [ ] AI가 생성한 근거 없는 test 결과나 사실이 없다.

## 데이터·평가 영향

- 데이터 유형: <!-- 없음 / synthetic / public / internal -->
- schema 또는 preprocessing 영향:
- test set version:
- baseline/report 경로:
- [ ] synthetic 결과를 실제 호텔 사실로 표현하지 않았다.
- [ ] 동작이 바뀐 경우 동일 test set의 before/after를 기록했다.

## 문서·운영 영향

- 변경한 문서:
- migration/deployment/rollback:
- 남은 위험과 후속 Issue:

## Review checklist

- [ ] 하나의 PR이 하나의 주된 목적을 가진다.
- [ ] 관련 없는 변경과 생성물이 포함되지 않았다.
- [ ] `main` 대상 PR은 `dev`에서 왔다.
- [ ] 품질 gate와 문서가 현재 동작을 반영한다.
