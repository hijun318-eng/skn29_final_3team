# Report Assistant V2 다음 단계 인수인계

## 현재 확인된 상태

- 작업 저장소: `report-assistant-advanced`
- 작업 브랜치: `codex/report-assistant-advanced-20260824`
- 기존 dirty 변경은 Report Assistant 구현물이므로 보존해야 한다.
- 격리 App DB `app_db_report_assistant_e2e`에 migration head `20260825_35`가 적용되어 있다.
- 실제 OpenAI `gpt-5.4-mini`와 실제 PostgreSQL을 사용한 기존 Artifact patch API E2E가 성공했다.
- 완료 흐름은 `ready → waiting_patch_approval → saving_revision → completed`이다.
- 실제 모델이 `set_report_title`, `add_text` patch를 생성했고 Report Revision 2가 저장됐다.
- 같은 patch 승인 재호출은 새 Revision을 만들지 않고 Revision 2를 반환했다.
- 관련 Backend·AI 테스트 41개와 `git diff --check`가 통과했다.
- production 코드에는 E2E 고정 ID·고정 질문 응답·production mock이 없다.
- 합성 매출·Artifact·고정 검증 SQL은 `tests/e2e/prepare_report_assistant_e2e.py`에만 있다.
- 1~4단계 통합 회귀에서 Backend·AI·migration·patch 테스트 82개와 Frontend 24개,
  production build가 통과했다. 로컬 Python에는 `pytest`가 없어 전체 pytest suite는 미실행이다.
- 최신 Backend의 운영 summary·failures·session evaluation API가 OpenAPI에 반영됐고,
  Browser 새로고침 뒤 Revision 7·제목·차트·텍스트·Artifact가 복구됐다.

## 현재 로컬 실행

- Frontend: `http://127.0.0.1:13002/reports`
- Backend: `http://127.0.0.1:18002`
- `app_postgres`, `migration`, `analysis_template_registry`, `model`,
  `auth_session_store`는 ready로 확인했다.
- `trino`, `datahub_transport`, `semantic_release`, `catalog_manifest`,
  `trino_schema`는 아직 not_ready다.
- OpenAI secret 원문은 출력하지 않는다. 현재 유효한 모델 설정은 저장소 밖 별도 secret 파일에 있다.
- 외부 deployment env에 복사된 OpenAI key는 401이었으므로 값을 출력하지 말고 별도 secret을 process 환경에 우선 주입한다.
- Windows 로컬 Backend는 psycopg async 호환을 위해 Selector event loop로 실행해야 한다.
- 로컬 Frontend `13002` origin은 Backend CORS에 포함하고 HTTP 개발에서는 secure cookie를 끈다.

## 다음 작업 우선순위

### 1. Browser UI E2E 완료

기능을 더 추가하기 전에 실제 화면에서 다음을 검증한다.

1. `analyst`로 로그인한다. 비밀번호는 사용자만 입력하고 출력·기록하지 않는다.
2. `/reports`에서 최신 Report Revision을 연다.
3. Report Assistant에 기존 근거로 가능한 편집 지시를 입력한다.
4. GPT가 반환한 변경 요약과 작업 종류가 승인 카드에 표시되는지 확인한다.
5. 승인 전에는 Report version과 block이 바뀌지 않는지 확인한다.
6. `변경안 적용` 뒤 `completed`와 새 Revision을 확인한다.
7. 페이지를 새로고침하고 같은 Revision·제목·block이 복구되는지 확인한다.
8. 같은 승인 요청을 다시 보내도 Revision이 증가하지 않는지 확인한다.
9. 브라우저 console error와 Backend 500이 없는지 확인한다.

Browser E2E가 끝나기 전에는 화면 렌더링만으로 전체 완료라고 표현하지 않는다.

### 2. 현재 구현 회귀 검증과 커밋

Browser 검증 뒤 다음을 다시 실행한다.

```powershell
$env:PYTHONPATH='.;app/backend'
python -m unittest `
  tests.ai.test_report_assistant_contract `
  tests.backend.test_report_assistant_session `
  tests.backend.test_report_migration
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
git diff --check

Set-Location app/frontend
npm.cmd run test
npm.cmd run build
```

그다음 변경 파일과 secret 미포함 여부를 검토하고 작업 브랜치에 커밋·푸시한다. 기존 dirty
변경을 삭제하거나 `origin/dev`로 강제 reset하지 않는다.

### 3. 새 데이터 분석 E2E

이 단계는 Trino·DataHub 준비 후 진행한다.

```text
사용자 지시
→ GPT new_data 계획
→ 사용자 승인 전 분석 호출 0회
→ 승인 후 AnalysisController 1회
→ DataHub 승인 metadata
→ SQL Guard
→ Trino
→ owner/request/query/checksum 결속 Artifact
→ CAS Report Revision
→ Canvas 및 새로고침 복구
```

Trino·DataHub가 준비되지 않은 동안 mock Artifact를 production에 추가하지 않는다. 필요하면
`tests/e2e`의 fake만 사용하고 live 데이터 성공이라고 표현하지 않는다.

## 새 계정에서 사용할 시작 프롬프트

```text
C:\Users\Playdata\Documents\파이널 프젝젝젝\report-assistant-advanced 저장소에서
Report Assistant V2 작업을 이어서 진행해.

먼저 AGENTS.md 전체와
docs/Report_Assistant_V2_다음단계_인수인계_20260825.md,
docs/Report_Assistant_V2_구현_진행_20260824.md를 읽어.

기존 dirty 변경은 구현물이므로 모두 보존하고 reset·checkout으로 버리지 마.
secret 원문을 채팅·명령 인자·로그·문서·Git diff에 출력하지 마.

이번 작업은 새 기능 추가보다 Browser UI E2E를 먼저 완료해.
실제 로그인 후 기존 승인 Artifact 기반 Report Assistant 변경 제안, 승인 전 무저장,
patch 승인, completed, 새 Revision, 새로고침 복구, 중복 승인 멱등성을 확인해.

현재 실제 OpenAI+PostgreSQL API E2E는 성공했지만 Trino·DataHub는 not_ready다.
따라서 기존 Artifact 편집 E2E와 new_data 실데이터 E2E를 구분해서 보고해.
production mock·고정 SQL·질문별 고정 응답을 추가하지 마.
검증 후 관련 테스트와 frontend build를 실행하고 결과를 진행 문서에 기록해.
```

## 남은 위험

- in-app Browser에서 Revision 2 화면 복구는 아직 최종 확인되지 않았다.
- `running_data_agent` 직후 process crash의 exactly-once 복구는 queue/outbox 없이 완전 보장되지 않는다.
- 외부 deployment env의 OpenAI key와 유효한 별도 secret key가 다르므로 운영 전 credential 정리가 필요하다.
- Trino·DataHub가 준비되지 않아 `new_data` 전체 live E2E는 아직 완료되지 않았다.
