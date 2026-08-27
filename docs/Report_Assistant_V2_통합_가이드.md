# Report Assistant V2 통합 가이드

## 1. 문서 목적

이 문서는 `seung` 브랜치 Report Assistant V2의 유일한 통합 참고 문서다. 기존 기능 설명서,
개발자 가이드, 구현 기록, 단계별 계획, 검증보고서와 실행 프롬프트에서 현재도 유효한 내용을
하나로 정리한다. Backend·Frontend 연동, GPT 계약, API·상태 전이, 파일 위치, migration,
검증 시나리오, 로컬 실행, 남은 위험과 팀 통합 기준을 함께 설명한다.

- 저장소: `report-assistant-advanced`
- 공유 브랜치: `seung`
- 문서 확인 기준: `codex/report-assistant-advanced-20260824`에서 검증한 현재 tree, 공유 대상 `seung`
- 문서 기준일: 2026-08-27
- 현재 작업 tree migration head: `20260826_40`
- active model release: `MODEL-RELEASE-v1.38.0`
- Report Assistant prompt: turn `PROMPT-v1.8.6`, review `PROMPT-v1.2.1`

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
13. 승인 전 변경안 재수정 대화와 최신 patch ID 충돌 차단
14. 비저장 보고서 품질 검토
15. 최대 다섯 승인 Artifact를 이용한 종합 편집
16. Report·선택 block 문맥형 후속 작업 제안
17. 검증된 텍스트 근거의 Revision·Canvas·새로고침 복구
18. operation별 변경 전·후 미리보기
19. 독립 patch operation 선택 승인과 동일 선택 멱등 처리
20. `saving_revision` 새로고침 복구와 CAS Revision 저장 재개
21. 부분 승인 operation의 삭제·수정·이동·anchor 충돌 검증
22. 대기 session 취소와 실패 session의 새 session 안전 재시도
23. 선택 operation의 내용·구성·삭제 영향, 근거 개수와 Revision 복구 안내

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
| 텍스트 Artifact 근거 참조 검증 | 구현·contract/unit 확인 | 안전한 catalog 별칭, 서버 ref 검증, 승인 카드·Revision·Canvas 표시 |
| 여러 Artifact 동시 종합 | 구현·contract/unit 확인 | session당 최대 5개 owner·checksum 결속 |
| 비저장 품질 검토 | 구현·contract/unit 확인 | finding 선택 전 Report·Revision 무변경 |
| 문맥형 후속 작업 제안 | 구현·contract/unit 확인 | 별도 GPT 호출·자동 적용 없이 composer만 채움 |
| operation 변경 전·후 미리보기 | 구현·contract/unit 확인 | 내부 ID 없이 서버 생성 preview를 session에 저장 |
| patch 선택 승인 | 구현·contract/unit 확인 | 선택 인덱스 CAS·server dry-run·다른 중복 선택 차단 |
| 중단된 Revision 저장 재개 | 구현·contract/unit 확인 | 기존 승인 API 재사용·선택 보존·CAS 중복 방지 |
| operation 의존성 검증 | 구현·contract/unit 확인 | 삭제 target·anchor 충돌과 동일 대상 중복 변경 차단 |
| 선택 변경 영향 표시 | 구현·contract/unit·로컬 Browser 확인 | 서버 분류를 선택 operation 기준으로 집계 |
| 대기 요청 취소 | 구현·contract/unit·로컬 Browser 확인 | 실행·저장 전 phase만 취소하고 terminal 재호출 멱등 처리 |
| 동시 승인·재수정 CAS | 구현·격리 PostgreSQL 확인 | 동일 승인 Revision 1건, stale 재수정 1건만 성공 |
| 모델 실패 원인 분류 | 구현·contract/unit 확인 | 인증·한도·4xx·timeout·transport·contract·설정 오류 구분 |

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
돌아간다. `ready`, `waiting_patch_approval`, `waiting_approval`에서는 전용 cancel API로 요청을
종료할 수 있지만 분석 실행·Artifact 대기·Revision 저장 중인 작업을 강제로 중단하지 않는다.

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
└─ 전체 또는 일부 operation 선택 승인
    → 선택 patch 서버 dry-run
    → saving_revision → CAS Revision → completed
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

승인 카드의 각 operation에는 사용자용 대상과 변경 전·후가 표시된다. 선택을 생략한 기존 Client는
전체 operation을 승인하며, 선택할 때는 서버 응답 순서의 0-based 인덱스를 오름차순으로 전달한다.
감사용 원본 patch는 유지하지만 실제 Revision에는 선택된 operation만 적용한다.

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
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/cancel` | 없음 | 취소된 terminal session |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/review` | 선택 block ID(선택) | 비저장 품질 검토 |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/messages` | `instruction` | proposal + session |
| `POST` | `/reports/assistant/sessions/{assistant_request_id}/patch-approval` | request ID + approved + 선택 operation | patch 결정 후 session |
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
  "approved": true,
  "operation_indexes": [0]
}
```

- patch 결정에는 `patch_request_id`를 전달한다.
- 분석 계획 결정에는 `analysis_plan.request_id`를 전달한다.
- 클라이언트가 새 request ID를 생성하면 안 된다.
- URL session ID와 body request ID를 혼동하면 서버가 `409`로 닫는다.
- `operation_indexes`를 생략하면 전체 patch 승인이고, 명시할 때는 비어 있지 않은 정렬·고유
  인덱스만 허용한다.

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
  "patch_preview": [
    {
      "index": 0,
      "operation": "update_text",
      "target": "핵심 요약",
      "before": "본문: 기존 요약",
      "after": "본문: 두 문장 요약",
      "impact_category": "CONTENT",
      "evidence_required": true,
      "evidence_count": 1
    },
    {
      "index": 1,
      "operation": "reposition_block",
      "target": "매출 차트",
      "before": "12/12 폭 · 3행",
      "after": "6/12 폭 · 보고서 끝",
      "impact_category": "LAYOUT",
      "evidence_required": false,
      "evidence_count": 0
    }
  ],
  "approved_operation_indexes": [],
  "result_artifact_id": null,
  "result_revision": null,
  "error_code": null,
  "retryable": false,
  "required_action": "NONE",
  "retry_of_assistant_request_id": null
}
```

응답에는 내부 patch JSON, SQL, raw prompt, raw model response, credential을 포함하지 않는다.

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

Report Assistant 모델 실패는 provider 원문을 노출하지 않고 다음 안전한 code로 구분한다.

- `REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED`
- `REPORT_ASSISTANT_MODEL_RATE_LIMITED`
- `REPORT_ASSISTANT_MODEL_REQUEST_REJECTED`
- `REPORT_ASSISTANT_MODEL_TIMEOUT`
- `REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED`
- `REPORT_ASSISTANT_MODEL_CONTRACT_INVALID`
- `REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID`

인증 실패와 재시도 불가능한 provider 4xx는 같은 요청을 반복하지 않는다. rate limit, timeout과
일시 transport 장애만 bounded retry 대상이며 실제 시도 횟수와 latency를 평가 레코드에 남긴다.

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
- `reviewAssistantReport`
- `cancelAssistantSession`
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
| `20260826_39` | Report block별 검증 근거 별칭 영속화 |
| `20260826_40` | patch operation 변경 전후 미리보기와 선택 승인 결속 |

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
| `tests/backend/test_report_assistant_postgres_concurrency.py` | 격리 PostgreSQL 승인·재수정 CAS 경쟁 |
| `tests/frontend/contracts.test.mjs` | URL/body·phase·retry·UI 계약 |
| `evals/report_assistant_quality_cases.json` | deterministic Assistant 품질 시나리오 |

2026-08-27 현재 Report Assistant 관련 Backend·AI·migration unittest 158개, Frontend test 24개,
production build, OpenAPI, 코드 문서화, architectural invariants, repository integrity, compileall과
`git diff --check`가 통과했다. migration 40 기준 기존 Artifact 편집은 이전 검증에서 실제 GPT·격리
PostgreSQL·Browser로 부분 승인, CAS Revision, 저장 재개와 새로고침 복구까지 확인했다. 현재
`MODEL-RELEASE-v1.38.0`의 실패 분류·지원 범위 prompt 변경은 deterministic contract/unit으로
검증했으며 새 유료 GPT·Browser 호출은 실행하지 않았다. Trino·DataHub `new_data` live E2E도 이
결과에 포함하지 않는다.

## 17. 현재 제한과 다음 고도화

### 현재 제한

- 대기 중인 session은 전용 API로 안전하게 취소할 수 있지만, 이미 실행·저장 중인 원격 작업을
  강제로 중단하는 worker-level cancellation은 지원하지 않는다.
- `running_data_agent` 직후 process crash의 완전한 exactly-once 복구는 보장하지 않는다.
- Trino·DataHub `new_data` live E2E는 미완료다.
- 기존 chart·table·Artifact block의 제목 직접 변경 operation은 없다. 해당 요청은 clarification으로
  닫고 보고서 제목·텍스트·구조 편집 중 지원되는 대안을 안내한다.
- active model release `v1.38.0`의 실제 유료 GPT·Browser 재검증은 별도 실행 승인이 필요하다.

### Trino·DataHub와 무관하게 가능한 다음 고도화

1. 장시간 대화와 다양한 보고서 구조에서 prompt 품질 평가 확대
2. 현재 model release의 실제 GPT·PostgreSQL·Browser 대표 시나리오 재검증
3. process 종료 시점별 복구와 운영 관측 통합 검증

이 항목들은 후속 계획이며 현재 구현 기능으로 소개하면 안 된다.

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

## 20. 사용자 요청 시나리오 카탈로그

Report Assistant는 요청을 `clarification`, `existing_artifact`, `new_data` 중 하나로 분류한다.
현재 로컬에서 끝까지 실행 가능한 범위는 승인된 기존 Artifact를 사용하는 편집이며, 새 데이터
요청은 분석 계획과 승인 카드까지만 확인할 수 있다.

### 20.1 기존 Artifact로 완료 가능한 편집

| 사용자 의도 | 예시 요청 | 서버 operation 또는 결과 |
|---|---|---|
| 보고서 제목 변경 | `제목을 8월 매출 성과 보고서로 바꿔줘` | `set_report_title` |
| 근거 기반 요약 추가 | `매출 핵심 내용을 두 문장으로 추가해줘` | `add_text` |
| 기존 텍스트 수정 | `핵심 매출 요약을 한 문장으로 줄여줘` | `update_text` |
| 텍스트 제목 수정 | `핵심 매출 요약 제목을 경영진 요약으로 바꿔줘` | `update_text` |
| 표 추가 | `승인 매출 데이터를 표로 추가해줘` | `add_artifact_view(table)` |
| 차트 추가 | `매출 결과를 차트로 추가해줘` | `add_artifact_view(chart)` |
| Artifact 묶음 추가 | `분석 결과 전체를 보고서에 추가해줘` | `add_artifact_view(artifact)` |
| 블록 이동 | `표를 차트 아래로 옮겨줘` | `reposition_block` |
| 블록 폭 변경 | `표를 전체 너비로 바꿔줘` | `reposition_block(full)` |
| 블록 복제 | `핵심 요약 블록을 복제해줘` | `duplicate_block` |
| 블록 삭제 | `매출 표를 삭제해줘` | `remove_block` |
| 직전 버전 복원 | `직전 저장 버전으로 되돌려줘` | `restore_previous_revision` 단독 실행 |
| 복합 편집 | `제목을 바꾸고 요약을 줄인 뒤 표를 추가해줘` | 최대 12개 typed operation |
| 선택 블록 편집 | 블록 선택 후 `이 내용을 두 문장으로 줄여줘` | 서버 검증 selected block 문맥 사용 |

새 텍스트와 본문 변경은 현재 session의 승인 Artifact evidence alias를 하나 이상 인용해야 한다.
배치 위치는 기존 block 뒤라는 상대 위치와 `half` 또는 `full` 폭만 허용하며 모델이 절대 grid
좌표를 정하지 않는다.

### 20.2 승인 전 변경안 재수정과 부분 승인

`waiting_patch_approval`에서도 현재 `patch_request_id`를 함께 보내 변경안을 대화로 교체할 수
있다. 예를 들어 `요약을 두 문장으로 줄이고 표를 추가해줘`라는 최초 제안 뒤 `표는 빼고 요약만
한 문장으로 바꿔줘`라고 요청하면 이전 operation을 누적하지 않고 전체 대체 patch를 만든다.

- 오래된 patch request ID는 GPT 호출 전에 `409`로 차단한다.
- 각 operation의 변경 전·후와 `CONTENT`, `LAYOUT`, `DESTRUCTIVE` 영향을 표시한다.
- 사용자는 여러 operation 중 일부만 선택해 승인할 수 있다.
- 승인 전과 거절 시에는 Report definition과 Revision을 변경하지 않는다.
- 동일 선택 승인을 다시 전송해도 Revision을 추가 생성하지 않는다.

### 20.3 여러 승인 Artifact 종합

대표 Artifact 한 개와 추가 Artifact 최대 네 개, 총 다섯 개를 한 session에 결속할 수 있다.
모든 Artifact의 owner, 승인 상태, query lineage와 checksum을 서버가 확인하고 각각 안전한 alias를
부여한다. GPT는 선택된 alias의 evidence만 사용해 종합 요약, 표·차트 또는 Artifact 묶음을 제안할
수 있다. 하나라도 검증에 실패하면 전체 요청을 닫고 선택하지 않은 Artifact를 참조하지 않는다.

### 20.4 비저장 품질 검토

`보고서 품질 검토`는 Report와 Revision을 바꾸지 않고 최대 열 개의 finding을 반환한다.

| Category | 검토 내용 |
|---|---|
| `duplicate_text` | 여러 블록의 중복 문장 |
| `verbose_summary` | 지나치게 긴 요약 |
| `title_mismatch` | 표·차트 내용과 맞지 않는 제목 |
| `inconsistent_metric_expression` | 동일 지표의 불일치한 표현 |
| `unsupported_claim` | Artifact 근거로 확인할 수 없는 단정 |

finding의 수정 제안을 선택해 composer에 가져올 수 있지만 자동 실행·자동 승인·자동 저장은 하지
않는다. 일반 변경안과 품질 검토 응답에는 현재 보고서 및 선택 block에 맞는 후속 요청을 최대 세
개까지 포함할 수 있다.

### 20.5 확인 질문으로 돌려보내는 요청

기간, 지표, 차원, 대상 block 또는 표현 방식 중 필수 요소를 안전하게 하나로 정할 수 없으면
`clarification`을 반환하고 `ready`를 유지한다.

- `보기 좋게 바꿔줘`: 변경 대상과 방향이 불명확하다.
- `매출을 추가해줘`: 요약·표·차트 중 원하는 표현이 불명확할 수 있다.
- `이거 삭제해줘`: 선택 block이나 대화 문맥으로 대상을 확정할 수 없으면 확인한다.
- `내용을 고쳐줘`: 어떤 내용과 방향인지 확인한다.

### 20.6 새 데이터가 필요한 요청

현재 Artifact에 없는 기간·지표·차원·비교·순위를 요구하면 patch를 만들지 않고 `new_data`
analysis plan을 제안한다.

- `9월 매출도 조회해서 8월과 비교해줘`
- `고객 등급별 매출을 새로 분석해줘`
- `객실과 식음 매출의 전년 대비 증감률을 계산해줘`

서버는 질문, 필요한 이유, 기간, 지표와 선택 차원을 고정하고 사용자 승인 전 분석을 호출하지
않는다. 현재 환경에서는 이 계획과 승인 카드까지 검증할 수 있지만 Analysis Agent·DataHub·Trino
연결이 준비되지 않아 새 Artifact와 Report Revision까지의 live E2E는 완료되지 않았다.

### 20.7 지원하지 않거나 차단하는 요청

- 글꼴·색상·테두리 등 허용 operation에 없는 세부 디자인 변경
- 임의 픽셀·grid 좌표 또는 `half`·`full` 이외의 폭 지정
- 기존 차트 종류나 기존 비텍스트 block 제목의 직접 수정
- Artifact에 없는 수치 계산·사실·원인 생성
- SQL 작성·노출·직접 실행 또는 dataset·column 선택
- 사용자 권한, Artifact 승인 상태 또는 Report 승인 상태 변경
- 사용자 확인 없는 자동 승인·자동 Revision 저장
- PDF 외부 전송, 공유, 스케줄 생성·변경
- 타인 소유 Report·session·Artifact 조회 또는 편집
- 실제 Artifact ID, query ID, checksum, raw prompt·model response 공개

### 20.8 실패·취소·복구

- 대기 phase의 session은 `요청 취소`로 terminal `cancelled` 처리한다.
- retry 가능한 실패는 원본을 변경하지 않고 새 `ready` child session을 만든다.
- 로그인·상태·Revision·Artifact 오류는 `REAUTHENTICATE`, `REFRESH`,
  `REOPEN_LATEST_REPORT`, `CONTACT_ADMIN`으로 구분한다.
- `saving_revision` 중 응답이 끊겨도 고정된 patch와 선택값으로 재개하며 GPT와 분석을 다시
  호출하지 않는다.
- `completed` 후 Client는 `result_revision`을 다시 조회해 Canvas를 교체하고 새로고침에서도 같은
  Revision을 복구한다.

### 20.9 현재 한도

| 항목 | 한도 |
|---|---:|
| 사용자 지시 | 500자 |
| patch operation | 최대 12개 |
| session Artifact | 최대 5개 |
| 품질 finding | 최대 10개 |
| 후속 suggestion | 최대 3개 |
| DB 원문 turn 보관 | 최근 6턴 |
| 텍스트 evidence ref | operation당 최대 16개 |

현재 Report Assistant를 설명할 때는 **기존 승인 Artifact를 근거로 보고서를 편집하는 GPT Agent는
실제 동작하고, 신규 데이터 분석은 계획·승인 경계까지만 준비됐으며 Analysis Agent·DataHub·Trino
live 연결은 남아 있다**고 구분한다.

## 21. 구현 이력 요약

세부 날짜별 작업 일지를 다시 만들지 않고, 현재 코드에 남아 있는 기능 경계만 요약한다.

| 구간 | 통합된 결과 |
|---|---|
| 1~3차 | 서버 session, strict 분류, 기존 Artifact patch, 새 데이터 승인·Artifact 검증 |
| 4~5차 | request별 품질·token·비용 평가, 운영 API, 실패 session 안전 재시도 |
| 6~9차 | evidence refs 영속화, operation preview·선택 승인, `saving_revision` 안전 재개 |
| 10~12차 | 부분 승인 의존성 검증, 안전 취소, 실제 GPT·PostgreSQL·Browser 편집 E2E |
| 13~15차 | 승인 카드 접근성·모바일, 품질 eval, 선택 operation 영향 설명 |
| 16차 | 격리 PostgreSQL 동시 승인·재수정 CAS와 완료 결과 멱등 read-back |
| 후속 결함 수정 | no-op Revision 차단, 상충 지시 clarification, 표 내부 반응형, typed 모델 실패 |

과거 단계 번호는 구현 순서를 설명할 뿐 runtime 계약이 아니다. 현재 동작은 이 문서의 API,
phase, model release, migration과 테스트 결과를 기준으로 판단한다.

## 22. 실제 검증 시나리오 요약

2026-08-27 Browser 순차 검증에서 다음 대표 시나리오를 사용했다. 화면 캡처는
`docs/e2e_mvp/derived/runtime_evidence/2026-08-27/`에 보존한다.

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| S01 | 로그인·Report·Artifact·Assistant 준비 | `ready`, 승인 Artifact 결속 |
| S02 | 비저장 품질 검토 | finding 반환, Report·Revision 무변경 |
| S03 | 현재와 같은 제목 요청 | no-op clarification, 승인 카드 없음 |
| S04 | 제목·요약 복합 변경 후 거절 | `ready`, Revision 무변경 |
| S05 | 복합 변경 일부 승인 | 선택 operation만 Revision 저장 |
| S06 | 승인 대기 변경안 재수정 | 새 patch ID, 이전 patch 승인 409 |
| S07 | 승인 대기 새로고침 | 동일 서버 session·preview 복구 |
| S08 | 동일 승인 재전송 | Revision 추가 생성 0건 |
| S09 | SQL·내부 식별자·자동 승인 유도 | 식별자 미노출, 실행·승인 우회 없음 |
| S10 | 서로 충돌하는 지시 | partial patch 대신 clarification |
| S11 | 대기 session 취소 | `cancelled`, Report 무변경 |
| S12 | 실패 session 재시도 | 원본 보존, 새 `ready` child 한 건 |
| S13 | 450px 작은 화면 | composer·preview·승인 조작 가능 |
| S14 | 여러 Artifact 요청 | 최대 5개 검증, 누락 시 안전한 prerequisite 안내 |

캡처는 보조 증거다. HTTP, DB session, model release, Artifact와 Revision이 같은 request ID로
연결된 경우에만 실제 E2E로 판정한다.

## 23. 로컬 실행과 확인

1. 저장소 root에서 외부 deployment env와 secret 경로가 준비됐는지 값은 출력하지 않고 확인한다.
2. `docker compose --env-file <외부 env> --profile full config --services`로 merge 결과를 확인한다.
3. volume을 삭제하지 않고 필요한 App DB·migration·Backend·Frontend만 기동한다.
4. Backend `/health`와 `/readiness`를 분리해 확인한다. `/health=200`만으로 Agent 완료를 선언하지 않는다.
5. 실제 로그인 후 `/reports`에서 승인 Artifact가 연결된 draft를 열어 S01~S12 중 대표 흐름을 실행한다.

Windows 로컬 Backend는 환경에 따라 Selector event loop가 필요하다. Frontend origin을 Backend
CORS에 포함하고 HTTP 개발 환경에서는 secure cookie 설정을 실제 origin과 맞춘다. 비밀번호,
OpenAI key, DataHub token과 DB credential은 저장소 내부 `.env`, 문서, 명령 인자와 Git diff에 넣지
않는다.

### 기본 회귀 명령

```powershell
$env:PYTHONPATH='.;app/backend'
python -m unittest `
  tests.ai.test_model_contracts_live `
  tests.ai.test_report_assistant_contract `
  tests.backend.test_async_model_transport `
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

실제 OpenAI 평가는 사용자의 비용 승인 후 한정된 시나리오로 따로 실행한다. DataHub·Trino가
준비되지 않은 fake 검증을 `new_data` live E2E로 기록하지 않는다.

## 24. 팀 통합과 충돌 방지

- 관리자 운영 UI를 다른 담당자가 수정 중이면 `ReportAssistantOperationsPanel.jsx`와 관리자 화면
  layout은 Report Assistant 사용자 흐름 변경과 분리한다.
- 충돌이 잦은 `ReportsPage.jsx`는 `ReportAssistantPanel` prop wiring만 최소 수정하고, 실제 상태는
  `useReportLifecycleState.ts`에서 소유한다.
- Backend 충돌은 router 코드를 복제하지 말고 `report_contracts.py`, repository CAS와 기존
  `AnalysisController` 경계를 유지한다.
- model prompt를 바꾸면 prompt version·SHA-256과 active model release manifest를 같은 patch에서
  갱신한다.
- migration `20260824_29`~`20260826_40`은 수정하지 않는다. 새 schema가 필요할 때만 additive
  migration을 만든다.
- merge 전 secret, production mock, 질문별 고정 응답, 고정 SQL과 fallback Artifact가 없는지
  확인하고 위 회귀 명령을 다시 실행한다.

## 25. 새 데이터 live E2E 완료 Gate

다음 dependency가 같은 release에서 ready일 때만 실행한다.

- 인증 session store와 `RUN_ANALYSIS` principal
- App PostgreSQL과 migration head
- 실제 model route
- DataHub read actor·token과 semantic release
- catalog manifest와 Trino schema checksum
- TLS·password 인증이 적용된 Trino runtime principal

완료 흐름은 다음과 같다.

```text
new_data 계획
→ 사용자 승인 전 AnalysisController·Trino 호출 0회
→ 최초 승인 후 AnalysisController 1회
→ DataHub 승인 metadata와 SQL Guard
→ Trino query
→ owner/request/query/checksum 결속 APPROVED Artifact
→ 고정 patch와 CAS Report Revision
→ completed·Canvas·새로고침 복구
```

Trino·DataHub가 준비되지 않으면 이 Gate는 미완료로 유지하며 기존 Artifact 편집 E2E와 분리해
보고한다. `docker compose down -v`, DB·volume 초기화, 운영 seed, mock Artifact와 고정 SQL로
우회하지 않는다.

## 26. 문서 유지 규칙

Report Assistant의 기능·검증·인수인계·남은 작업은 이 파일 하나에서만 갱신한다. 새 단계별
계획서, 실행 프롬프트, 별도 검증보고서와 날짜별 중복 가이드를 `docs/` root에 추가하지 않는다.
대용량 실행 로그는 Git에 넣지 않고, 필요한 화면 증거만 기존 runtime evidence 경계에 보존한다.
