# Report Assistant V2 전체 구현 검증보고서

기준일: 2026-08-26
저장소: `report-assistant-advanced`
작업 브랜치: `codex/report-assistant-advanced-20260824`
공유 브랜치: `origin/seung`
검증 방식: 코드·migration·API·Frontend 연결 추적, unit/contract 테스트, 정적 검사, build

## 1. 결론

Report Assistant V2는 화면만 존재하는 prototype이 아니다. production 코드에서 실제 GPT adapter,
strict JSON schema, 서버 소유 DB session, 사용자 승인, Artifact lineage 검증, CAS Report Revision,
Frontend Canvas 갱신 경로가 연결돼 있다.

검증에서 발견된 코드 결함은 현재 dirty tree에서 다음과 같이 수정했다.

1. `new_data`의 최종 patch를 `saving_revision` 전에 고정해 복구 중 GPT 재호출을 제거했다.
2. Report 공개 Artifact·definition 응답과 Report UI 상태에서 query ID·checksum 값을 제거하고,
   저장 시 Backend가 Artifact ID로 lineage를 다시 조회하게 했다.
3. 비저장 품질 검토도 request별 token·latency·비용 평가와 제한에 연결했다.
4. turn prompt의 내부 식별자 금지 문구와 prompt/model release를 수정했다.
5. 11차 Report Assistant 전용 안전 취소 API와 UI를 구현했다.
6. operation 선택 read-back을 typed 응답 검증으로 fail-closed했다.

현재 남은 차단 항목은 migration 39·40을 적용한 실제 PostgreSQL transaction과 실제 GPT·Browser
E2E다. 실행 중인 원격 작업을 강제로 중단하는 worker-level cancellation은 이번 11차 범위가 아니며,
UI도 이를 가능한 기능으로 표시하지 않는다.

따라서 현재 tree를 전체 완료 또는 live E2E 완료로 표시하면 안 된다.

## 2. Git 상태

- HEAD: `ed16f1fb feat(reports): advance report assistant GPT workflows`
- `origin/seung...HEAD`: `0 0`
- commit 기준 ahead/behind 없음
- Report Assistant 관련 dirty 변경 29개 파일: `+1208 / -54`
- untracked migration:
  - `app/backend/migrations/versions/20260826_39_report_block_evidence_refs.py`
  - `app/backend/migrations/versions/20260826_40_report_assistant_patch_selection.py`
- untracked 문서:
  - `docs/Report_Assistant_V2_GPT_고도화_10_14차_구현계획_20260826.md`
- conflict marker 없음
- `git diff --check` 통과
- 기존 dirty 변경은 모두 보존해야 한다.

금지 사항:

- reset, checkout, clean, stash drop 금지
- 기존 migration 수정 금지
- 별도 지시 없는 commit, push, merge 금지
- secret 원문 출력·기록 금지

## 3. 실제 GPT 연결

판정: **완료 — production 코드 기준, 현재 live 호출은 미검증**

- `generate_report_change_proposal()`과 `generate_report_quality_review()`가 실제
  `openai_transport()`를 호출한다.
- OpenAI 요청은 `response_format.type=json_schema`, `strict=true`를 사용한다.
- provider 응답 후에도 versioned JSON schema와 Pydantic 계약으로 다시 검증한다.
- malformed response, 모델 transport 실패, 잘못된 patch는 성공값으로 대체하지 않는다.
- 모델은 권한, 승인, SQL 실행, request ID, Artifact ID, query ID, checksum의 권위가 아니다.
- `assistant_request_id`, `patch_request_id`, `data_request_id`는 서버가 생성한다.

이번 검증에서는 실제 OpenAI 비용 호출을 실행하지 않았다.

## 4. 서버 session과 phase

다음 상태는 repository SQL과 API에 연결돼 있다.

```text
ready
→ waiting_patch_approval
→ saving_revision
→ completed

ready
→ waiting_approval
→ running_data_agent
→ waiting_artifact
→ saving_revision
→ completed
```

종료 상태:

- `failed`
- `cancelled`

각 주요 UPDATE는 owner, assistant request ID, patch/data request ID, expected phase,
legacy `status='running'`을 조건으로 사용한다. 승인·거절 시각, 완료 시각, error code도 DB에
저장한다.

단, `cancelled` phase는 공개 계약에만 있고 Report Assistant 전용 cancel endpoint는 없다.

## 5. 기존 Artifact 편집

지원 operation 8종:

- `set_report_title`
- `add_text`
- `update_text`
- `add_artifact_view`
- `reposition_block`
- `duplicate_block`
- `remove_block`
- `restore_previous_revision`

검증된 동작:

- 승인 전 Report Revision 저장 0회
- 거절 시 Report Revision 저장 0회
- 승인 후에만 CAS 새 Revision 생성
- 같은 patch 승인 재호출 시 Revision 추가 생성 방지
- 존재하지 않는 block과 anchor 거부
- 마지막 block 삭제 거부
- `restore_previous_revision` 단독 실행 강제
- 모델이 실제 Artifact ID/query ID/checksum을 저장값으로 주입할 수 없음
- 최종 저장 전에 Artifact owner·approval·query·checksum 재검증
- `completed + result_revision` 이후 Frontend가 definition을 다시 조회해 Canvas 교체

판정: **부분 완료**. 코드·API·unit/contract는 연결됐지만 migration 39·40을 적용한 실제
PostgreSQL·Browser 검증이 없다.

## 6. GPT 고도화 기능 판정

| 기능 | 판정 | 근거 |
|---|---|---|
| 변경안 재수정 | 완료 | 현재 patch ID 검증, 전체 patch 교체, stale ID는 모델 호출 전 409 |
| bounded 대화 | 완료 | 최근 6 turn만 DB에 보존하고 최대 12 role message 전달 |
| Artifact 근거 alias | 부분 완료 | 모델 alias 검증은 완료, 브라우저 lineage 노출 문제 있음 |
| 비저장 품질 검토 | 부분 완료 | 무저장 typed finding은 완료, 평가·비용 관측 누락 |
| 여러 Artifact 종합 | 완료 | 최대 5개, owner·승인·checksum 전체 결속 |
| 문맥형 suggestion | 완료 | 기존 proposal/review에 포함, 클릭은 composer만 변경 |
| block 근거 영속화 | 부분 완료 | migration·ORM·Canvas 연결, 실제 DB/Browser 미검증 |
| operation preview | 부분 완료 | 서버 preview 저장·복구 구현, 실제 Browser 미검증 |
| operation 선택 승인 | 부분 완료 | 서버 재검증·CAS 구현, 실제 PostgreSQL/Browser 미검증 |
| operation dependency | 완료 | 삭제 target·anchor·동일 대상 중복 변경 차단 |

## 7. 승인·CAS·멱등성

기존 Artifact patch 경로는 다음을 만족한다.

- 최초 승인만 DB CAS로 claim
- 선택 operation을 서버에서 다시 dry-run
- session 생성 시 고정한 definition version과 base revision 검증
- 최신 version이 이미 있으면 `REPORT_REVISION_CONFLICT`
- 새 version, blocks, session `completed`를 하나의 transaction에서 저장
- 동일 선택의 중복 승인은 기존 완료 Revision 반환
- 다른 선택으로 중복 승인하면 409

새 데이터 경로는 승인 전 AnalysisController를 호출하지 않고 최초 승인 claim 뒤 한 번 호출한다.
반환 Artifact는 owner, request, APPROVED status, query ID, checksum으로 다시 검증한다.

Trino·DataHub live E2E는 범위 밖이며 완료되지 않았다.

## 8. 실패 session 재시도

판정: **완료 — code/unit 기준**

- 원본 failed session을 ready로 되돌리지 않는다.
- 새 assistant request ID의 child session을 만든다.
- `retry_of_assistant_request_id`를 저장한다.
- 원본당 child 하나인 unique index로 중복 retry를 같은 session에 결속한다.
- 사용자 지시, 기존 승인, data request ID, analysis plan, patch를 자동 복사하지 않는다.
- retry endpoint 자체는 모델, AnalysisController, Revision 저장을 호출하지 않는다.

실제 migration 39·40 기준 PostgreSQL 재검증은 남아 있다.

## 9. Frontend·Canvas 연결

실제 연결:

```text
reportClient
→ useReportLifecycleState
→ useReportsPageController
→ ReportsPage
→ ReportAssistantPanel
```

구현된 기능:

- session 생성·조회·retry
- message body의 current patch request ID 전달
- patch/data 승인·거절
- operation preview·선택
- 품질 검토
- 여러 Artifact 선택
- 문맥형 suggestion
- completed Revision 재조회
- sessionStorage를 서버 session 복구 포인터로 사용
- `saving_revision` 자동 재개

현재 live Browser가 실행되지 않아 실제 승인·부분 선택·새로고침 E2E는 검증하지 못했다.

## 10. 하드코딩·mock 검사

발견하지 못한 항목:

- 질문 문자열별 production 분기
- 특정 질문 고정 응답
- production fallback Artifact
- 고정 Report/Artifact/request/user ID
- 자동 승인 또는 승인 우회
- 모델 호출 없이 GPT 결과를 흉내 내는 production 응답
- Frontend만 성공 처리하고 Backend 저장을 생략하는 경로

테스트 fake/mock은 `tests/` 아래에서 명시적으로 주입된다. repository의 SQL은 session, lineage,
CAS 영속 SQL이며 질문별 분석용 고정 SQL이 아니다.

## 11. Migration

- 단일 Alembic head: `20260826_40`
- 연결: `20260826_38 → 20260826_39 → 20260826_40`
- 기존 migration 수정 없음
- migration 39: Report block `evidence_refs`
- migration 40: `patch_preview_json`, `approved_operation_indexes`
- ORM·repository SQL과 신규 column 연결 확인

`alembic current`는 SQLAlchemy DB URL 미설정으로 연결 전에 실패했다. 따라서 migration 39·40의
실제 테스트 DB 적용 여부는 **검증 불가**다. 공용·운영 DB에는 적용하지 않았다.

## 12. 실행한 검증

Backend 지정 모듈:

```powershell
$env:PYTHONPATH='.;app/backend'
python -m unittest `
  tests.ai.test_report_assistant_contract `
  tests.backend.test_report_assistant_session `
  tests.backend.test_report_assistant_operations `
  tests.backend.test_report_assistant_patch `
  tests.backend.test_report_migration
```

결과:

- 119 tests
- 119 passed
- 실패·skip 0

정적 검증:

- OpenAPI contract: 통과
- 코드 문서화: 349 source files, 63 executable configs 통과
- architectural invariants: 301 source files 통과
- repository integrity: 884 files 통과
- Python compileall: 통과
- `git diff --check`: 통과

Frontend:

- 24/24 tests 통과
- Vite production build 통과
- 테스트 중 WebSocket port 24678 사용 중 경고 2회가 있었으나 실패 없음

## 13. 실제 E2E 여부

이번 검증에서 실행하지 못한 항목:

- 실제 OpenAI 호출
- 실제 PostgreSQL transaction integration
- migration 39·40 DB 적용
- Browser 승인·부분 선택·Canvas·새로고침
- Trino·DataHub `new_data` 흐름

환경 확인 결과:

- Docker daemon 미실행
- 과거 문서의 Backend 주소 접근 불가
- 과거 문서의 Frontend 주소 접근 불가
- DB URL 미설정

과거 문서에는 이전 revision의 실제 OpenAI+PostgreSQL+Browser 검증 기록이 있지만, 현재 dirty
tree의 migration 39·40과 10차 변경을 증명하는 현재 실행 근거로 사용할 수 없다.

## 14. 구현 담당자가 우선 수정할 결함

### P1. `new_data saving_revision`이 GPT를 다시 호출함

위치:

- `app/backend/app/api/report_router.py`
- `_compose_assistant_revision()`
- `decide_assistant_plan()`

현재 동작:

```text
검증 Artifact 저장
→ saving_revision
→ generate_report_change_proposal 재호출
→ patch 생성
→ CAS Revision
```

문제:

- `saving_revision` 복구 시 GPT가 다시 호출된다.
- 같은 Artifact에서도 patch가 달라질 수 있다.
- 추가 비용과 모델 장애가 발생할 수 있다.
- “고정된 patch/Artifact만 사용하고 모델 재호출 0회” 계약을 위반한다.
- 현재 테스트도 compose 재호출을 정상 동작으로 고정한다.

완료 조건:

1. 최초 분석 성공 후 `saving_revision` 진입 전에 최종 typed patch와 model trace를 DB에 고정한다.
2. 저장 재개는 고정 patch, 선택값, Artifact binding, source revision만 사용한다.
3. 재개 중 GPT와 AnalysisController 호출이 각각 0회임을 테스트한다.
4. 응답 유실 뒤 중복 재호출에서 Revision이 하나만 존재함을 실제 PostgreSQL로 검증한다.

### P1. 브라우저 상태에 query ID와 checksum이 저장됨

위치:

- `app/frontend/src/contracts/reportContract.ts`
- `app/frontend/src/features/reports/useReportArtifacts.ts`
- Report Artifact 공개 응답 계약

현재 동작:

- `ReportArtifactResponse`가 `query_id`, `artifact_checksum`을 반환한다.
- `useReportArtifacts`가 이를 `queryId`, `artifactChecksum`으로 Client state에 저장한다.

문제:

- Assistant session 응답만 숨겨도 전체 브라우저 상태에는 lineage 식별자가 남는다.
- 명시된 “모델과 브라우저에 query ID/checksum/SQL 미노출” 조건을 충족하지 못한다.

완료 조건:

1. Assistant UI에 필요한 공개 Artifact view와 서버 내부 lineage 계약을 분리한다.
2. 브라우저에는 안전한 evidence alias와 사용자용 label만 반환한다.
3. query ID/checksum 검증은 Backend에만 유지한다.
4. Frontend state, sessionStorage, DOM, network response에 금지 값이 없는 테스트를 추가한다.

### P2. 품질 검토가 평가·비용 관측을 우회함

위치:

- `app/backend/app/api/report_router.py`
- `review_assistant_report()`

현재 동작:

- input/output token 상한은 검사한다.
- 모델 trace는 response에 반환한다.
- evaluation upsert, estimated cost 계산, cost limit 검사는 하지 않는다.

문제:

- 운영 summary가 실제 모델 호출 수·latency·token·비용을 과소 집계한다.
- 품질 검토 반복 호출은 비용 상한을 우회할 수 있다.

완료 조건:

1. 동일 assistant request ID 평가 레코드에 review 모델 사용량을 안전하게 반영한다.
2. 가격이 없으면 비용은 null을 유지한다.
3. 비용 상한을 모델 결과 적용 전에 fail-closed로 검사한다.
4. 평가 저장 실패가 review 응답이나 성공한 Revision을 rollback하지 않게 한다.

### P2. prompt 안전 문구 오류

위치:

- `src/ai/prompt_registry.py`
- `report.assistant.turn`

현재 문구 일부:

```text
emit coordinates, real Artifact IDs, query IDs, checksums, or hidden metadata.
```

문맥상 `Never emit ...`이 의도된 것으로 보인다.

문제:

- 모델에 내부 식별자 출력을 지시하는 의미가 된다.
- strict schema와 서버 검증이 직접 저장은 막지만 contract failure와 정보 복사 위험을 높인다.

완료 조건:

1. 금지 문구를 명확한 `Never emit ...`으로 수정한다.
2. prompt version과 model release를 함께 갱신한다.
3. 악의적 지시에서도 identifier·SQL이 응답에 없는 계약 테스트를 유지한다.

### P3. DB operation 선택 constraint가 API 계약보다 약함

위치:

- `app/backend/migrations/versions/20260826_40_report_assistant_patch_selection.py`

현재 DB constraint는 배열 길이와 NULL만 검사한다. 음수, 중복, 정렬, patch operation 범위는 API와
서버 코드에서만 검사한다.

완료 조건:

- 기존 migration 40은 수정하지 않는다.
- DB-level 강화가 실제로 필요하다고 판단되면 additive migration을 사용한다.
- 최소한 repository read-back과 response validation이 음수·중복·범위 초과를 fail-closed하는지
  테스트한다.

## 15. 11차 요청 취소 상태

판정: **미구현**

존재하는 것:

- `cancelled` phase
- terminal 상태 표시 문구

없는 것:

- `POST /reports/assistant/sessions/{assistant_request_id}/cancel`
- repository cancel CAS
- Client cancel method
- phase별 cancel 버튼
- 실행·저장 중 취소 불가 안내의 API/UI 계약

Analysis 전용 cancel API는 Report Assistant 취소 기능으로 계산하지 않는다.

## 16. 구현 완료 후 필수 재검증

```powershell
$env:PYTHONPATH='.;app/backend'
python -m unittest `
  tests.ai.test_report_assistant_contract `
  tests.backend.test_report_assistant_session `
  tests.backend.test_report_assistant_operations `
  tests.backend.test_report_assistant_patch `
  tests.backend.test_report_migration

python app/backend/scripts/export_openapi.py --check
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
python scripts/audit_repository_integrity.py
python -m compileall -q app/backend src evals tests
git diff --check

Set-Location app/frontend
npm.cmd run test
npm.cmd run build
```

격리 PostgreSQL·Browser 검증 시 필수 시나리오:

1. migration 39·40과 후속 additive migration 적용
2. 실제 GPT가 2개 이상 operation 제안
3. 승인 전 Report version 무변경
4. operation 일부 승인 후 선택한 항목만 저장
5. 동일 승인 재전송 시 Revision 증가 없음
6. `saving_revision` 중단 뒤 GPT·AnalysisController 재호출 없이 복구
7. Canvas와 새로고침 뒤 evidence refs·Revision 동일
8. 브라우저 state·DOM·network에 query ID/checksum/SQL 없음
9. 품질 검토 호출도 token·latency·비용 평가에 연결
10. console error와 관련 Backend 500 없음

실제 OpenAI, PostgreSQL, Browser를 사용하지 않은 결과는 live E2E로 표현하지 않는다.

## 17. 최종 완료 Gate

다음이 같은 release와 assistant request ID로 연결돼야 기존 Artifact 편집 흐름을 완료로 판정한다.

```text
실제 GPT 호출
→ strict 계약 검증
→ 서버 DB session
→ owner·Artifact lineage 검증
→ 사용자 선택 승인
→ CAS Report Revision 한 건
→ Canvas 반영
→ 새로고침 복구
→ 중복 승인 Revision 0건
```

Trino·DataHub가 준비되지 않았다면 `new_data` live E2E는 계속 미완료로 별도 표기한다.
