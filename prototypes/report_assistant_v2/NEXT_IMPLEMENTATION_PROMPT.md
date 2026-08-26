# Report Assistant V2 다음 고도화 실행 프롬프트

아래 프롬프트를 다음 구현 작업의 시작 지시로 사용한다.

---

당신은 Answervice 저장소의 Report Assistant V2를 구현하는 시니어 풀스택 엔지니어다.
저장소 루트의 `AGENTS.md`와 현행 코드 계약을 먼저 읽고, 기존 dirty 파일과 과거 migration을
수정하지 않는다.

## 목표

현재 단발성 흐름인

```text
승인 Artifact 1개 + 사용자 지시 → 제목·요약·표·차트 제목 생성 → 새 draft 저장
```

을 다음과 같은 감사 가능한 멀티턴 흐름으로 고도화한다.

```text
승인 Artifact 검증 → 보고서 초안/편집 세션 → 사용자 지시
  ├─ 기존 Artifact로 가능 → 기존 보고서 Revision CAS 저장
  └─ 새 데이터 필요 → 분석 계획 제시 → 사용자 승인
                         → Data Agent 실행 → 새 Artifact 검증
                         → 기존 보고서 lineage에 연결 → Revision CAS 저장
```

첫 vertical slice는 **“현재 Artifact에 없는 직전 월 비교 요청”** 하나다. 범용 agent framework,
별도 queue, 자동 승인, 장기 대화 메모리, 새로운 microservice는 추가하지 않는다.

## 시작 전 확인

1. `git status --short --branch`와 현재 migration head를 확인한다.
2. 다음 파일을 실제 구현 기준으로 읽는다.
   - `app/backend/app/adapters/report_assistant.py`
   - `app/backend/app/api/report_router_support.py`
   - `app/backend/app/report_contracts.py`
   - `app/backend/app/adapters/report_artifact_repository.py`
   - `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx`
   - `app/frontend/src/features/reports/useReportsPageController.jsx`
   - `prototypes/report_assistant_v2/workflow.py`
3. `VITE_REPORT_ASSISTANT_SHOWCASE=true` 화면의 승인 전·후 UX를 확인한다.
4. 운영 데이터, seed, 고정 SQL, 질문별 JSON, mock Artifact를 production 경로에 추가하지 않는다.

## 백엔드 계약

최소한 다음 상태를 서버가 영속화하고 소유하게 한다.

```text
ready
waiting_approval
running_data_agent
waiting_artifact
saving_revision
completed
failed
cancelled
```

- 모델은 `existing_artifact` 또는 `new_data`를 제안할 수 있지만 승인·권한·실행 여부를 결정하지 않는다.
- 모델 응답은 strict versioned schema로 검증한다.
- `new_data`에는 `request_id`, 사용자에게 보여 줄 질문, 필요 이유, 기간·지표 범위가 반드시 있다.
- 승인 전에는 분석 controller, DataHub, Trino를 호출하지 않는다.
- 승인 명령은 사용자·세션·request ID·현재 phase가 모두 일치할 때 한 번만 적용한다.
- 사용자 거절은 분석 없이 `ready`로 복귀하고 감사 기록을 남긴다.
- Data Agent는 기존 AnalysisController 경계를 재사용하고 새 `artifact_id`만 반환한다.
- 반환 Artifact는 owner scope, approved 상태, checksum, 승인된 request ID, query lineage를 검증한다.
- Revision 저장 요청에는 `base_revision`을 포함하고 CAS 불일치는 409로 닫는다.
- 중복 승인·중복 callback·새로고침 후 재시도는 멱등이어야 한다.
- model·DataHub·Trino·DB 실패를 성공, 빈 Artifact 또는 기존 결과로 대체하지 않는다.

기존 `report_v1.report_assistant_requests`를 확장하는 새 migration을 만들되 배포된 migration은
수정하지 않는다. 테이블을 새로 분리할 필요가 명확하지 않으면 기존 request row에 phase,
base revision, pending plan, 승인 receipt, 새 Artifact lineage를 추가하는 최소 변경부터 시작한다.

## API 최소 범위

기존 명명과 router 패턴을 따라 다음 책임만 제공한다. endpoint 수는 실제 코드와 충돌하지 않는
최소 형태로 조정해도 된다.

1. Assistant 세션 시작 또는 기존 draft 세션 조회
2. 지시 제출과 검증된 변경 제안 반환
3. 대기 분석 계획 승인·거절
4. 세션 상태 조회
5. 내부 Data Agent 결과 attach와 Revision 저장 완료

공개 응답에는 SQL, credential, raw model metadata를 노출하지 않는다. 사용자 화면에는 phase,
승인 계획, 안전한 실패 code, 새 Artifact ID와 Revision receipt만 반환한다.

## 프런트엔드

- `ReportAssistantPanel.jsx`의 현재 승인 카드를 실제 API 상태에 연결한다.
- 브라우저 로컬 state가 아니라 서버 phase를 새로고침 후 복구한다.
- `waiting_approval`에서만 승인·거절 버튼을 활성화한다.
- `running_data_agent`, `waiting_artifact`, `saving_revision`을 서로 다른 진행 receipt로 표시한다.
- 실패 시 재시도 가능한 단계와 새 요청이 필요한 단계를 구분한다.
- 승인 전에는 기존 보고서 canvas를 변경하지 않는다.
- 새 Artifact가 검증되고 Revision 저장이 성공한 뒤에만 block과 lineage를 화면에 반영한다.
- 오래된 요청 응답이 최신 선택을 덮지 않도록 request generation/cancellation 경계를 유지한다.
- showcase flag는 기본값 false를 유지하며 운영 인증 우회로 사용하지 않는다.

## 테스트

최소 회귀 항목:

1. 기존 Artifact 변경은 Data Agent 호출 없이 다음 Revision을 저장한다.
2. 새 데이터 결정은 `waiting_approval`에서 멈춘다.
3. 거절 시 Data Agent 호출이 0회이며 `ready`로 복귀한다.
4. 승인 후에만 기존 AnalysisController가 정확히 1회 호출된다.
5. 승인 request ID와 다른 Artifact callback은 거부된다.
6. 승인되지 않은 Artifact와 checksum 불일치는 거부된다.
7. 중복 승인·중복 callback이 새 실행이나 Revision을 만들지 않는다.
8. CAS 충돌은 409이며 기존 draft를 덮지 않는다.
9. 새로고침 후 서버 phase와 승인 카드가 복구된다.
10. 모델·Data Agent·저장 실패가 각각 typed error로 표시된다.

실데이터가 없는 개발 환경에서는 fake를 `tests/` 아래에 명시적으로 주입한 contract 테스트만
실행한다. 이를 live/E2E 성공이라고 부르지 않는다.

## 완료 조건

- 단일 vertical slice가 API·repository·UI까지 연결된다.
- 기존 `/reports/assistant/drafts` 호환성과 승인 보고서 불변성이 유지된다.
- prompt/schema/model release가 같은 version 경계로 갱신된다.
- OpenAPI export check, 문서화 검사, 아키텍처 검사, 관련 backend/frontend 테스트와 build가 통과한다.
- 실제 DataHub·Trino·DB를 실행하지 않았다면 마지막 보고서에 명확히 `미실행`으로 기록한다.
- 변경 파일, 검증 명령과 결과, 남은 live 위험을 요약한다.

---
