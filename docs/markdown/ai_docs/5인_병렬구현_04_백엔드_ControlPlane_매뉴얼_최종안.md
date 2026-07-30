# 역할 4 — 백엔드 Control Plane 매뉴얼

> 문서 상태: 팀 확정용 최종안
> 작성 기준일: 2026-07-30
> 담당자: 김재홍
> 개인 브랜치: `jaehong`
> 역할 ID: `R4`
> 기준 기획서: `docs/Answervice_기획서.md`
> 통합 일정: `docs/markdown/ai_docs/5인_병렬구현_통합일정_20260729-20260903.md`
> 쉬운 용어: Gate는 통과 검사, fixture는 고정 테스트 데이터, Artifact는 검증 결과물, trace는 처리 기록을 뜻한다.

## 0. 역할 한 문장

김재홍은 인증된 요청을 승인 Context와 G1·G2·G3를 거쳐 읽기 전용으로 실행하고, 재현 가능한 Artifact·Cache·Audit·Report 실행으로 연결하는 결정론적 백엔드 제어 경로를 구현한다.

## 1. 최종 책임과 경계

### 1.1 R4 최종 책임

- FastAPI 공통 entrypoint·OpenAPI·Pydantic contract
- 인증 경계, request context, role·entitlement 확인
- 분석 Controller 상태 머신과 checkpoint
- Template Binding과 route 결정
- Context Registry·Builder
- G1 Context Gate
- G2 SQL Policy Gate와 G2′ 재검증
- R2 DataHub·Trino adapter 호출과 query timeout/cancel/status
- Result Shaper와 G3 Result Check
- Artifact·Audit·Trace
- SQL Plan Cache와 Result Cache
- application PostgreSQL model과 단일 Alembic chain
- R5 Report module 등록과 분석 실행 contract
- Report 영속 job store·worker 1개·schedule trigger·중복 실행 방지(idempotency)
- backend·worker Dockerfile, health/readiness, service test command
- 접근 정책 강제·mask/redaction 증거와 backend 보안 test

### 1.2 R4가 구현하지 않는 것

- source DDL·seed·DataHub recipe·Trino connector: R2 정승
- LLM prompt·Node·model serving: R3 윤대성
- frontend·Report UI·Report domain 내부: R5 송민지
- 루트 Compose·env·CI·release Gate: R1 박준희

## 2. 단일 작성자와 충돌 경계

| 대상 | 단일 작성자 | 다른 역할의 방식 |
|---|---|---|
| FastAPI entrypoint·공통 router 등록 | R4 김재홍 | R5는 Report router 등록 요청 제출 |
| 공통 OpenAPI·request/error/state schema | R4 김재홍 | R2/R3/R5는 contract diff 제출 |
| application DB model·Alembic chain | R4 김재홍 | R5는 migration proposal 제출 |
| Controller·Gate·Cache·Artifact·worker | R4 김재홍 | 다른 역할은 adapter/contract 소비 |
| backend·worker Dockerfile | R4 김재홍 | R1은 루트 Compose에 등록 |
| 루트 Compose·`.env.example`·CI | R1 박준희 | R4는 service fragment 제출 |
| Report domain/router 내부 | R5 송민지 | R4는 공통 entrypoint에 등록 |

R4는 R3 model server나 R2 vendor client를 중복 구현하지 않고 typed adapter를 사용한다.

## 3. AI 실행 방식

### 3.1 통합 Wave 시작 시 AI 입력

```text
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-Wx
TARGET_INTEGRATION_GATE=Ix
CHECKPOINT_GATES=<Wave 안 중간 확인 Gate>
TASK_CARD_RANGE=R4-xx~yy
CURRENT_TASK_CARD_ID=<범위 안 현재 카드>
REPOSITORY_ROOT=<절대 경로>
BASE_BRANCH=dev
BASE_SHA=<시작 SHA>
I0_DECISION_VERSION=<R1 기준 정렬 승인 버전>
CONTRACT_VERSION=<OpenAPI/state/error 계약>
DB_REVISION_HEAD=<현재 migration head>
ADAPTER_VERSION=<R2/R3 adapter 계약>
FIXTURE_VERSION=<test fixture>
ALLOWED_PATHS=<R4 허용 경로>
FORBIDDEN_PATHS=<다른 역할 소유 경로>
EXTERNAL_ACTION_PERMISSION=<설치·외부 배포·데이터 전송·secret·Git 권한>
ACCEPTANCE_CRITERIA=<완료 조건>
TEST_COMMANDS=<검증 명령>
STOP_CONDITIONS=<Gate 도달·범위 밖 변경·계약 충돌·검증 실패>
```

### 3.2 R4 AI용 최종 프롬프트

```text
너는 Answervice 프로젝트의 R4 백엔드 Control Plane 담당 AI다.
담당자는 김재홍이고 개인 브랜치는 jaehong이다.

저장소 AGENTS.md, 기획서, 이 매뉴얼, 협업 규칙, 통합 일정을 읽고
승인된 EXECUTION_BUNDLE_ID 하나의 TASK_CARD_RANGE를 번호 순서대로 수행한다.
범위 안에서는 카드 사이 별도 승인 없이 진행하고 CHECKPOINT_GATES에서는 계약·증거만 확인한다.
TARGET_INTEGRATION_GATE 또는 STOP_CONDITIONS에 도달하면 멈추며 다음 Wave 카드는 선행하지 않는다.
작업 전 branch, BASE_SHA, dirty worktree, contract/adapter/fixture version,
현재 migration head를 확인한다.
AGENTS.md·공식 WBS·기획서 충돌이 I0 decision으로 해결되지 않았으면 구현하지 않고 Blocked로 보고한다.

ALLOWED_PATHS만 수정한다. DB 원천·AI prompt/model·frontend·루트 Compose는 수정하지 않는다.
공유 FastAPI/OpenAPI/Alembic의 단일 작성자로서 다른 역할의 router·migration proposal을
계약 test 후 순차 등록한다.

Controller는 자유 ReAct loop를 사용하지 않고 고정 상태 전이를 따른다.
모든 SQL 출처는 G1과 G2를 통과하고, 실행 결과는 G3를 통과해야 설명·Artifact 성공이 가능하다.
Node 2′ 수정은 한 번만 허용하며 Cache·Template·worker도 Gate를 우회하지 않는다.
원천 DB는 read-only adapter로만 호출한다.

설치·외부 배포·secret·stage·commit·push·merge는 승인 없이 실행하지 않는다.
실행하지 않은 test는 Pass로 기록하지 않는다.
완료 시 변경 파일, 계약/migration/fixture version, 상태 전이,
실행한 검증, 미검증, R1/R2/R3/R5 handoff와 남은 위험을 보고한다.
```

### 3.3 공통 수행 순서

1. R1 공통 계약과 R2/R3/R5 interface를 확인한다.
2. 상태 전이·오류·입출력 contract test를 먼저 작성한다.
3. fake DataHub·Trino·model·Report adapter로 구현한다.
4. 정상·차단·timeout·partial fixture를 통과시킨다.
5. 실제 R2/R3 adapter를 하나씩 연결한다.
6. migration은 단일 head를 유지한다.
7. backend·worker service fragment를 R1에게 전달한다.
8. OpenAPI example과 상태 fixture를 R5에게 전달한다.

## 4. 순차 작업 카드

| 카드 | 작업 | 출력 | 완료 검증 |
|---|---|---|---|
| R4-00 | backend 경계·의존 방향 | architecture decision | 순환 의존 0건 |
| R4-01 | 공통 객체·OpenAPI·오류 | versioned contract | schema/example contract test |
| R4-02 | 인증·request context | context middleware | role·as_of·trace 누락 차단 |
| R4-03 | application DB·migration | models·Alembic head | 빈/기존 DB upgrade |
| R4-04 | Router·Template Binding | route decision | Template도 Gate 경유 |
| R4-05 | Controller 상태 머신 | transition table | 불법 전이·무한 loop 차단 |
| R4-06 | Context Registry·Builder | versioned Context Package | token·hash·URN/FQN 추적 |
| R4-07 | G1 Context Gate | decision/evidence | 모호·권한·비활성 구분 |
| R4-08 | R3 Node 호출 계약 | typed model client | invalid schema·timeout 처리 |
| R4-09 | G2 SQL Policy Gate | AST/policy decision | DDL/DML·비승인 JOIN 차단 |
| R4-10 | Node 2′·G2′ 통제 | repair counter | 수정 최대 1회 |
| R4-11 | R2 Trino 실행 통제 | query lifecycle | pass token·timeout·cancel |
| R4-12 | Result Shaper·G3 | shaped result·evidence | 범위·mask·partial·0건 분류 |
| R4-13 | Node 3·Artifact | immutable artifact | G3 실패 시 호출·저장 금지 |
| R4-14 | SQL/Result Cache | versioned cache keys | Gate 우회·권한 공유 0건 |
| R4-15 | Audit·Trace·관측 | linked trace | request→context→query→artifact |
| R4-16 | Report integration | analysis run contract | R5 router/module 등록 |
| R4-17 | Worker·schedule runtime | 영속 job·worker·중복 실행 방지 | retry·중복·실패 격리; 외부 queue는 필요할 때만 |
| R4-18 | 권한·mask·redaction | enforcement evidence | 원문 PII·secret 노출 0건 |
| R4-19 | retention·backup/restore hook | 보존 job·백업/복구 절차 | 삭제·복구·RPO/RTO 측정 가능 |
| R4-20 | health·Dockerfile·회귀 | service fragment | R1 profile smoke 가능 |
| R4-21 | Release backend 동결 | API/migration/policy manifest | 필수 30건 backend 회귀 |

## 5. 결정론적 실행 상세

### 5.1 공통 요청 Context

```text
request_id
trace_id
conversation_id
user_id
role
entitlement_hash
route_type
as_of
timezone
time_policy_version
contract_version
context_release
policy_version
template_id 또는 sql_plan_cache_key
sql_generation_model_version
sql_policy_version
g1_result
g2_result
query_execution_id 또는 result_cache_key
g3_result
artifact_id
```

인증되지 않은 role, 누락된 `as_of`, 잘못된 contract version은 모델 호출 전에 차단한다.

보고서 요청에는 `report_definition_version`, `report_plan_id`, `report_run_id`를 더한다. 아직 만들어지지 않은 ID는 미리 채우지 않고, 해당 단계가 끝날 때 같은 `request_id` trace에 연결한다.

초기 role:

```text
hotel_analyst
report_admin
data_admin
```

공통 오류:

```text
CONTEXT_INCOMPLETE
ACCESS_DENIED
SQL_POLICY_BLOCKED
QUERY_SOURCE_FAILED
RESULT_EVIDENCE_MISSING
PARTIAL_FAILURE
INSUFFICIENT_EVIDENCE
RATE_LIMITED
INTERNAL_ERROR
```

오류 응답에는 DB 원문 오류, stack trace, credential, 내부 allowlist, 민감 SQL parameter를 포함하지 않는다.

### 5.2 상태 머신

```text
RECEIVED
ROUTED
CONTEXT_BUILT
G1_PASSED / G1_FAILED
SQL_SELECTED
G2_PASSED / G2_REPAIRABLE / G2_FAILED
RESULT_CACHE_CHECKED
RESULT_CACHE_HIT / RESULT_CACHE_MISS
QUERY_RUNNING
QUERY_SUCCEEDED / QUERY_PARTIAL / QUERY_FAILED
SHAPED
G3_PASSED / G3_FAILED
EXPLAINED
ARTIFACT_SAVED
```

필수 불변식:

- G1 통과 전 SQL 선택 금지
- G2 통과 전 실행·Result Cache 사용 금지
- repair count는 최대 1
- Result Cache miss에서만 Trino 실행
- Result Cache hit도 권한 범위(entitlement)와 G3 재검증
- G3 통과 전 Node 3 호출과 성공 Artifact 금지
- 부분 실패를 전체 성공으로 전이 금지
- timeout·cancel 뒤 query terminal state 확인
- 한 요청의 LLM 호출은 최대 4회이며 데모 동시 실행은 2건으로 제한
- 동시 실행 2건을 넘으면 대기시키거나 `429 RATE_LIMITED` 반환

### 5.3 Context Builder와 G1

Context Builder:

1. R2 DataHub 후보와 승인된 업무 정책을 병렬 조회한다.
2. 권한 없는 asset을 model 입력 전에 제거한다.
3. metric, time, dimension history, JOIN, selected columns, examples 순으로 구성한다.
4. `context_release`, policy/time version, entitlement hash, URN/FQN, token count, hash를 기록한다.
5. 승인된 Context release는 수정하지 않는다. 변경이 필요하면 새 version을 만들고 approver·published_at·hash·rollback target을 기록한다.
6. 초기 상한은 최대 8개 dataset, 60개 column, `min(6,000 tokens, 모델 유효 context의 25%)`다.
7. token 한도 초과 시 권한·시간·JOIN 정책은 제거하지 않는다. asset 후보를 줄이거나 사용자에게 범위를 다시 묻는다.

G1:

- 질문에 필요한 metric·기간·대상 존재
- role·entitlement·asset·column 허용
- Context·policy·time version 활성
- Template 활성과 parameter 완전성
- 모호성은 최소 재질문, 권한 거부는 안전 종료

### 5.4 SQL 출처와 G2

SQL 선택 순서:

1. 승인 Template SQL
2. 승인 SQL Plan Cache
3. R3 Node 2 생성 SQL

모든 출처에 동일한 G2를 적용한다.

G2 검사:

- 단일 statement와 parse 가능한 AST
- SELECT/read-only
- Context의 catalog/schema/table/column allowlist
- 승인 JOIN과 cardinality·temporal condition
- parameter binding과 시간 함수 금지
- DDL·DML·procedure·passthrough query·외부 함수·`system` catalog 차단
- hard LIMIT·resource policy
- 실행 전 Trino `EXPLAIN (TYPE VALIDATE|IO)` 검사
- 내부 오류를 정규화한 안전 코드

`G2_REPAIRABLE`만 R3 Node 2′에 전달하고 G2′ 재실패 시 종료한다.

### 5.5 실행·Shaper·G3

R2 adapter 호출 전 G2 decision ID와 SQL hash를 묶는다.

Result Shaper:

- row·column·cell·chart 표시 상한
- 단위·null·빈 결과 표준화
- raw·shaped checksum
- mask·sampling·partial source 정보

G3:

- result schema와 예상 schema 일치
- row filter·mask·sampling 증적
- 정상 0건과 의심 0건 구분
- 범위·이상치·부분 실패
- 조건부 checksum

G3 실패 시 설명을 만들지 않고 증적 부족 상태와 trace ID만 반환한다.

### 5.6 Cache

SQL Plan Cache key:

```text
normalized_question + context_release + policy_version + authz_scope
```

Result Cache key:

```text
sql_hash + entitlement_hash + as_of + source_watermark_set + row_filter/mask
```

Template·SQL Plan Cache 경로도 G1·G2를 통과한다. Result Cache는 G1·G2 뒤에 확인하며, hit에서도 사용자 권한 범위와 G3를 다시 확인한다. role·policy·`as_of`·watermark·row filter·mask가 바뀌면 공유하지 않는다.

### 5.7 Artifact·Report·Worker

Artifact에 최소한 다음을 연결한다.

```text
artifact_id, request_id, normalized_question, context_release,
policy/model/prompt version, query_id, source_urns, filters, as_of,
source_watermarks, result_schema, result_snapshot, chart_spec,
explanation, gate_evidence, status, created_at
```

Report 연계:

- R5가 Report domain/router와 migration proposal을 제공한다.
- R4가 공통 router와 Alembic chain에 등록한다.
- Report block은 `artifact_id` 또는 승인 analysis request를 참조한다.
- Definition version과 Run을 분리한다.

Worker:

- manual과 schedule이 같은 실행 경로를 사용한다.
- 영속 job store와 worker 1개로 시작한다.
- 같은 요청을 여러 번 받아도 한 번만 처리하기 위한 idempotency key 없이 비동기 job을 받지 않는다.
- attempt·retry·실패 격리(dead-letter와 같은 역할)·cancel을 기록한다.
- 외부 queue는 동시 실행·재시도 병목이 실제로 확인될 때만 분리한다.
- 같은 job 재전달로 중복 Artifact가 생기지 않게 한다.
- 스케줄 시작 시 하나의 `as_of`를 모든 block에 고정한다.
- block 실패를 전체 성공으로 저장하지 않는다.

### 5.8 Retention·Backup·Restore

- R4는 application DB, Artifact, Audit, Report Definition/Run의 보존·삭제 job과 백업·복구 hook을 구현한다.
- R2는 합성 source를 DDL·seed로 재생성하는 절차와 DataHub·Trino 설정 backup 입력을 제공한다.
- R1은 Compose profile에서 backup·restore를 실행하고 실제 RPO/RTO를 측정한다.
- 삭제·mask·retention 변경은 role·policy version과 audit를 남긴다.
- backup에는 secret을 포함하지 않고 checksum·schema version·migration head를 기록한다.
- backup은 암호화하고 암호화 key는 backup 파일과 다른 위치·권한으로 관리한다.
- restore 후 request→artifact→report trace와 대표 result checksum을 검증한다.

## 6. 보안·관측·장애

적용 순서:

1. API 인증·role
2. Context asset 선필터
3. G1
4. G2
5. Trino·source read-only
6. row filter·column mask
7. result redaction
8. UI 제한

로그 금지:

- credential·token
- 직접 식별자 원문
- 민감 SQL parameter
- stack trace와 내부 allowlist

외부 model endpoint에는 승인된 질문, Context Package와 꼭 필요한 최소 metadata만 전달한다. 실제 고객 원문, credential, 민감 parameter와 불필요한 sample value는 보내지 않는다. 별도 데이터 전송 승인이 있는 경우에만 합성·마스킹 여부와 전송 범위를 audit에 남긴다.

OpenTelemetry trace·metric·log로 `request → context → model → Trino/cache → artifact → report`를 연결한다. 필수 Gate checkpoint는 먼저 저장하고, 세부 관측 로그는 나중에 비동기로 기록할 수 있다.

장애 fixture:

- DataHub 검색 지연·없음
- Trino source timeout·partial
- model timeout·invalid JSON
- worker restart·중복 전달
- DB migration mismatch
- Cache stale watermark
- Report block 일부 실패

## 7. I5 이후 후속 단계

아래 작업은 현재 I5 완료 조건이 아니다. I5 이후 R1이 별도 실행 묶음을 발행할 때 시작한다.

| 후속 ID | R4 책임 |
|---|---|
| F-01 MCP Tool Registry | Tool I/O·권한·timeout·오류·감사 계약과 호출 Gate |
| F-02 문서 RAG | 문서별 권한 확인, 인용 trace, SQL 근거와 문서 근거 분리 |
| F-03 ML-as-a-Tool | model·feature version 확인, Tool Gate, 예측 결과 trace |
| F-04 고객 360 | 고객 scope 고정, role·row filter·column mask·감사 강제 |

## 8. 인수인계

| 받는 역할 | R4 전달물 |
|---|---|
| R1 박준희 | backend/worker Dockerfile, service fragment, env·health, migration head, test command |
| R2 정승 | adapter 오류·필요 metadata·query lifecycle 변경 요청 |
| R3 윤대성 | Node I/O, 정규화 G2 오류, timeout·retry, model trace 요구 |
| R5 송민지 | OpenAPI examples, 화면 상태·오류, Artifact·Report contract, mock server |

```text
작업 카드:
contract/adapter/fixture version:
migration head:
변경 파일:
상태 전이:
실행한 검증:
negative fixture:
OpenAPI/consumer handoff:
미실행·남은 위험:
```

## 9. 병합 패키지

| 패키지 | 완료 범위 | 소비자 |
|---|---|---|
| R4-M1 | OpenAPI·context·DB·Controller skeleton | R1·R3·R5 |
| R4-M2 | Context·G1·G2·Trino·G3·Artifact | 전 역할 |
| R4-M3 | Node·Cache·Audit·실제 adapter | R1·R3·R5 |
| R4-M4 | Report 등록·worker·schedule·권한 | R1·R5 |
| R4-M5 | retention·backup hook·health·회귀·release manifest | R1 |

R5 Report migration proposal은 먼저 독립 module로 병합하고, R4가 최신 `dev`에서 migration head와 router 등록을 별도 작은 패키지로 처리한다.

## 10. 최종 체크리스트

- [ ] FastAPI/OpenAPI/state/error contract가 versioned다.
- [ ] Controller가 고정 상태 전이이며 자유 Tool loop가 없다.
- [ ] 모든 SQL 출처가 G1·G2를 통과한다.
- [ ] DDL·DML·procedure·passthrough·`system` catalog가 차단되고 실행 전 `EXPLAIN`이 통과한다.
- [ ] Node 2′ 수정은 최대 1회다.
- [ ] timeout·cancel 뒤 query terminal state를 확인한다.
- [ ] G3 실패 후 설명·성공 Artifact가 생성되지 않는다.
- [ ] Cache hit가 Gate·권한·watermark를 우회하지 않는다.
- [ ] 기획서 §7.5의 필수 ID와 request→context→model/policy→query/cache→artifact→report trace가 연결된다.
- [ ] Report router와 migration이 단일 chain에 등록된다.
- [ ] 영속 job·worker의 중복·retry·실패 격리·부분 실패 test가 통과한다.
- [ ] read-only·mask·redaction negative test가 통과한다.
- [ ] 암호화 backup·분리 key·restore hook과 실제 RPO/RTO가 R1 통합 시험에서 재현된다.
- [ ] backend·worker Dockerfile과 health가 R1 Compose에서 재현된다.
