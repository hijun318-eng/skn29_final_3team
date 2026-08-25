# Report Assistant V2 구현 진행 기록

기준일: 2026-08-24
대상 브랜치: `codex/report-assistant-advanced-20260824`

## 이번 구현 완료

- 기존 `report_v1.report_assistant_requests`를 재생성하지 않고 확장하는 migration 추가
- 서버 소유 phase 8종과 base revision, 승인 계획, 결과 Artifact/Revision 필드 추가
- 현재 소유자의 draft와 그 block이 참조하는 승인 Artifact를 검증한 뒤 `ready` 세션 생성
- 세션 생성 API `POST /reports/assistant/sessions` 추가
- 새로고침 복구 API `GET /reports/assistant/sessions/{assistant_request_id}` 추가
- Pydantic 응답 계약에서 데이터 실행 phase에 완전한 `analysis_plan`을 강제
- 프런트엔드 Report client에 세션 생성·복구와 phase 검증 추가
- 기존 `/reports/assistant/drafts` 호환 경로 유지

## 이번 단계에서 의도적으로 미실행

- DataHub 조회
- Trino 쿼리
- 운영 DB migration 적용
- 운영 데이터 적재
- 실제 모델 호출

따라서 이번 결과는 Report Assistant V2의 unit/contract 구현 완료이며 live 데이터 E2E 완료가 아니다.

## 단계별 구현 범위

### 2단계 완료

- Report Assistant 변경 제안용 `report_assistant_turn` strict request/response schema 추가
- 전용 `report.assistant.turn` prompt와 active model release `v1.23.0` 결속
- 모델 제안을 `existing_artifact`와 `new_data`로만 제한하고 승인·실행·SQL 출력을 거부
- 지시 제출 API `POST /reports/assistant/sessions/{assistant_request_id}/messages` 추가
- 서버가 분석 계획 request ID를 생성하고 `new_data`만 `waiting_approval`로 원자 전이
- ready phase·owner 범위·승인 Artifact를 모델 호출 전에 재검증
- 모델 실패·계획 불일치·동시 phase 충돌을 성공으로 대체하지 않고 502·409로 종료
- 프런트엔드 Report client에 지시 제출 및 응답 phase 검증 추가

### 3단계 완료

- 승인·거절 API `POST /reports/assistant/sessions/{assistant_request_id}/approval` 추가
- owner·session·request ID·phase·legacy status·`RUN_ANALYSIS` 권한을 승인 전에 검증
- 최초 승인만 claim하고 중복 승인·거절은 동일 request ID의 현재 phase를 반환
- 거절 시 분석 호출 없이 `rejected_at`을 기록하고 `ready`로 복귀
- 기존 분석 API의 execution gate·영속화·`AnalysisController` 경계를 그대로 재사용
- 서버 `data_request_id`를 분석 `RequestContext.request_id`로 고정
- 반환 Artifact를 owner·request·승인 상태·query lineage·checksum으로 재검증
- 검증된 Artifact ID·query ID·checksum을 새 migration에 저장하고 `saving_revision`으로 전이
- 분석·Artifact 검증 실패는 기존 결과로 대체하지 않고 typed `failed`로 종료
- 프런트엔드 Report client에 승인·거절 API 추가
- 보고서 block·Canvas는 변경하지 않음

### 4단계 완료

- additive migration으로 draft `revision` CAS token 추가
- 일반 draft block 저장마다 revision을 같은 transaction에서 증가
- Assistant 세션 시작 시 owner·draft·Artifact 참조와 현재 revision을 함께 고정
- `saving_revision` 세션과 기준 draft를 잠그고 최신 version·revision을 CAS 검증
- 기존 Artifact를 참조하던 block만 검증된 새 Artifact·query·analysis definition lineage로 치환
- 기존 제목·글·블록 ID·크기·배치·표시 설정을 보존한 다음 draft version 생성
- 새 version과 모든 block, Assistant `completed`·`result_revision`을 한 transaction에서 저장
- CAS 또는 lineage 충돌 시 전체 rollback 후 `REPORT_REVISION_CONFLICT` 또는
  `ARTIFACT_LINEAGE_MISMATCH`로 종료
- `saving_revision` 재호출은 AnalysisController를 다시 호출하지 않고 revision 저장만 재개
- 완료된 동일 승인은 현재 session을 반환하고 모든 실행·저장을 반복하지 않음
- 실제 ReportsPage에서 session 생성·지시·승인·거절·새로고침 복구 상태를 연결
- 서버가 `completed`를 반환하고 새 definition을 다시 조회한 뒤에만 Canvas 갱신
- 브라우저 sessionStorage 실패가 서버 저장 성공을 되돌리지 않음

### 5단계 완료

- 조회·승인 진입 시 오래 멈춘 `running_data_agent`·`waiting_artifact` 세션을 owner 범위의
  단일 UPDATE로 탐지하고 `ASSISTANT_EXECUTION_INTERRUPTED` typed failure로 종료
- stale 판정 시간은 `REPORT_ASSISTANT_STALE_SECONDS`로 설정하며 60~86400초 범위를 벗어나면
  서버가 fail closed
- CAS 저장을 안전하게 재개할 수 있는 `saving_revision`은 stale 실패 대상에서 제외
- Report Assistant 패널에 `completed`·`failed`·`cancelled` 종료 상태와 안전한 error code 표시
- 스케줄러가 비활성화된 앱 수명주기에서는 DataHub·Trino·model 분석 런타임을 eager 생성하지 않음
- 로그인 없는 로컬 showcase를 LAN `http://192.168.0.37:13000`에 실행
- 실제 backend image를 LAN `http://192.168.0.37:18000`에 실행하고 `/health` 200 확인
- 운영 DB migration·데이터 적재·DataHub·Trino·model 연결은 수행하지 않았으며 `/readiness`는
  의도대로 503 fail-closed

## V2 이후 선택적 운영 고도화

- `running_data_agent` 직후 process crash를 재실행까지 복구할 lease·outbox·worker 설계
- 운영 migration 적용 및 실제 DB transaction 통합 검증
- DataHub·Trino·model을 연결한 권한·실패·취소 시나리오 검증

## 2026-08-25 DataHub 비의존 편집 고도화

- strict `report_assistant_turn` patch에 `reposition_block` 연산 추가
- 모델은 기존 block ID, 선택적 기준 block ID, `half`·`full` 폭 의도만 반환
- 실제 grid 좌표는 계속 서버가 계산하며 원시 좌표·Artifact ID·query ID는 모델 출력에서 금지
- 기존 block의 ID·내용·Artifact lineage·query lineage·높이를 보존한 채 상대 위치와 폭만 변경
- 존재하지 않는 block과 자기 자신을 기준으로 한 순환 배치는 patch 전체를 거부
- 모델 release `MODEL-RELEASE-v1.27.0`, schema `MODEL-v1.20.0`, prompt
  `report.assistant.turn@PROMPT-v1.4.0`으로 결속
- 이 기능은 승인된 기존 보고서 block 편집이므로 DataHub·Trino 없이 unit/contract 검증 가능
- 실제 모델·App DB·Browser가 연결된 편집 검증은 별도 integration 증거가 필요하며 이번 결과를
  live E2E로 표현하지 않음

### 삭제·복제·직전 Revision 복원

- `remove_block`은 기존 block ID만 받아 대상 하나를 제거하고 마지막 남은 block 삭제는 거부
- `duplicate_block`은 새 block ID를 서버에서 생성하고 원본 내용·배치 크기·Artifact/query
  lineage를 보존한 복제본을 원본 바로 뒤에 배치
- `restore_previous_revision`은 명시적인 되돌리기 요청에서만 단독 연산으로 허용
- 직전 version의 제목·블록·방향·통화 표시를 읽되 과거 version을 수정하지 않고 최신 draft를
  CAS 확인한 다음 새 version으로 저장
- 직전 version이 없거나 owner·source revision·phase가 충돌하면 기존 revision을 변경하지 않고
  fail closed
- 새 분석 Artifact 합성 단계에서는 이전 revision 복원을 허용하지 않아 분석 결과를 버리는
  우회를 차단

## 2026-08-25 OpenAI 로컬 연결 준비

- `compose.report-assistant-stage5.yml`의 backend가 저장소 밖 model env 파일을 직접 읽도록 연결
- `REPORT_ASSISTANT_MODEL_ENV_FILE` 절대 경로가 없으면 Compose 단계에서 fail closed
- secret 원문은 저장소·문서·Compose environment 값에 복사하지 않음
- OpenAI key에 최소 `List models=Read`, `Model capabilities=Request` 권한을 적용
- `/v1/models` HTTP 200과 `gpt-5.4-mini` exact model 존재를 확인
- `/readiness`의 `model=ready` 확인
- 합성 승인 Artifact 입력으로 실제 `report.assistant` strict 계약 호출 1건 성공
- model `gpt-5.4-mini`, prompt `report.assistant`/`PROMPT-v1.0.0`, 1회 시도 확인
- 생성 문장과 secret 원문은 검증 출력·문서에 기록하지 않음
- 기존 App DB volume을 유지한 채 backend image 재빌드·기동 완료, `/health` HTTP 200
- 실행 container에서 endpoint·model·key 존재 여부만 확인했고 secret 원문은 출력하지 않음
- model env 경로 제공 시 Compose service 해석 성공, 누락 시 required-variable 오류로 거부
- 동일 backend image에서 mock 기반 readiness unittest 24개 통과
- `tests.ai.test_runtime_model_configuration`은 image에도 `pytest`가 없어 미실행

## 검증 결과

- Backend·AI 핵심 단위 테스트: 43개 통과
- 5단계 Report Assistant·migration 단위 테스트: 31개 통과
- runtime lifecycle·scheduler 회귀 테스트: Docker 이미지에서 4개 통과
- Frontend 전체 테스트: 24개 통과
- Frontend production build: 통과
- 코드 문서화 검사: 337 source files, 62 executable configs 통과
- repository integrity inventory 갱신 및 850 files 감사: 통과
- migration 소스 체인: `20260824_29 → 20260824_30 → 20260824_31 → 20260824_32 → 20260824_33` 확인
- `git diff --check`: 통과
- Alembic CLI head 확인: 현재 로컬 Python에 `alembic`이 없어 미실행
- OpenAPI export 및 전체 Backend suite: 현재 로컬 Python에 `pytest`, `sqlglot`이 없어 미실행
- Docker backend image build 및 container healthcheck: 통과
- LAN frontend 실제 브라우저 렌더링: 통과 (`/agent`, 로그인 화면 제외)
- backend readiness: 외부 의존성·운영 설정 미주입으로 503 확인(예상된 결과)

## 5단계 로컬 배포 재검증

> 2026-08-25 정정: 아래 LOCAL VERIFICATION showcase는 실제 Assistant 실행 근거가 아니며
> 현재 production source와 배포 설정에서 제거되었다. 실제 session·ReportsPage 연결은
> 인증과 외부 dependency readiness를 통과한 뒤 별도로 검증한다.

기존 13000/18000 showcase를 최신 dirty source와 실제 App DB migration까지 반영한 독립
검증 stack으로 교체해 `13001/18001`에서 실행했다.

- 기존 App DB named volume 보존
- 공식 DB role provisioning 완료
- 실제 DB Alembic head `20260824_33` 확인
- 최신 backend `/health` HTTP 200
- 최신 frontend `/agent` HTTP 200 및 브라우저 렌더링 확인
- 실제 `/readiness` 결과를 LOCAL VERIFICATION 화면에 표시
- 브라우저에서 승인 카드 진입 및 console warning/error 0건 확인

단, Trino·DataHub transport/token·semantic release·catalog manifest·model·auth session store가
준비되지 않아 readiness는 503이다. 따라서 이번 판정은 애플리케이션 로컬 배포 성공이며,
실제 모델→DataHub→SQL Guard→Trino→Artifact→Revision live E2E 완료는 아니다.

세부 증빙과 재실행 명령은
`docs/Report_Assistant_V2_5단계_로컬배포_검증보고서_20260824.md`에 기록했다.
