# Report Assistant V2 GPT 고도화 10~14차 구현 계획

## 1. 목적과 현재 기준선

이 문서는 Analysis Agent, Trino, DataHub 연결을 제외하고 Report Assistant V2를 추가로 고도화하는
10~14차 작업 순서와 완료 조건을 정의한다.

현재 1~9차에서 다음 흐름이 구현돼 있다.

```text
승인 Artifact와 현재 Report 선택
→ GPT strict 변경안 생성
→ 변경안 재수정 대화·품질 검토
→ operation별 변경 전후 미리보기
→ 전체 또는 일부 operation 승인
→ CAS Report Revision
→ saving_revision 중단 자동 재개
→ Canvas·새로고침 복구
```

10~14차는 위 경계를 교체하지 않는다. 새 Agent framework, queue, worker, microservice를 추가하지
않으며 분석 실행과 신규 Artifact 생성은 범위에서 제외한다.

## 2. 전체 순서

| 차수 | 작업 | 우선순위 | migration 예상 |
|---|---|---:|---|
| 10차 | 부분 승인 operation 의존성 검증 | P0 · 구현 완료 | 없음 |
| 11차 | 안전한 요청 취소와 timeout UX | P1 | 기존 상태로 부족할 때만 신규 migration |
| 12차 | 실제 GPT·PostgreSQL·Browser 통합 E2E | P0 | `39`, `40` 적용만 수행 |
| 13차 | 승인 카드 접근성·모바일·긴 본문 UI | P1 | 없음 |
| 14차 | GPT 품질 평가셋 확대와 prompt 튜닝 | P1 | 없음 |

각 차수는 이전 차수의 회귀 검증이 통과한 뒤 진행한다. 12차 전까지 fake 기반 결과를 실제 E2E로
표현하지 않는다.

## 3. 10차: 부분 승인 operation 의존성 검증

### 목표

사용자가 operation 일부만 선택했을 때 개별 operation은 유효하지만 조합 결과가 사용자의 의도나
Report 불변식을 깨뜨리는 경우를 승인 전에 차단한다.

### 구현 흐름

```text
서버 patch dry-run
→ operation이 사용하는 기존 block·anchor·Artifact 별칭 추출
→ 삭제 대상과 target·anchor 참조 충돌 검증
→ 동일 대상 중복 변경 검증
→ 선택 patch 재 dry-run
→ CAS Revision
```

### 서버 규칙

- `set_report_title`과 독립적인 block 추가는 기본적으로 독립 선택을 허용한다.
- 삭제할 block을 동시에 수정·이동·복제하지 못하게 한다.
- 삭제 대상 block을 수정·이동·복제하는 operation을 분리 승인해 모순 상태를 만들지 않는다.
- anchor block을 삭제하면서 해당 anchor 뒤 배치를 선택하는 조합을 거부한다.
- `restore_previous_revision`은 기존 계약대로 단독 operation만 허용한다.
- 모델이 의존성이나 선택 그룹을 결정하지 않는다. 서버가 typed patch만 보고 계산한다.
- 최종 선택은 기존 `_apply_existing_artifact_patch()`를 반드시 다시 통과한다.
- 잘못된 조합은 `REPORT_ASSISTANT_PATCH_INVALID` 또는 기존 state conflict 정책으로 닫는다.

현재 typed patch는 서버가 새 block ID를 생성하므로 새 block을 후속 operation이 참조할 수 없다.
따라서 별도 선택 그룹이나 migration을 만들지 않고 공통 patch 적용기에서 실제 존재하는 충돌만
검증한다.

### Frontend

- 기존 operation별 checkbox를 유지한다.
- 선택 불가능한 조합을 Client에서 중복 구현하지 않고 서버 오류를 최종 권위로 사용한다.
- 서버의 안전한 patch 오류를 기존 사용자 조치 안내로 표시한다.

### 예상 변경 파일

- `app/backend/app/report_patch.py`
- `tests/backend/test_report_assistant_patch.py`
- `tests/backend/test_report_assistant_session.py`

### 필수 테스트

1. 독립 operation 한 개만 승인 가능
2. 동일 block의 필수 결속 operation은 함께 선택
3. 삭제와 수정의 모순 조합 거부
4. 삭제된 anchor를 사용하는 배치 조합 거부
5. 잘못된 조합에서 Revision 저장 0회
6. 전체 승인 기존 동작 유지
7. 동일 선택 중복 승인 멱등 유지
8. 실제 block ID가 공개 응답에 노출되지 않음

### 완료 조건

- 모든 부분 승인이 서버 계산 의존성과 최종 dry-run을 통과한다.
- Client가 검증을 우회해도 잘못된 Revision이 생성되지 않는다.
- 질문별 규칙이나 GPT 추가 심사 호출이 없다.

## 4. 11차: 안전한 요청 취소와 timeout UX

### 목표

사용자가 더 이상 필요하지 않은 대기 요청을 Report 변경 없이 닫고, 실행 중이거나 저장 중인 요청은
실제로 중단 가능한 범위만 정확하게 안내한다.

### 취소 허용 범위

| Phase | 동작 |
|---|---|
| `ready` | session을 `cancelled`로 종료 |
| `waiting_patch_approval` | patch·승인 감사값을 보존하고 `cancelled` |
| `waiting_approval` | AnalysisController 호출 없이 `cancelled` |
| `running_data_agent` | 즉시 취소를 보장하지 않고 기존 실행 상태를 반환 |
| `waiting_artifact` | 즉시 취소를 보장하지 않고 새로고침 안내 |
| `saving_revision` | transaction 중단을 시도하지 않고 CAS 결과 확인 안내 |
| terminal phase | 기존 상태를 멱등 반환 |

### API

```text
POST /reports/assistant/sessions/{assistant_request_id}/cancel
```

요청 body는 비워 두고 URL의 서버 session ID만 사용한다. owner·phase·legacy status를 같은 DB UPDATE
조건으로 검증한다.

### 서버 규칙

- 타인 또는 미존재 session은 `404`다.
- 취소 가능한 phase만 한 transaction에서 `cancelled`로 변경한다.
- patch, request ID, model trace, 오류와 대화 감사 기록은 삭제하지 않는다.
- 취소로 모델, AnalysisController, Artifact 생성, Revision 저장을 호출하지 않는다.
- 실행 중인 외부 작업을 취소했다고 거짓말하지 않는다.
- `saving_revision`은 9차 복구 또는 최종 session 조회로 결과를 확인한다.

### Frontend

- 취소 가능한 phase에서만 `요청 취소` 버튼을 표시한다.
- 실행·저장 phase에서는 버튼 대신 `처리 결과 확인 중`과 새로고침 안내를 표시한다.
- 중복 클릭을 막고 서버 terminal 응답을 그대로 반영한다.

### 예상 변경 파일

- `app/backend/app/api/report_router.py`
- `app/backend/app/adapters/report_artifact_repository.py`
- `app/backend/app/report_contracts.py`
- `app/frontend/src/api/reportClient.ts`
- `app/frontend/src/features/reports/useReportLifecycleState.ts`
- `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx`
- `tests/backend/test_report_assistant_session.py`
- `tests/frontend/contracts.test.mjs`

### 필수 테스트

1. 승인 대기 patch 취소 후 Report 무변경
2. 새 데이터 승인 대기 취소 시 AnalysisController 0회
3. 타인 session `404`
4. 실행·저장 phase 취소 거부 또는 상태 유지
5. terminal 취소 멱등
6. 기존 감사 필드 보존
7. Frontend phase별 버튼 노출
8. 취소 후 자동 retry·자동 승인 없음

### 완료 조건

- 취소 가능한 범위와 불가능한 범위가 API·UI에서 일치한다.
- 외부 실행 취소를 지원하지 않는 현재 구조의 한계를 숨기지 않는다.

## 5. 12차: 실제 GPT·PostgreSQL·Browser 통합 E2E

### 목표

1~11차의 GPT 기반 기존 Artifact 편집을 같은 request ID와 실제 저장 결과로 검증한다. 이 단계는
기능 추가보다 배포 후보 검증이 목적이다.

### 사전 조건

- 대상은 운영·공용 DB가 아닌 격리 E2E DB다.
- 현재 DB revision과 target DB 이름을 먼저 확인한다.
- migration `20260826_39`, `20260826_40`을 순서대로 적용한다.
- 실제 OpenAI 호출은 사용자 승인 후 bounded 1~2건만 실행한다.
- 비밀번호와 API key는 외부 secret 파일 또는 secure input으로만 제공한다.

### 검증 시나리오 A: 부분 승인

```text
실제 로그인
→ 실제 GPT가 두 개 이상 operation 제안
→ 변경 전후 미리보기 확인
→ 한 operation만 선택
→ 승인 전 Report version 무변경
→ 승인 후 Revision 한 건 생성
→ 선택하지 않은 operation 미적용
→ 새로고침 뒤 동일 Revision 복구
```

### 검증 시나리오 B: 중단 복구

```text
승인된 patch session을 격리 DB에서 saving_revision 상태로 준비
→ Backend 재기동 또는 Browser 새로고침
→ 저장된 선택 operation으로 자동 재개
→ completed
→ 같은 승인 재호출
→ Revision 증가 없음
```

production test hook은 추가하지 않는다. 중단 지점 준비가 필요하면 `tests/e2e` 아래의 격리 DB 준비
도구를 사용한다.

### 증빙 항목

- assistant request ID와 patch request ID
- model·prompt release ID
- 승인 operation 인덱스
- source Report version과 결과 Revision
- 승인 전후 Report version 개수
- Browser console error와 Backend 500 발생 여부

SQL, credential, raw prompt, raw model response는 증빙에 포함하지 않는다.

### 필수 검증

- Backend·AI 관련 unittest 전체
- Frontend test와 production build
- migration 단일 head와 격리 DB current revision
- OpenAPI·문서화·아키텍처·repository integrity
- Browser 부분 승인·새로고침·중복 승인

### 완료 조건

- 실제 GPT, Backend, 격리 PostgreSQL, Browser가 같은 request ID로 연결된다.
- 이 단계가 끝나도 Trino·DataHub `new_data` live E2E 완료로 표현하지 않는다.

## 6. 13차: 승인 카드 접근성·모바일·긴 본문 UI

### 목표

operation이 많거나 본문이 길어도 사용자가 변경 내용을 읽고 키보드만으로 선택·승인할 수 있게 한다.

### 구현 항목

- 각 operation checkbox와 제목을 명시적으로 연결한다.
- 전체 선택·전체 해제와 선택 개수를 제공한다.
- 변경 전·후 긴 본문은 기본 요약 후 펼치기로 확인한다.
- `before`와 `after`를 색상만이 아니라 텍스트 label로 구분한다.
- 오류 발생 시 승인 카드와 해당 operation으로 focus를 이동한다.
- 모바일 폭에서 checkbox, 본문, 승인 버튼이 가로 overflow를 만들지 않게 한다.
- `prefers-reduced-motion`과 키보드 focus-visible을 지원한다.
- 화면 확대 200%에서도 버튼과 본문이 겹치지 않게 한다.

### 예상 변경 파일

- `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx`
- `app/frontend/src/features/reports/v2/report-builder-v2.css`
- `tests/frontend/report-builder-v2.test.mjs`

### 필수 테스트

1. 키보드만으로 operation 선택·승인
2. 전체 선택·해제
3. 빈 선택 승인 불가
4. 긴 본문 펼치기·접기
5. 360px viewport 가로 overflow 없음
6. 200% zoom에서 주요 control 접근 가능
7. dark/light theme 대비와 focus 표시
8. SQL·내부 ID가 DOM에 없음

### 완료 조건

- Desktop·mobile Browser에서 동일 승인 기능을 사용할 수 있다.
- 접근성 개선이 ReportsPage의 다른 팀원 UI를 광범위하게 변경하지 않는다.

## 7. 14차: GPT 품질 평가셋 확대와 prompt 튜닝

### 목표

기능 추가 없이 GPT 변경안의 계약 성공률, 수정 가능성, 불필요한 operation과 근거 사용 품질을
반복 측정하고 개선한다.

### 평가 시나리오

- 제목만 바꾸는 단일 작업
- 요약 축약과 근거 refs 유지
- 여러 operation 중 일부만 필요한 요청
- 현재 Report로 답할 수 없는 요청
- 존재하지 않는 block을 지칭하는 요청
- 모호한 기간·대상 요청
- 여러 Artifact의 내용을 종합하는 요청
- 변경안 재수정 후 이전 operation 제거
- 품질 검토 finding을 patch로 전환
- 악의적인 Artifact ID·SQL·승인 우회 지시

### 평가 지표

- strict contract 성공률
- 예상 route 일치율
- 허용 operation 정확도
- server dry-run 성공률
- 불필요 operation 비율
- evidence ref 유효률
- 재수정 후 사용자 지시 반영률
- 평균 모델 시도 횟수·latency·token·추정 비용

### 실행 규칙

- deterministic fake 평가는 기본 CI에서 실행한다.
- 실제 OpenAI 평가는 별도 명령과 명시적 비용 승인으로만 실행한다.
- 실제 모델 결과를 질문별 production 분기나 고정 응답으로 복사하지 않는다.
- prompt 변경 전 기준 결과를 저장하고 동일 평가셋으로 전후를 비교한다.
- 개선 기준을 충족하지 못하면 prompt release를 올리지 않는다.

### 예상 변경 파일

- `evals/report_assistant_quality_cases.json`
- `evals`의 기존 실행기
- `src/ai/prompt_registry.py`
- `src/ai/contracts/node_io.v0.1.json` — 계약 변경이 필요한 경우만
- `tests/ai/test_report_assistant_contract.py`

### 완료 조건

- fake와 실제 모델 평가 결과를 구분한다.
- prompt·model release와 평가 결과가 연결된다.
- token·비용이 없는 응답은 `null`로 유지한다.
- 보안·승인·owner·Artifact 검증을 prompt로 대체하지 않는다.

## 8. 공통 금지 사항

- Analysis Agent 또는 `AnalysisController` 변경
- Trino query 실행과 DataHub 검색
- production mock, fallback Artifact, 고정 SQL, 질문별 고정 응답
- 자동 승인 또는 사용자 승인 우회
- raw prompt·model response·SQL·credential 저장 및 공개
- 기존 migration 수정
- 관리자 운영 화면 변경
- 별도 Agent framework, queue, worker, microservice 추가
- 테스트 통과를 live E2E 성공으로 표현

## 9. 공통 검증 명령

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
python scripts/audit_repository_integrity.py
python -m compileall -q app/backend src evals tests
git diff --check

Set-Location app/frontend
npm.cmd run test
npm.cmd run build
```

실행하지 못한 검증은 PASS로 기록하지 않는다. 실제 GPT 호출, migration 적용, Browser 조작은 각각
실행 여부와 대상 환경을 별도로 기록한다.

## 10. 최종 완료 판정

```text
10차 의존성 검증
→ 11차 안전 취소
→ 12차 실제 GPT·PostgreSQL·Browser E2E
→ 13차 접근성·모바일 QA
→ 14차 평가 기반 prompt 개선
```

10~11차는 기능 완성, 12차는 실제 통합 증명, 13~14차는 사용성과 품질 안정화 단계다. 14차까지
완료해도 Analysis Agent·Trino·DataHub를 포함하는 `new_data` live E2E는 별도 남은 작업이다.

## 11. 11차 구현 결과: 안전 취소

- 구현 API: `POST /reports/assistant/sessions/{assistant_request_id}/cancel`
- 취소 가능 phase: `ready`, `waiting_patch_approval`, `waiting_approval`
- 취소 불가 phase: `running_data_agent`, `waiting_artifact`, `saving_revision`
- 완료·실패·취소 terminal session 재호출은 새 mutation 없이 현재 session을 반환한다.
- 취소 CAS는 owner, assistant request ID, phase, legacy running status를 한 UPDATE 조건으로 확인한다.
- 취소 시 모델, AnalysisController, Report Revision 호출은 모두 0회다.
- Frontend는 취소 가능한 대기 상태에만 버튼을 표시하고, 실행·저장 상태에서는 중단 불가 안내를
  표시한다. 관리자 운영 UI는 변경하지 않았다.

11차는 code/unit 기준 구현 완료다. 실제 PostgreSQL transaction과 Browser 취소 동작은 12차
통합 E2E에서 검증하며, 그 전에는 live 완료로 표시하지 않는다.
