# Report Assistant V2 개발자 가이드

## 1. 문서 목적

이 문서는 `seung` 브랜치에 구현된 Report Assistant V2의 기능, 데이터 흐름, 코드 위치,
API, migration, 테스트 증거와 미완료 범위를 다른 개발자가 한 문서에서 확인할 수 있도록 정리한다.

- 저장소: `report-assistant-advanced`
- 공유 브랜치: `seung`
- 이전 통합 기준 커밋: `2da6d88` (`feat(report): complete assistant v2 stages 1-4`)
- 현재 문서 기준: migration 36과 실패 복구 실제 DB·Browser 검증을 포함한 `seung` 최신 push
- 문서 기준일: 2026-08-25
- 현재 migration code head: `20260825_36`

Report Assistant는 별도 Agent framework나 microservice가 아니다. 기존 Report API,
`AnalysisController`, model gateway, PostgreSQL repository와 ReportsPage를 연결한 서버 소유
상태 기반 기능이다.

## 2. 한눈에 보는 현재 기능

| 영역 | 구현 상태 | 설명 |
|---|---|---|
| 서버 소유 Assistant session | 구현 | 서버가 request ID와 phase를 생성·저장하고 새로고침 뒤 복구한다. |
| GPT strict 변경 제안 | 구현 | 모델 출력은 typed schema로 검증하며 권한·승인·SQL을 모델에 맡기지 않는다. |
| 기존 Artifact 기반 편집 | 구현·실제 편집 E2E 확인 | 승인된 Artifact 근거 안에서 보고서 patch를 만들고 사용자 승인 뒤 Revision을 저장한다. |
| 새 데이터 분석 계획 | 구현·unit/contract 확인 | `new_data` 계획을 저장하고 사용자 승인 뒤 기존 `AnalysisController`를 한 번만 호출한다. |
| Trino·DataHub live `new_data` | 미완료 | 관련 dependency readiness가 확보되지 않아 실제 데이터 E2E는 완료되지 않았다. |
| Report Revision CAS | 구현 | 기준 Revision이 바뀌면 덮어쓰지 않고 typed conflict로 중단한다. |
| 중복 승인 방지 | 구현 | 같은 승인 요청이 분석이나 Revision을 추가 생성하지 않는다. |
| Canvas·새로고침 복구 | 구현·Browser 확인 | 완료 Revision을 화면에 반영하고 재진입 시 서버 상태를 복구한다. |
| 품질·token·비용 평가 | 구현 | request ID별 평가 한 건을 멱등 저장한다. usage나 가격이 없으면 `null`이다. |
| 사용자 실행 영수증 | 구현 | 사용자는 자신의 route·계약·Revision·지연·안전한 오류만 확인한다. |
| 관리자 운영 API | 구현 | 기간 summary, 실패 목록, session evaluation API가 있다. |
| 실패 복구·안전 재시도 | 구현·실제 DB·Browser 확인 | 모델 실패를 typed `failed`로 종결하고 원본을 보존한 새 `ready` session을 멱등 생성한다. |

## 3. 전체 구조

```text
ReportsPage / ReportAssistantPanel
        │
        ▼
reportClient.ts
        │ cookie 인증 + request context headers
        ▼
app/api/report_router.py
        ├── report_contracts.py              typed HTTP/domain 계약
        ├── adapters/report_assistant.py     strict model 호출
        ├── report_patch.py                  검증 patch 적용
        ├── AnalysisController               기존 new_data 분석 pipeline
        └── ReportRepository
              ├── report_artifact_repository.py
              │     session·승인·Artifact·Revision·retry
              ├── report_definition_repository.py
              │     owner 범위 Report 조회·draft CAS revision
              └── report_assistant_operations_repository.py
                    평가·품질·비용 관측
```

핵심 원칙은 다음과 같다.

1. Frontend가 phase, request ID, 승인 결과를 임의로 만들지 않는다.
2. 모델 출력은 신뢰하지 않고 strict schema와 서버 dry-run을 통과시킨다.
3. 사용자 승인 전에는 분석이나 Report Revision 저장을 실행하지 않는다.
4. Artifact는 owner, 승인 상태, 분석 상태, request/query/checksum lineage로 다시 검증한다.
5. Report 변경은 기존 version을 덮어쓰지 않고 CAS 방식의 새 Revision으로 저장한다.
6. production 코드에는 질문별 고정 응답, fallback Artifact, 분석용 고정 SQL이나 mock이 없다.

## 4. 서버 session phase

현재 공개 phase는 다음과 같다.

| Phase | 의미 |
|---|---|
| `ready` | 사용자 지시를 받을 수 있다. |
| `waiting_patch_approval` | 기존 Artifact 기반 변경안을 사용자가 검토한다. |
| `waiting_approval` | 새 데이터 분석 계획을 사용자가 검토한다. |
| `running_data_agent` | 최초 승인 claim 뒤 기존 분석 pipeline을 실행한다. |
| `waiting_artifact` | 분석 결과 Artifact를 검증·결속한다. |
| `saving_revision` | 검증된 patch 또는 Artifact를 CAS Revision으로 저장한다. |
| `completed` | 새 Revision 저장이 완료됐다. |
| `failed` | 안전한 error code와 함께 중단됐다. |
| `cancelled` | 사용자 거절 또는 취소 결과다. 일부 거절 흐름은 다시 `ready`로 돌아간다. |

## 5. 기능별 데이터 흐름

### 5.1 Session 생성과 모델 판단

```text
Report draft 선택
→ Report가 참조하는 APPROVED Artifact 확인
→ POST /reports/assistant/sessions
→ 서버 assistant_request_id 생성
→ ready 저장
→ 사용자 지시 제출
→ report.assistant.turn strict 모델 호출
→ clarification / existing_artifact / new_data 분류
→ 서버 phase 저장
```

- session에는 owner, definition ID/version, base revision, Artifact ID와 prompt release가 결속된다.
- 사용자 지시의 감사 값은 SHA-256 hash로 남고 운영 API에 원문을 공개하지 않는다.
- 모델이 반환한 임의 request ID, Artifact ID, query ID, SQL은 실행 권위로 사용하지 않는다.
- 세션 ID는 브라우저 `sessionStorage`에 복구 포인터로만 저장하며 권위 상태는 서버 DB다.

### 5.2 기존 Artifact 기반 보고서 편집

```text
existing_artifact
→ typed patch 생성
→ 서버 dry-run
→ waiting_patch_approval
→ 사용자 적용 또는 취소
→ saving_revision
→ CAS 새 Report Revision
→ completed
→ Canvas 반영 및 새로고침 복구
```

지원 patch operation은 다음 8종이다.

- `set_report_title`: 보고서 제목 변경
- `add_text`: 텍스트 블록 추가
- `update_text`: 기존 텍스트 블록 수정
- `add_artifact_view`: 승인 Artifact 기반 차트·표·Artifact view 추가
- `reposition_block`: 블록 이동 및 폭 변경
- `duplicate_block`: 블록 복제
- `remove_block`: 블록 삭제
- `restore_previous_revision`: 직전 Revision 복원

검증 규칙:

- 존재하지 않는 block ID는 거부한다.
- 마지막 block 삭제는 거부한다.
- `restore_previous_revision`은 단독 operation으로만 허용한다.
- Artifact ID, query ID, checksum은 서버의 `VerifiedArtifactBinding`에서만 가져온다.
- 승인 전과 거절 시 Report definition/block은 변경되지 않는다.
- 같은 patch 승인 재호출은 기존 완료 Revision을 반환한다.

### 5.3 새 데이터 분석

```text
new_data
→ 서버 data_request_id 생성
→ waiting_approval
├─ 거절: rejected_at 기록 → AnalysisController 0회 → ready
└─ 승인: owner·권한·request ID·phase 검증
          → running_data_agent
          → 기존 AnalysisController 1회
          → waiting_artifact
          → Artifact lineage 검증
          → saving_revision
          → CAS Report Revision
          → completed
```

승인 전 검증:

- session owner
- `Capability.RUN_ANALYSIS`
- `waiting_approval` phase와 legacy `running` status
- 서버가 만든 `data_request_id`
- 완전한 typed analysis plan

Artifact 검증:

- session owner와 Artifact owner 일치
- Artifact status `APPROVED`
- 분석 request status `SUCCEEDED` 또는 `PARTIAL`
- Artifact request ID와 `data_request_id` 일치
- query execution 및 `trino_query_id` 존재
- 64자리 소문자 SHA-256 checksum
- controller query ID와 저장 query ID 일치

현재 이 코드 경로는 fake repository/controller 기반 회귀 테스트를 통과했다. Trino와 DataHub가
ready인 동일 release에서 수행한 live `new_data` E2E는 아직 없다.

### 5.4 품질·비용·운영 관측

request ID당 평가 한 건에 다음을 연결한다.

- definition, Artifact, data/patch request ID
- prompt/model release
- `existing_artifact` 또는 `new_data` route
- patch operation 종류
- strict 계약 성공 여부
- 승인·거절 결정
- 최종 phase와 error code
- Revision 생성 및 중복 Revision 방지
- model attempts와 latency
- provider input/output token
- 설정된 단가가 있을 때만 계산한 예상 비용

평가 저장 transaction은 핵심 Revision transaction과 분리돼 있다. 평가 저장 장애 때문에 이미
검증된 Revision을 rollback하지 않는다. SQL, raw prompt, raw model response, credential과 전체
사용자 지시는 평가 table이나 운영 API에 저장·반환하지 않는다.

### 5.5 실패 복구와 안전 재시도

```text
failed 원본 session
→ error code retry 정책 판단
→ 사용자 재시도 선택
→ Report revision 재검증
→ Artifact owner·approval·query·checksum 재검증
→ 새 assistant_request_id를 ready로 저장
→ 사용자가 지시를 다시 입력
```

재시도는 실패 세션을 `ready`로 되돌리지 않는다. migration 36의 자기참조 lineage와 unique
index로 원본 실패 session당 자식 session 하나만 만든다. 중복 HTTP 호출은 같은 자식 session을
반환한다.

재시도 시 자동으로 복사하거나 실행하지 않는 항목:

- 사용자 지시 원문
- 기존 `data_request_id`
- 기존 analysis plan과 patch request
- 기존 사용자 승인
- 모델 호출
- `AnalysisController`
- Report Revision 저장

모델 transport 또는 strict turn 계약이 실패하면 Backend는 평가만 기록하고 세션을 남겨두지 않는다.
`REPORT_ASSISTANT_TURN_MODEL_FAILED` 또는 `REPORT_ASSISTANT_TURN_MODEL_INVALID`로 원본 session을
`failed`에 종결한다. Frontend는 실패 HTTP 응답 직후 같은 session을 서버에서 다시 조회해
`retryable`·`required_action`을 반영하므로 새로고침 없이도 안전한 실패 카드가 표시된다.

서버가 반환하는 `required_action`:

| Action | 사용자 조치 |
|---|---|
| `NONE` | 자동 재시도하지 않고 현재 요청을 다시 확인한다. |
| `RETRY` | 새 session에서 지시를 다시 입력한다. |
| `REFRESH` | 서버 최신 상태를 새로고침한다. |
| `REAUTHENTICATE` | 다시 로그인하고 권한을 확인한다. |
| `REOPEN_LATEST_REPORT` | 최신 Report Revision을 다시 연다. |
| `CONTACT_ADMIN` | Artifact lineage, checksum, 권한 또는 예산 설정을 운영자가 확인한다. |

일시적인 모델·분석·동시성 장애만 `retryable=true`다. 권한, Artifact lineage/checksum,
Revision conflict와 알 수 없는 오류는 fail-closed로 자동 재시도하지 않는다.

## 6. Backend API

| Method | Path | 역할 |
|---|---|---|
| `POST` | `/reports/assistant/sessions` | Report·Artifact 결속을 검증하고 `ready` session 생성 |
| `GET` | `/reports/assistant/sessions/{assistant_request_id}` | owner 범위 session 복구 |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/messages` | strict 모델 제안 생성·저장 |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/patch-approval` | 기존 Artifact patch 승인·거절 및 CAS 저장 |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/approval` | 새 데이터 계획 승인·거절 및 분석 실행 |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/retry` | 실패 원본을 보존하고 새 session 생성 |
| `GET` | `/reports/assistant/sessions/{assistant_request_id}/evaluation` | 자신의 안전한 실행 평가 조회 |
| `GET` | `/reports/assistant/operations/summary` | 관리자 기간 품질·비용 집계 |
| `GET` | `/reports/assistant/operations/failures` | 관리자 기간 실패 목록 |
| `POST` | `/reports/assistant/drafts` | 기존 관리자용 단발성 AI draft 호환 API |

모든 session endpoint는 기존 cookie 인증과 request context header 계약을 사용한다. 타인 또는
미존재 session은 404로 숨기고, request/phase 충돌은 409, 권한 부족은 403으로 반환한다.

## 7. 주요 Backend 파일 위치

| 파일 | 책임 |
|---|---|
| `app/backend/app/api/report_router.py` | Assistant HTTP endpoint, phase 실행 순서, 권한·승인 경계 |
| `app/backend/app/api/report_router_support.py` | Report draft/admin context와 기존 router 조립 |
| `app/backend/app/report_contracts.py` | session, plan, patch, evaluation, retry typed 계약 |
| `app/backend/app/report_patch.py` | 검증된 patch 8종을 immutable Report definition에 적용 |
| `app/backend/app/adapters/report_assistant.py` | `report.assistant`와 `report.assistant.turn` strict 모델 호출 |
| `app/backend/app/adapters/model_schemas.py` | 모델 request/response schema 등록 |
| `app/backend/app/adapters/report_artifact_repository.py` | Artifact 검증, session 상태, 승인 claim, Revision CAS, retry lineage |
| `app/backend/app/adapters/report_definition_repository.py` | owner 범위 Report 값 객체와 retry 전 draft CAS revision 조회 |
| `app/backend/app/adapters/report_assistant_operations_repository.py` | 평가 upsert와 기간 조회 |
| `app/backend/app/services/report_assistant_operations.py` | 품질·승인·Revision·latency·token·비용 지표 집계 |
| `app/backend/app/controllers/analysis_controller.py` | 새 분석에서 재사용하는 기존 분석 pipeline |
| `app/backend/contracts/openapi.v0.1.json` | 현재 API 공개 계약 생성본 |

## 8. 주요 Frontend 파일 위치

| 파일 | 책임 |
|---|---|
| `app/frontend/src/api/reportClient.ts` | session 생성·복구·지시·승인·평가·retry HTTP client와 phase 검증 |
| `app/frontend/src/contracts/reportContract.ts` | Backend와 공유하는 Assistant TypeScript 계약 |
| `app/frontend/src/features/reports/useReportLifecycleState.ts` | session, 승인, retry, 평가 영수증과 비동기 상태 소유 |
| `app/frontend/src/features/reports/useReportsPageController.jsx` | Assistant 결과 Revision을 editor와 Artifact hydration에 적용 |
| `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx` | 대화, 승인 카드, 실패 조치, retry 버튼, 사용자 평가 영수증 |
| `app/frontend/src/features/reports/components/ReportAssistantOperationsPanel.jsx` | 관리자용 운영 지표 화면 |
| `app/frontend/src/pages/ReportsPage.jsx` | Report editor와 Assistant panel의 최소 wiring |

실패 화면에서는 서버가 `retryable=true`로 반환한 경우에만 `새 세션으로 다시 시도` 버튼이
표시된다. 버튼 클릭은 새 `ready` session으로 교체하고 이전 평가 영수증과 입력창을 비우지만,
지시를 자동 제출하지 않는다.

## 9. Migration chain

| Revision | 역할 |
|---|---|
| `20260812_11` | 기존 단발성 Report Assistant request 기반 |
| `20260824_29` | 서버 소유 session phase와 analysis plan |
| `20260824_30` | 결과 Artifact query/checksum lineage |
| `20260824_31` | Report definition revision CAS |
| `20260824_32` | typed report patch 감사 필드 |
| `20260824_33` | session turn history |
| `20260825_34` | patch 승인 phase와 request ID |
| `20260825_35` | request ID별 품질·비용 평가 |
| `20260825_36` | 실패 session retry lineage와 원본별 unique child |

`20260825_36`은 기존 migration을 수정하지 않는 additive migration이다. 코드 graph는 단일 head이며
격리 DB `app_db_report_assistant_e2e`에 실제 적용했다. 공용·운영 App DB에는 적용하지 않았고 기존
volume이나 데이터를 삭제하지 않았다.

## 10. 테스트와 평가 위치

| 파일 | 검증 범위 |
|---|---|
| `tests/ai/test_report_assistant_contract.py` | strict model schema와 typed patch 변환 |
| `tests/backend/test_report_assistant_session.py` | session, 승인, 분석, Artifact, CAS, retry |
| `tests/backend/test_report_assistant_patch.py` | patch 8종과 안전한 거부 |
| `tests/backend/test_report_assistant_operations.py` | 평가 upsert, 지표, 권한, 기간·비용 계약 |
| `tests/backend/test_report_migration.py` | migration chain과 민감 column 부재 |
| `tests/frontend/contracts.test.mjs` | client URL/body, phase, retry, UI 권한·표시 계약 |
| `evals/report_assistant_quality_cases.json` | deterministic 품질 시나리오 16건 |
| `evals/report_assistant_quality.py` | fake 결과와 route·operation·승인·오류 기대값 비교 |
| `tests/e2e/prepare_report_assistant_e2e.py` | 격리 DB의 기존 Artifact 편집 E2E fixture 전용 |

2026-08-25 최종 회귀 결과:

- Backend·AI·migration 관련 `unittest` 89개 통과
- Frontend test 24개 통과
- Frontend production build 통과
- OpenAPI contract 검증 통과
- 코드 문서화, architecture invariant, repository integrity 검사 통과
- Python `compileall` 및 `git diff --check` 통과
- 로컬 Python에 `pytest`가 없어 전체 pytest suite는 미실행

테스트의 fake model/repository/controller는 `tests` 아래에서만 명시적으로 주입한다. fake 테스트는
unit/contract 증거이며 live 데이터 E2E로 표현하지 않는다.

## 11. 실제 확인된 E2E와 미완료 범위

### 확인된 범위

- 실제 OpenAI model과 격리 PostgreSQL을 사용한 기존 Artifact 편집 API E2E
- 실제 모델의 `set_report_title`, `add_text` patch 생성
- 승인 전 Report 무변경
- 승인 뒤 CAS Revision 생성
- 같은 승인 요청의 중복 Revision 방지
- Browser에서 승인 카드, completed, Canvas 반영과 새로고침 복구
- Browser console error와 관련 Backend 500 부재 확인
- migration 36을 적용한 실제 PostgreSQL에서 retry API 중복 호출이 동일 자식 session을 반환
- 원본 실패 phase·error code·완료 시각 보존과 Report Revision 무변경 확인
- Browser에서 모델 장애의 typed 실패 카드, `새 세션으로 다시 시도` 버튼과 새 `ready` session 전환 확인
- 실패·retry 동작 동안 모델 재호출, AnalysisController, Report Revision 저장이 실행되지 않음

### 아직 완료되지 않은 범위

- Trino, DataHub, semantic release, catalog manifest, Trino schema readiness
- `new_data`의 DataHub → SQL Guard → Trino → Artifact → Revision live E2E
- `running_data_agent` claim 직후 process가 종료될 때의 완전한 exactly-once 보장

queue/outbox/worker를 추가하지 않았기 때문에 분석 실행 직전·직후 crash의 완전한 exactly-once는
보장하지 않는다. 현재는 DB claim과 서버 고정 request ID로 정상 재호출의 중복 실행을 막는다.
반면 retry session 생성은 원본별 unique index가 있어 DB commit 뒤 응답이 유실돼도 같은 자식을
다시 조회할 수 있다.

## 12. 로컬 실행 참고

기존 검증에서 사용한 주소:

- Frontend: `http://127.0.0.1:13002/reports`
- Backend: `http://127.0.0.1:18002`

현재 process가 같은 commit으로 실행 중이라는 보장은 없으므로 개발자는 먼저 `/health`,
`/readiness`, migration revision과 Frontend build source를 확인해야 한다. `/health` 200이나 화면
렌더링만으로 Agent E2E 성공으로 판단하지 않는다.

필수 설정은 저장소의 `.env.example`과 기존 외부 deployment env 패턴을 따른다. secret 값은
저장소 `.env`, 문서, 명령 인자나 Git diff에 넣지 않는다.

주요 제한 설정 이름:

- `REPORT_ASSISTANT_MAX_MODEL_ATTEMPTS`
- `REPORT_ASSISTANT_MAX_INPUT_TOKENS`
- `REPORT_ASSISTANT_MAX_OUTPUT_TOKENS`
- `REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD`
- `REPORT_ASSISTANT_REQUESTS_PER_HOUR`
- `REPORT_ASSISTANT_STALE_SECONDS`

## 13. 다음 개발자가 진행할 순서

1. `AGENTS.md`, `docs/README.md`와 이 문서를 읽는다.
2. `git status --short --branch`로 다른 개발자의 dirty 변경을 확인하고 보존한다.
3. 대상 DB의 migration 36 적용 여부를 확인하고 공용·운영 DB에는 별도 승인 없이 적용하지 않는다.
4. 최신 Backend와 Frontend를 재기동하고 model·App DB·auth readiness를 확인한다.
5. 실패 복구 회귀 시 기존 원본 불변·retry child uniqueness·Revision 무변경을 다시 확인한다.
6. 새 session에 사용자가 지시를 입력한 뒤 기존 승인 흐름이 정상인지 회귀 확인한다.
7. Trino·DataHub가 ready가 된 후에만 `new_data` live E2E를 별도 수행한다.

## 14. 팀 공유 시 핵심 설명

Report Assistant V2는 화면에 고정 응답을 보여주는 기능이 아니다. 실제 모델이 승인된 Artifact와
현재 Report definition을 바탕으로 typed 변경안을 제안하고, 서버가 owner·권한·request ID·
Artifact lineage를 검증한 뒤 사용자 승인 시에만 새 Revision을 저장한다. 새 데이터가 필요하면
기존 `AnalysisController`로 연결하지만 현재 Trino·DataHub live E2E는 아직 남아 있다. 실패한
요청은 덮어쓰지 않고 감사 기록을 보존한 새 session으로만 안전하게 다시 시작한다.
