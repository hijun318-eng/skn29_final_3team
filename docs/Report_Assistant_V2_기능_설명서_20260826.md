# Report Assistant V2 기능 설명서

## 1. 문서 목적

이 문서는 `seung` 브랜치의 Report Assistant V2를 백엔드 개발자와 클라이언트 개발자가
연동·검증할 때 사용하는 기능 설명서다. 작업 일지나 향후 계획이 아니라 현재 코드에 구현된
기능, 공개 API, 상태 계약, 책임 경계와 미완료 범위를 설명한다.

- 저장소: `report-assistant-advanced`
- 공유 브랜치: `seung`
- 문서 확인 기준 커밋: `0ea675cf3560973e8931e634bc3844f0b727bcc8`
- 문서 기준일: 2026-08-26
- 현재 작업 tree migration head: `20260826_38` (`seung` 마지막 공유 커밋은 `20260825_36`)

실제 구현 여부의 최종 권위는 현재 코드, OpenAPI, migration과 실행 결과다. 다른 브랜치에서
migration 번호를 재배치했다면 번호가 아니라 revision graph와 실제 schema를 함께 확인한다.

## 2. 제품 기능 요약

Report Assistant V2는 고정 문구를 반환하는 화면 기능이 아니다. 실제 GPT가 승인된 Analysis
Artifact와 현재 Report draft를 읽고 제한된 변경안을 생성하며, 서버 검증과 사용자 승인을
통과한 경우에만 새 Report Revision을 저장하는 서버 소유 Assistant다.

현재 제공하는 핵심 기능은 다음과 같다.

1. 서버 소유 Assistant session 생성 및 새로고침 복구
2. GPT strict schema 기반 요청 분류
3. 부족한 요청에 대한 추가 질문
4. 기존 승인 Artifact 기반 보고서 변경안 생성
5. 변경안 dry-run과 사용자 승인·거절
6. 제목·텍스트·Artifact 블록의 추가·수정·이동·복제·삭제·복원
7. 승인 시에만 CAS 방식의 새 Report Revision 저장
8. 동일 승인 요청의 모델·분석·Revision 중복 실행 방지
9. 새 데이터 필요 요청의 승인 계획 생성
10. 분석 결과 Artifact의 owner·request·query·checksum lineage 재검증
11. 실패 유형별 안전한 사용자 조치 및 새 session 재시도
12. 모델 계약·지연·token·예상 비용·승인·Revision 결과 평가

## 3. 구현 범위와 현재 판정

| 기능 | 현재 판정 | 근거 범위 |
|---|---|---|
| GPT 기반 기존 Artifact 편집 | 구현 및 실제 GPT·PostgreSQL E2E 확인 | 모델 변경안, 승인 전 무저장, Revision 저장 |
| Browser 승인·Canvas 복구 | 구현 및 Browser 확인 | 승인 카드, completed, 새로고침 복구 |
| 변경안 중복 승인 방지 | 구현 | 동일 request ID에서 Revision 추가 생성 방지 |
| 실패 session 안전 재시도 | 구현 및 PostgreSQL·Browser 확인 | 원본 보존, 동일 자식 session 반환 |
| 평가·token·비용 관측 | 구현 | request ID별 멱등 평가 레코드 |
| 새 데이터 분석 코드 경로 | 구현 및 unit/contract 확인 | 승인·AnalysisController·Artifact 검증·Revision |
| Trino·DataHub `new_data` live E2E | 미완료 | dependency readiness 미확보 |
| 변경안에 대한 추가 수정 대화 | 구현·contract/unit 확인 | 최신 patch ID를 결속한 전체 대체 patch, 승인 전 무저장 |
| 텍스트 Artifact 근거 참조 검증 | 구현·contract/unit 확인 | 안전한 catalog 별칭, 서버 ref 검증, 승인 카드 표시 |
| 여러 Artifact 동시 종합 | 미구현 | session당 Artifact 한 개 결속 |

`model=ready`, 화면 렌더링 또는 fake 테스트만으로 전체 Agent E2E 완료라고 판정하지 않는다.

## 4. 전체 구성

```text
ReportsPage
  └─ ReportAssistantPanel
       └─ useReportLifecycleState
            └─ reportClient.ts
                 │ cookie 인증 + request context
                 ▼
            report_router.py
              ├─ report_contracts.py
              ├─ report_assistant.py ── GPT strict model gateway
              ├─ report_patch.py ────── server dry-run/apply
              ├─ report_artifact_repository.py
              ├─ report_assistant_operations_repository.py
              └─ AnalysisController ─── new_data 경로에서만 재사용
```

Report Assistant는 별도 microservice나 범용 Agent framework가 아니다. 기존 Report API, model
gateway, PostgreSQL repository와 `AnalysisController`를 서버 상태 머신으로 연결한다.

## 5. GPT가 담당하는 것과 담당하지 않는 것

### GPT가 담당하는 것

- 사용자 지시와 최근 대화 문맥 이해
- 현재 Report 구조와 승인 Artifact 내용 해석
- `clarification`, `existing_artifact`, `new_data` 중 하나 제안
- 기존 Artifact로 가능한 경우 제한된 typed patch 생성
- 새 데이터가 필요한 경우 사용자에게 보여 줄 질문·필요 이유·범위 제안

### 서버만 담당하는 것

- owner와 capability 검증
- session, patch, data request ID 생성
- Artifact 승인·query·checksum lineage 검증
- 모델 output strict schema 검증
- patch dry-run 및 block ID 검증
- 승인 상태와 phase 전이
- 분석 실행 여부 결정
- Report Revision CAS 저장
- 중복 실행 방지와 실패 정책

### GPT에 맡기지 않는 것

- 로그인·권한 결정
- 사용자 승인
- SQL 생성·실행 권위
- 실제 Artifact ID, query ID, checksum 선택
- Report Revision 직접 저장
- 존재하지 않는 데이터를 성공으로 대체하는 fallback

## 6. Assistant session 상태

| Phase | 의미 | 클라이언트 동작 |
|---|---|---|
| `ready` | 사용자 지시 입력 가능 | 메시지 제출 허용 |
| `waiting_patch_approval` | 기존 Artifact 변경안 검토 중 | 변경안 적용 또는 거절 |
| `waiting_approval` | 새 데이터 계획 검토 중 | 분석 승인 또는 거절 |
| `running_data_agent` | 최초 승인 claim 후 분석 실행 | 중복 승인 금지, 상태 표시 |
| `waiting_artifact` | 반환 Artifact lineage 검증 | 상태 표시 |
| `saving_revision` | CAS Revision 저장 중 또는 안전한 저장 재개 가능 | 현재 request ID 유지 |
| `completed` | 새 Revision 저장 완료 | `result_revision` 조회 후 Canvas 반영 |
| `failed` | typed error로 안전하게 종료 | `retryable`, `required_action` 표시 |
| `cancelled` | 취소 terminal 상태 | 입력을 자동 재실행하지 않음 |

기존 Artifact 변경안과 새 데이터 계획을 사용자가 거절하면 감사 시각을 보존하고 `ready`로
돌아간다. `cancelled` phase는 공개 계약에 존재하지만 현재 Report Assistant 전용 cancel API는
없다.

## 7. 정상 사용자 흐름

### 7.1 Session 생성과 요청 분류

```text
draft Report 및 승인 Artifact 선택
→ POST /reports/assistant/sessions
→ ready session 반환
→ POST /reports/assistant/sessions/{id}/messages
→ GPT strict 응답 검증
→ clarification / existing_artifact / new_data
```

- session은 owner, Report definition ID/version, base revision, Artifact에 결속된다.
- 브라우저에 저장한 session ID는 복구 포인터일 뿐 권위 상태는 서버 DB다.
- 사용자 지시는 감사용 SHA-256 hash를 남긴다.
- 최근 대화는 bounded history로 전달되며 권한이나 데이터 근거로 사용하지 않는다.

### 7.2 추가 질문

필수 기간, 지표, 차원 또는 표현 방식이 불명확하면 GPT는 `clarification`을 반환한다.

```text
불명확한 사용자 지시
→ clarification 메시지
→ phase ready 유지
→ 사용자 보충 답변
→ bounded history를 포함해 다시 GPT 호출
```

추가 질문에는 analysis plan이나 patch가 함께 올 수 없도록 schema가 막는다.

### 7.3 기존 Artifact 기반 편집

```text
existing_artifact
→ typed patch 생성
→ 서버 dry-run
→ waiting_patch_approval
├─ 거절: rejected_at 기록 → Report 무변경 → ready
└─ 승인: saving_revision → CAS Revision → completed
```

지원 operation은 다음 8종이다.

| Operation | 기능 | 주요 서버 검증 |
|---|---|---|
| `set_report_title` | 보고서 제목 변경 | 빈 제목·길이 제한 |
| `add_text` | 텍스트 블록 추가 | 내용·상대 위치·폭 검증 |
| `update_text` | 기존 텍스트 수정 | 기존 text block ID 확인 |
| `add_artifact_view` | 차트·표·Artifact view 추가 | 서버 별칭 `source_artifact`만 허용 |
| `reposition_block` | 블록 이동 및 폭 변경 | 기존 block/anchor, 상대 위치만 허용 |
| `duplicate_block` | 기존 블록 복제 | 서버가 새 block ID 생성 |
| `remove_block` | 기존 블록 삭제 | 존재 여부 및 마지막 블록 보호 |
| `restore_previous_revision` | 직전 Revision 복원 | 다른 operation과 혼합 금지 |

모델은 절대 좌표, 실제 Artifact ID, query ID나 checksum을 patch에 넣을 수 없다. 서버가 현재
Report와 `VerifiedArtifactBinding`을 사용해 최종 값을 계산한다.

### 7.4 새 데이터 계획

```text
new_data
→ 서버 data_request_id 생성
→ waiting_approval
├─ 거절: AnalysisController 0회 → ready
└─ 승인: 권한·owner·request ID·phase 검증
          → AnalysisController 최초 1회
          → Artifact lineage 검증
          → CAS Revision
          → completed
```

이 경로의 코드와 fake 기반 회귀 테스트는 구현돼 있다. 현재 문서 기준으로 DataHub, Trino와
동일 request ID로 연결한 live E2E는 완료되지 않았다.

## 8. Backend 공개 API

모든 endpoint는 기존 cookie 인증과 request context 계약을 사용한다. UUID 예시는 형식 설명용
가상 값이다.

| Method | Path | 요청 | 성공 결과 |
|---|---|---|---|
| `POST` | `/reports/assistant/sessions` | definition/version/artifact | `ready` session |
| `GET` | `/reports/assistant/sessions/{assistant_request_id}` | 없음 | 현재 서버 session |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/messages` | `instruction` | proposal + session |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/patch-approval` | request ID + approved | patch 결정 후 session |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/approval` | request ID + approved | 분석 계획 결정 후 session |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/retry` | 없음 | 새 `ready` session |
| `GET` | `/reports/assistant/sessions/{assistant_request_id}/evaluation` | 없음 | 자신의 안전한 평가 |
| `GET` | `/reports/assistant/operations/summary` | 기간 query | 관리자 집계 |
| `GET` | `/reports/assistant/operations/failures` | 기간 query | 관리자 실패 목록 |

### 8.1 Session 생성 요청

```json
{
  "definition_id": "00000000-0000-4000-8000-000000000001",
  "definition_version": 3,
  "artifact_id": "00000000-0000-4000-8000-000000000002"
}
```

### 8.2 메시지 제출 요청

```json
{
  "instruction": "핵심 요약을 세 문장으로 줄이고 차트를 위로 옮겨줘"
}
```

응답의 `change_kind`는 다음 세 값 중 하나다.

- `clarification`: 추가 질문, session은 `ready`
- `existing_artifact`: patch 미리보기, session은 `waiting_patch_approval`
- `new_data`: 분석 계획, session은 `waiting_approval`

### 8.3 승인·거절 요청

```json
{
  "request_id": "00000000-0000-4000-8000-000000000003",
  "approved": true
}
```

- patch 결정에는 `patch_request_id`를 전달한다.
- 분석 계획 결정에는 `analysis_plan.request_id`를 전달한다.
- 클라이언트가 새 request ID를 생성하면 안 된다.
- URL session ID와 body request ID를 혼동하면 서버가 `409`로 닫는다.

### 8.4 핵심 Session 응답 필드

```json
{
  "assistant_request_id": "...",
  "phase": "waiting_patch_approval",
  "definition_id": "...",
  "definition_version": 3,
  "base_revision": 3,
  "artifact_id": "...",
  "analysis_plan": null,
  "patch_request_id": "...",
  "patch_summary": "요약을 줄이고 차트를 위로 이동합니다.",
  "patch_operations": ["update_text", "reposition_block"],
  "result_artifact_id": null,
  "result_revision": null,
  "error_code": null,
  "retryable": false,
  "required_action": "NONE",
  "retry_of_assistant_request_id": null
}
```

응답에는 patch의 전체 본문, SQL, raw prompt, raw model response, credential을 포함하지 않는다.

## 9. HTTP 오류와 클라이언트 처리

| HTTP | 의미 | 클라이언트 처리 |
|---|---|---|
| `403` | 권한 부족 | 재인증 또는 권한 안내, 자동 재시도 금지 |
| `404` | session/Artifact 미존재 또는 타인 소유 | 존재 여부를 추측하지 않고 목록으로 복귀 |
| `409` | phase, request ID, Revision 충돌 | session 재조회 또는 최신 Report 열기 |
| `422` | 요청 typed 계약 위반 | 입력값 수정 |
| `429` | rate/token/cost/concurrency 제한 | 서버 `error_code`에 따라 안내 |
| `502` | 모델·분석·Artifact·compose 실패 | session 재조회 후 retry 정책 표시 |

대표 `required_action`:

- `RETRY`: 새 session을 만들고 사용자가 지시를 다시 입력
- `REFRESH`: 서버 session 재조회
- `REAUTHENTICATE`: 다시 로그인
- `REOPEN_LATEST_REPORT`: 최신 Report Revision 다시 열기
- `CONTACT_ADMIN`: Artifact lineage, checksum, 권한 또는 예산 설정 확인

오류 응답 직후에도 서버가 session을 `failed`로 저장했을 수 있다. 클라이언트는 모델 요청 실패를
로컬 오류로만 끝내지 말고 같은 session을 한 번 재조회해 `retryable`과 `required_action`을
반영한다.

## 10. 멱등성과 데이터 보호

### 승인 멱등성

- owner, session ID, request ID, phase를 DB `UPDATE ... WHERE`에서 함께 확인한다.
- 최초 승인만 실행을 claim한다.
- 같은 request ID의 중복 승인은 현재 완료 session을 반환한다.
- 오래된 request ID를 phase만 보고 성공으로 인정하지 않는다.

### Revision CAS

- session 생성 당시의 Report definition version과 base revision을 고정한다.
- 다른 편집자가 먼저 저장해 기준 Revision이 바뀌면 덮어쓰지 않는다.
- 충돌 시 `REPORT_REVISION_CONFLICT`로 중단하고 최신 Report를 다시 열게 한다.

### 실패 재시도

- 원본 `failed` session을 `ready`로 되돌리지 않는다.
- 새 `assistant_request_id`를 가진 자식 session을 만든다.
- 기존 사용자 지시, 승인, data request ID, patch를 자동 복사하거나 실행하지 않는다.
- 원본 session당 retry child 하나라는 DB unique constraint로 중복 생성을 막는다.

## 11. Backend 개발자 연동 지침

1. HTTP 계약은 `report_contracts.py`와 생성된 OpenAPI를 권위로 사용한다.
2. 모델 output은 `report_assistant.py`에서 strict schema 검증 후에만 router로 전달한다.
3. 새 operation은 모델 JSON schema, Pydantic 계약, patch dry-run/apply와 테스트를 함께 변경한다.
4. phase 변경은 repository의 owner·request ID·phase CAS 조건을 거치게 한다.
5. Report 저장은 기존 Revision CAS 경계를 재사용한다.
6. Artifact의 실제 ID·query·checksum은 모델 출력에서 받지 않는다.
7. 평가 저장 실패가 이미 성공한 Revision을 rollback하지 않게 transaction을 분리한다.
8. 새 schema 변경은 새 migration으로 추가하며 29~36을 수정하지 않는다.
9. test fake는 `tests/`에서 명시적으로 주입하고 production fallback을 추가하지 않는다.

Backend 주요 파일:

| 파일 | 책임 |
|---|---|
| `app/backend/app/api/report_router.py` | endpoint, 권한, phase orchestration |
| `app/backend/app/report_contracts.py` | 공개 typed 계약과 retry 정책 |
| `app/backend/app/adapters/report_assistant.py` | GPT strict 호출과 trace 추출 |
| `app/backend/app/adapters/model_schemas.py` | active 모델 schema 제공 |
| `src/ai/contracts/node_io.v0.1.json` | strict request/response JSON schema |
| `src/ai/prompt_registry.py` | versioned Report Assistant prompt |
| `app/backend/app/report_patch.py` | patch dry-run 및 immutable definition 변환 |
| `app/backend/app/adapters/report_artifact_repository.py` | session·승인·Artifact·Revision·retry 영속성 |
| `app/backend/app/adapters/report_assistant_operations_repository.py` | 평가 upsert·조회 |
| `app/backend/app/services/report_assistant_operations.py` | 품질·token·비용 지표 계산 |

## 12. 클라이언트 개발자 연동 지침

1. Assistant phase와 request ID는 서버 응답을 그대로 사용한다.
2. `ready`에서만 사용자 지시를 제출한다.
3. `waiting_patch_approval`에서는 `patch_request_id`로 적용·거절한다.
4. `waiting_approval`에서는 `analysis_plan.request_id`로 승인·거절한다.
5. 승인 전에는 로컬 Canvas를 성공 상태로 선반영하지 않는다.
6. `completed`와 `result_revision`을 받은 뒤 해당 definition을 다시 조회해 Canvas를 교체한다.
7. 새로고침 시 저장한 session ID로 서버 session을 복구한다.
8. 실패 시 서버 session을 재조회하고 typed retry 정책만 표시한다.
9. retry 버튼은 모델을 호출하지 않고 새 `ready` session만 만든다.
10. SQL, raw model response, credential과 전체 사용자 평가를 브라우저 상태에 저장하지 않는다.

Client 주요 파일:

| 파일 | 책임 |
|---|---|
| `app/frontend/src/api/reportClient.ts` | Assistant HTTP 호출과 응답 phase 검증 |
| `app/frontend/src/contracts/reportContract.ts` | Report/Assistant TypeScript 계약 |
| `app/frontend/src/features/reports/useReportLifecycleState.ts` | session·승인·retry·평가 상태 소유 |
| `app/frontend/src/features/reports/useReportsPageController.jsx` | 완료 Revision과 editor 연결 |
| `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx` | 대화·승인·실패·retry UI |
| `app/frontend/src/pages/ReportsPage.jsx` | Report editor와 Assistant wiring |

`reportClient.ts`에서 이미 제공하는 Assistant method:

- `createAssistantSession`
- `getAssistantSession`
- `submitAssistantMessage`
- `approveAssistantPatch` / `rejectAssistantPatch`
- `approveAssistantPlan` / `rejectAssistantPlan`
- `retryAssistantSession`
- `getAssistantEvaluation`

## 13. 권한과 보안 계약

- Report draft 접근 권한이 있어야 session을 생성·조회·수정할 수 있다.
- 새 데이터 승인은 `Capability.RUN_ANALYSIS`가 추가로 필요하다.
- 전체 운영 summary와 failures는 기존 관리자 capability가 필요하다.
- analyst는 자신의 session과 자신의 안전한 평가만 조회한다.
- 타인 session 또는 Artifact는 `404`로 숨겨 존재 여부를 노출하지 않는다.
- SQL, credential, cookie, token, raw prompt, raw model response와 stack trace를 공개 API에 싣지 않는다.
- production에 질문 문구별 분기, 고정 응답, 고정 SQL, fallback Artifact와 mock을 두지 않는다.

## 14. 평가와 운영 정보

request ID당 평가 한 건으로 다음을 연결한다.

- definition/version와 Artifact
- patch/data request ID
- model·prompt version
- route와 operation 종류
- strict 계약 성공 여부
- 승인·거절 결정
- 최종 phase와 error code
- Revision 생성 및 중복 방지
- 모델 attempts와 latency
- provider가 제공한 input/output token
- 가격 설정이 있을 때만 계산한 예상 비용

token usage가 없으면 `0`으로 만들지 않고 `null`, 가격 정보가 없으면 예상 비용도 `null`이다.
SQL, 사용자 지시 원문과 raw model response는 평가 레코드나 API에 저장하지 않는다.

## 15. Migration

| Revision | 기능 |
|---|---|
| `20260824_29` | 서버 소유 session phase와 analysis plan |
| `20260824_30` | 결과 Artifact query/checksum lineage |
| `20260824_31` | Report Revision CAS |
| `20260824_32` | typed report patch 감사 필드 |
| `20260824_33` | bounded turn history |
| `20260825_34` | patch 승인 phase와 request ID |
| `20260825_35` | request ID별 품질·비용 평가 |
| `20260825_36` | 실패 session retry lineage와 unique child |
| `20260826_37` | bounded 원문 turn 정리를 위한 runtime DELETE 권한 |
| `20260826_38` | 세션별 최대 5개 승인 Artifact의 별칭·순서·checksum 결속 |

공용 또는 운영 DB에 적용하기 전 현재 revision, target DB와 단일 migration head 여부를 확인해야
한다. 기존 migration을 수정하거나 volume을 초기화하지 않는다.

## 16. 테스트 위치와 검증된 결과

| 파일 | 범위 |
|---|---|
| `tests/ai/test_report_assistant_contract.py` | GPT strict schema와 patch 변환 |
| `tests/backend/test_report_assistant_session.py` | session·승인·분석·Artifact·CAS·retry |
| `tests/backend/test_report_assistant_patch.py` | patch 8종과 안전한 거부 |
| `tests/backend/test_report_assistant_operations.py` | 평가·지표·권한·기간·비용 |
| `tests/backend/test_report_migration.py` | migration chain과 민감정보 부재 |
| `tests/frontend/contracts.test.mjs` | URL/body·phase·retry·UI 계약 |
| `evals/report_assistant_quality_cases.json` | deterministic Assistant 품질 시나리오 |

2026-08-26 현재 변경안 재수정과 근거 참조 계약을 포함한 Backend·AI unittest 100개와 Frontend
test 24개가 통과했다. 새 기능의 실제 GPT·PostgreSQL·Browser 검증은 아직 실행하지 않았다. 이전
기능의 실제 GPT와 격리 PostgreSQL 편집 E2E 및 Browser 승인·새로고침 복구는 확인한 상태다.

## 17. 현재 제한과 다음 고도화

### 현재 제한

- 근거 별칭은 승인 patch와 카드에는 남지만 저장된 Report block에는 아직 영속되지 않는다.
- session은 승인 Artifact 한 개에 결속된다.
- Report Assistant 전용 실행 취소 API가 없다.
- `running_data_agent` 직후 process crash의 완전한 exactly-once 복구는 보장하지 않는다.
- Trino·DataHub `new_data` live E2E는 미완료다.

### Trino·DataHub와 무관하게 가능한 다음 고도화

1. 현재 보고서의 중복·장문·표현 불일치를 찾는 비저장 품질 검토
2. 여러 승인 Artifact를 함께 사용하는 종합 보고서 변경안
3. 현재 Report와 선택 block에 맞춘 문맥형 추천 요청
4. 필요성이 확인되면 Report block 근거 영속과 Canvas 복구 migration

이 항목들은 계획이며 현재 구현 기능으로 소개하면 안 된다.

## 18. 인수인계 체크리스트

### Backend 담당

- [ ] 현재 branch와 commit 확인
- [ ] migration head 및 적용 DB 확인
- [ ] OpenAPI와 실제 router 일치 확인
- [ ] model·App DB·auth readiness 확인
- [ ] owner·request ID·phase CAS 유지
- [ ] production mock·고정 SQL·질문별 응답 부재 확인
- [ ] 기존 Artifact 편집과 `new_data` live 판정을 분리

### Client 담당

- [ ] 서버 session ID 복구 포인터 유지
- [ ] phase별 버튼과 입력 잠금 연결
- [ ] 승인 body에 서버 request ID 전달
- [ ] 승인 전 Canvas 무변경 확인
- [ ] completed 뒤 `result_revision` 재조회
- [ ] 실패 후 typed retry 안내 표시
- [ ] raw model/SQL/credential을 브라우저 상태에 저장하지 않음

## 19. 팀 공유용 한 문장

Report Assistant V2는 GPT가 승인 Artifact와 현재 Report를 바탕으로 제한된 변경안을 만들고,
서버가 owner·계약·Artifact lineage·Revision을 검증한 뒤 사용자가 승인한 경우에만 새 Report
Revision으로 저장하며, 실패와 중복 요청도 서버 session 기준으로 안전하게 처리하는 기능이다.
