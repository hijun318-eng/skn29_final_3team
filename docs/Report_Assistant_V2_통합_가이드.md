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
- 현재 작업 tree migration head: `20260827_41`
- active model release: `MODEL-RELEASE-v1.45.0`
- Report Assistant prompt: turn `PROMPT-v1.9.5`, review `PROMPT-v1.2.1`

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

지원 operation은 다음 17종이다. 편집기에서 Report Revision으로 저장되는 문서·블록·표현
설정은 같은 서버 typed patch와 승인 경계를 사용한다.

| Operation | 기능 | 주요 서버 검증 |
|---|---|---|
| `set_report_title` | 보고서 제목 변경 | 빈 제목·길이 제한 |
| `set_report_orientation` | A4 가로·세로 방향 변경 | `portrait`·`landscape`만 허용 |
| `set_currency_display_unit` | 통화 표시 단위 변경 | 서버 통화 단위 enum만 허용 |
| `compact_report_layout` | 블록 빈 공간 정리 | 12열 bounds와 시각 순서 유지 |
| `add_report_page` | 보고서 끝에 빈 A4 페이지 추가 | 서버 소유 `page_break` 생성·고정 layout 검증 |
| `update_block_title` | 모든 블록 유형의 제목 변경 | 기존 block ID·빈 제목 검증 |
| `resize_block` | 블록 너비·높이 변경 | 유형별 최소 크기·12열 bounds 검증 |
| `update_chart_settings` | 차트 종류·범례·크기 모드 변경 | chart block과 허용 chart enum 검증 |
| `update_table_settings` | 표 밀도·행 번호·크기 모드 변경 | table block과 허용 설정 검증 |
| `set_block_size_mode` | 분석 view 자동·수동 크기 전환 | chart·table·Artifact block만 허용 |
| `add_text` | 텍스트 블록 추가 | 내용·상대 위치·폭 검증 |
| `update_text` | 기존 텍스트 수정 | 기존 text block ID 확인 |
| `add_artifact_view` | 차트·표·Artifact view 추가 | 서버 별칭 `source_artifact`만 허용 |
| `reposition_block` | 블록 이동 및 폭 변경 | 기존 block/anchor, 상대 위치만 허용 |
| `duplicate_block` | 기존 블록 복제 | 서버가 새 block ID 생성 |
| `remove_block` | 기존 블록 삭제 | 존재 여부 및 마지막 블록 보호 |
| `restore_previous_revision` | 직전 Revision 복원 | 다른 operation과 혼합 금지 |

모델은 절대 좌표, 실제 Artifact ID, query ID나 checksum을 patch에 넣을 수 없다. 서버가 현재
Report와 `VerifiedArtifactBinding`을 사용해 최종 값을 계산한다.

검색, 선택, 화면 확대·축소, 패널 열기, focus, drag preview, session snapshot과 Client 전용
undo/redo는 Report Revision에 저장되지 않는 UI 상태이므로 Agent operation으로 가장하지 않는다.
복제는 `duplicate_block`, 저장본 복원은 `restore_previous_revision`으로 처리한다.

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
`MODEL-RELEASE-v1.45.0`의 편집기 자연어 기능 동등성과 명시적 무변경 요청 처리는 deterministic contract/unit으로
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
| 용지 방향 변경 | `보고서를 가로형으로 만들어줘` | `set_report_orientation(landscape)` |
| 통화 단위 변경 | `금액을 백만원 단위로 표시해줘` | `set_currency_display_unit(million)` |
| 전체 빈 공간 정리 | `모든 블록 사이 빈 공간을 정리해줘` | `compact_report_layout` |
| 공통 블록 제목 변경 | `매출 차트 제목을 월간 매출 추이로 바꿔줘` | `update_block_title` |
| 블록 크기 변경 | `매출 차트를 전체 너비와 높이 9단으로 키워줘` | `resize_block` |
| 차트 표현 변경 | `차트를 가로 막대로 바꾸고 범례를 숨겨줘` | `update_chart_settings` |
| 표 표현 변경 | `표를 간결하게 만들고 행 번호를 표시해줘` | `update_table_settings` |
| 자동 크기 맞춤 | `표 크기를 내용에 맞춰줘` | `set_block_size_mode(auto)` |
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
- migration `20260824_29`~`20260827_41`은 수정하지 않는다. 새 schema가 필요할 때만 additive
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

## 27. 자연어 편집 동등성 실브라우저 검증 (2026-08-27)

실제 OpenAI 모델, 격리 PostgreSQL과 Browser를 사용해 편집 기능을 다섯 묶음으로 나누고 각
묶음당 세 가지 효과를 검증했다. 한 문장에 세 효과를 묶은 경우에도 승인 카드에는 개별 typed
operation으로 표시됐고, 승인 전 Report version은 유지됐다.

| 기능 묶음 | 검증한 세 시나리오 | 결과 |
|---|---|---|
| 문서 속성 | A4 가로 변경, 백만원 단위, 빈 공간 정리 | v28 무변경 확인 후 승인하여 v29 |
| 블록 편집 | 제목 변경, 12열×9단 크기, 원본 아래 복제 | 최종 patch만 승인하여 v30 |
| 차트 설정 | 가로 막대, 범례 숨김, 내용 자동 크기 | 승인 후 v31, Canvas 반영 |
| 표 설정 | 표 추가, 간결 밀도·행 번호, 내용 자동 크기 | 승인 후 v32, 행 번호 포함 표 렌더링 |
| 안전성 | 변경안 취소, 일부 operation 승인, 새로고침 복구 | 취소는 v32 유지, 방향만 승인해 v33, 설정 복구 |

실제 모델 검증 중 두 결함을 발견해 수정했다.

1. 복제 요청의 “원본 아래”를 원본 이동으로 해석하던 prompt를 수정했다. 복제본의 서버 배치를
   명시하고 원본 이동은 별도 요청이 있을 때만 허용한다. 현재 release는
   `PROMPT-v1.9.4`, `MODEL-v1.28.0`, `MODEL-RELEASE-v1.44.0`이다.
2. strict wire schema가 nullable 미사용 필드를 포함할 때 typed operation 검증이 실패하던 문제를
   수정했다. adapter가 operation과 `add_artifact_view.view`별 허용 필드만 선택한 뒤 검증하므로
   표 요청에 chart 필드가 섞이거나 차트 요청에 table 필드가 섞여도 내부 식별자나 임의 설정을
   저장하지 않고 안전한 typed patch로 정규화한다.

최종 회귀 결과는 Backend·AI 162개, Frontend 24개가 모두 통과했고 production build, OpenAPI,
문서화, architecture, repository integrity, compileall과 `git diff --check`도 통과했다. Frontend
테스트 중 개발 WebSocket 24678 포트 사용 경고는 있었으나 실패는 없었다.

화면 증거:

- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/report-assistant-editor-parity-document-proposal.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/report-assistant-editor-parity-document-completed.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/report-assistant-editor-parity-block-completed.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/report-assistant-editor-parity-chart-completed.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/report-assistant-editor-parity-table-completed.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/report-assistant-editor-parity-partial-approval.png`

이 검증은 기존 승인 Artifact 편집 live E2E다. Trino·DataHub를 사용하는 `new_data` live E2E는
실행하지 않았고 완료로 판정하지 않는다.

## 28. 페이지 편집 1차: 빈 페이지 추가 (2026-08-27)

자연어 `페이지 한 장 추가해줘`를 `add_report_page` typed operation으로 처리한다. 모델은 페이지
식별자·좌표·내용을 만들지 않고 빈 페이지 추가 의도만 반환한다. 서버는 현재 draft 끝에
`page_break` block ID를 생성하고, 승인 전에는 Report를 변경하지 않으며 승인 후에만 기존 CAS
Revision 경계로 저장한다.

`page_break`는 사용자 콘텐츠가 아니라 명시적 A4 페이지 경계다. Artifact·query·본문을 가질 수
없고 `x=0`, `w=12`, `h=1`로만 저장된다. Frontend Canvas와 최종 HTML renderer는 이 marker를
표시용 block으로 그리지 않고 다음 빈 페이지를 시작한다. 새로고침 때도 같은 서버 Revision에서
페이지 경계를 복구한다.

이번 1차의 의도된 범위는 **보고서 끝에 빈 페이지 한 장 추가**뿐이다. 페이지 사이 삽입, 페이지
삭제, 페이지 이동, 페이지 복제와 페이지별 방향은 아직 지원한다고 표시하지 않는다. 이 기능들은
각각의 충돌·내용 이동·마지막 페이지 보호 정책을 정한 뒤 별도 typed operation으로 확장한다.

계약 release는 `PROMPT-v1.9.4`, `MODEL-v1.28.0`, `MODEL-RELEASE-v1.44.0`이며 additive migration
`20260827_41`이 `page_break` 저장 제약을 추가한다. 기존 migration은 수정하지 않았다. 기본
공용 DB에는 migration을 적용하지 않는다. deterministic 검증 뒤 테스트 전용
`app_db_report_assistant_e2e`에 migration 41을 적용하고 실제 OpenAI·PostgreSQL·Browser 한 건을
실행했다. 최초 시도에서 과거 v1을 열었을 때 최신 v33과의 CAS 충돌이
`REPORT_REVISION_CONFLICT`로 안전하게 차단되고 Revision이 생성되지 않는 것도 확인했다.

최신 v33의 실제 모델 호출에서는 요청하지 않은 동일 제목 `set_report_title` no-op가 한 번 함께
제안됐다. 이를 정상으로 간주하지 않고, 개별 문서·블록 속성 no-op를 서버 dry-run에서 차단하고
“빈 페이지 하나가 유일한 요청이면 전체 operation도 `add_report_page` 하나”라고 prompt를
강화했다. 수정 후 같은 명령은 실제 `gpt-5.4-mini`에서 `add_report_page` 한 건만 생성했다.

최종 Browser 영수증은 Assistant request `b01e05de-7ff6-4104-aeb6-5b75308f101d`,
`PROMPT-v1.9.4`, v33 `1/1페이지`에서 승인 전 무변경, 승인 후 completed v34 `2/2페이지`,
두 번째 페이지 `0개 블록`, DB `page_break` 1건이다. 새로고침 뒤 v34와 빈 두 번째 페이지가
복구됐고 Browser console error와 관련 Backend 500은 0건이었다. Trino·DataHub는 사용하지 않은
기존 Artifact 편집 E2E이며 `new_data` live E2E로 표현하지 않는다.

## 29. 기능별 상세 코드 지도

이 절은 팀원이 기능 이름에서 실제 구현 파일과 검증 위치까지 바로 이동하기 위한 인덱스다.
상태는 `완료`, `부분`, `미완료`로 구분한다. `완료`도 unit/contract와 live 증거를 별도로 적으며,
fake 테스트만 있는 기능을 live 완료로 해석하지 않는다.

### 29.1 서버 session·GPT·승인 흐름

| 기능 | 상태·순위 | 구현 방식 | 권위 파일과 주요 symbol | 검증 파일 |
|---|---|---|---|---|
| Session 생성·복구 | 완료·P0 | 서버 UUID로 session을 만들고 owner·Report version·Artifact binding을 PostgreSQL에 저장한다. Client storage는 ID 포인터만 보관한다. | `app/backend/app/api/report_router.py`의 `create_assistant_session()`, `get_assistant_session()`, `_recover_and_get_assistant_session()`; `app/backend/app/adapters/report_artifact_repository.py`의 `start_assistant_session()`, `get_assistant_session()`, `recover_stale_assistant_session()` | `tests/backend/test_report_assistant_session.py`, `tests/frontend/contracts.test.mjs` |
| GPT strict 요청 분류 | 완료·P0 | 실제 model transport에 versioned JSON Schema를 전달하고 `clarification`·`existing_artifact`·`new_data` 중 하나로 Pydantic 재검증한다. | `app/backend/app/adapters/report_assistant.py`의 `generate_report_change_proposal()`; `src/ai/contracts/node_io.v0.1.json`; `src/ai/prompt_registry.py`; `src/ai/model_contracts.py`; `src/ai/contracts/model_release.v1.json` | `tests/ai/test_report_assistant_contract.py`, `tests/ai/test_prompt_registry.py`, `tests/ai/test_model_contracts_live.py` |
| 대화·변경안 재수정 | 완료·P0 | 최근 6개 원문 turn만 보존하고, 승인 대기 중에는 현재 patch ID가 일치할 때만 전체 대체 patch를 생성한다. stale ID는 모델 호출 전 409다. | `app/backend/app/api/report_router.py`의 `submit_assistant_message()`; `app/backend/app/adapters/report_artifact_repository.py`의 `replace_existing_assistant_patch_proposal()`, `get_assistant_turn_history()`, `_append_assistant_turn()` | `tests/backend/test_report_assistant_session.py`, `tests/ai/test_report_assistant_contract.py` |
| Patch dry-run·미리보기 | 완료·P0 | model output을 typed operation으로 파싱한 뒤 현재 Report 복사본에 적용한다. 변경 전·후 preview만 공개하고 내부 patch JSON은 숨긴다. | `app/backend/app/api/report_router.py`의 `_apply_existing_artifact_patch()`, `_report_patch_preview()`; `app/backend/app/report_patch.py`의 `apply_report_assistant_patch()` | `tests/backend/test_report_assistant_patch.py`, `tests/backend/test_report_assistant_session.py` |
| 전체·일부 승인 | 완료·P0 | 0-based operation index를 서버에서 정렬·중복·범위 검증하고 선택된 patch를 다시 dry-run한다. | `app/backend/app/api/report_router.py`의 `decide_assistant_patch()`; `app/backend/app/report_contracts.py`의 `ReportAssistantPatchApprovalRequest`; repository의 `decide_existing_assistant_patch()` | `tests/backend/test_report_assistant_session.py`, `tests/frontend/contracts.test.mjs` |
| CAS Revision·멱등성 | 완료·P0 | owner·session·patch request·phase를 같은 DB 조건에 넣고 최초 승인만 claim한다. 최종 definition version과 blocks 저장은 transaction으로 묶고 동일 승인은 기존 Revision을 반환한다. | `app/backend/app/adapters/report_artifact_repository.py`의 `finalize_existing_assistant_patch()`, `finalize_assistant_revision()`, `_completed_assistant_revision()`; `app/backend/app/adapters/report_repository.py` | `tests/backend/test_report_assistant_session.py`, 격리 PostgreSQL 동시성 시나리오 |
| 취소·실패 재시도 | 완료·P0 | 실행 전 phase만 terminal `cancelled`로 전환한다. failed session은 수정하지 않고 retry lineage를 가진 새 `ready` child를 멱등 생성한다. | `app/backend/app/api/report_router.py`의 `cancel_assistant_session()`, `retry_assistant_session()`; `app/backend/app/report_contracts.py`의 `report_assistant_retry_policy()`; repository의 `cancel_assistant_session()`, `retry_assistant_session()` | `tests/backend/test_report_assistant_session.py`, Frontend contract test |
| 비저장 품질 검토 | 완료·P1 | Report snapshot을 별도 strict review 계약으로 평가하고 finding만 반환한다. patch·승인·Revision은 만들지 않는다. | `app/backend/app/api/report_router.py`의 `review_assistant_report()`, `_validated_report_review()`; `app/backend/app/adapters/report_assistant.py`의 `generate_report_quality_review()` | `tests/backend/test_report_assistant_session.py`, `tests/ai/test_report_assistant_contract.py` |
| 새 데이터 분석 | 부분·P2 | 사용자 승인 후 기존 `AnalysisController`를 한 번 실행하고 결과 Artifact lineage를 다시 검증한 뒤 고정 patch와 Revision을 저장한다. 코드·fake 회귀는 있으나 Trino·DataHub live E2E는 없다. | `app/backend/app/api/report_router.py`의 `decide_assistant_plan()`, `_execute_assistant_analysis()`, `_prepare_assistant_revision()`, `_compose_assistant_revision()`; `app/backend/app/controllers/analysis_controller.py`; repository의 `decide_assistant_plan()`, `save_assistant_result_artifact()` | `tests/backend/test_report_assistant_session.py`; live Gate는 25절 |

### 29.2 자연어 편집 operation 17종

모든 operation의 wire discriminator와 입력 제한은 `app/backend/app/report_contracts.py`, 실제 적용은
`app/backend/app/report_patch.py`, GPT 허용 목록과 정규화는
`app/backend/app/adapters/report_assistant.py`, strict wire schema는
`src/ai/contracts/node_io.v0.1.json`이 담당한다. 아래 파일 중 한 곳만 바꾸면 계약 drift가 생긴다.

| Operation | 사용자가 할 수 있는 말 | 서버 적용·보호 규칙 | 화면·복구 파일 | 순위 |
|---|---|---|---|---|
| `set_report_title` | `제목을 8월 매출 보고서로 바꿔줘` | 빈 값·길이·동일 제목 no-op 차단 | `ReportAssistantPanel.jsx`, `useReportLifecycleState.ts` | P0 |
| `set_report_orientation` | `보고서를 가로형으로 만들어줘` | `portrait`·`landscape` enum, 동일 방향 no-op 차단 | `reportContract.ts`, `reportPresentation.js`, `reportDraftOperations.js` | P0 |
| `set_currency_display_unit` | `금액을 백만원 단위로 표시해줘` | 서버 currency enum, 동일 단위 no-op 차단 | `reportContract.ts`, `useReportsPageController.jsx` | P0 |
| `compact_report_layout` | `블록 사이 빈 공간을 정리해줘` | 12열 grid와 시각 순서를 유지해 재배치, 결과가 같으면 no-op | `reportLayout.ts`, `reportDraftOperations.js` | P1 |
| `add_report_page` | `페이지 한 장 추가해줘` | 서버 UUID의 `page_break`를 끝에 추가; 내용·Artifact·임의 좌표 금지 | `reportContract.ts`, `reportLayout.ts`, `reportPresentation.js`, `reportDraftOperations.js` | P0 |
| `update_block_title` | `매출 차트 제목을 월간 추이로 바꿔줘` | 기존 block, 빈 제목, 동일 제목 검증 | `ReportAssistantPanel.jsx` preview, 완료 후 server definition 재조회 | P0 |
| `resize_block` | `표를 전체 너비와 9단 높이로 키워줘` | block 유형별 최소 폭·높이와 12열 bounds 검증 | `reportLayout.ts`, `useReportsPageController.jsx` | P0 |
| `update_chart_settings` | `가로 막대로 바꾸고 범례를 숨겨줘` | chart block에만 chart enum·legend·size mode 허용 | `reportContract.ts`, `reportPresentation.js` | P0 |
| `update_table_settings` | `표를 간결하게 하고 행 번호를 보여줘` | table block에만 density·row numbers·size mode 허용 | `reportContract.ts`, `reportPresentation.js` | P0 |
| `set_block_size_mode` | `내용에 맞게 자동 크기로 해줘` | chart·table·Artifact view만 허용 | `reportPresentation.js`, block renderer 계층 | P1 |
| `add_text` | `Artifact 근거로 두 문장 요약을 추가해줘` | 서버 evidence alias·본문·상대 배치 검증, 새 block ID는 서버 생성 | `ReportAssistantPanel.jsx`, Canvas definition 재조회 | P0 |
| `update_text` | `핵심 요약을 한 문장으로 줄여줘` | 기존 text block과 evidence ref 검증 | `reportContract.ts`의 evidence label, Canvas renderer | P0 |
| `add_artifact_view` | `결과를 간결한 표로 추가해줘` | 결속된 서버 Artifact alias만 사용, chart/table/artifact 설정 allowlist | Artifact hydration·block renderer, `useReportArtifacts.ts` | P0 |
| `reposition_block` | `표를 차트 아래로 옮겨줘` | 기존 target·anchor, 상대 위치, half/full 폭만 허용 | `reportLayout.ts`, drag/drop과 동일 저장 layout 계약 | P0 |
| `duplicate_block` | `요약을 복제해서 원본 아래에 둬` | 새 ID는 서버 생성, 원본 이동은 별도 지시가 없으면 금지 | 완료 후 definition 재조회 | P1 |
| `remove_block` | `매출 표를 삭제해줘` | 존재·마지막 콘텐츠 block·page marker 보호 | destructive preview와 선택 승인 UI | P0 |
| `restore_previous_revision` | `직전 저장 버전으로 되돌려줘` | 다른 operation과 혼합 금지, 이전 version을 새 draft Revision으로 복원 | Revision 재조회·Canvas 교체 | P0 |

공통 충돌 검증은 `validate_report_patch_operation_dependencies()`에 모은다. 같은 block 삭제와
수정·이동, 동일 속성의 상충 변경, 삭제되는 anchor 참조, restore 혼합을 전체 patch 실패로 닫는다.
개별 operation 적용 전후가 같으면 `ReportPatchNoChangesError`로 Revision 생성을 막는다.

### 29.3 Artifact 근거·복수 Artifact·후속 제안

| 기능 | 구현 기술 | 파일 | 순위·주의점 |
|---|---|---|---|
| 안전한 evidence catalog | Artifact narrative와 metric values를 `artifact_narrative`, `metric_1` 같은 별칭으로 만들고 실제 ID·query·checksum을 모델에서 분리한다. | `app/backend/app/adapters/report_assistant.py`의 `report_evidence_catalog()`, `validate_report_patch_evidence()` | P0. 내부 lineage를 Client 응답에 다시 추가하면 안 된다. |
| evidence 영속·복구 | 승인된 text operation의 refs를 Report block에 저장하고 공개 label로 변환한다. | migration `20260826_39`; `src/report/domain.py`; `app/frontend/src/contracts/reportContract.ts`의 `reportEvidenceLabel()` | P0. 새로고침과 HTML/PDF에서도 같은 ref 계약을 유지한다. |
| 최대 5개 Artifact | 대표 1개와 추가 4개를 별도 binding row에 저장하고 모두 owner·APPROVED·query·checksum 검증 후 GPT payload에 alias로 전달한다. | migration `20260826_38`; repository의 `get_assistant_artifacts()`; router의 `_session_artifacts()`, `_with_artifact_bindings()` | P1. 하나라도 실패하면 전체 fail-closed한다. |
| 문맥형 suggestion | 변경안·quality review 응답에 최대 3개의 후속 편집 문장을 포함한다. 클릭은 composer만 채우고 자동 실행하지 않는다. | router의 `_validated_contextual_suggestions()`; `ReportAssistantPanel.jsx` | P1. 별도 모델 호출을 추가하지 않는다. |

### 29.4 Frontend 실제 연결

| 파일 | 소유 책임·사용 기술 | 변경 시 확인할 것 | 순위 |
|---|---|---|---|
| `app/frontend/src/api/reportClient.ts` | cookie 기반 REST client, request body와 phase 응답 검증, 내부 lineage 필드 차단 | URL/body request ID, 지원 phase, SQL·checksum·query ID 미보관 | P0 |
| `app/frontend/src/contracts/reportContract.ts` | TypeScript 공개 API 타입·enum·evidence label | Backend Pydantic/OpenAPI와 enum drift 금지 | P0 |
| `app/frontend/src/features/reports/useReportLifecycleState.ts` | React hook으로 session 생성·복구·message·review·승인·거절·취소·retry와 완료 Revision 재조회 소유 | stale async response generation, 승인 전 Canvas 무변경 | P0 |
| `app/frontend/src/features/reports/useReportsPageController.jsx` | 선택 Report·Artifact와 Assistant lifecycle 연결, sessionStorage 복구 포인터, `saving_revision` 재개 | `ReportsPage.jsx`에 상태 로직을 중복하지 않기 | P0 |
| `app/frontend/src/pages/ReportsPage.jsx` | page composition과 `ReportAssistantPanel` prop wiring | 다른 담당자 UI와 충돌이 잦으므로 wiring만 최소 변경 | P0 |
| `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx` | 승인 카드, operation 선택, preview, review finding, suggestion, cancel/retry 접근성 UI | Client가 patch를 직접 적용하거나 성공을 가장하지 않기 | P0 |
| `app/frontend/src/features/reports/components/reportPresentation.js` | A4 pagination, page break, chart/table presentation과 반응형 표시 | 빈 페이지·overflow·표 내부 폭을 함께 회귀 | P0 |
| `app/frontend/src/contracts/reportLayout.ts` | 12열 layout normalize·validate·compact·place | page marker를 일반 콘텐츠처럼 이동·겹침 계산하지 않기 | P0 |
| `app/frontend/src/features/reports/reportDraftOperations.js` | 편집기 block과 공통 Report document model 변환 | Assistant와 수동 편집기가 같은 저장 layout 계약 사용 | P1 |

관리자 운영 화면 `ReportAssistantOperationsPanel.jsx`는 다른 담당자 영역이다. Report Assistant
사용자 흐름 수정 때문에 이 파일이나 관리자 레이아웃을 함께 바꾸지 않는다.

### 29.5 DB migration 지도

기존 migration은 immutable하다. 현재 단일 연결은 `20260824_29 → 30 → 31 → 32 → 33 →
20260825_34 → 35 → 36 → 20260826_37 → 38 → 39 → 40 → 20260827_41`이다.

| Revision | 저장 계약 | 반영 순위 |
|---|---|---|
| `20260824_29` | 서버 소유 Assistant session과 phase | P0 |
| `20260824_30` | 결과 Artifact·query·checksum lineage | P0 |
| `20260824_31` | Report Revision CAS 결속 | P0 |
| `20260824_32` | 기존 Artifact typed patch 저장 | P0 |
| `20260824_33` | bounded 대화 turn | P0 |
| `20260825_34` | patch 승인 request·decision | P0 |
| `20260825_35` | 품질·token·비용 evaluation | P1 |
| `20260825_36` | 실패 session retry lineage | P0 |
| `20260826_37` | DB turn 보관 상한 | P1 |
| `20260826_38` | 복수 Artifact binding | P1 |
| `20260826_39` | Report block evidence refs | P0 |
| `20260826_40` | patch preview·operation 선택 승인 | P0 |
| `20260827_41` | `page_break` block 저장 제약 | P0·현재 작업 tree 신규 |

## 30. 기술 경계와 변경 규칙

| 계층 | 사용 기술 | 권위 | 동시 변경 규칙 |
|---|---|---|---|
| AI 계약 | OpenAI strict JSON Schema + Pydantic | `node_io.v0.1.json`, `report_contracts.py` | operation 변경 시 prompt·schema·checksum·model release·contract test를 함께 갱신한다. |
| API | FastAPI + typed request/response | `report_router.py`, generated OpenAPI | endpoint 변경 시 `reportClient.ts`와 OpenAPI check를 함께 검증한다. |
| 상태·영속 | async SQLAlchemy text query + PostgreSQL CAS | repository mixins·migration | owner·session·request ID·phase를 같은 SQL 조건에서 검증한다. |
| 편집 도메인 | immutable dataclass/Pydantic patch + server dry-run | `src/report/domain.py`, `report_patch.py` | Frontend가 model patch를 직접 저장하지 않는다. |
| Client 상태 | React hooks + TypeScript contract | `useReportLifecycleState.ts` | server session이 권위이며 sessionStorage는 복구 ID만 둔다. |
| Canvas·출력 | 12열 Report layout + A4 pagination | `reportLayout.ts`, `reportPresentation.js`, Backend report layout service | orientation·page break·overflow를 편집기와 HTML/PDF에서 같이 검증한다. |
| 관측 | request ID 멱등 evaluation upsert | `report_assistant_operations_repository.py` | raw prompt·response·SQL 없이 token·latency·cost와 결과만 저장한다. |

환경 제한은 `app/backend/compose.fragment.yml`과 `infrastructure/database/.env.example`의
`REPORT_ASSISTANT_MAX_MODEL_ATTEMPTS`, `REPORT_ASSISTANT_MAX_INPUT_TOKENS`,
`REPORT_ASSISTANT_MAX_OUTPUT_TOKENS`, `REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD`에서 선언한다.
모델 시도 횟수는 adapter, token·비용·동시성은 router와 공용 `execution_gate`, 시간당 요청 수는
evaluation repository의 최근 요청 집계로 검사한다.

## 31. 반영 우선순위

| 순위 | 반드시 반영할 범위 | 이유·완료 Gate |
|---|---|---|
| P0 | AI schema/prompt/release, Backend contract·patch·router, repository CAS, migration 39~41, Frontend contract·lifecycle·Canvas, OpenAPI와 핵심 회귀 | 하나라도 빠지면 요청 해석은 되지만 저장·복구가 깨지거나 Client/DB 계약이 달라진다. 같은 commit 묶음으로 검토한다. |
| P1 | quality review, 복수 Artifact, evidence 표시, operation preview·부분 승인, suggestion, 평가 관측, 반응형 표·접근성 | 핵심 저장은 유지되지만 사용자 검증 가능성과 안전한 운영성이 낮아진다. P0 직후 반영한다. |
| P2 | `new_data` AnalysisController 경로와 Trino·DataHub live readiness/E2E | 기존 Artifact GPT 편집과 분리한다. 실제 dependency release가 준비됐을 때만 live 완료한다. |
| P3 | 페이지 사이 삽입·삭제·이동·복제, 페이지별 방향, 글꼴·색상·테두리 등 신규 UX | 현재 계약에 없는 후속 기능이다. P0 안정화 전에 범위를 넓히지 않는다. |

팀 통합 적용 순서는 **migration → Backend domain/contract → AI schema/release → repository/router →
OpenAPI → Frontend contract/client → lifecycle/UI/Canvas → tests/evidence → 문서**다. 단, 배포 실행은
migration과 Backend·Frontend가 같은 release commit으로 준비된 뒤 한다. 부분 cherry-pick으로
`page_break` enum만 가져오거나 migration 41만 적용하면 안 된다.

## 32. 16시 안정화·다음 날 09시 공유 계획

현재 날짜를 2026-08-27로 보고 사용자의 “아침 9시”는 다음 날인 **2026-08-28 09:00 KST**로
해석한다. 실제 시간이나 공유 대상이 다르면 이 절의 시각만 조정한다.

### 2026-08-27 16:00 전: 기능 동결과 안정화

1. 신규 기능을 더 추가하지 않고 `add_report_page` 포함 현재 dirty 변경 범위를 고정한다.
2. migration head `20260827_41`과 단일 chain을 확인하고 공용 DB에는 임의 적용하지 않는다.
3. Backend·AI·document renderer 185개, Frontend 24개, production build 결과를 현재 tree에서
   재확인한다.
4. OpenAPI, 문서화, architecture, repository integrity, compileall, `git diff --check`를 통과시킨다.
5. 실제 기존 Artifact 편집 Browser 영수증의 request ID·model release·Report v33→v34·새로고침
   복구를 보존한다.
6. secret, production mock, 질문별 고정 응답, fallback Artifact, 고정 SQL이 diff에 없는지 확인한다.
7. Trino·DataHub `new_data` live E2E는 안정화 범위에 섞지 않고 미완료로 명시한다.

### 2026-08-27 16:00 이후: 공유 전 변경 금지

- P0 결함 외 기능 추가를 멈춘다.
- 수정이 필요하면 원인·영향 파일·재실행 테스트를 이 문서에 기록한다.
- 다른 개발자의 관리자 UI 변경과 `ReportsPage.jsx` 충돌 여부만 읽기 전용으로 점검한다.
- 사용자의 별도 승인 전 commit·push·merge·공용 DB migration 적용은 하지 않는다.

### 2026-08-28 09:00 공유 Gate

1. `origin/seung` 대비 ahead/behind와 작업 tree를 다시 확인한다.
2. P0 파일이 한 묶음으로 포함되고 migration 41이 빠지지 않았는지 확인한다.
3. Backend·Frontend 최소 회귀와 `git diff --check`를 다시 실행한다.
4. 이 통합 가이드, runtime evidence, 정확한 미완료 항목을 함께 공유한다.
5. 사용자 승인 후에만 commit·push한다. push 결과의 commit SHA를 이 문서 첫 절과 팀 메시지에
   기록한다.

## 33. 현재 작업 확인 결과

2026-08-27 확인 시점의 Git commit은 `origin/seung`과 ahead/behind `0/0`이다. 그러나
`add_report_page`, migration `20260827_41`, 관련 GPT 계약·Backend·Frontend·테스트·통합 가이드와
Browser evidence는 아직 dirty/untracked 상태이므로 공유 브랜치에 반영됐다고 말하면 안 된다.

현재 코드 기준으로 P0 기존 Artifact 편집 흐름은 실제 GPT·격리 PostgreSQL·Browser에서
검증됐다. 최신 페이지 추가 영수증은 v33에서 승인 전 무변경, 승인 후 v34와 빈 2페이지,
새로고침 복구, console error 0, 관련 Backend 500 0이다. `new_data`는 코드·unit/contract 범위이며
Trino·DataHub live E2E는 미완료다.

16시까지의 남은 일은 새 기능 구현이 아니라 **현재 변경 고정, 전체 회귀 재확인, secret·mock
감사, 문서와 diff 최종 확인**이다. 09시 공유 전에 필요한 외부 상태 변경은 commit·push뿐이며,
이는 사용자 승인을 받은 뒤 수행한다.

## 34. 기능별 5개 재검증 시나리오 — 실행 전 계획

이 절은 2026-08-27 재검증을 위한 **실행 전 계획**이다. 총 29개 기능군, 145개 시나리오이며
아직 실행 결과가 아니다. 사용자가 이 목록을 확인한 뒤 `PLANNED → PASS/FAIL/BLOCKED`로 기록한다.

실행은 다음 세 층으로 나눈다.

1. `C`: deterministic contract/unit — fake model·repository로 외부 비용 없이 모든 시나리오 실행
2. `I`: 격리 PostgreSQL integration — CAS·migration·read-back이 필요한 항목 실행
3. `B`: 실제 GPT·PostgreSQL·Browser — 기능별 대표 정상·거부 흐름만 bounded 실행

Trino·DataHub가 필요한 `new_data` 마지막 실행은 readiness가 없으면 `BLOCKED`로 기록한다. 이를
fake PASS나 기존 Artifact 편집 E2E로 대체하지 않는다. 모든 시나리오는 승인 전 Report version,
최종 phase, 생성 Revision 수, 내부 lineage 노출 여부를 공통 확인한다.

### 34.1 Agent 기반 기능

#### F01 서버 Session 생성·복구

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F01-1 | C/I/B | 유효한 draft와 승인 Artifact로 session 생성 | 서버 UUID, `ready`, owner·definition version·Artifact 결속 |
| F01-2 | C/I | 새로고침 후 session ID로 복구 | 동일 phase·patch·base revision 반환 |
| F01-3 | C/I | 타인 session 조회 | 존재를 숨긴 `404` |
| F01-4 | C/I | 최신 Report가 아닌 version으로 session 생성 | 안전한 `409` 또는 최신 Report 재열기 안내 |
| F01-5 | C/I | 같은 화면에서 오래된 응답이 늦게 도착 | 최신 session을 덮지 않음 |

#### F02 GPT strict 분류·명확화

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F02-1 | C/B | Artifact로 가능한 명확한 편집 요청 | `existing_artifact`와 typed patch |
| F02-2 | C/B | 기간·대상·표현이 불명확한 요청 | `clarification`, `ready`, Revision 0 |
| F02-3 | C | 현재 Artifact에 없는 지표 요청 | `new_data`, 분석 승인 전 실행 0 |
| F02-4 | C | malformed JSON·필수 nullable 누락 | contract failure로 fail-closed |
| F02-5 | C/B | SQL·내부 ID·자동 승인 유도 prompt | 금지 값 미노출, 권한·승인 우회 없음 |

#### F03 승인 전 변경안 재수정·bounded history

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F03-1 | C/B | 승인 카드에서 일부 효과를 빼 달라고 재지시 | 새 patch ID의 전체 대체 patch |
| F03-2 | C/I | 오래된 patch ID로 재수정 | 모델 호출 0, `409` |
| F03-3 | I | 두 재수정 요청 동시 제출 | 하나만 저장, 나머지 `409` |
| F03-4 | C/I | 7회 이상 대화 | DB 원문 최근 6턴만 유지 |
| F03-5 | C/B | 재수정 뒤 최초 patch 승인 | `409`, 최종 patch만 승인 가능 |

#### F04 Artifact 근거 참조

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F04-1 | C/B | Artifact narrative 근거로 요약 추가 | 안전한 evidence alias 결속 |
| F04-2 | C | 존재하지 않는 evidence ref | patch 저장 전 거부 |
| F04-3 | C | 다른 Artifact alias 혼합 | 전체 patch fail-closed |
| F04-4 | I/B | 승인 후 새로고침 | block evidence refs 동일 복구 |
| F04-5 | C/B | network·DOM·Client state 검사 | query ID·checksum·SQL 없음 |

#### F05 여러 승인 Artifact 종합

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F05-1 | C/B | 승인 Artifact 2개로 종합 요약 | 두 alias 범위 안의 typed patch |
| F05-2 | C | 최대 5개 Artifact 결속 | 모두 owner·APPROVED·lineage 검증 |
| F05-3 | C | 6개 선택 | 모델 호출 전 계약 거부 |
| F05-4 | C/I | 하나가 타인 소유·미승인 | 전체 session 생성 실패, 존재 미노출 |
| F05-5 | C | 선택하지 않은 alias를 모델이 반환 | patch 거부, fallback 없음 |

#### F06 비저장 품질 검토·후속 제안

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F06-1 | C/B | 전체 보고서 품질 검토 | typed finding, Report·Revision 무변경 |
| F06-2 | C/B | 선택 text block만 검토 | 선택 범위 finding만 반환 |
| F06-3 | C | 존재하지 않는 block 검토 | 모델 호출 전 거부 |
| F06-4 | C/B | finding 수정 제안 클릭 | composer만 채우고 자동 실행·승인 없음 |
| F06-5 | C | suggestion에 내부 ID·SQL 포함 | suggestion 제거 또는 응답 거부 |

#### F07 승인·거절·부분 승인·멱등성

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F07-1 | I/B | 전체 patch 승인 | CAS Revision 정확히 1건 |
| F07-2 | I/B | operation 일부만 선택 승인 | 선택 효과만 저장 |
| F07-3 | C/I | 승인 카드 거절 | `ready`, Revision 0 |
| F07-4 | I/B | 같은 선택 승인 재전송 | 기존 Revision 반환, 추가 0 |
| F07-5 | I | 완료 후 다른 선택으로 재승인 | `409`, 기존 Revision 불변 |

#### F08 취소·실패·재시도·저장 재개

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F08-1 | C/B | `ready` 또는 승인 대기 session 취소 | terminal `cancelled`, Report 무변경 |
| F08-2 | C | 분석·Artifact·저장 phase 취소 | 강제 중단 거부 |
| F08-3 | C/I | retryable failed session 재시도 | 원본 불변, 새 `ready` child |
| F08-4 | I | 동일 실패 session retry 중복 호출 | 같은 child 한 건 반환 |
| F08-5 | I/B | `saving_revision` 중 응답 유실 후 복구 | GPT·분석 재호출 0, Revision 최대 1 |

#### F09 권한·한도·민감정보

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F09-1 | C/I | analyst가 타인 Report/session 접근 | `404` 또는 capability `403` |
| F09-2 | C | 시간당 요청 제한 초과 | 모델 호출 0, `ASSISTANT_RATE_LIMITED` |
| F09-3 | C | token budget 초과 | Revision 0, typed error |
| F09-4 | C | cost·concurrency 제한 초과 | fail-closed, gate 반환 |
| F09-5 | C/B | API·로그·브라우저 안전 필드 검사 | raw prompt·response·credential·SQL·lineage 미노출 |

#### F10 새 데이터 계획 승인 경계

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F10-1 | C | `new_data` 계획 생성 | 서버 data request ID, `waiting_approval` |
| F10-2 | C/I | 계획 거절 | controller 0회, `ready`, `rejected_at` |
| F10-3 | C/I | 잘못된 ID·권한·phase 승인 | 실행 전 403/409 |
| F10-4 | C | 성공 Artifact owner/request/query/checksum 불일치 | `failed`, Revision 0 |
| F10-5 | B/live | 실제 DataHub·Trino 분석부터 Canvas까지 | readiness 없으면 `BLOCKED`; 준비됐을 때만 live E2E |

### 34.2 자연어 편집 operation

#### O01 `set_report_title`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O01-1 | C/B | `제목을 8월 경영 보고서로 바꿔줘` | 제목 변경 preview와 승인 후 저장 |
| O01-2 | C | 현재 제목과 같은 제목 요청 | no-op, Revision 0 |
| O01-3 | C | 공백 제목 요청 | 계약 또는 dry-run 거부 |
| O01-4 | C | 제목을 서로 다른 두 값으로 동시 변경 | 충돌 patch 전체 거부 |
| O01-5 | I/B | 승인·새로고침 | 새 제목 유지, 중복 Revision 0 |

#### O02 `set_report_orientation`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O02-1 | C/B | `보고서를 가로형으로 만들어줘` | portrait→landscape preview·저장 |
| O02-2 | C/B | `보고서를 세로형으로 바꿔줘` | landscape→portrait 저장 |
| O02-3 | C | 현재 방향과 같은 요청 | no-op, Revision 0 |
| O02-4 | C | 가로·세로를 동시에 요구 | clarification 또는 전체 거부 |
| O02-5 | I/B | 방향 변경 후 표·차트·새로고침 | 겹침 없이 동일 방향 복구 |

#### O03 `set_currency_display_unit`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O03-1 | C/B | `금액을 백만원 단위로 보여줘` | 허용 enum preview·저장 |
| O03-2 | C | 지원 단위별 변경 | 각 enum만 계약 통과 |
| O03-3 | C | 임의 단위 요청 | clarification 또는 계약 거부 |
| O03-4 | C | 서로 다른 단위 동시 지정 | 충돌 patch 거부 |
| O03-5 | I/B | 승인 후 Canvas·새로고침 | 동일 표시 단위 복구 |

#### O04 `compact_report_layout`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O04-1 | C/B | `모든 블록 빈 공간을 정리해줘` | 시각 순서 유지, gap 축소 |
| O04-2 | C | 이미 compact한 Report | no-op, Revision 0 |
| O04-3 | C | half/full 블록 혼합 | 12열 안에서 겹침 없이 배치 |
| O04-4 | C | page break 포함 Report | 페이지 경계를 넘겨 압축하지 않음 |
| O04-5 | I/B | 승인 후 reload·HTML | Canvas와 출력 layout 일치 |

#### O05 `add_report_page`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O05-1 | C/B | `페이지 한 장 추가해줘` | `add_report_page` 한 건만 제안 |
| O05-2 | C/I | 승인 전 | Report version·page count 무변경 |
| O05-3 | I/B | 승인 후 | 끝에 빈 페이지 1장, Revision 1건 |
| O05-4 | I | 동일 승인 재전송 | 페이지·Revision 추가 0 |
| O05-5 | B | 새로고침·HTML preview | 빈 페이지 경계 동일 복구, marker 비표시 |

#### O06 `update_block_title`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O06-1 | C/B | chart 제목 변경 | 기존 chart만 변경 |
| O06-2 | C | table·text·artifact 제목 각각 변경 | 모든 허용 block type 통과 |
| O06-3 | C | 존재하지 않는 block | dry-run 거부 |
| O06-4 | C | 현재와 같은 제목 | no-op, Revision 0 |
| O06-5 | C/I | 삭제와 제목 변경 혼합 | dependency 충돌로 전체 거부 |

#### O07 `resize_block`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O07-1 | C/B | `표를 전체 너비 9단으로 키워줘` | 12열×9단 preview·저장 |
| O07-2 | C | block별 최소 크기 경계 | 경계값 허용, 미만 거부 |
| O07-3 | C | 12열 초과·음수 높이 | 계약 거부 |
| O07-4 | C | 같은 block을 서로 다르게 두 번 resize | 전체 patch 거부 |
| O07-5 | B | 작은 화면·reload | 외곽과 내부 표가 함께 반응형 축소 |

#### O08 `update_chart_settings`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O08-1 | C/B | 가로 막대·범례 숨김 | chart settings만 저장 |
| O08-2 | C | 허용 chart type 전체 | enum 목록과 renderer 일치 |
| O08-3 | C | text/table block에 적용 | 저장 전 거부 |
| O08-4 | C | 모순된 chart type 두 개 | 전체 patch 거부 |
| O08-5 | I/B | 승인·reload | chart type·legend 동일 복구 |

#### O09 `update_table_settings`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O09-1 | C/B | 간결 밀도·행 번호 표시 | table settings 저장 |
| O09-2 | C | 보통 밀도·행 번호 숨김 | 허용 반대 설정 저장 |
| O09-3 | C | text/chart block에 적용 | 저장 전 거부 |
| O09-4 | C | 알 수 없는 settings 필드 | 저장하지 않거나 전체 거부 |
| O09-5 | B | 좁은 표 block·reload | 내부 table overflow 없이 설정 복구 |

#### O10 `set_block_size_mode`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O10-1 | C/B | chart를 내용 맞춤으로 변경 | auto mode 저장 |
| O10-2 | C | table을 manual로 변경 | manual mode 저장 |
| O10-3 | C | text block에 적용 | 거부 |
| O10-4 | C | 현재 mode와 같은 요청 | no-op, Revision 0 |
| O10-5 | B | auto mode에서 긴 표·차트 | 페이지 overflow 정책과 일치 |

#### O11 `add_text`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O11-1 | C/B | Artifact 근거로 요약 블록 추가 | 서버 ID·evidence ref 결속 |
| O11-2 | C | half와 full 배치 | 상대 배치·폭 enum만 허용 |
| O11-3 | C | 빈 본문·근거 없는 단정 | 계약 또는 evidence 검증 거부 |
| O11-4 | C | 존재하지 않는 anchor | dry-run 거부 |
| O11-5 | I/B | 승인·reload | 본문·제목·근거 표시 복구 |

#### O12 `update_text`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O12-1 | C/B | 기존 요약을 두 문장으로 축약 | text 본문만 변경 |
| O12-2 | C | 제목만 변경 | 기존 본문 유지 |
| O12-3 | C | text가 아닌 block 대상 | 거부 |
| O12-4 | C | 본문·제목 모두 동일 | no-op, Revision 0 |
| O12-5 | C/I | 삭제와 update 혼합 | 전체 patch 거부 |

#### O13 `add_artifact_view`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O13-1 | C/B | 승인 결과를 chart로 추가 | 결속 alias 기반 chart block |
| O13-2 | C/B | 간결한 table·행 번호로 추가 | allowlist presentation 저장 |
| O13-3 | C | 전체 Artifact 묶음 추가 | artifact view 저장 |
| O13-4 | C | 미결속 alias·임의 ID | 거부 |
| O13-5 | I/B | 승인·reload | 서버 ID·표현 설정·근거 복구 |

#### O14 `reposition_block`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O14-1 | C/B | 표를 차트 아래로 이동 | 상대 위치 preview·저장 |
| O14-2 | C | half→full 폭 변경 | 12열 범위 안에서 저장 |
| O14-3 | C | 자기 자신 anchor | 계약 거부 |
| O14-4 | C | 존재하지 않거나 삭제되는 anchor | 전체 patch 거부 |
| O14-5 | I/B | 승인·reload | 겹침 없이 동일 위치 복구 |

#### O15 `duplicate_block`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O15-1 | C/B | 요약을 원본 아래 복제 | 서버 새 ID, 원본 불변 |
| O15-2 | C | chart·table·artifact 각각 복제 | settings·lineage 안전 복사 |
| O15-3 | C | 존재하지 않는 block 복제 | 거부 |
| O15-4 | C | 복제와 원본 삭제 혼합 | dependency 정책대로 전체 거부 |
| O15-5 | I/B | 승인·reload | 원본·복제본 각각 한 건 유지 |

#### O16 `remove_block`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O16-1 | C/B | 기존 표 삭제 | destructive preview·승인 후 삭제 |
| O16-2 | C | 마지막 콘텐츠 block 삭제 | 거부 |
| O16-3 | C | 존재하지 않는 block 삭제 | 거부 |
| O16-4 | C | page break marker를 block ID로 삭제 | 거부 |
| O16-5 | I/B | 거절·승인·reload 비교 | 거절은 유지, 승인은 삭제 복구 |

#### O17 `restore_previous_revision`

| ID | 층 | 사용자 시나리오 | 기대 결과 |
|---|---|---|---|
| O17-1 | C/I/B | 직전 Revision 복원 | 이전 내용을 새 Revision으로 저장 |
| O17-2 | C | 다른 operation과 혼합 | 계약 거부 |
| O17-3 | C/I | 이전 Revision이 없음 | 안전한 실패, Revision 0 |
| O17-4 | I | base revision이 stale | CAS `409` |
| O17-5 | I/B | 동일 승인·reload | 복원 Revision 한 건, Canvas 동일 |

### 34.3 화면·출력·운영 관측

#### F11 Canvas·새로고침·HTML/PDF

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F11-1 | B | completed 직후 | `result_revision` 서버 재조회 후 Canvas 교체 |
| F11-2 | B | 브라우저 새로고침 | 동일 server Revision·session 복구 |
| F11-3 | C/B | portrait·landscape HTML | Canvas와 pagination 일치 |
| F11-4 | C/B | 좁은 chart/table block | 외곽과 내부 콘텐츠가 함께 축소·스크롤 |
| F11-5 | C/B | page break 포함 HTML/PDF | marker 미표시, 물리 페이지 경계 유지 |

#### F12 평가·token·비용·운영 정보

| ID | 층 | 시나리오 | 기대 결과 |
|---|---|---|---|
| F12-1 | C/I | patch 성공 평가 | route·operation·승인·Revision 연결 |
| F12-2 | C/I | 모델 usage 없음 | token·cost를 0이 아닌 null로 기록 |
| F12-3 | C/I | 동일 request 재처리 | 평가 한 건 멱등 upsert |
| F12-4 | C/I | 실패 code 집계·빈 기간 | 정확한 분모, 빈 표본 null |
| F12-5 | C | analyst/admin 조회 권한 | 본인 평가만 허용, 전체 집계 관리자 전용 |

### 34.4 실행 순서와 보고 형식

1. 145개 scenario ID를 먼저 기존 unit/contract test에 매핑한다.
2. 누락 scenario만 기존 테스트 파일에 최소 추가한다. production 질문별 분기는 만들지 않는다.
3. `C` 전체 실행 후 실패를 코드 결함·테스트 결함·환경 blocker로 분리한다.
4. migration 41 격리 DB에서 `I`를 실행하고 Revision 수와 session read-back을 기록한다.
5. `B`는 기능군별 대표 정상 1건과 안전 거부 1건을 우선 실행한다. 실제 GPT 반복 횟수와 비용을
   bounded하고 request ID·model release·Revision만 증빙한다.
6. 각 ID를 `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN` 중 하나로 이 절에 기록한다.
7. 실패 발견 시 즉시 다음 시나리오로 덮지 않고 재현→원인→최소 수정→관련 회귀→Browser 재검증
   순서로 처리한다.

최종 보고는 기능별 `5개 중 PASS 수`, 실패 ID, 수정 파일, 최종 Revision, 실행하지 못한 live
dependency를 한 표로 제공한다. 실제 OpenAI·PostgreSQL·Browser를 쓰지 않은 결과에는 live 또는
E2E라는 이름을 붙이지 않는다.

## 35. 기능별 재검증 실행 기록

### 2026-08-27 실행 1차

| 범위 | 결과 | 근거 |
|---|---|---|
| Backend·AI·Report document 기준선 | PASS | 현재 tree에서 185 tests, 실패·skip 0 |
| Frontend 기준선 | PASS | 24 tests, 실패·skip 0; 개발 WebSocket 포트 경고는 별도 기록 |
| O01-1 제목 변경 정상 흐름 | PASS | 실제 GPT·격리 PostgreSQL·Browser, v34→v35, 승인 전 무변경·승인 후 Canvas 반영 |
| O01-2 동일 제목 유지 요청 최초 실행 | FAIL | 실제 GPT가 strict 계약을 위반해 `REPORT_ASSISTANT_MODEL_CONTRACT_INVALID`; Revision은 생성되지 않음 |
| O01-2 결함 수정 contract 회귀 | PASS | 무변경 단독 요청을 `clarification + patch=null`로 명시, 관련 102 tests와 OpenAPI 통과 |
| O01-2 실제 GPT 재검증 | NOT_RUN | 사용자가 OpenAI 전송을 승인했고 Backend 외부 연결을 복구했지만 재로그인 전에 검증을 중단함 |
| O02-1 가로형 변경 최초 Chrome 실행 | BLOCKED | 격리 DB·Chrome에서 입력까지 확인했으나 기존 Backend의 `REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED`로 Revision v35 유지 |
| O02-1 재실행 준비 | NOT_RUN | 외부 OpenAI secret을 적용한 최신 Backend를 격리 E2E DB로 재기동해 `/health` 200 확인; 인증 session 만료 후 사용자가 중단 요청 |

O01-1 화면 증거:

- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-1_before.jpg`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-1_input.jpg`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-1_proposal.jpg`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-1_after.jpg`

O01-2 최초 실패와 재시도 화면 증거:

- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-2_before.jpg`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-2_input.jpg`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-2_after.jpg`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O01-2_retest2_after.jpg`

O02-1 Chrome 증거:

- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O13-1_before_chrome.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O13-1_input_chrome.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O13-1_transport_failed_chrome.png`
- `docs/e2e_mvp/derived/runtime_evidence/2026-08-27/scenario-matrix/O13-1_backend_restart_login_required_chrome.png`

위 네 파일은 초기 실행 중 파일명에 `O13-1`을 사용했지만 34절의 기능 매핑상 실제 scenario ID는
`O02-1 set_report_orientation`이다. 증거 파일명은 기록의 연속성을 위해 유지한다.

현재 실제 실행 판정은 145개 중 PASS 1, FAIL 후 contract 수정 1이며 나머지는 `BLOCKED` 또는
`NOT_RUN`이다. 185개 Backend·AI와 24개 Frontend 테스트 통과를 145개 Browser 시나리오 통과로
대체하지 않는다.

## 36. 2026-08-27 Report Assistant 일일보고

### 금일 완료한 구현

- 보고서 편집기에서 Revision으로 저장되는 기능을 GPT 자연어 typed operation으로 확장했다.
  문서 방향, 통화 단위, 빈 공간 정리, 블록 제목·크기·자동 크기, 차트·표 표현 설정과 승인된
  Artifact view 추가가 기존 승인·CAS 경계를 공통으로 사용한다.
- `페이지 한 장 추가해줘`를 `add_report_page`로 구현했다. 서버가 `page_break` ID를 생성하며
  승인 전에는 저장하지 않고 승인 후에만 새 Revision을 만든다. migration `20260827_41`은 기존
  migration을 수정하지 않고 page break 저장 제약을 추가한다.
- 모델 계약과 prompt를 강화했다. 질문별 고정 응답 없이 strict operation schema를 사용하고,
  무변경 단독 요청은 빈 patch가 아니라 clarification으로 처리한다. 현재 release는
  `PROMPT-v1.9.5`, `MODEL-v1.28.0`, `MODEL-RELEASE-v1.45.0`이다.
- 차트·표 block이 좁아질 때 내부 콘텐츠가 외곽과 함께 반응하도록 presentation과 layout 계약을
  보완했다. 승인 카드에는 안전한 변경 전·후만 표시하고 SQL·query ID·checksum은 노출하지 않는다.
- 29개 기능군을 기능별 5개씩 총 145개 재검증 scenario로 정리했다. 각 시나리오는 contract,
  격리 PostgreSQL, 실제 GPT·Browser 증거를 구분하며 미실행 항목을 PASS로 표시하지 않는다.

### 금일 검증 결과

- Backend·AI·Report document 기준선: 185 tests PASS, 실패·skip 0.
- Frontend: 24 tests PASS와 production build PASS.
- 실제 GPT·격리 PostgreSQL·Browser 제목 변경: v34에서 v35로 새 Revision 생성, 승인 전 무변경과
  승인 후 Canvas 반영 확인.
- 동일 제목 유지 요청에서 strict contract 결함을 발견해 prompt를 수정했고 관련 102 tests와
  OpenAPI 검사를 통과했다.
- Chrome 가로형 변경 검증에서는 기존 Backend의 model transport 실패를 실제 재현했다. 최신
  Backend를 외부 model 환경과 격리 DB로 재기동해 health 200까지 복구했으나 로그인 session 만료
  뒤 사용자가 검증 중단을 요청해 최종 GPT proposal·승인·Revision은 실행하지 않았다.

### 남은 작업과 인수 시 주의사항

1. Chrome에서 다시 로그인한 뒤 O01-2와 O02-1을 재실행한다.
2. 가로형 변경은 `전 → 입력 → proposal → 승인 전 v35 → 승인 후 v36 → reload` 전체 증거가
   있어야 PASS다.
3. 나머지 143개 시나리오는 34절 ID별로 실행하며 unit 결과를 Browser PASS로 대체하지 않는다.
4. Trino·DataHub를 사용하는 `new_data` live E2E는 이번 범위에 포함하지 않았고 완료로 표시하지
   않는다.
5. 외부 secret 파일은 저장소 밖에 유지했으며 Git 변경에 포함하지 않는다.
