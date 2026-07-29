# 역할 4 — 사용자 경험·리포팅 Full-stack 작업 매뉴얼

> 문서 상태: 팀 검토용 초안  
> 작성 기준일: 2026-07-28  
> 대상 역할: R4 사용자 경험·리포팅 Full-stack 담당  
> 기준 기획서: `docs/Answervice_기획서.md`  
> 현재 확인: 기존 저장소에는 React·JavaScript·Vite 기반 fixture 화면이 있으며 backend·DB·LLM은 연결되지 않았다.

## 0. 5개 AI 공통 실행·충돌 방지 계약

### R4가 수정할 수 있는 논리 영역

- frontend app·component·route·style·test·fixture
- frontend package와 build 설정
- Report 도메인 model·service·repository·router·test
- ReportDefinition·Version·Block·Run·BlockRun·Schedule·Job 계약
- Report 실행 화면, Catalog·Operations·Audit 사용자 경험

### R4가 직접 수정하면 안 되는 영역

- 공통 OpenAPI·Pydantic·오류 코드와 FastAPI entrypoint: R3 소유
- 공통 Alembic revision chain: R3 소유
- 분석 Controller·Context·Gate·LLM·Cache·Artifact 내부 구현: R3 소유
- 원천 DDL·seed·DataHub·Trino adapter: R2 소유
- root dependency·Compose·CI·배포·worker runtime·secret: R5 소유
- 업무 정의·평가 정답·최종 수용 판정: R1 소유

### 공유 파일 단일 작성자

| 공유 대상 | 단일 작성자 | R4의 작업 방식 |
|---|---|---|
| 공통 API schema·오류 코드 | R3 | UI 요구 field와 contract change request 제출 |
| FastAPI entrypoint·router 등록 | R3 | 완성한 Report router와 등록 요청 제출 |
| Alembic revision chain | R3 | Report migration proposal과 검증 SQL 제출 |
| frontend package·공통 UI 설정 | R4 | R4만 직접 수정 |
| root dependency·Compose·CI | R5 | dependency·service 변경 요청 제출 |

### AI에 반드시 같이 제공할 입력

```text
ROLE_ID=R4
TASK_CARD_ID=R4-xx
REPOSITORY_ROOT=<절대 경로>
BASE_BRANCH=<통합 기준 branch>
BASE_SHA=<작업 시작 commit SHA>
CONTRACT_VERSION=<현재 승인 contract version>
FIXTURE_VERSION=<현재 승인 fixture version>
ALLOWED_PATHS=<이 카드에서 수정 가능한 경로>
FORBIDDEN_PATHS=<수정 금지 경로>
ACCEPTANCE_CRITERIA=<완료 조건>
EXTERNAL_ACTION_PERMISSION=<배포·외부 전송 허용 여부>
STOP_CONDITION=<중단·질문 조건>
```

한 번에 작업 카드 한 개만 AI에 준다. 시작 전에 repository root, branch, dirty worktree, `AGENTS.md`, 대상 파일, contract version을 확인한다. 허용 경로 밖 변경은 하지 않고 변경 요청으로 넘긴다.

각 사람은 `docs/markdown/collaboration/README.md`에 정해진 자기 개인 branch(`junhee`, `minji`, `seung`, `daesung`, `jaehong` 중 배정된 branch)와 자기 clone을 사용한다. 다섯 AI가 같은 working directory를 공유하지 않는다. AI는 승인 없이 stage·commit·push·merge하지 않고, 사람이 검증 후 통합한다.

### AI에 전달할 실행 프롬프트

```text
너는 ROLE_ID 담당 AI다. 기준 기획서와 이 역할 매뉴얼을 모두 읽되, 이번에는 TASK_CARD_ID 하나만 수행한다.
먼저 repository root, 적용되는 AGENTS.md, branch, BASE_SHA, dirty worktree, 선행 계약·fixture version을 읽기 전용으로 확인한다.
확인된 사실·가정·blocker와 이 카드의 입력·출력·완료 조건을 짧게 보고한 뒤 작업한다.
ALLOWED_PATHS만 수정하고 FORBIDDEN_PATHS와 다른 역할 소유 파일은 수정하지 않는다.
공통 API·router 등록·Alembic chain 변경은 직접 하지 않고 contract·router·migration proposal을 R3에 handoff한다.
기존 변경을 보존하고 승인 없는 설치·비용·배포·데이터 전송·stage·commit·push·merge를 하지 않는다.
완료 조건에 맞는 검증을 실제 실행하고, 미실행 검증은 통과로 쓰지 않는다.
마지막에는 매뉴얼의 handoff 형식으로 변경 파일, contract version, 검증, 미검증, 남은 위험을 보고한다.
```

### 병렬 통합 Gate와 handoff

| Gate | 공통 의미 | R4 완료 조건 |
|---|---|---|
| I0 기준 정렬 | 주제·backend·기술 우선순위·소유권 확정 | 화면·Report·공유 파일 경계 승인 |
| I1 Contract Freeze | metric/time·API·오류·fixture 고정 | 화면 상태·Report schema·API 예제 승인 |
| I2 Deterministic Slice | Template 경로의 전체 왕복 | mock과 실제 deterministic Chat→Report smoke |
| I3 General LLM | 일반 질문·Node 경로 | 일반 질문 상태·증거·오류 UI 검증 |
| I4 Reporting | definition/run·수동/schedule·부분 실패 | router·migration·worker 계약·Report 기능 통과 |
| I5 Release | 필수 30건·full profile·보안·복구·model 비교 | production build·접근성·실제 API 수용 통과 |

```text
TASK_CARD_ID:
BASE_SHA / RESULT_SHA:
수정 파일:
변경한 계약과 version:
실행한 검증과 결과:
실행하지 못한 검증:
mock 제한:
R3/R5가 적용할 proposal:
남은 위험:
```

## 1. 이 역할의 최종 책임

R4는 사용자가 질문하고, 실행 상태를 이해하고, 검증된 결과를 저장된 Report 정의·실행 이력으로 재사용할 수 있도록 사용자 경험과 Report 도메인을 구현한다.

최종 책임:

- Chat
- Shared Status
- Shared Evidence
- 표·차트
- Report editor
- Report run history
- Catalog
- Operations & Audit
- API client와 typed contract
- Report domain model·service·repository·API
- 수동 실행·schedule 정의·job payload
- 성공·빈 결과·차단·부분 실패 화면
- 접근성

R4는 schedule과 job의 업무 상태를 소유하지만 worker process·queue·배포는 R5가 소유한다.

### R4 작업 패키지

| 작업 패키지 | 포함 카드 | 병렬 시작 조건 | 완료 증거 |
|---|---|---|---|
| WP1 UI 기반 | R4-01~05 | R1 흐름, R3 example | mock build·component test |
| WP2 상태·근거·Chat | R4-06~15 | 상태 fixture | 상태·접근성 test |
| WP3 Report backend | R4-RPT-01~07 | R3 분석 계약 초안 | repository·router contract test |
| WP4 Report UI | R4-16~22 | WP3 fixture | editor·run·history test |
| WP5 Catalog·운영 | R4-23~27 | R2/R3 fixture | 실제 API smoke·production build |

R4가 보안 경계로 사용하면 안 되는 것:

- 메뉴 숨김
- button 비활성화
- client role
- client-side validation만으로 권한 판정

서버의 권한·Gate 결과를 화면에 반영하되 UI가 실행 허용을 판정하지 않는다.

## 2. 다른 역할과 동시에 시작하는 방법

backend를 기다리지 않고 다음 fixture로 개발한다.

| fixture | 상태 |
|---|---|
| Query 성공 | 표·차트·설명·출처 |
| G1 문맥 부족 | 재질문 |
| G2 정책 차단 | 안전한 수정 힌트 |
| G3 증적 미달 | 결과 숨김·검증 실패 |
| 빈 결과 | 정상 0건 |
| 부분 실패 | source·block별 성공/실패 |
| Report run | block 상태·snapshot |
| Catalog | 5 source ingestion 상태 |
| Audit | request trace |

R3가 제공한 OpenAPI example을 단일 기준으로 사용한다.

## 3. 착수 전에 받아야 할 입력

| 입력 | 제공자 | 없을 때 처리 |
|---|---|---|
| 사용자 흐름·문구 | R1 | 기획서 기반 초안을 만들고 검수 요청 |
| source·URN fixture | R2 | 고정 예제 사용 |
| OpenAPI·오류 코드 | R3 | UI용 필요한 field 목록을 먼저 전달 |
| 인증·배포 경계 | R5 | demo auth와 production auth를 구분 표시 |

## 4. 단계별 상세 작업

### 단계 R4-01 — 기존 frontend 현황 조사

수행:

1. 현재 route와 page를 목록화한다.
2. layout, header, sidebar, card, table, chart를 목록화한다.
3. fixture와 실제 API 호출을 구분한다.
4. 재사용 가능한 component와 특정 화면 결합 component를 구분한다.
5. JavaScript·TypeScript 상태를 확인한다.
6. package와 build 결과를 확인한다.
7. 현재 사용자 작업을 건드리지 않는다.

출력:

| component/page | 현재 용도 | 재사용 | 수정 필요 | 새 계약 |
|---|---|---|---|---|

### 단계 R4-02 — 화면 정보구조 확정

P0/P1 메뉴:

- Chat
- Reports
- Catalog
- Operations & Audit

P2 전 숨김:

- Tool Console
- 문서 RAG 관리
- ML Tool
- Customer 360

수행:

1. 사용자 role별 접근 가능 메뉴를 표시한다.
2. URL·화면 제목·breadcrumb를 정한다.
3. 기존 VOC fixture 화면과 새 분석 화면의 관계를 정한다.
4. 미확정 화면은 구현하지 않고 navigation에서 제외한다.

### 단계 R4-03 — TypeScript 점진 적용

수행:

1. 새 feature부터 `.ts/.tsx`를 사용한다.
2. R3 OpenAPI에서 공유 type을 생성하거나 동일 schema로 정의한다.
3. 기존 JSX를 일괄 변환하지 않는다.
4. 재사용하면서 수정이 필요한 component만 변환한다.
5. strictness와 path 설정은 작은 proof로 확인한다.

완료 기준:

- 새 Query·Artifact·Report 상태에 명시적 type이 있다.
- 기존 build가 깨지지 않는다.

### 단계 R4-04 — API Client 구현

기능:

- base URL 환경 변수
- JSON request
- timeout/cancellation
- safe error parsing
- auth credential 전달
- `trace_id` 보존
- polling helper

API:

```http
POST /api/v1/query-runs
GET  /api/v1/query-runs/{run_id}
GET  /api/v1/artifacts/{artifact_id}
POST /api/v1/reports
PATCH /api/v1/reports/{report_id}
POST /api/v1/reports/{report_id}/runs
GET  /api/v1/report-runs/{run_id}
GET  /api/v1/catalog/sources
GET  /api/v1/catalog/assets
GET  /api/v1/audit/requests/{request_id}
```

검증:

- 성공 JSON
- non-JSON 오류
- timeout
- 401/403
- 429
- 500
- cancellation

### 단계 R4-05 — Mock Adapter 구현

목적: 실제 backend 이전 병렬 개발.

수행:

1. API interface는 하나만 둔다.
2. mock과 실제 client가 같은 type을 반환한다.
3. 상태별 fixture를 분리한다.
4. 화면에서 `if mock` 분기를 흩뿌리지 않는다.
5. 실제 API 연결 시 adapter만 교체한다.
6. fixture version을 R3 contract version과 맞춘다.

### 단계 R4-RPT-01 — Report Domain Contract 확정

최소 객체:

```text
ReportDefinition
ReportVersion
ReportBlock
ReportRun
ReportBlockRun
ScheduleDefinition
ReportJobPayload
```

수행:

1. definition은 사용자 편집 대상, version은 승인 시점 immutable snapshot으로 분리한다.
2. block에는 query/template/artifact 참조, layout, 표시 option을 둔다.
3. run에는 실행 당시 definition version, `as_of`, timezone, Context release, policy version을 저장한다.
4. block run에는 queued/running/success/blocked/failed/cancelled와 artifact reference를 저장한다.
5. schedule은 daily·weekly·monthly, active, timezone, next run만 P0로 둔다.
6. job payload에는 실행에 필요한 ID·version만 넣고 secret이나 사용자 원문을 넣지 않는다.
7. schema 변경안을 R3 공통 계약에 제안하고 승인 version을 기록한다.

### 단계 R4-RPT-02 — Report 저장 모델·Repository 구현

수행:

1. Report 영역 model과 repository를 독립 module에 둔다.
2. definition 수정은 새 version 생성 전까지 draft로 관리한다.
3. 승인된 version은 update하지 않고 새 version을 만든다.
4. run과 block run은 과거 snapshot을 유지한다.
5. ownership·role·project scope를 모든 조회 조건에 포함한다.
6. optimistic locking 또는 version check로 동시 편집 덮어쓰기를 막는다.
7. 삭제는 참조 중인 version·run·artifact를 훼손하지 않도록 정책을 둔다.
8. repository 단위 test에 권한 오염, version 불변성, 부분 실패를 포함한다.

### 단계 R4-RPT-03 — Report API Router 구현

자기 module에 다음 router를 구현한다.

```text
definition create/get/update
version preview/approve/get
block create/update/delete/reorder
manual run/status/cancel
schedule create/update/activate/deactivate
run history/detail
```

수행:

1. R3 공통 인증·오류·trace dependency를 interface로 주입받는다.
2. 요청·응답은 승인된 공통 contract를 따른다.
3. definition과 run endpoint를 분리한다.
4. idempotency key로 manual run 중복 생성을 막는다.
5. 부분 실패를 전체 성공으로 변환하지 않는다.
6. router 단위 test와 OpenAPI example을 작성한다.
7. FastAPI 공통 entrypoint는 수정하지 않고 R3에 router 등록 요청을 제출한다.

### 단계 R4-RPT-04 — Artifact Bridge 구현

수행:

1. R3의 `execute_analysis_block` contract만 호출한다.
2. 모든 block에 동일한 `as_of`, timezone, Context release, policy version을 전달한다.
3. 실행 중 R3 status를 ReportBlockRun 상태로 매핑한다.
4. 성공한 block에는 immutable `artifact_id`를 연결한다.
5. 차단·실패·timeout·취소를 서로 다른 상태와 안전 문구로 보존한다.
6. 재실행은 새 block run을 만들고 과거 결과를 덮어쓰지 않는다.
7. R3 fake provider와 consumer contract test를 실행한다.

### 단계 R4-RPT-05 — 수동 실행·부분 실패 Orchestration

수행:

1. 승인된 ReportVersion만 실행한다.
2. run 시작 시 실행 context를 한 번 고정한다.
3. block별 job을 생성하고 상태를 수집한다.
4. 성공·차단·실패 block 수로 ReportRun의 최종 상태를 계산한다.
5. 하나의 block 실패를 전체 성공으로 표시하지 않는다.
6. retry는 실패한 block에만 새 시도로 수행한다.
7. 완료 snapshot에는 block 순서·layout·artifact·evidence를 고정한다.
8. 동일 idempotency key 중복 실행 test와 부분 실패 test를 작성한다.

### 단계 R4-RPT-06 — Schedule 정의와 Worker Handoff

수행:

1. schedule 계산 기준 timezone과 다음 실행 시각을 저장한다.
2. 실행 시점에 사용할 최신 승인 version 규칙을 명시한다.
3. R5 worker에 넘길 versioned `ReportJobPayload`를 작성한다.
4. payload schema, retry 가능 상태, idempotency key, timeout, dead-letter 조건을 정의한다.
5. worker가 반환할 accepted/running/terminal event 계약을 정의한다.
6. R5 fake worker와 producer contract test를 실행한다.

R4는 queue·worker process·배포·운영 retry를 구현하지 않는다.

### 단계 R4-RPT-07 — Migration Proposal·통합 Handoff

수행:

1. Report table·index·constraint의 migration proposal을 만든다.
2. upgrade·downgrade·기존 데이터 영향과 검증 SQL을 적는다.
3. 현재 R3 revision head를 기준으로 의존성을 선언한다.
4. R3가 선형 revision으로 등록하면 빈 DB와 기존 DB에서 검증한다.
5. router 등록 후 실제 OpenAPI에 endpoint가 한 번만 나타나는지 확인한다.
6. R5 backup·restore 대상과 보존 주기 field를 전달한다.
7. R1에 definition·run·evidence 산출물 증거를 전달한다.

### 단계 R4-06 — Shared Status 구현

상태:

```text
idle
queued
running
success
blocked
partial
failed
```

표시:

- 상태 이름
- 현재 단계
- 사용자가 할 수 있는 행동
- `trace_id`
- retry 가능 여부
- 마지막 갱신 시각

세부 단계:

- Context
- G1
- SQL generation
- G2
- Query
- G3
- Explanation
- Artifact
- Report block

주의:

- 색상만으로 상태를 구분하지 않는다.
- loading과 queued를 구분한다.
- 빈 결과를 failed로 표시하지 않는다.

### 단계 R4-07 — Shared Evidence 구현

표시 항목:

- 데이터셋 이름
- DataHub URN
- Trino catalog/schema/table
- metric
- filter
- 기간
- timezone
- `as_of`
- Context release
- policy version
- source watermark
- masking·sampling
- 부분 실패 source

interaction:

- 기본 요약
- 상세 펼치기
- Audit trace 이동
- 관리자 권한의 SQL 보기 여부는 서버 응답 기준

### 단계 R4-08 — Chat 입력 영역

기능:

1. 질문 입력
2. 전송
3. 실행 중 중복 전송 방지
4. 예시 질문
5. 후속 질문
6. G1 clarification 입력
7. 취소 또는 화면 이탈 처리

접근성:

- label
- keyboard submit
- 전송 상태 announcement
- 오류와 입력 연결

### 단계 R4-09 — Query Run 상태 연결

수행:

1. `POST /query-runs`로 run ID를 받는다.
2. run 상태를 polling한다.
3. terminal state에서 polling을 멈춘다.
4. 화면 이탈 시 cancellation 또는 polling 정리를 한다.
5. 429는 대기·재시도 안내로 표시한다.
6. source·Gate·단계별 상태를 표시한다.

test:

- 즉시 성공
- 장시간 running
- 429
- G1 blocked
- G2 blocked
- query failed
- partial
- G3 failed

### 단계 R4-10 — Chat 결과 카드

구성 순서:

1. 질문
2. 핵심 설명
3. KPI
4. 표 또는 차트
5. 조건·기간
6. Evidence
7. 부분 실패·한계
8. Report에 담기
9. trace

주의:

- 설명만 먼저 보여주고 근거를 숨기지 않는다.
- G3 실패 결과는 성공 카드로 렌더링하지 않는다.
- 결과 숫자를 client에서 다시 계산하지 않는다.

### 단계 R4-11 — 결과 Table

기능:

- column label과 type
- 정렬
- sticky header
- overflow
- 빈 결과
- 값 mask 표시
- row 상한 안내
- download는 권한과 요구가 확정될 때만

검증:

- 긴 column
- null
- 큰 숫자
- 날짜·timezone
- masked value
- 0 row
- 최대 row

### 단계 R4-12 — Chart

수행:

1. 서버의 검증된 chart spec을 받는다.
2. 허용 chart type만 렌더링한다.
3. 현재 Recharts로 가능한 유형을 먼저 검증한다.
4. 부족한 기능이 확인될 때만 ECharts 도입을 검토한다.
5. axis, unit, tooltip, legend를 표시한다.
6. 표 대체 정보를 제공한다.

금지:

- LLM 문자열을 chart code로 실행
- client가 raw 결과에서 임의 집계
- 허용되지 않은 dynamic component 실행

### 단계 R4-13 — G1 재질문 화면

표시:

- 부족한 조건
- 현재 이해한 metric·대상
- 필요한 입력
- 기존 질문과 trace

사용자는 전체 질문을 다시 작성하지 않고 필요한 조건만 보완할 수 있어야 한다.

### 단계 R4-14 — G2 정책 차단 화면

표시:

- 안전한 차단 사유
- 수정 가능한 질문 힌트
- `trace_id`

금지:

- 내부 allowlist
- source credential
- DB 원문 오류
- 우회 방법

### 단계 R4-15 — 실행·G3·부분 실패 화면

실행 실패:

- 실패 source
- retry 가능 여부
- 성공한 source 또는 block

G3 실패:

- 결과 검증 실패
- 설명·차트 숨김
- trace

부분 실패:

- 전체 상태 `partial`
- block/source별 badge
- stale 또는 마지막 성공값 사용 여부

### 단계 R4-16 — Artifact 상세

표시:

- artifact ID
- 생성 질문
- 조건
- Context·policy version
- source
- query run 상태
- 결과 snapshot
- chart
- 설명
- Report 참조 상태

권한이 없는 사용자는 원문 SQL·parameter·민감 결과를 보지 못한다.

### 단계 R4-17 — “보고서에 담기”

flow:

1. Chat artifact에서 action 선택
2. 대상 Report 선택 또는 새 Report
3. block type 선택
4. preview
5. layout 위치 확인
6. 사용자 승인
7. block 생성
8. artifact ID와 출처 유지 확인

AI가 기존 block을 자동 덮어쓰지 않는다.

### 단계 R4-18 — Report Editor

기능:

- 12-column grid
- KPI·table·chart·text block
- drag
- resize
- keyboard 대체 이동
- layout serialization
- breakpoint
- conflict 처리
- unsaved state
- preview
- version 표시

수행 순서:

1. 고정 fixture로 layout proof를 만든다.
2. serialization→reload를 검증한다.
3. keyboard 대체 조작을 구현한다.
4. artifact block을 연결한다.
5. definition save API를 연결한다.

### 단계 R4-19 — AI Assistant Preview

수행:

1. 질문 또는 artifact 선택
2. 제안 block 미리보기
3. source·filter·기간 확인
4. 사용자가 승인·취소
5. 승인 후에만 insert/replace

금지:

- 사용자 승인 없는 block 변경
- 기존 block 자동 삭제
- source 없는 제안

### 단계 R4-20 — Report Manual Run

flow:

1. definition version 확인
2. 수동 실행
3. report run ID 표시
4. block별 queued/running/success/failed
5. 공통 `as_of`
6. partial 상태
7. 완료 snapshot
8. 재실행

### 단계 R4-21 — Schedule UI

초기 범위:

- daily·weekly·monthly
- timezone 하나
- active/inactive
- 다음 실행
- 마지막 성공·실패
- 수동 재실행

제외:

- 복잡한 cron builder
- 다단 승인
- 외부 배포
- 복잡한 retry policy

### 단계 R4-22 — Report Run History

표시:

- definition version
- run ID
- 실행 `as_of`
- 시작·종료
- 전체 상태
- block별 상태
- source watermark
- snapshot

과거 run을 최신 definition으로 다시 그려 결과를 바꾸지 않는다.

### 단계 R4-23 — Catalog

source 목록:

- source 이름
- engine
- DataHub platform instance
- 최근 ingestion
- 상태
- owner
- 자산 수
- Trino catalog 상태

asset 검색:

- 이름·설명
- domain·tag·owner
- URN
- FQN
- column
- active binding 여부

P1 화면 전체 완성보다 P0에서 필요한 ingestion/API 증거를 먼저 표시한다.

### 단계 R4-24 — Operations & Audit

검색:

- request ID
- 사용자
- 기간
- 상태

trace:

```text
Context release
→ model/prompt/policy
→ Gate
→ query ID
→ artifact
→ report
```

표시 권한:

- 일반 trace metadata
- 관리자용 SQL hash
- 별도 권한의 원문 SQL·parameter·결과
- JSON export

### 단계 R4-25 — 인증·Role UI

수행:

1. 서버 세션을 단일 기준으로 사용한다.
2. 만료 시 로그인 경계로 이동한다.
3. role별 메뉴는 서버 권한 결과로 표시한다.
4. 사용자가 role을 바꾸는 UI를 만들지 않는다.
5. test impersonation을 운영 UI에 두지 않는다.

### 단계 R4-26 — 접근성

검사:

- keyboard navigation
- focus order
- visible focus
- form label
- error association
- status live region
- chart text alternative
- grid keyboard alternative
- color contrast
- responsive overflow
- motion 감소 설정

### 단계 R4-27 — Frontend Test

단위:

- status mapping
- error mapping
- Evidence formatting
- Report layout serialization

component:

- Chat success
- G1 clarification
- G2 blocked
- G3 failed
- partial
- Report insert

통합:

- mock adapter
- 실제 API test environment
- production build

회귀:

- 기존 fixture 주요 화면

## 5. 다른 역할과의 병렬 인수인계

| 필요 항목 | 제공자 | R4 작업 |
|---|---|---|
| 사용자 문구 | R1 | UI copy·상태 |
| URN·source fixture | R2 | Evidence·Catalog |
| OpenAPI·오류 | R3 | API client·types |
| auth·trace·배포 | R5 | session·audit·build |

R4가 다른 역할에 제공:

- UI가 요구하는 field 목록
- mock fixture 불일치
- API 상태 전이 문제
- 사용자 과업·접근성 결함

## 6. R4 작업 완료 체크리스트

- [ ] 기존 frontend 재사용 목록이 있다.
- [ ] 새 feature는 typed contract를 사용한다.
- [ ] mock과 실제 API adapter가 같은 interface다.
- [ ] 성공·빈 결과·G1·G2·G3·partial 화면이 있다.
- [ ] Evidence에 source·metric·filter·기간·`as_of`가 있다.
- [ ] Chat artifact를 Report에 담을 수 있다.
- [ ] Report 변경은 preview·승인 후 반영된다.
- [ ] definition과 run history가 분리된다.
- [ ] Report domain repository·router contract test가 통과한다.
- [ ] 승인 version과 과거 run snapshot이 불변이다.
- [ ] R3가 router·migration을 등록했고 중복 endpoint·revision이 없다.
- [ ] R5 worker와 job payload contract test가 통과한다.
- [ ] Catalog에서 5 source 상태를 볼 수 있다.
- [ ] Audit trace를 재구성해 볼 수 있다.
- [ ] role 변경 UI가 없다.
- [ ] keyboard·focus·chart 대체 정보가 있다.
- [ ] production build와 주요 화면 test가 통과한다.

## 7. R4 완료 보고 형식

```text
구현한 화면:
재사용한 기존 component:
추가한 typed contract:
mock/실제 API 연결 상태:
성공·오류·부분 실패 상태:
Report 왕복 결과:
Catalog·Audit 결과:
접근성 검증:
production build:
R3에 요청한 contract 변경:
남은 UI 리스크:
```

## 8. R4 병합 절차와 권장 병합 시점

R4는 UI와 Report 독립 module을 먼저 병합하고, 공통 router·migration 등록 뒤 실제 연결을 다시 병합한다. Git 절차는 `docs/markdown/collaboration/README.md`를 따른다.

### 공통 절차

1. 배정된 개인 branch에 최신 `dev`를 반영한다.
2. frontend package와 Report module 외 경로 변경이 없는지 확인한다.
3. mock·consumer contract·component·repository·build 검증을 실행한다.
4. 공통 API·FastAPI 등록·Alembic 변경은 proposal로 R3에 전달한다.
5. 사람이 staged diff를 확인한 뒤 개인 branch에 commit·push한다.
6. 관리자가 `dev` 병합 후 UI build 또는 Report contract 회귀를 실행한다.
7. R3·R5 후속 병합 뒤 최신 `dev`를 다시 반영해 실제 연결 카드를 시작한다.

### 권장 R4 병합 패키지

| 병합 | 여기까지 완료 | 선행 | 병합 직후 소비자 | 필수 검증 |
|---|---|---|---|---|
| R4-M1 / I1 | 화면 IA, typed frontend type, 상태 fixture, mock adapter | R1 문구, R3 example | R1 검수·R5 build | production build, fixture schema, 주요 component |
| R4-M2 / I2~I3 | Chat·Shared Status·Evidence·표·차트·오류 상태 | R3 deterministic API | R1·R5 | success/G1/G2/G3/empty/partial UI |
| R4-M3 / I4-A | Report domain·repository·router 독립 module, migration proposal | R3 분석 block contract | R3 등록 | repository·router consumer test, version 불변성 |
| R4-M4 / I4-B | R3 등록 API와 R5 worker를 사용한 editor·manual run·schedule·history | R3-M5, R5 worker contract | R1·R5 | Chat→Report 왕복, 중복 실행, partial snapshot |
| R4-M5 / I5 | Catalog·Audit·접근성·수용 결함 수정 | full profile | R1 수용 | 실제 API smoke, keyboard/focus/chart 대체, build |

R4-M3에는 공통 FastAPI entrypoint나 Alembic chain 수정을 포함하지 않는다. R3-M5가 병합된 뒤 R4-M4를 시작하며, 두 작업 사이에 반드시 최신 `dev`를 반영한다.

병합하지 않는 상태:

- 화면에 `if mock` 분기가 흩어져 실제 client 교체가 불가능함
- 서버 오류·부분 실패를 성공으로 표시함
- 승인된 ReportVersion이나 과거 Run snapshot을 update함
- router·migration 공통 파일을 R4가 직접 수정함
- production build 또는 핵심 consumer contract test가 실패함
