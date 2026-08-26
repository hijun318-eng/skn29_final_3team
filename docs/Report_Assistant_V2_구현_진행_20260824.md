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

## 2026-08-25 변경안 사전 승인 고도화

- 기존 Artifact 변경을 모델 응답 직후 저장하지 않고 서버 patch 적용기로 먼저 dry-run
- 검증된 patch만 `waiting_patch_approval`에 저장하고 요약·허용 연산 종류를 사용자에게 공개
- 사용자가 취소하면 Report definition/block 저장 없이 `ready`로 복귀
- 사용자가 적용하면 owner·session·patch request ID·phase를 단일 DB CAS로 claim한 뒤
  `saving_revision`에서 기존 revision 저장 경계를 재사용
- 중복 적용은 동일 patch request ID에 한해 현재 상태를 반환하고 Revision을 중복 생성하지 않음
- 새 migration `20260825_34`에서 `patch_request_id`와 승인 phase를 추가하고, 기존 Artifact
  patch의 `completed` 상태를 잘못 막던 analysis plan 제약을 수정
- Frontend Assistant 카드에서 변경 요약과 작업 종류를 확인한 뒤 `변경안 적용` 또는 `취소`
- Backend 관련 단위·계약 테스트 54개, Frontend 24개 및 production build 통과
- OpenAPI·state mapping과 repository inventory 갱신
- 실제 App DB migration 적용과 Browser live E2E는 아직 수행하지 않았으며 완료로 판정하지 않음

## 2026-08-25 실제 모델·격리 App DB API E2E

- 기존 App DB와 volume은 유지하고 `app_db_report_assistant_e2e` 격리 DB에 migration head
  `20260825_34` 적용
- `tests/e2e/prepare_report_assistant_e2e.py`가 현재 분석 응답 계약의 metric ID·결과 필드·정의·
  기준일을 포함한 승인 Artifact를 멱등 준비하도록 수정
- OpenAI strict 변환 결과에 남던 미지원 `allOf`를 제거하고 provider HTTP 400을 해소
- 실제 `report.assistant.turn` 호출이 1회 시도에서 `existing_artifact`를 반환하는 것을 확인
- 모델 제안은 `set_report_title`, `add_text` 두 연산과 `waiting_patch_approval` phase로 저장
- patch 승인 CAS에서 nullable UUID parameter의 PostgreSQL 타입 추론 실패를 명시적 UUID cast로 수정
- process 중단 뒤 `saving_revision` 세션을 같은 patch request ID로 재개하여 `completed` 도달
- 결과 Report Revision `2`, 제목 변경, 기존 Artifact block을 포함한 block 2개를 API로 재조회
- 동일 승인을 다시 호출했을 때 새 version을 만들지 않고 동일 Revision `2`를 반환
- 관련 Backend·AI 단위/계약 테스트 41개 통과 및 `git diff --check` 통과

이번 검증은 실제 OpenAI 모델과 실제 PostgreSQL transaction을 사용한 로컬 API E2E다. Trino와
DataHub는 호출하지 않았으므로 새 데이터 분석 E2E가 아니며, in-app Browser 연결이 중간에
종료되어 Revision 2의 화면 새로고침 복구 검증은 아직 남아 있다.

## 2026-08-25 Browser UI E2E 완료

- Docker Desktop 중단으로 `auth_session_store`가 503을 반환하던 로그인 장애를 확인하고 기존
  volume 삭제 없이 Docker를 재기동해 `app_postgres`, `auth_session_store` ready 복구
- 격리 E2E Artifact의 화면 근거 계약에 누락됐던 artifact/query identity, 기간, 합성 source,
  G1~G3 gate를 `tests/e2e/prepare_report_assistant_e2e.py`에만 보강
- production mock·질문별 응답·고정 SQL은 추가하지 않았으며 migration head는 `20260825_34` 유지
- 실제 로그인 화면에서 승인 Artifact가 라이브러리와 Canvas에 표시되는 것을 확인
- 실제 OpenAI가 보고서 제목 변경안을 생성하고 승인 카드에 변경 요약·작업 종류 표시
- 승인 전 제목 `8월 승인 매출 현황`, Revision 2, block 2개가 유지됨을 확인
- `변경안 적용` 뒤 CAS Revision 3, 제목 `8월 승인 매출 요약`, block 2개 및 `completed` 확인
- 보고서 목록 재진입·새로고침 뒤 같은 Revision 3·제목·block·Artifact 화면 복구 확인
- Browser console warning/error 0건, 관련 Assistant·Report API 500 0건
- 동일 patch 승인 재호출 멱등성은 완료 UI가 승인 버튼을 다시 노출하지 않아 Browser에서 재전송하지
  않았고, 기존 실제 API E2E의 동일 Revision 반환과 Backend 회귀 테스트로 검증 유지
- Backend·AI 회귀 테스트 55개, Frontend 테스트 24개, production build, 코드 문서화 검사,
  architectural invariants, `git diff --check` 통과

이 검증은 실제 OpenAI와 격리 PostgreSQL을 연결한 기존 Artifact 편집 Browser E2E다. Trino,
DataHub, semantic release가 아직 not ready이므로 `new_data` 실데이터 E2E 완료로 표현하지 않는다.

### Browser 편집 상태 후속 보강

- Artifact hydration의 자동 차트·표 높이 맞춤을 사용자 편집 history로 기록하지 않고 현재 draft와
  저장 기준선에 동일 적용해, 보고서를 열기만 해도 `저장되지 않은 변경`이 되던 문제를 수정
- Report Assistant에는 Artifact payload에 없는 표시 제목 대신 검증된 Artifact source 제목을 전달
- 최신 v4 Browser 재진입에서 `저장됨`, block 2개, Artifact 제목 표시를 확인
- 별도 대기 세션이 없는 v3에서 Artifact 라이브러리를 클릭하지 않아도 Assistant 입력 활성화 확인
- v4에 이미 존재하던 다른 `waiting_patch_approval` 변경안은 사용자 작업으로 간주해 승인·취소하지
  않고 그대로 보존
- Frontend 전체 테스트 24개와 production build 통과

## 2026-08-25 후속 고도화 4단계: Agent 품질·운영

- 새 migration `20260825_35`로 Assistant request ID당 평가 한 건을 멱등 저장하는
  `report_v1.report_assistant_evaluations` 추가
- 평가에는 model/prompt release, route, 허용 patch operation, 계약 성공, 승인 결정, 최종 phase,
  Revision 생성·중복 방지, 시도·지연·token·추정 비용·안전한 error code만 저장
- 사용자 지시는 기존 SHA-256 hash만 유지하며 SQL, raw prompt, raw model response, credential은 평가
  table과 운영 API 계약에서 제외
- 모델 transport의 실제 token usage가 있으면 기록하고, provider usage나 단가가 없으면 `null` 유지
- 평가 저장 transaction을 핵심 Report Revision transaction과 분리해 관측 장애가 성공한 Revision을
  rollback하지 않도록 best-effort 경계 적용
- 관리자 전용 기간 summary·실패 API와 owner/admin 평가 상세 API 추가. 조회 기간은 timezone 포함
  최대 31일, 실패 목록은 100건으로 제한
- 계약·patch·승인·거절·Revision·중복 방지·error code·평균/p95 latency·token·추정 비용 지표 추가.
  표본 또는 usage가 없으면 0으로 가장하지 않고 `null` 반환
- 관리자 Report 목록에 품질·비용·최근 실패 code 패널을 추가하고 analyst 화면에는 전체 사용자
  집계와 비용을 노출하지 않음
- 기존 분석 execution gate를 모델 제안 동시 실행 제한에도 재사용하고, 환경 설정 기반 모델 시도,
  시간당 요청, input/output token, 추정 비용 상한을 fail-closed로 적용
- production 응답을 고정하지 않는 deterministic 평가 시나리오 16개를 `evals`에 추가
- Backend·AI·migration·운영 지표 테스트 60개, Frontend 테스트 24개와 production build 통과

실제 OpenAI 반복 평가는 비용 발생 승인을 받지 않아 실행하지 않았다. 이번 검증은 deterministic
fake와 정적·단위 회귀 검증이며 live E2E로 표현하지 않는다. 기존 Artifact 편집 Browser E2E는
이전 단계의 실제 OpenAI+PostgreSQL 결과가 유지된다. Trino·DataHub·semantic release가 not ready라
`new_data` live E2E는 여전히 미완료다. process가 `running_data_agent` claim 직후 종료되는 경우의
완전한 exactly-once 복구 위험도 queue/outbox 없이 남아 있다.

## 2026-08-25 실구현 1~4단계 통합 재검증

- 기존 dirty 변경을 삭제하거나 다른 Agent framework로 교체하지 않고 1~4단계 흐름을 기존
  router·repository·AnalysisController·Report Revision 경계로 통합 점검
- migration `20260824_29 → 30 → 31 → 32 → 33 → 20260825_34 → 20260825_35`가
  단일 head임을 확인하고, 기존 App DB·volume을 보존한 채 격리 DB
  `app_db_report_assistant_e2e`만 head 35로 적용
- 평가 upsert가 이전 transient error를 성공 재시도 뒤 남기던 문제를 수정하고, 관리자 summary가
  임의 1,000건이 아니라 요청한 최대 31일 전체 표본을 정확한 분모로 계산하도록 수정
- 모델이 반환한 patch가 서버 dry-run에서 거부되거나 new_data 계획이 손상된 경우에도 안전한
  error code와 계약·route 관측치를 request ID 한 건에 기록하도록 보강
- 실제 입력 token·동시 실행 제한이 모델 호출 전에 차단되고, 비용 제한은 Report Revision 저장
  전에 안전 실패하는 회귀 테스트 추가
- 1~4단계 관련 Backend·AI·migration·patch 테스트 82개 통과, Frontend 24개 통과,
  production build·OpenAPI·문서화·아키텍처·repository 감사·compileall·`git diff --check` 통과
- 로컬 Python에는 `pytest`가 설치되어 있지 않아 전체 pytest suite는 미실행이며 PASS로 계산하지 않음
- 최신 Backend를 `127.0.0.1:18002`에 외부 env 값 노출 없이 재기동하고 `app_postgres`,
  `migration`, `analysis_template_registry`, `model`, `auth_session_store` ready 확인
- Browser에서 analyst 로그인 유지, 최신 Revision 7, 제목·차트·텍스트·Artifact hydration과
  새로고침 복구, console error 0건, Backend 500 0건 확인

이번 통합 재검증에서는 비용이 발생하는 새 OpenAI 호출을 실행하지 않았다. 기존 문서화된 실제
OpenAI+PostgreSQL 편집 E2E 증거는 유지되지만, 이번 실행의 Browser 검증은 저장된 Revision 복구
회귀다. `trino`, `datahub_transport`, `semantic_release`, `catalog_manifest`, `trino_schema`는
여전히 not ready이므로 `new_data` live E2E는 완료되지 않았다. 관리자 계정으로 운영 패널을 실제
화면에서 여는 검증도 사용자 비밀번호 입력 전까지 남아 있다.

## 2026-08-25 실패 복구 실제 PostgreSQL 통합 검증

- 격리 DB `app_db_report_assistant_e2e`에 기존 데이터 재적재 없이 migration head
  `20260825_36`만 적용하고 최신 Backend를 `127.0.0.1:18002`에 재기동
- 실제 analyst 인증과 PostgreSQL 실패 세션으로 retry API를 실행하던 중, 도메인
  `ReportDefinitionVersion`에 존재하지 않는 `revision` 속성을 router가 읽어 500을 반환하는 문제 발견
- CAS counter를 도메인 표시 객체에 억지로 추가하지 않고 owner 범위의 draft revision만 조회하는
  `get_draft_revision()` 저장소 경계를 추가하고, 최종 자식 세션 생성 시 기존 원자 SQL 조건을 유지
- 동일 실패 세션에 retry API를 두 번 호출해 새 `ready` 세션 하나만 생성되고 동일 ID가 반환됨을 확인
- 원본 세션의 `failed` phase·`ANALYSIS_FAILED`·완료 시각은 유지되고, 새 세션에는 기존 승인,
  `data_request_id`, 분석 계획, patch가 복사되지 않으며 Report version 개수도 변하지 않음을 확인
- 이 통합 검증에서는 모델, AnalysisController, Trino, DataHub, Report Revision 저장을 호출하지 않음
- 모델 transport·strict plan 실패를 평가에만 남기지 않고 원본 세션을 typed `failed`로 종결하며,
  Frontend가 실패 응답 직후 서버 session을 재조회해 안전한 retry 카드를 표시하도록 연결
- 관련 Backend·AI 테스트 89개, Frontend 테스트 24개, production build, 코드 문서화 검사,
  architectural invariants와 `git diff --check` 통과

Browser에서 analyst 로그인 후 연결 불가 test model route로 비용 없는 실패를 만들고
`REPORT_ASSISTANT_TURN_MODEL_FAILED` 안내, `새 세션으로 다시 시도` 버튼, 새 `ready` session 전환과
Revision 7 무변경을 확인했다. 정상 Backend로 복원한 뒤 model·App DB·migration·auth readiness도
ready다. `new_data` live E2E는 기존과 같이 Trino·DataHub release readiness가 준비될 때까지
미완료다.

## 2026-08-26 GPT 고도화 3차: 비저장 보고서 품질 검토

- 기존 서버 소유 Assistant session과 승인 Artifact 결속을 재사용하는
  `POST /reports/assistant/sessions/{assistant_request_id}/review` 추가
- 별도 `report_assistant_review` strict 모델 계약과 prompt release를 추가해 중복 문장, 긴 요약,
  표·차트 제목 불일치, 지표 표현 불일치, 근거 확인이 필요한 단정만 typed finding으로 제한
- 모델 finding의 `block_id`를 현재 Report block으로, `evidence_refs`를 현재 Artifact의 안전한
  `artifact_narrative`·`metric_n` 별칭으로 서버가 다시 검증
- 실제 Artifact ID, query ID, checksum, SQL, raw model response는 모델 검토 응답과 Client 상태에서 제외
- 검토 요청은 `ready` phase에서만 가능하고 session phase, patch request, Report definition/block,
  Revision을 저장하지 않음
- 사용자가 finding의 `이 항목 수정하기`를 누르면 제안 문구만 기존 composer에 복사하며, 기존
  메시지→typed patch→dry-run→사용자 승인 흐름을 거쳐야만 Revision 저장 가능
- 신규 DB migration 없이 기존 session·Report·Artifact read boundary만 사용하고 관리자 운영 UI는 미변경
- AI·Backend 관련 전체 회귀 테스트 100개, Frontend 전체 테스트 24개와 production build 통과

이번 검증은 fake model과 단위·계약 테스트다. 실제 GPT 비용 호출, PostgreSQL API E2E, Browser
상호작용은 실행하지 않았으므로 3차 live E2E 완료로 표현하지 않는다. Trino·DataHub와 Analysis
Agent는 이번 범위에서 호출하거나 변경하지 않았다.

## 2026-08-26 GPT 고도화 4차: 여러 승인 Artifact 종합 편집

- 기존 대표 `artifact_id` 계약을 유지하면서 요청당 최대 네 개의 추가 Artifact를 선택하는 API·UI 추가
- 신규 migration `20260826_38`로 session별 Artifact ID, 서버 별칭, 순서, 64자리 checksum을 별도
  결속하고 기존 세션의 대표 Artifact를 `source_artifact`로 backfill
- 추가 Artifact는 `source_artifact_2`~`source_artifact_5`, 근거는 `artifact_2_*` 형식의 서버
  별칭으로만 GPT에 전달하며 실제 Artifact ID·query ID·checksum은 모델 입력에서 제외
- 모든 결속 Artifact의 owner, APPROVED 상태, 분석 SUCCEEDED/PARTIAL, query lineage, 저장 checksum을
  매 요청마다 함께 재검증하고 하나라도 불일치하면 전체 요청을 fail-closed
- 모델이 선택되지 않은 Artifact 별칭이나 evidence ref를 반환하면 기존 patch dry-run 단계에서 거부
- 승인 전에는 Report definition/block/Revision을 저장하지 않고, 최종 승인 시 기존 CAS Revision
  적용기가 선택된 모든 Artifact binding을 사용
- Frontend Assistant에서 대표 근거를 고정하고 추가 근거를 체크박스로 선택하며 전체 5개로 제한
- retry 자식 세션도 원본의 검증된 다중 Artifact 결속을 그대로 복사하고 원본은 변경하지 않음
- 신규 Agent framework, AnalysisController 변경, Trino·DataHub 호출, 관리자 운영 UI 변경 없음
- AI·Backend 관련 회귀 테스트 109개, Frontend 전체 테스트 24개, production build와 정적 검사 통과

이번 검증은 deterministic fake와 contract/unit 테스트다. migration 38의 실제 PostgreSQL 적용,
실제 GPT 종합 제안, Browser 선택·승인·새로고침 E2E는 아직 실행하지 않았으므로 live 완료로
표현하지 않는다.

## 2026-08-26 GPT 고도화 5차: 문맥형 후속 작업 제안

- Frontend에 고정되어 있던 빠른 요청 세 문장을 제거하고 기존 proposal·quality review 응답이
  반환하는 최대 세 개의 문맥형 suggestion으로 교체
- 선택 block ID는 Client에서 전달하되 서버가 현재 Report definition에 실제로 존재하는지 확인하고
  검증된 title·type만 strict GPT 입력의 `selected_block`으로 전달
- 존재하지 않는 선택 block은 GPT 호출 전에 `409 ASSISTANT_STATE_CONFLICT`로 차단
- 모델 suggestion은 비어 있지 않은 고유 문장 최대 세 개로 제한하고 Report block ID, Artifact alias,
  evidence ref가 포함된 응답을 fail-closed
- suggestion을 누르면 composer 입력만 변경하고 모델 호출, 승인, patch 적용, Report Revision 저장은
  자동 실행하지 않음
- 선택 Report·block이 달라지면 이전 context의 suggestion을 숨기며 SQL, raw model response와 실제
  Artifact/query/checksum 식별자는 Client 상태에 저장하지 않음
- 별도 GPT 호출, 신규 migration, Agent framework, AnalysisController, Trino·DataHub와 관리자 운영 UI
  변경 없음
- model schema `MODEL-v1.25.0`, release `MODEL-RELEASE-v1.32.0`, turn prompt
  `PROMPT-v1.8.0`, review prompt `PROMPT-v1.2.0`으로 결속
- AI·Backend 관련 회귀 테스트 112개와 Frontend 전체 테스트 24개, production build 통과

이번 검증은 strict contract와 deterministic fake 기반이다. 실제 GPT 비용 호출, PostgreSQL migration
적용, Browser 상호작용은 실행하지 않았으므로 5차 live E2E 완료로 표현하지 않는다. 1~5차 실제
GPT·PostgreSQL·Browser 통합 검증과 2차 근거 ref의 block·Canvas 영속 여부 결정이 후속 작업이다.

## 2026-08-26 GPT 고도화 6차: Report block 근거 영속화

- 신규 migration `20260826_39`로 Report block에 최대 16개의 검증 근거 별칭을 저장
- Assistant `add_text`·본문 변경 `update_text`가 서버에서 검증한 `evidence_refs`를 최종 CAS
  Revision까지 전달하며 이동·복제·직전 Revision 복원에서도 기존 근거를 보존
- 일반 Report 생성 API가 임의 근거를 만들지 못하게 차단하고, 수동 편집은 같은 본문·같은 근거를
  보존하거나 근거를 지우는 동작만 허용
- Client는 근거 있는 본문을 직접 수정할 때 이전 근거를 자동 해제해 변경된 문장에 오래된 근거가
  남지 않도록 처리
- Report definition 응답과 저장 요청에 근거 별칭을 연결하고 Canvas·속성 패널에서 실제 Artifact
  ID·query ID·checksum 대신 안전한 사용자용 라벨로 표시
- AnalysisController, Trino, DataHub, 별도 GPT 호출, 관리자 운영 UI 변경 없음
- Backend·AI 관련 unittest 109개와 Frontend 전체 테스트 24개 통과

이번 검증은 deterministic fake와 contract/unit 테스트다. migration 39의 실제 PostgreSQL 적용,
실제 GPT patch 승인, Browser Canvas·새로고침 복구는 실행하지 않았으므로 live E2E 완료로 표현하지
않는다.

## 2026-08-26 GPT 고도화 7·8차: operation 미리보기와 선택 승인

- 서버가 검증·dry-run한 patch를 operation별 `target`, `before`, `after` 미리보기로 만들어 Assistant
  session에 저장하고 새로고침 뒤에도 같은 승인 카드를 복구
- block ID, Artifact ID, query ID, checksum과 SQL은 미리보기에서 제외하고 사용자용 제목·배치·본문만
  공개
- 승인 카드에서 각 operation을 체크해 일부만 승인할 수 있고, 선택된 operation으로 다시 server
  dry-run한 뒤에만 기존 CAS Report Revision 저장기를 호출
- operation 인덱스는 서버 patch 순서의 0-based 값이며, 범위 밖·중복·비정렬·빈 선택은 모델·DB
  mutation 전에 거부
- 기존 Client의 `operation_indexes` 없는 요청은 전체 operation 승인으로 유지
- 최초 선택을 session에 원자 저장하고 동일 patch request ID의 중복 승인은 같은 선택일 때만 멱등;
  다른 선택으로 재호출하면 `ASSISTANT_STATE_CONFLICT`
- migration 이전 완료 patch의 NULL 선택값은 기존 계약대로 전체 승인으로 해석해 중복 승인 호환 유지
- 감사용 원본 patch는 보존하고 실제 Revision에는 선택된 operation만 적용
- 신규 migration `20260826_40`으로 안전한 preview JSON과 최대 12개의 승인 operation 인덱스를 추가
- AnalysisController, Trino, DataHub, 별도 GPT 호출과 관리자 운영 UI 변경 없음
- AI·Backend 관련 unittest 116개와 Frontend 전체 테스트 24개, production build, OpenAPI,
  문서화·아키텍처·repository 감사·compileall·`git diff --check` 통과

이번 검증은 deterministic fake와 contract/unit 테스트다. migration 40의 실제 PostgreSQL 적용,
실제 GPT patch 생성, Browser 부분 승인·새로고침 복구는 실행하지 않았으므로 live E2E 완료로
표현하지 않는다.

## 2026-08-26 GPT 고도화 9차: saving_revision 안전 재개

- 새로고침으로 복구한 session이 `saving_revision`이면 기존 patch 승인 또는 분석 계획 승인 API를
  재사용해 Revision 저장만 한 번 재개
- patch 재개 시 8차에서 저장한 `approved_operation_indexes`를 그대로 전달하고 controller 중간
  경계가 선택값을 누락하던 연결 오류 수정
- Backend는 이미 승인된 session의 claim을 다시 획득하지 않고 저장된 patch·Artifact·Report version을
  재검증한 뒤 기존 CAS Revision transaction만 실행
- transaction commit 뒤 응답이 끊긴 경우 session 조회가 `completed`를 반환하므로 추가 Revision을
  만들지 않음
- Report version이 바뀌었거나 patch·Artifact 검증이 실패하면 기존 typed conflict로 중단
- GPT, AnalysisController를 다시 호출하는 별도 복구 경로, queue, worker, migration은 추가하지 않음
- 1~9차 관련 Backend·AI unittest 116개와 Frontend 전체 테스트 24개, production build 및 정적 검사 통과

## 2026-08-26 GPT 고도화 10차: 부분 승인 operation 의존성 검증

- 공통 Report patch 적용기에 typed operation 조합 검증을 추가해 모델 제안·부분 승인·재개가 같은
  정책을 사용
- 삭제할 block을 동시에 수정·이동·복제하거나 새 block의 anchor로 사용하는 조합을 승인 전에 차단
- 같은 Report 제목, 같은 text 수정, 같은 block 이동·삭제를 한 patch에서 반복하는 모호한 변경 차단
- 서로 다른 대상의 제목 변경·block 삭제처럼 독립 operation 조합은 기존대로 허용
- 충돌 조합은 DB 승인 claim과 Report Revision 저장 전에 `REPORT_ASSISTANT_PATCH_INVALID`로 종료
- 실제 block ID를 오류 응답에 포함하지 않고 Client 전용 의존성 규칙이나 신규 migration은 추가하지 않음
- 1~10차 관련 Backend·AI unittest 119개, Frontend 테스트 24개와 production build 및 정적 검사 통과

## 2026-08-26 검증보고서 결함 수정과 11차 안전 취소

- `new_data` 분석 성공 직후 최종 typed patch·preview·model trace를 `saving_revision` 전이에 함께
  고정하고, 이후 재개 경로는 저장된 patch만 사용하도록 분리했다. 따라서 재개 중 GPT와
  `AnalysisController`를 다시 호출하지 않는다.
- Report 공개 Artifact 응답과 definition block 응답에서 실제 query ID와 Artifact checksum 값을
  제거했다. Report 저장소는 브라우저 입력 대신 Artifact ID로 승인 lineage와 query ID를 다시
  조회해 저장한다.
- 비저장 품질 검토도 모델 latency·attempt·token·추정 비용을 기존 request ID 평가 레코드에
  누적하고, token·cost 제한을 모델 결과 공개 전에 적용한다. provider usage나 가격이 없으면
  `null`을 유지한다.
- `report.assistant.turn`의 내부 식별자 금지 문구를 `Never emit ...`으로 바로잡고 prompt를
  `PROMPT-v1.8.1`, release를 `MODEL-RELEASE-v1.33.0`으로 갱신했다.
- `ready`, `waiting_patch_approval`, `waiting_approval`만 취소할 수 있는 Assistant 전용 cancel API와
  Client action을 추가했다. 취소는 모델·분석·Revision을 실행하지 않으며 terminal 재호출은
  멱등이다. 실행·Artifact 대기·Revision 저장 중에는 취소 가능하다고 가장하지 않고 안내만 한다.
- operation 선택값은 공개 응답을 만들기 전에 typed contract로 재검증해 음수·중복·비정렬·범위
  초과 저장값을 fail-closed한다. 기존 migration 40은 수정하지 않았다.

현재 검증은 deterministic fake·unit/contract 범위다. migration 39·40 실제 PostgreSQL 적용과
실제 GPT·Browser 통합 E2E는 별도로 남아 있으며, Trino·DataHub `new_data` live E2E도 완료로
표현하지 않는다.

검증 결과: Report 등록을 포함한 Backend·AI unittest 136개 중 134개 통과·환경 통합 2개 skip,
Frontend 24개 전부 통과, production build·OpenAPI·문서화·아키텍처·repository 감사·compileall·
`git diff --check` 통과. Alembic head는 단일 `20260826_40`이다.

## 2026-08-26 migration 40 기준 실제 GPT·PostgreSQL·Browser 편집 E2E

- 격리 DB `app_db_report_assistant_e2e`에 Alembic 단일 head `20260826_40`을 실제 적용하고
  test 전용 승인 Artifact와 Report definition만 준비했다.
- 실제 OpenAI strict proposal은 제목 변경과 근거 기반 텍스트 블록 추가 두 operation을 반환했고,
  승인 전 Canvas는 최신 Report `v10`과 1개 block을 그대로 유지했다.
- 제목 operation을 해제하고 텍스트 추가만 승인해 `approved_operation_indexes={1}`과 새 draft
  `v11` 한 건이 저장됐다. 제목은 유지되고 근거가 결속된 텍스트 block만 추가됐다.
- Revision 저장 중 Backend 재시작 상황에서 session이 `saving_revision`을 보존했고, 같은 승인 요청을
  다시 보내자 GPT·AnalysisController 재호출 없이 고정 patch로 `completed`에 도달했다.
- 새로고침 뒤 목록과 Canvas에서 `v11`, 기존 차트, 추가 텍스트 block이 동일하게 복구됐다.
- Browser DOM에는 query ID, 64자리 checksum과 SQL이 없었고 console error도 없었다.

실제 PostgreSQL에서만 드러난 nullable bind parameter 결함 두 건도 함께 수정했다.

- Report block lineage 검증의 nullable query ID를 명시적 `text` cast로 결속해 psycopg의
  `AmbiguousParameter` 500을 제거했다.
- 평가 upsert의 nullable 예상 비용을 명시적 `numeric` cast로 결속해 평가 레코드 누락을 제거했다.
  수정 후 격리 DB에서 `existing_artifact`, `approved`, `completed`, `revision_created=true` 평가
  read-back을 확인했다. 실제 provider token 사용량과 가격 정보가 없는 필드는 `null`로 유지했다.

회귀 검증은 Backend·AI 137개 중 135개 통과·환경 통합 2개 skip, Frontend 24개 전부 통과,
production build·OpenAPI·문서화·아키텍처·repository 감사·compileall·`git diff --check` 통과다.
이번 결과는 기존 승인 Artifact 편집 E2E이며 Trino·DataHub와 Analysis Agent를 사용하는
`new_data` live E2E는 실행하지 않았다.
