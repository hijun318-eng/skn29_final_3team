# Report Assistant V2 GPT 고도화 기획

## 1. 목적

이 문서는 Analysis Agent, Trino, DataHub 연결을 제외하고 현재 연결된 GPT와 기존 승인 Artifact만
사용해 Report Assistant V2를 고도화하는 순서와 완료 조건을 정의한다.

이번 고도화의 목표는 기능 수를 늘리는 것이 아니라 다음 사용자 경험을 완성하는 것이다.

```text
사용자 지시
→ GPT 변경안
→ 사용자가 변경안을 대화로 수정
→ Artifact 근거를 확인할 수 있는 최종 변경안
→ 사용자 승인
→ CAS Report Revision
```

## 2. 범위

### 포함

- GPT가 만든 변경안의 승인 전 재수정 대화
- 기존 승인 Artifact와 생성 텍스트의 안전한 근거 참조
- 현재 Report를 읽는 비저장 품질 검토
- 여러 승인 Artifact를 이용한 보고서 종합 편집
- 현재 문맥에 맞는 후속 작업 제안
- 대화 이력의 bounded 보관과 민감정보 노출 방지

### 제외

- Analysis Agent 변경 또는 신규 분석 pipeline
- Trino query 실행
- DataHub 검색·Glossary·lineage 연결
- semantic release와 catalog readiness
- 고정 SQL, 질문별 응답, production mock
- 자동 승인과 승인 우회
- 별도 Agent framework, queue, worker, microservice
- 관리자 운영 화면 변경

## 3. 현재 구현과 확인된 공백

### 현재 가능한 기능

- GPT strict schema 기반 `clarification`, `existing_artifact`, `new_data` 분류
- 현재 Report와 승인 Artifact를 입력으로 한 typed patch 8종 생성
- patch 서버 dry-run
- 사용자 승인 전 Report 무변경
- 승인 후 CAS Revision 저장
- 중복 승인 멱등 처리
- bounded history를 이용한 추가 질문
- 모델 실패의 typed 종료와 새 session retry

### 현재 불가능하거나 부족한 기능

1. ~~`waiting_patch_approval`에서 입력창이 잠겨 변경안을 다시 수정할 수 없다.~~ 1단계 구현 완료.
2. ~~사용자는 변경안을 적용하거나 거절할 수만 있고 일부만 유지해 달라고 말할 수 없다.~~ 1단계 구현 완료.
3. GPT가 만든 텍스트에는 안전한 Artifact 근거 별칭이 없다.
4. 서버는 Artifact 전체 binding을 검증하지만 문장과 근거 별칭의 연결은 검증하지 않는다.
5. 현재 session은 승인 Artifact 한 개만 사용한다.
6. 빠른 요청은 현재 Report 문맥과 관계없는 고정 UI 문구다.
7. DB 조회는 최근 turn만 제한하지만 session의 원문 turn은 계속 누적될 수 있다.

## 4. 단계별 개발 순서

한 번에 모두 구현하지 않는다. 각 단계의 회귀 검증이 끝난 뒤 다음 단계로 진행한다.

| 단계 | 기능 | 우선순위 | DB migration |
|---|---|---:|---|
| 1 | 승인 전 변경안 재수정 대화 | P0 | 원칙적으로 없음 |
| 2 | 텍스트와 Artifact 근거 참조 결속 | P0 | 승인 patch 범위 구현, block 영속은 보류 |
| 3 | 비저장 보고서 품질 검토 | P1 | 없음 |
| 4 | 여러 승인 Artifact 종합 편집 | P1 | 신규 결속 table 필요 |
| 5 | 문맥형 후속 작업 제안 | P2 | 없음 |

첫 구현 주기는 1단계만 완료한다. 2~5단계를 위한 범용 framework나 미사용 schema를 미리 만들지
않는다.

## 5. 1단계: 승인 전 변경안 재수정 대화

### 사용자 결과

현재:

```text
GPT 변경안 → 적용 또는 거절
```

고도화 후:

```text
GPT 변경안
├─ 적용
├─ 거절
└─ 추가 수정 지시
    → 기존 변경안 + 새 지시를 GPT에 전달
    → 새 typed patch
    → 서버 dry-run
    → 같은 승인 대기 화면
```

예시:

```text
사용자: 핵심 내용을 세 문장으로 줄이고 차트를 위로 옮겨줘.
GPT: update_text + reposition_block 변경안을 제안.
사용자: 차트 위치는 그대로 두고 요약만 두 문장으로 바꿔줘.
GPT: update_text만 포함한 대체 변경안을 제안.
사용자: 적용.
서버: 최종 변경안만 새 Revision으로 저장.
```

### API 설계

새 endpoint를 만들지 않고 기존 메시지 endpoint를 재사용한다.

```text
POST /reports/assistant/sessions/{assistant_request_id}/messages
```

요청 계약을 다음처럼 확장한다.

```json
{
  "instruction": "차트 위치는 그대로 두고 요약만 두 문장으로 바꿔줘",
  "expected_patch_request_id": "현재 서버 patch request ID"
}
```

규칙:

- `ready`에서는 `expected_patch_request_id=null`만 허용한다.
- `waiting_patch_approval`에서는 현재 `patch_request_id`와 정확히 일치해야 한다.
- 다른 phase에서는 `409 ASSISTANT_STATE_CONFLICT`로 닫는다.
- 오래된 patch request ID는 모델 호출 전에 거부한다.
- 클라이언트가 새 patch request ID를 만들지 않는다.
- 서버가 검증 성공 후 새 patch request ID를 생성한다.

### 모델 계약

`report_assistant_turn_request`에 nullable `current_patch`를 추가한다.

```json
{
  "current_patch": {
    "summary": "현재 승인 대기 중인 변경 요약",
    "operations": []
  }
}
```

- 최초 요청에서는 `current_patch=null`이다.
- 재수정 요청에서만 현재 서버 저장 patch를 전달한다.
- 모델은 기존 patch를 무조건 누적하지 않고 새 사용자 지시를 반영한 전체 대체 patch를 반환한다.
- 모델 output 형식은 기존 `existing_artifact` patch 계약을 재사용한다.
- 실제 Artifact ID, query ID, checksum, 절대 grid 좌표는 계속 금지한다.
- prompt version은 변경하고 model/prompt trace에 기록한다.

### 서버 저장과 동시성

- 원본 Report definition과 Artifact binding을 다시 읽고 검증한다.
- 대체 patch도 기존 `_apply_existing_artifact_patch()`로 dry-run한다.
- owner, session ID, 기존 patch request ID, `waiting_patch_approval` phase를 하나의 DB UPDATE 조건으로 확인한다.
- 성공 시 `report_patch_json`, decision hash, model/prompt trace와 patch request ID를 새 값으로 교체한다.
- Report definition과 block은 변경하지 않는다.
- 두 재수정 요청이 경쟁하면 하나만 현재 patch가 되고 나머지는 `409`다.
- 승인 endpoint는 최종 patch request ID만 허용한다.
- 기존 turn table에는 사용자 재수정 지시와 안전한 Assistant 메시지만 추가한다.
- 모델이 최대 6개 turn만 사용하므로 새 turn 저장 transaction에서 오래된 원문 turn을 제거해 session당 원문 보관도 같은 범위로 제한한다.
- 과거 raw patch 전체를 보관하는 신규 table은 이번 단계에서 만들지 않는다.

### 클라이언트 동작

- `waiting_patch_approval`에서도 composer 입력을 허용한다.
- 버튼 문구는 `변경안 수정 요청`으로 바꾼다.
- 메시지 body에 현재 `patch_request_id`를 전달한다.
- 응답이 오기 전 기존 승인 카드를 유지하고 중복 submit을 막는다.
- 성공하면 승인 카드의 summary와 operation 목록을 새 값으로 교체한다.
- `409`이면 session을 재조회하고 서버 최신 변경안을 표시한다.
- 적용·거절 버튼은 기존 API를 그대로 사용한다.
- 변경안 수정 요청만으로 Canvas나 Revision을 변경하지 않는다.

### 1단계 필수 테스트

1. `waiting_patch_approval`에서 재수정 메시지를 받을 수 있다.
2. `ready` 최초 요청은 기존 동작을 유지한다.
3. 다른 phase의 재수정은 모델 호출 0회와 `409`다.
4. 오래된 patch request ID는 모델 호출 0회와 `409`다.
5. 모델 입력에 현재 patch와 원본 Report·Artifact가 포함된다.
6. 새 patch는 기존 server dry-run을 다시 통과한다.
7. 잘못된 block ID를 포함한 대체 patch는 저장되지 않는다.
8. 재수정 전후 Report definition/block 변경은 0회다.
9. 성공한 재수정은 새 patch request ID를 반환한다.
10. 경쟁 재수정은 하나만 저장된다.
11. 이전 patch request ID의 승인은 `409`다.
12. 최종 patch 승인만 Revision 한 건을 만든다.
13. 최종 승인 중복 호출은 Revision을 추가 생성하지 않는다.
14. 거절은 Report를 변경하지 않고 `ready`로 돌아간다.
15. Frontend가 현재 patch request ID를 정확히 body에 전달한다.
16. 승인 대기 중 composer와 적용·거절 버튼이 함께 동작한다.
17. 관리자 운영 UI 파일은 변경하지 않는다.
18. 기존 clarification·retry·승인 흐름 회귀가 없다.
19. session당 원문 turn이 6개를 초과해 누적되지 않는다.

### 1단계 예상 변경 파일

- `src/ai/contracts/node_io.v0.1.json`
- `src/ai/prompt_registry.py`
- `app/backend/app/report_contracts.py`
- `app/backend/app/adapters/report_assistant.py`
- `app/backend/app/api/report_router.py`
- `app/backend/app/adapters/report_artifact_repository.py`
- `app/frontend/src/api/reportClient.ts`
- `app/frontend/src/features/reports/useReportLifecycleState.ts`
- `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx`
- `tests/ai/test_report_assistant_contract.py`
- `tests/backend/test_report_assistant_session.py`
- `tests/frontend/contracts.test.mjs`

patch 교체는 기존 session row와 turn table을 재사용한다. 원문 turn을 실제로 6개 이내로 정리하려면
runtime role의 `DELETE` 권한이 필요하므로 기존 migration을 수정하지 않고 `20260826_37`을 추가했다.

## 6. 2단계: Artifact 근거 참조 결속

### 목표

GPT가 생성한 텍스트가 어느 승인 Artifact 근거를 참고했는지 안전한 별칭으로 추적한다.

### 최소 설계

- 서버가 Artifact narrative와 `evidence_json.metric_values`에서 안전한 근거 catalog를 만든다.
- 실제 Artifact ID나 query ID 대신 `artifact_narrative`, `metric_1` 같은 서버 별칭을 사용한다.
- `add_text`와 content를 변경하는 `update_text`가 `evidence_refs`를 반환한다.
- 서버는 모든 ref가 현재 session의 catalog에 존재하는지 확인한다.
- 구조 변경 operation에는 근거 ref를 강제하지 않는다.
- ref가 맞는다는 사실을 문장 의미의 완전한 진실 검증으로 과장하지 않는다.
- 별도의 두 번째 GPT 심사 호출은 추가하지 않는다.

### 영속 결정 Gate

근거를 승인 화면에서만 보여 줄지, 저장된 Report block에서도 복구할지 먼저 결정한다. Canvas와
새로고침 뒤에도 표시하려면 기존 migration을 수정하지 않고 block 근거용 신규 migration을
추가한다.

### 완료 조건

- 존재하지 않는 ref는 patch 저장 전 차단된다.
- 다른 Artifact의 ref를 섞을 수 없다.
- SQL, query ID, checksum은 모델과 클라이언트에 노출하지 않는다.
- 승인 전 Revision 변경은 0회다.
- 구조 operation과 기존 Artifact 편집 회귀가 없다.

### 구현 상태

현재 작업 tree에서 승인 patch 범위 구현과 contract/unit 검증을 완료했다. GPT turn에는 실제
Artifact ID·query ID·checksum 대신 `source_artifact`와 narrative·metric catalog만 전달한다.
`add_text`와 본문 변경 `update_text`는 근거 별칭을 요구하고 서버가 현재 catalog에 없는 ref를
거부한다. 승인 카드에는 안전한 별칭을 표시한다. Report block 영속과 Canvas 새로고침 복구는
일반 수동 편집 API까지 같은 계약으로 바꿔야 하므로 migration 없이 이번 차수에서 보류했다.

## 7. 3단계: 비저장 보고서 품질 검토

### 목표

현재 Report를 수정하지 않고 GPT가 다음 문제를 typed finding으로 제안한다.

- 중복 문장
- 지나치게 긴 요약
- 표·차트와 맞지 않는 제목
- 동일 지표의 불일치한 표현
- 근거 없는 단정 표현

사용자가 finding을 선택한 뒤에만 기존 patch 생성 흐름으로 전환한다. 검토 요청 자체는 patch,
승인 상태나 Revision을 만들지 않는다.

### 보류 이유

1단계 재수정 대화와 2단계 근거 참조가 먼저 있어야 검토 결과를 사용자가 안전하게 다듬고
적용할 수 있다.

## 8. 4단계: 여러 승인 Artifact 종합 편집

### 목표

한 Report session에 여러 승인 Artifact를 결속하고 GPT가 각 Artifact의 범위 안에서 종합 요약과
블록 구성을 제안한다.

### 필수 경계

- 모든 Artifact의 owner와 `APPROVED` 상태를 서버에서 확인한다.
- Artifact별 안전한 alias를 서버가 만든다.
- patch operation은 등록된 alias만 사용한다.
- 모든 Artifact checksum을 session binding에 포함한다.
- Artifact 하나라도 검증 실패하면 전체 요청을 fail-closed한다.
- 선택하지 않은 Artifact를 모델이 참조할 수 없다.

이 단계는 session의 단일 `artifact_id` 계약을 바꾸므로 1~3단계 이후 별도 migration과 Client
선택 UX로 진행한다.

## 9. 5단계: 문맥형 후속 작업 제안

구현 완료. 고정 quick request를 제거하고 Report title, 서버가 현재 definition에서 다시 검증한 선택
block type과 사용 가능한 operation에 맞는 제안으로 교체했다. 별도 GPT 호출을 추가하지 않고 기존
proposal 또는 review 응답에 최대 3개의 suggestion을 함께 반환한다.

- Client는 선택 block ID만 전달하고 서버가 현재 Report block에서 title·type을 다시 해석한다.
- 존재하지 않는 선택 block은 모델 호출 전에 `409 ASSISTANT_STATE_CONFLICT`로 닫는다.
- suggestion은 고유한 비어 있지 않은 문자열 최대 3개이며 block ID, Artifact alias, evidence ref가
  포함되면 응답 전에 거부한다.
- suggestion 버튼은 composer만 채우고 모델 호출·사용자 승인·Report Revision 저장을 자동 실행하지
  않는다.
- 선택 Report나 block이 바뀌면 이전 context의 suggestion을 표시하지 않는다.
- 신규 migration, 별도 Agent framework와 관리자 운영 UI 변경은 없다.

추가 모델 호출이 필요하다면 비용과 실제 사용성을 측정하기 전까지 구현하지 않는다.

## 10. 공통 안전 규칙

- 사용자 승인 전 Report Revision 저장 금지
- 모델 output을 권한·식별자·승인 근거로 사용 금지
- SQL, credential, raw model response 공개 금지
- owner·session·request ID·phase를 DB 조건에서 함께 검증
- strict schema 실패는 fail-closed
- 동일 승인 request ID의 Revision 중복 생성 금지
- 원문 대화는 공개 API와 평가 API에 반환하지 않음
- bounded history만 모델에 전달
- production mock, 질문별 하드코딩 응답, fallback Artifact 금지
- 기존 migration 수정 금지

## 11. 단계별 검증

각 단계에서 다음 기본 회귀를 반복한다.

```powershell
$env:PYTHONPATH='.;app/backend'
python -m unittest `
  tests.ai.test_report_assistant_contract `
  tests.backend.test_report_assistant_session `
  tests.backend.test_report_assistant_patch `
  tests.backend.test_report_assistant_operations `
  tests.backend.test_report_migration

python app/backend/scripts/export_openapi.py --check
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
git diff --check

Set-Location app/frontend
npm.cmd run test
npm.cmd run build
```

실제 GPT 검증은 사용자의 API 비용 승인을 받은 단일 bounded 시나리오로 별도 실행한다. fake 모델
통과를 실제 GPT E2E로 표현하지 않는다.

## 12. 구현 시작 조건

1단계 구현은 다음 조건으로 시작한다.

- 현재 dirty 문서 변경을 보존한다.
- 프론트 담당자의 mock Report 이식 파일과 충돌 여부를 먼저 확인한다.
- 관리자 운영 UI는 수정하지 않는다.
- `waiting_patch_approval`의 현재 patch request ID가 Client까지 전달되는지 확인한다.
- 모델 contract와 prompt version 변경 범위를 먼저 고정한다.
- 구현 후 실제 GPT 호출 전 사용자에게 비용 발생 범위를 알린다.

## 13. 최종 개발 순서

```text
1차: 승인 전 변경안 재수정 대화
→ 실제 GPT 1건 + 기존 Artifact + PostgreSQL + Browser 검증

2차: Artifact 근거 참조 결속
→ 잘못된 ref 거부 + 승인 카드 검증 완료, block/Canvas 영속은 별도 gate

3차: 비저장 품질 검토
→ 검토만으로 Report 무변경 검증

4차: 여러 승인 Artifact 종합
→ 모든 Artifact owner/checksum 결속 검증

5차: 기존 응답에 문맥형 후속 제안 추가
```

1~5차는 현재 작업 tree에 구현했고 contract/unit 검증을 마쳤다. 3차는 현재 서버 session과 승인
Artifact를 읽어 typed finding만 반환하며 phase, patch, Report Revision을 저장하지 않는다. 사용자가
finding을 선택하면 제안 지시가 기존 composer에 채워질 뿐 자동 적용되지 않는다. 실제 GPT·
PostgreSQL·Browser 검증 전에는 live 완료로 판정하지 않는다. 4차는 대표 근거 호환성을 유지하며
최대 다섯 승인 Artifact를 별칭·순서·checksum으로 결속하고 종합 patch를 dry-run한다. 5차는 기존
proposal·review 호출에서만 문맥형 후속 제안을 만들고 클릭 시 composer 입력만 채운다. 실제 GPT·
PostgreSQL·Browser 통합 검증 전에는 1~5차 live 완료로 판정하지 않는다.
