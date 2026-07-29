# 역할 5 — Platform·ModelOps·보안 QA 작업 매뉴얼

> 문서 상태: 팀 검토용 초안  
> 작성 기준일: 2026-07-28  
> 대상 역할: R5 Platform·ModelOps·보안 QA 담당  
> 기준 기획서: `docs/Answervice_기획서.md`  
> 주의: 외부 시스템 변경, RunPod 비용 발생, secret 등록, 배포는 사용자·팀의 명시적 승인 후 수행한다.

## 0. 5개 AI 공통 실행·충돌 방지 계약

### R5가 수정할 수 있는 논리 영역

- root dependency lock·Compose·`.env.example`·CI
- deploy·orchestration·health·observability·backup·restore
- worker runtime·queue·schedule 실행 환경
- `access-policy.yaml`과 실제 보안 강제 설정
- RunPod·vLLM·checkpoint·adapter serving·비용·성능 증거
- 독립 보안·장애·복구·system test와 release evidence

### R5가 직접 수정하면 안 되는 영역

- 업무 metric·기간 정책·평가 정답·수용 판정: R1 소유
- 원천 DDL·seed·DataHub recipe·Trino catalog 내용과 adapter: R2 소유
- 공통 API·Controller·Gate·LLM prompt·학습 로직: R3 소유
- Report domain·API 내부 구현과 frontend: R4 소유

### 공유 파일 단일 작성자

| 공유 대상 | 단일 작성자 | 다른 역할의 변경 방법 |
|---|---|---|
| root dependency·lockfile | R5 | 필요 package·version·이유·검증 명령 제출 |
| Compose·`.env.example`·CI | R5 | service/config 변경 요청 제출 |
| 공통 OpenAPI·FastAPI entrypoint·Alembic chain | R3 | R3에 contract/router/migration proposal 제출 |
| frontend package | R4 | R4에 dependency 요청 제출 |
| source recipe·Trino catalog | R2 | R2에 runtime 요구 조건 전달 |

### AI에 반드시 같이 제공할 입력

```text
ROLE_ID=R5
TASK_CARD_ID=R5-xx
REPOSITORY_ROOT=<절대 경로>
BASE_BRANCH=<통합 기준 branch>
BASE_SHA=<작업 시작 commit SHA>
CONTRACT_VERSION=<현재 승인 contract version>
FIXTURE_VERSION=<현재 승인 fixture version>
ALLOWED_PATHS=<이 카드에서 수정 가능한 경로>
FORBIDDEN_PATHS=<수정 금지 경로>
ACCEPTANCE_CRITERIA=<완료 조건>
EXTERNAL_ACTION_PERMISSION=<비용·배포·데이터 전송 허용 여부>
COST_LIMIT=<승인된 경우에만 한도>
STOP_CONDITION=<Pod·job·test 종료 조건>
```

한 번에 작업 카드 한 개만 AI에 준다. 시작 전에 repository root, branch, dirty worktree, `AGENTS.md`, 대상 환경과 비용 권한을 확인한다. 비용·외부 변경 권한이 없으면 manifest·runbook·dry-run까지만 수행한다.

각 사람은 `docs/markdown/collaboration/README.md`에 정해진 자기 개인 branch(`junhee`, `minji`, `seung`, `daesung`, `jaehong` 중 배정된 branch)와 자기 clone을 사용한다. 다섯 AI가 같은 working directory를 공유하지 않는다. AI는 승인 없이 stage·commit·push·merge하지 않고, 사람이 검증 후 통합한다.

### AI에 전달할 실행 프롬프트

```text
너는 ROLE_ID 담당 AI다. 기준 기획서와 이 역할 매뉴얼을 모두 읽되, 이번에는 TASK_CARD_ID 하나만 수행한다.
먼저 repository root, 적용되는 AGENTS.md, branch, BASE_SHA, dirty worktree, 선행 계약·fixture version과 외부 권한을 읽기 전용으로 확인한다.
확인된 사실·가정·blocker와 이 카드의 입력·출력·완료 조건을 짧게 보고한 뒤 작업한다.
ALLOWED_PATHS만 수정하고 FORBIDDEN_PATHS와 다른 역할 소유 파일은 수정하지 않는다.
root dependency·Compose·CI의 단일 작성자로서 변경 요청의 version·보안·재현성 영향을 검토한다.
기존 변경을 보존하고 승인 없는 설치·비용·배포·데이터 전송·stage·commit·push·merge를 하지 않는다.
비용 작업은 COST_LIMIT과 STOP_CONDITION이 없으면 dry-run까지만 수행한다.
완료 조건에 맞는 검증을 실제 실행하고, 미실행 검증은 통과로 쓰지 않는다.
마지막에는 매뉴얼의 handoff 형식으로 변경 파일, environment version, 검증, 비용, rollback, 남은 위험을 보고한다.
```

### 병렬 통합 Gate와 handoff

| Gate | 공통 의미 | R5 완료 조건 |
|---|---|---|
| I0 기준 정렬 | 주제·backend·기술 우선순위·소유권 확정 | 자원·version·profile 후보와 비용 권한 기록 |
| I1 Contract Freeze | metric/time·API·오류·fixture 고정 | health·access·job event·CI 계약 승인 |
| I2 Deterministic Slice | Template 경로의 전체 왕복 | 5 catalog와 deterministic smoke·trace 통과 |
| I3 General LLM | 일반 질문·Node 경로 | model serving·장애·보안·성능 기준선 확보 |
| I4 Reporting | definition/run·수동/schedule·부분 실패 | worker·retention·backup·부분 실패 검증 |
| I5 Release | 필수 30건·full profile·보안·복구·model 비교 | 독립 시험·scan·runbook·release evidence 제출 |

```text
TASK_CARD_ID:
BASE_SHA / RESULT_SHA:
수정 파일:
version·image·config:
실행한 검증과 결과:
실행하지 못한 검증:
외부 비용·자원 사용:
defect와 재현 방법:
rollback:
남은 위험:
```

## 1. 이 역할의 최종 책임

R5는 전체 환경의 재현성, 실행 경계의 실제 보안 강제, 장애·복구, 수용 시험, release 근거를 책임진다.

최종 책임:

- full/dev/split-host profile
- DB 5개·DataHub·Trino·앱 기동
- 고정 version·image·driver
- health·readiness
- secret 관리
- RunPod·vLLM
- worker runtime·queue·schedule 실행
- OpenTelemetry
- CI
- 보안 negative test
- source 장애·부분 실패 test
- 성능·자원 측정
- backup·restore
- SBOM·SCA·image scan
- release 판정과 runbook

R5는 R2·R3가 작성한 안전 정책을 그대로 신뢰하지 않고 독립적인 negative test를 수행한다.

### R5 작업 패키지

| 작업 패키지 | 포함 카드 | 병렬 시작 조건 | 완료 증거 |
|---|---|---|---|
| WP1 실행 기반 | R5-01~10 | R2 version 후보 | profile·health·5 source smoke |
| WP2 접근 통제 | R5-11~13 | R1 role, R2 column 정책 | negative test·secret scan |
| WP3 ModelOps | R5-14~16 | R3 model interface | serving·trace·비용 비교표 |
| WP4 CI·독립 QA | R5-17~22 | 각 역할 test entrypoint | CI·장애·재현성·성능 결과 |
| WP5 운영·Release | R5-23~29 | 통합 profile | 보존·backup·restore·release evidence |

## 2. 다른 역할과 동시에 시작하는 방법

실제 서비스가 없어도 다음 순서로 병렬 작업한다.

1. 빈 service health contract를 정한다.
2. R2의 대표 table 한 개로 DB·connector를 검증한다.
3. R3의 fake API·fake model adapter로 trace·CI를 검증한다.
4. R4의 production build를 배포 fixture로 검증한다.
5. 실제 component가 들어올 때 같은 health·test 경로로 교체한다.

## 3. 착수 전에 받아야 할 입력

| 입력 | 제공자 | 없을 때 병렬 작업 |
|---|---|---|
| DB 후보 version·recipe·catalog | R2 | engine별 최소 connector spike |
| API health·Gate test entrypoint | R3 | 공통 health·trace contract부터 작성 |
| frontend build 명령 | R4 | 현재 package 기준 build 확인 |
| 사용자 role·수용 30건 | R1 | 보안 fixture·test harness부터 작성 |

## 4. 단계별 상세 작업

### 단계 R5-01 — 실행 자원 조사

수행:

1. 개발 PC 또는 server의 CPU·RAM·disk를 기록한다.
2. Docker Desktop 또는 container runtime 제한을 기록한다.
3. 사용 가능한 port와 충돌을 확인한다.
4. GPU 사용 여부와 RunPod 권한을 확인한다.
5. 외부 network·firewall 조건을 확인한다.
6. 저장 공간과 backup 위치를 확인한다.

출력:

| 자원 | 현재값 | 최소 요구 | 위험 | 대응 |
|---|---:|---:|---|---|

### 단계 R5-02 — Profile 정의

Profile:

| profile | 목적 | 포함 범위 |
|---|---|---|
| dev | 일상 개발 | 필요한 source와 fake service 중심 |
| full | 최종 수용 | 5 DB, DataHub, Trino, API, UI, model |
| split-host | full 자원 부족 대응 | DataHub/Trino 또는 model 분리 |

원칙:

- dev profile 결과를 full 수용 결과로 사용하지 않는다.
- service가 줄어든 경우 화면과 trace에 명시한다.
- profile별 config·port·resource limit을 기록한다.

### 단계 R5-03 — Version·Image 고정

대상:

- PostgreSQL
- MySQL
- SQL Server
- ClickHouse
- DataHub Core
- Trino
- Python
- FastAPI
- PostgreSQL driver
- SQLGlot
- Node.js
- React·Vite
- vLLM
- model checkpoint

수행:

1. 기획서 후보를 목록화한다.
2. 실제 호환 가능한 version을 실행한다.
3. image tag만 쓰지 않고 digest 또는 lockfile을 기록한다.
4. connector driver 조건을 기록한다.
5. 실패 조합과 되돌림을 기록한다.

### 단계 R5-04 — Container·Service 구성

서비스:

- DB 5개
- DataHub dependencies와 GMS/UI
- Trino
- application PostgreSQL
- API
- frontend
- worker
- observability component

수행:

1. service 이름과 network를 정한다.
2. volume을 구분한다.
3. secret을 image에 넣지 않는다.
4. resource limit을 설정한다.
5. health check를 작성한다.
6. 시작 순서에 의존하지 않고 readiness로 대기한다.
7. 재기동과 volume 보존을 확인한다.

### 단계 R5-05 — 환경 변수·Secret 관리

수행:

1. `.env.example`에는 이름과 설명만 둔다.
2. 실제 credential은 commit하지 않는다.
3. DB·DataHub·Trino·RunPod secret을 분리한다.
4. log와 error에 secret이 없는지 검사한다.
5. frontend 환경 변수에 server secret을 넣지 않는다.
6. key rotation 절차를 작성한다.

negative scan:

- staged secret
- API key pattern
- password
- private key
- connection URL credential

### 단계 R5-06 — Health·Readiness

component별:

- process alive
- dependency ready
- DB connection
- DataHub GMS/Search
- Trino coordinator
- catalog
- API DB
- model endpoint
- worker
- frontend asset

수행:

1. liveness와 readiness를 분리한다.
2. dependency 실패를 health에 표시한다.
3. source별 상태를 제공한다.
4. startup timeout을 설정한다.
5. 자동 smoke script에서 확인한다.

### 단계 R5-07 — 5개 DB 기동 검증

R2와 함께:

1. 빈 volume 기동
2. DDL
3. seed
4. row count
5. 재기동
6. 동일 결과
7. read-only account
8. write 차단

R5는 R2의 개발 account가 아니라 서비스 query account로 test한다.

### 단계 R5-08 — DataHub 통합 검증

수행:

1. DataHub full component health를 확인한다.
2. source별 ingestion recipe를 실행한다.
3. 실행 ID·상태·시간을 수집한다.
4. schema·table·column count를 fixture와 비교한다.
5. 5 platform instance 분리를 확인한다.
6. Search API를 호출한다.
7. 재기동 후 자산과 검색을 확인한다.
8. ingestion snapshot과 재기동 runbook을 작성한다.

실패 신호:

- GMS health
- Search indexing delay
- Kafka·DB dependency
- memory pressure

### 단계 R5-09 — Trino 통합 검증

수행:

1. 5 catalog를 load한다.
2. catalog별 단독 query를 실행한다.
3. PMS↔CRM JOIN을 실행한다.
4. 대표 3-source JOIN을 실행한다.
5. `EXPLAIN`을 확인한다.
6. query ID를 수집한다.
7. source별 timeout을 검증한다.
8. connector 하나를 중단해 장애 격리를 확인한다.

### 단계 R5-10 — Trino Access Control

검증:

- system read-only
- catalog rule
- schema/table rule
- column rule
- mask
- row filter
- resource group
- `system` catalog 차단
- procedure 차단
- passthrough 차단

negative SQL:

```text
INSERT
UPDATE
DELETE
CREATE
DROP
ALTER
CALL
connector passthrough
system catalog
권한 밖 table
권한 밖 column
```

합격:

- 원본 실행 0건

### 단계 R5-11 — Versioned Access Policy 구현·검증

role 후보:

- `hotel_analyst`
- `report_admin`
- `data_admin`

수행:

1. 사람이 검토 가능한 `access-policy.yaml`을 단일 정책 입력으로 둔다.
2. user·group·role mapping, catalog·schema·table·column allow/deny, mask, row filter를 명시한다.
3. policy schema version, content hash, approver, activated_at, previous version을 기록한다.
4. 정책을 애플리케이션 seed와 Trino access control 설정으로 변환하는 결정론적 절차를 만든다.
5. source policy와 생성 결과의 hash·diff를 CI에서 검증한다.
6. role별 API와 SQL 허용·거부를 검사한다.
7. 사용자가 role이나 policy를 변경할 API가 없는지 확인한다.
8. UI 숨김과 무관하게 server와 Trino가 각각 차단하는지 확인한다.
9. request·query·artifact·report trace에 policy version과 hash가 남는지 확인한다.
10. 이전 승인 version으로 rollback하고 동일 negative test를 재실행한다.

`access-policy.yaml` 직접 수정 권한, 검토자, 승인자, 적용자 권한을 분리한다. 실제 production identity provider와 연결하지 못하면 demo mapping임을 명시한다.

### 단계 R5-12 — 개인정보·Mask·Redaction

출력 경로 전체:

- query result
- model input
- model output
- API response
- application log
- trace
- artifact
- report snapshot
- export

수행:

1. synthetic direct identifier fixture를 만든다.
2. 일반 role query를 실행한다.
3. 모든 출력 경로를 검색한다.
4. mask와 앱 2차 redaction을 확인한다.
5. 관리자 권한 경계를 확인한다.

합격:

- 일반 role 직접식별 원문 노출 0건

### 단계 R5-13 — RunPod 사용 전 승인 확인

실행 전 체크:

- 계정
- 예산
- Pod 생성 권한
- region
- GPU type
- storage
- network
- checkpoint license
- data 전송 정책
- 종료 책임자

승인 없이는 실제 Pod를 생성하지 않는다.

### 단계 R5-14 — vLLM·Model Serving

수행:

1. Qwen3.5-4B, Qwen3-4B Instruct 계열, Gemma 3 4B-IT checkpoint·license·revision을 기록한다.
2. 우선 24GB GPU profile을 측정하고 수용 실패 근거가 있을 때만 48GB profile을 측정한다.
3. 각 후보에서 8K와 16K context profile의 VRAM·latency·처리량을 측정한다.
4. 지원되는 후보는 `--language-model-only` 적용 여부와 효과를 별도 기록한다.
5. Node 1·3 Base 요청과 Node 2·2′ SQL adapter 요청을 확인한다.
6. Base와 QLoRA adapter를 동시에 제공하는 hybrid serving 구성을 검증한다.
7. 승인된 adapter를 사전 적재하고 runtime dynamic loading을 끈다.
8. 동시 실행 2건과 초과 요청의 queue 또는 429를 확인한다.
9. model·checkpoint·adapter·serving option·GPU가 trace에 남는지 확인한다.
10. R3의 고정 평가 명령을 동일 image·region·GPU·seed에서 실행하고 비용을 기록한다.

Qwen3.5-4B가 main/nightly runtime에서만 동작해 안정 릴리스 재현성을 만족하지 못하면 SGLang·Transformers의 main branch를 안정 fallback으로 간주하지 않는다. 해당 후보를 제품 채택에서 제외하고 고정된 안정 릴리스에서 재현되는 Qwen3 또는 Gemma 후보로 돌아간다.

오류:

- OOM
- load timeout
- invalid adapter
- endpoint unavailable
- context overflow

### 단계 R5-14A — DataHub Analytics Agent 기준선 환경

수행:

1. 비교 가능한 Analytics Agent version·image·설정·지원 source를 고정한다.
2. 제품 경로와 격리된 baseline profile로 실행한다.
3. R3 평가 harness가 동일 질문·권한·`as_of`·synthetic data를 전달할 adapter를 제공한다.
4. 지원하지 않는 기능과 설정 차이를 명시한다.
5. latency·resource·운영 절차·실행 비용을 수집한다.
6. 결과를 자동으로 제품 채택으로 간주하지 않고 R1 판정 자료로 넘긴다.

### 단계 R5-15 — Checkpoint·Storage

수행:

1. container disk와 persistent storage를 구분한다.
2. checkpoint를 영속 경로에 저장한다.
3. 외부 backup을 만든다.
4. checksum을 기록한다.
5. Pod 재생성 후 load를 확인한다.
6. 비용·종료 조건을 기록한다.

### 단계 R5-16 — OpenTelemetry

span:

```text
HTTP request
Router
Node 1
DataHub search
Policy lookup
Context build
G1
Node 2/2′
G2
Trino
Result Shaper
G3
Node 3
Artifact
Report run
```

metric:

- request count
- success/block/failure
- Gate별 block
- LLM latency
- Trino p50/p95
- source scan
- cache hit
- report block failure
- queue/429

log:

- structured
- `trace_id`
- secret·PII redaction

### 단계 R5-17 — CI 기본 검증

Pipeline:

1. 문서·format 정책
2. Python test
3. frontend build
4. schema/migration check
5. SQL policy negative test
6. secret scan
7. dependency scan
8. image scan
9. integration smoke

실패 시 release를 중단할 항목을 명시한다.

### 단계 R5-17A — Report Worker Runtime

R4가 제공한 `ReportJobPayload`와 event contract를 실행 환경에 연결한다.

수행:

1. queue backend와 worker process의 고정 version·resource limit을 정한다.
2. accepted·running·terminal event를 R4 contract와 일치시킨다.
3. idempotency key로 동일 job의 중복 실행을 막는다.
4. timeout, graceful shutdown, retry 가능 오류, 최대 시도, dead-letter 조건을 설정한다.
5. retry마다 새 실행을 만들지, 같은 run의 attempt로 남길지 R4 계약을 따른다.
6. worker 재시작·queue 재전달·network 단절에서 중복 artifact가 생기지 않는지 검사한다.
7. schedule trigger와 manual trigger가 같은 worker 경로를 사용하는지 확인한다.
8. job payload·log·trace에 secret·원문 개인정보가 없는지 검사한다.
9. queue depth, oldest job age, success·failure·retry·dead-letter metric을 수집한다.
10. worker 배포·확장·중단·재처리 runbook을 작성한다.

R5는 Report 상태 판정 규칙이나 domain model을 재구현하지 않는다.

### 단계 R5-18 — Gate 독립 Negative Test

G1:

- role 없음
- 권한 밖 domain
- 비활성 Context
- 잘못된 `as_of`
- 비활성 asset

G2:

- DDL/DML
- 비승인 table·column
- 비승인 JOIN
- 시간 함수
- LIMIT 초과
- complex query
- procedure

G3:

- schema mismatch
- mask evidence 누락
- row filter evidence 누락
- NaN·범위 초과
- 의심 0건

상태 머신:

- G2 repair 2회 시도
- G3 실패 후 Node 3 호출 시도

### 단계 R5-19 — Cache 보안 Test

변경하면서 반복 조회:

- role
- entitlement
- `as_of`
- policy version
- Context release
- source watermark
- row filter
- mask

합격:

- 다른 권한·시점 결과 공유 0건
- Cache hit의 G2·G3 우회 0건

### 단계 R5-20 — Source 장애·부분 실패

수행:

1. connector 하나 중단
2. source timeout
3. DataHub Search 실패
4. vLLM 실패
5. worker 실패
6. report block 하나 실패

확인:

- 실패 source·block 표시
- retry 범위
- 전체 성공 오표시 없음
- trace 보존
- stale 결과 사용 여부 명시

### 단계 R5-21 — 재현성 Test

고정:

- seed
- schema version
- `as_of`
- timezone
- Context release
- model/prompt
- policy

수행:

1. 환경 삭제 후 재구성
2. seed 재적재
3. 대표 질문 실행
4. 결과 정규화
5. checksum 비교
6. Report block snapshot 비교

합격:

- 동일 조건 결과 checksum 일치

### 단계 R5-22 — 성능·자원 측정

Profile별:

- idle CPU/RAM
- startup 시간
- ingestion
- 단일 query
- 2-source JOIN
- 3-source JOIN
- 동시 요청 2건
- report run
- peak RAM·disk
- LLM VRAM

기록:

- p50/p95
- source scan
- timeout
- queue
- failure

수용 상한은 baseline 측정 후 팀이 승인한다.

### 단계 R5-23 — Full·Split-host 판정

full 실패 기준:

- swap
- container restart
- indexing 지연
- query timeout
- model OOM
- 재기동 불안정

판정:

1. full 결과 기록
2. 병목 component 식별
3. DataHub·Trino·model 분리 후보 검토
4. split-host 재측정
5. 선택과 rollback 기록

### 단계 R5-23A — 보존·삭제·복구 정책 적용

초기 보존 기준:

| 대상 | 기본 보존 |
|---|---:|
| Result Cache payload | 24시간 |
| 일반 Artifact·실행 결과 | 30일 |
| 승인 Report snapshot | 90일 |
| Audit·policy·Gate·trace metadata | 180일 |
| Report definition·Context release | project 존속 기간 + 종료 후 90일 |

수행:

1. 각 저장소에서 보존 기준을 TTL·partition·scheduled cleanup으로 구현한다.
2. legal hold·조사 보존 대상은 자동 삭제에서 제외하고 승인자를 기록한다.
3. 삭제 전후 대상 수, 실패, 재시도, policy version을 audit에 남긴다.
4. backup 보존 기간이 본 저장소보다 무기한 길어지지 않게 맞춘다.
5. 실제 데이터 사용 시 개인정보·계약·기관 정책 담당자의 재승인을 받는다.
6. 복구 목표는 초기 `RPO 24시간`, `RTO 4시간`으로 검증하고 불충족 근거를 남긴다.
7. 보존 변경은 migration·rollback·기존 데이터 처리 계획과 함께 승인받는다.

### 단계 R5-24 — Backup

대상:

- 애플리케이션 PostgreSQL
- Context release
- role mapping
- report definition
- audit trace
- model checkpoint
- 필요한 config

수행:

1. 암호화 backup
2. 일일 주기
3. 저장 위치 분리
4. checksum
5. 보존·삭제
6. key 관리

### 단계 R5-25 — Restore

수행:

1. 별도 환경 준비
2. backup 복원
3. migration version 확인
4. Context release 확인
5. role mapping 확인
6. report definition 확인
7. audit trace 연결 확인
8. 대표 query 실행
9. RPO/RTO 기록

### 단계 R5-26 — SBOM·SCA·Image Scan

수행:

1. dependency lockfile 확인
2. SBOM 생성
3. Python·Node dependency scan
4. container image scan
5. critical/high 분류
6. 수정 또는 만료일 있는 예외 승인
7. release 결과에 첨부

합격:

- 미승인 critical/high 0건

### 단계 R5-27 — 필수 수용 30건 실행

R1·R2 승인 세트를 독립 실행한다.

기록:

- case ID
- 입력
- role
- 실행 결과
- Gate
- result hash
- trace
- pass/fail
- defect ID

원칙:

- 올바른 중단도 pass
- 실행하지 않은 항목을 pass로 표시하지 않음

### 단계 R5-28 — Runbook 작성

포함:

- 기동
- health 확인
- ingestion
- catalog 확인
- API·UI 실행
- RunPod 시작·종료
- 대표 질문
- 장애 진단
- backup·restore
- log·trace 조회
- secret 교체
- rollback

신규 팀원이 runbook만으로 재현 가능한지 검사한다.

### 단계 R5-29 — Release 판정

필수 증거:

- 5 source ingestion·query
- 금지 실행 0건
- PII 노출 0건
- trace 100%
- checksum 재현
- Chat→Report
- Cache Gate 재검증
- backup restore
- SCA/image scan
- full/split profile 자원표

High 결함이 미해결이면 Pass로 판정하지 않는다.

## 5. 다른 역할과의 병렬 인수인계

| 받는 자료 | 제공자 | R5 검증 |
|---|---|---|
| 업무 수용 30건 | R1 | 독립 end-to-end |
| DB·recipe·catalog | R2 | 기동·권한·장애 |
| Gate·API·trace | R3 | negative·보안·상태 전이 |
| UI build·상태 | R4 | production build·smoke·오표시 |

R5가 제공:

- 고정 version
- profile
- health contract
- CI 결과
- trace dashboard
- defect
- release evidence

## 6. R5 작업 완료 체크리스트

- [ ] dev/full/split-host 목적과 구성이 있다.
- [ ] version·image·driver가 고정됐다.
- [ ] secret이 저장소와 log에 없다.
- [ ] 5 DB·DataHub·Trino health가 자동 검사된다.
- [ ] 원본·Trino read-only negative test가 통과한다.
- [ ] 일반 role PII 노출이 0건이다.
- [ ] RunPod 사용 승인·종료 조건이 있다.
- [ ] `access-policy.yaml`과 적용 결과의 version·hash·negative test가 일치한다.
- [ ] 세 Base 후보와 QLoRA·24GB/48GB·8K/16K 결과가 비교됐다.
- [ ] Base·SQL adapter 분리가 trace에 보인다.
- [ ] Analytics Agent 기준선 version·설정·비용 증거가 있다.
- [ ] Report worker가 중복·재시작·dead-letter contract test를 통과한다.
- [ ] 전체 OpenTelemetry trace가 연결된다.
- [ ] Gate·Cache·부분 실패 test가 있다.
- [ ] 동일 실행 checksum이 일치한다.
- [ ] full 또는 split-host 판정 근거가 있다.
- [ ] 24시간·30일·90일·180일 보존 정책과 삭제 audit이 검증됐다.
- [ ] RPO 24시간·RTO 4시간을 restore test로 측정했다.
- [ ] backup restore가 검증됐다.
- [ ] 미승인 critical/high 취약점이 없다.
- [ ] 필수 수용 30건 결과가 있다.
- [ ] runbook으로 재현할 수 있다.

## 7. R5 완료 보고 형식

```text
검증한 profile:
고정 version/image:
5 source/DataHub/Trino health:
read-only·권한·mask 결과:
RunPod·vLLM 결과:
trace·metric 결과:
Gate·Cache negative test:
장애·부분 실패 결과:
성능·자원 baseline:
backup·restore:
SCA·image scan:
수용 30건:
release 판정:
미해결 결함·리스크:
```

## 8. R5 병합 절차와 권장 병합 시점

R5는 root dependency·Compose·`.env.example`·CI의 단일 작성자다. 다른 역할의 dependency·service fragment를 작은 요청으로 받아 검증 후 반영한다. Git 절차는 `docs/markdown/collaboration/README.md`를 따른다.

### 공통 절차

1. 배정된 개인 branch에 최신 `dev`를 반영하고 base SHA를 기록한다.
2. dependency·image·driver·config 변경의 이유와 rollback을 확인한다.
3. secret·실제 데이터·대용량 image/checkpoint가 diff에 없는지 검사한다.
4. fake 또는 실제 profile에 맞는 CI·health·security·smoke를 실행한다.
5. 사람이 staged diff와 비용·외부 작업 기록을 확인한 뒤 개인 branch에 commit·push한다.
6. 관리자가 `dev`에 병합하고 profile smoke·affected test를 실행한다.
7. R5가 독립 검증에서 발견한 defect는 해당 소유 역할 branch로 돌려보내고 R5가 임의로 업무 코드를 수정하지 않는다.

### 권장 R5 병합 패키지

| 병합 | 여기까지 완료 | 선행 | 병합 직후 소비자 | 필수 검증 |
|---|---|---|---|---|
| R5-M1 / I1 | version matrix, dev/full/split profile skeleton, root dependency·CI·health contract | R1 I0, R2 driver 후보 | 전 역할 | config parse, fake health, lint/test entrypoint |
| R5-M2 / I2 | 5 DB·DataHub·Trino runtime, read-only·access control, observability 기본 | R2 service fragment | R2·R3 | 5 catalog health, secret scan, deterministic smoke |
| R5-M3 / I3 | RunPod/vLLM, 24GB 우선·48GB fallback, model trace·비용 | R3 model interface | R3 | Base/adapter load, 8K/16K, OOM·429·rollback |
| R5-M4 / I4 | Report worker runtime, retention, backup·restore, reporting 장애 test | R4 job contract, R3 등록 | R4·R1 | duplicate/retry/dead-letter, 24h·30d·90d·180d, restore |
| R5-M5 / I5 | 전체 보안·장애·성능·SCA/image scan·runbook·release evidence | 모든 역할 기능 병합 | R1 최종 판정 | 필수 30건, full regression, RPO/RTO, 미승인 High 0건 |

R5-M1은 기능 code를 기다리지 않고 먼저 병합한다. 이후 dependency나 Compose 변경은 각 체크포인트에서 별도 작은 병합으로 처리해 다른 역할의 branch가 오래된 root 설정을 들고 가지 않게 한다.

병합하지 않는 상태:

- 실제 secret·고객 데이터·checkpoint binary가 포함됨
- 비용 사용 승인·COST_LIMIT·STOP_CONDITION이 없음
- image tag·model revision·driver version이 고정되지 않음
- critical/high 취약점의 승인된 예외나 수정이 없음
- full 실패를 기록하지 않고 split-host만 성공으로 보고함
- R5가 R2/R3/R4 업무 source를 직접 수정함
