# 역할 3 — 대화형 분석 Control Plane·AI 작업 매뉴얼

> 문서 상태: 팀 검토용 초안  
> 작성 기준일: 2026-07-28  
> 대상 역할: R3 대화형 분석 Control Plane·AI 담당  
> 기준 기획서: `docs/Answervice_기획서.md`  
> 주의: 기술 구조는 실제 구현·호환성 검증 결과로 고정하고, 문서의 잠정 선택을 구현 완료로 간주하지 않는다.

## 0. 5개 AI 공통 실행·충돌 방지 계약

### R3가 수정할 수 있는 논리 영역

- 공통 OpenAPI·Pydantic 계약과 공통 오류 코드
- 분석 요청 API, Controller 상태 머신, Context·Gate·LLM·Cache·Artifact
- 분석용 애플리케이션 모델과 repository
- 분석 단위·계약·통합·평가 test
- FastAPI 공통 entrypoint와 router 등록
- 공통 Alembic revision 선형화

### R3가 직접 수정하면 안 되는 영역

- 원천 데이터 DDL·seed, DataHub recipe, Trino catalog와 connector adapter: R2 소유
- Report 도메인·API 내부 구현과 frontend: R4 소유
- root dependency, Compose, `.env.example`, CI, 배포, model serving: R5 소유
- 업무 정의, 수용 기준, 평가 정답과 통합 판정: R1 소유

### 공유 파일 단일 작성자

| 공유 대상 | 단일 작성자 | R3 이외 역할의 변경 방법 |
|---|---|---|
| 공통 OpenAPI·Pydantic·오류 코드 | R3 | `contract-change-request` 제출 |
| FastAPI entrypoint·router 등록 | R3 | 자기 router와 등록 요청 제출 |
| Alembic revision chain | R3 | 자기 migration proposal 제출 |
| root dependency·Compose·`.env.example` | R5 | dependency/config 변경 요청 제출 |
| frontend package·공통 UI 설정 | R4 | R4에 변경 요청 |

공유 파일은 단일 작성자만 직접 수정한다. 다른 AI는 완성된 module, proposal, contract diff와 검증 결과를 handoff한다.

### AI에 반드시 같이 제공할 입력

```text
ROLE_ID=R3
TASK_CARD_ID=R3-xx
REPOSITORY_ROOT=<절대 경로>
BASE_BRANCH=<통합 기준 branch>
BASE_SHA=<작업 시작 commit SHA>
CONTRACT_VERSION=<현재 승인 contract version>
FIXTURE_VERSION=<현재 승인 fixture version>
ALLOWED_PATHS=<이 카드에서 수정 가능한 경로>
FORBIDDEN_PATHS=<수정 금지 경로>
ACCEPTANCE_CRITERIA=<완료 조건>
EXTERNAL_ACTION_PERMISSION=<비용·배포·데이터 전송 허용 여부>
STOP_CONDITION=<중단·질문 조건>
```

한 번에 이 문서 전체가 아니라 작업 카드 한 개만 AI에 준다. AI는 시작 전에 repository root, branch, dirty worktree, 적용되는 `AGENTS.md`, 대상 파일, 계약 version을 확인하고 허용 경로 밖 변경을 중단한다.

각 사람은 `docs/markdown/collaboration/README.md`에 정해진 자기 개인 branch(`junhee`, `minji`, `seung`, `daesung`, `jaehong` 중 배정된 branch)와 자기 clone을 사용한다. 다섯 AI가 같은 working directory를 공유하지 않는다. AI는 승인 없이 stage·commit·push·merge하지 않고, 사람이 검증 후 통합한다.

### AI에 전달할 실행 프롬프트

```text
너는 ROLE_ID 담당 AI다. 기준 기획서와 이 역할 매뉴얼을 모두 읽되, 이번에는 TASK_CARD_ID 하나만 수행한다.
먼저 repository root, 적용되는 AGENTS.md, branch, BASE_SHA, dirty worktree, 선행 계약·fixture version을 읽기 전용으로 확인한다.
확인된 사실·가정·blocker와 이 카드의 입력·출력·완료 조건을 짧게 보고한 뒤 작업한다.
ALLOWED_PATHS만 수정하고 FORBIDDEN_PATHS와 다른 역할 소유 파일은 수정하지 않는다.
공유 파일의 단일 작성자로서 변경 요청의 영향·breaking 여부를 확인하고, 다른 소유 영역은 proposal만 받는다.
기존 변경을 보존하고 승인 없는 설치·비용·배포·데이터 전송·stage·commit·push·merge를 하지 않는다.
완료 조건에 맞는 검증을 실제 실행하고, 미실행 검증은 통과로 쓰지 않는다.
마지막에는 매뉴얼의 handoff 형식으로 변경 파일, contract version, 검증, 미검증, 남은 위험을 보고한다.
```

### 병렬 통합 Gate

| Gate | 공통 의미 | R3 역할 |
|---|---|---|
| I0 기준 정렬 | 주제·backend·기술 우선순위·소유권 확정 | module·공유 파일 경계 승인 |
| I1 Contract Freeze | metric/time·API·오류·fixture version 승인 | 공통 기술 계약·adapter interface 고정 |
| I2 Deterministic Slice | Template 경로의 전체 왕복 | fake/실제 adapter로 Context→Gate→Artifact 증명 |
| I3 General LLM | Node 1·2·2′·3 일반 질문 경로 | 모델·prompt·repair·trace 검증 |
| I4 Reporting | definition/run·수동/schedule·부분 실패 | R4 Report 계약·router·migration 통합 |
| I5 Release | 필수 30건·full profile·보안·복구·model 비교 | 결함 수정·회귀 결과와 분석 trace 제출 |

### 카드 완료 handoff 형식

```text
TASK_CARD_ID:
BASE_SHA / RESULT_SHA:
수정 파일:
변경한 계약과 version:
실행한 검증과 결과:
실행하지 못한 검증:
fixture·mock 제한:
통합 담당자가 적용할 proposal:
남은 위험:
```

## 1. 이 역할의 최종 책임

R3는 인증된 사용자 요청이 승인 Context와 Gate를 거쳐 읽기 전용으로 실행되고, 검증된 artifact로 저장되는 분석 제어 경로를 책임진다. Report 도메인의 소유자는 R4이며 R3는 분석 실행 계약과 통합 지점을 제공한다.

최종 책임:

- FastAPI와 typed API contract
- 애플리케이션 PostgreSQL 저장 모델
- Router와 Controller 상태 머신
- Context Registry·Builder·release
- G1·G2·G3
- SQLGlot 검증
- R2 Trino adapter를 호출하는 실행 통제
- Result Shaper
- Node 1·2·2′·3
- SQL Plan Cache·Result Cache
- Artifact API와 Report 실행용 분석 계약
- 평가 자동화와 trace metadata

### R3 작업 패키지

| 작업 패키지 | 포함 카드 | 병렬 시작 조건 | 완료 증거 |
|---|---|---|---|
| WP1 계약·Controller | R3-01~08 | R1 상태·오류 초안 | schema test, 상태 전이 test |
| WP2 Context·Gate | R3-09~15 | R1 정책 fixture, R2 metadata fixture | G1/G2 positive·negative test |
| WP3 조회·설명 | R3-16~19 | R2 adapter interface | G3·부분 실패·trace test |
| WP4 Artifact·Cache | R3-20~22 | WP1 contract | 격리·무효화 test |
| WP5 Report 연동 | R3-23 | R4 report contract proposal | consumer/provider contract test |
| WP6 Model 실험·평가 | R3-24~26 | R1 평가셋, R5 실행 환경 | 후보 비교표, 회귀 평가 결과 |

## 2. 절대 지켜야 할 실행 경계

```text
질문 또는 report_plan_id
→ 인증·role·request_id·as_of 확정
→ Router
→ Node 1 또는 Template Binding
→ DataHub + 업무 정책 조회
→ Context Package
→ G1
→ Template SQL / Plan Cache / Node 2
→ G2
→ 실패 시 Node 2′ 1회 → G2′
→ Result Cache 또는 Trino
→ Result Shaper
→ G3
→ Node 3
→ Artifact
→ Chat / Report
```

금지:

- LLM이 권한·합격·실행을 판정
- Template·Cache가 Gate를 우회
- G2 실패 SQL을 실행
- Node 2′를 반복 호출
- G3 실패 후 Node 3 호출
- Node 3이 수치를 재계산
- 원문 DB 오류·stack trace·chain-of-thought 노출

## 3. 착수 전에 받아야 할 입력

| 입력 | 제공자 | 없을 때 병렬 작업 |
|---|---|---|
| metric·time policy | R1 | typed schema와 대표 fixture부터 작성 |
| URN·FQN·JOIN | R2 | 승인 Context fixture를 임시 사용 |
| frontend 필요 상태 | R4 | OpenAPI example을 먼저 제공 |
| 실행·보안 profile | R5 | fake executor와 local PostgreSQL로 단위 개발 |

## 4. 단계별 상세 작업

### 단계 R3-01 — 모듈 경계와 의존 방향 확정

목적: API·AI·SQL·보고서가 서로 순환 의존하지 않게 한다.

논리 모듈:

- API entrypoint
- application service
- controller
- context
- gates
- query
- llm adapters
- artifact
- report integration
- audit
- evaluation

원칙:

- 핵심 로직은 `src`에 둔다.
- `app`은 사용자 노출 서비스의 실행 진입점으로 둔다.
- 실제 구현할 때만 하위 module을 만든다.
- P2 승인 전 embeddings·retrieval 모듈을 만들지 않는다.
- DB·vLLM client는 core interface 바깥 adapter로 둔다.
- DataHub·Trino는 R2 adapter interface를 사용하고 vendor client를 중복 구현하지 않는다.

출력:

- 의존 방향 표
- 주요 public interface

### 단계 R3-02 — 공통 객체 Schema 작성

작성 대상:

```text
NormalizedQuestion
ContextPackage
GateDecision
QueryPlan
QueryRun
ShapedResult
Artifact
ReportDefinition
ReportRun
ErrorResponse
```

`ReportDefinition`·`ReportRun`의 업무 의미와 내부 domain model은 R4가 소유하고, R3는 승인된 transport schema를 공통 계약에 등록한다.

수행:

1. Pydantic schema를 작성한다.
2. field마다 required·optional을 명시한다.
3. enum과 version field를 정의한다.
4. 시간은 timezone이 포함된 형식으로 통일한다.
5. ID 생성 주체를 정한다.
6. OpenAPI example을 추가한다.
7. R4가 frontend type으로 사용할 수 있게 제공한다.
8. breaking change version 규칙을 정한다.

완료 기준:

- mock과 실제 API가 같은 schema를 사용한다.

### 단계 R3-03 — 오류 계약 구현

필수 오류:

```text
CONTEXT_INCOMPLETE
ACCESS_DENIED
SQL_POLICY_BLOCKED
QUERY_SOURCE_FAILED
RESULT_EVIDENCE_MISSING
PARTIAL_FAILURE
INSUFFICIENT_EVIDENCE
```

각 오류:

- HTTP status
- 내부 오류 코드
- 사용자 메시지
- 수정 가능한 입력
- `trace_id`
- retry 가능 여부
- 내부 audit metadata

redaction:

- DB 원문 메시지 제거
- SQL parameter 민감값 제거
- stack trace 사용자 응답 제외
- 내부 policy 상세 제외

### 단계 R3-04 — Application PostgreSQL 모델

최소 저장 대상:

- users 또는 test identity reference
- Context registry record
- Context release
- policy version
- query request/run
- Gate decision
- artifact
- audit event
- cache metadata

수행:

1. 논리 ERD를 작성한다.
2. versioned 객체와 mutable 상태를 분리한다.
3. 분석 영역 migration을 작성한다.
4. FK·unique·state constraint를 적용한다.
5. 민감 payload와 trace metadata 보존을 분리한다.
6. R5가 backup restore 검증할 핵심 table을 표시한다.
7. R4가 제출한 Report migration proposal을 검토하고 revision chain에 선형으로 등록한다.

R4의 ReportDefinition·ReportVersion·ReportBlock·ReportRun·ReportBlockRun·Schedule·Job table은 R3가 다시 구현하지 않는다.

### 단계 R3-05 — 인증 경계와 요청 Context

P0 원칙:

- 별도 IAM 제품을 만들지 않는다.
- versioned role mapping을 읽는다.
- 사용자가 자신의 role을 변경하는 API를 두지 않는다.

요청 시작 시 확정:

```text
request_id
trace_id
user_id
role
entitlement_hash
as_of
timezone
calendar_id
```

검증:

- 만료 세션
- 위조 user
- role 누락
- timezone 누락
- 잘못된 `as_of`

### 단계 R3-06 — Router 구현

Router가 하는 일:

- 활성 승인 Template ID 매칭
- `report_plan_id` 존재·활성 상태 확인
- 일반 질문 경로 선택

Router가 하지 않는 일:

- asset 검색
- 권한 판정
- SQL 실행 허용
- 자유 Tool 선택

test:

- template positive
- 유사하지만 다른 negative
- 비활성 template
- 잘못된 parameter
- 존재하지 않는 report plan

### 단계 R3-07 — Template Binding 구현

수행:

1. 승인 template parameter schema를 정의한다.
2. 자연어 상대 기간을 요청 `as_of` 기준 parameter로 변환한다.
3. role별 허용 parameter를 검사한다.
4. SQL 문자열 결합 대신 typed parameter binding을 사용한다.
5. template ID와 version을 trace에 기록한다.
6. Template SQL도 G1·G2를 통과시킨다.

### 단계 R3-08 — Controller 상태 머신 구현

상태 예시:

```text
RECEIVED
ROUTED
NORMALIZED
CONTEXT_BUILT
G1_PASSED / G1_FAILED
SQL_SELECTED
G2_PASSED / G2_REPAIRABLE / G2_FAILED
QUERY_RUNNING
QUERY_SUCCEEDED / QUERY_PARTIAL / QUERY_FAILED
SHAPED
G3_PASSED / G3_FAILED
EXPLAINED
ARTIFACT_SAVED
```

수행:

1. 허용 전이를 명시한다.
2. 실패 terminal state를 명시한다.
3. Node 2′ 카운터를 상태에 포함한다.
4. G3 전 Node 3 호출을 불가능하게 한다.
5. 각 전이에 audit event를 남긴다.
6. 재시도 가능 범위를 source와 block 단위로 제한한다.

test:

- 정상 경로
- G1 실패
- G2 실패→수정→성공
- G2 실패→수정→재실패
- Trino source 실패
- G3 실패
- report block 부분 실패

### 단계 R3-09 — Context Registry 구현

레코드:

- `asset_binding`
- `metric_definition`
- `time_policy`
- `dimension_history_policy`
- `join_policy`
- `term_alias`
- `column_policy_ref`
- `context_release`

수행:

1. R1·R2 승인 field를 저장한다.
2. draft와 published release를 구분한다.
3. published release를 불변으로 만든다.
4. 수정은 새 version으로 생성한다.
5. approver, published_at, hash, rollback target을 기록한다.
6. 참조 중인 release 삭제를 막는다.

### 단계 R3-10 — Context Builder 구현

입력:

- `NormalizedQuestion` 또는 Template ID
- request role
- `as_of`

처리:

1. R2 DataHub adapter와 정책 DB 조회를 시작한다.
2. role·domain으로 권한 없는 asset을 선필터한다.
3. DataHub 후보의 schema·description·glossary·owner를 읽는다.
4. `asset_binding` 없는 asset을 실행 후보에서 제외한다.
5. time policy로 절대 기간을 만든다.
6. dimension history rule을 결합한다.
7. metric과 1~2 hop 승인 JOIN을 결합한다.
8. 무관 column을 제거한다.
9. dataset 최대 8개, column 최대 60개를 적용한다.
10. 6,000 token 또는 모델 context 25% 이하를 적용한다.
11. 시간·권한·JOIN policy는 잘라내지 않는다.
12. package hash와 token count를 기록한다.

출력:

- versioned `ContextPackage`

### 단계 R3-11 — G1 Context Gate 구현

검사 순서:

1. role·entitlement
2. Context release active 여부
3. policy version
4. `as_of`, timezone, calendar
5. template active 여부
6. 참조 asset·column 유효성
7. metric·time field 유효성
8. dimension history 유효성
9. JOIN active 여부
10. package 크기 상한

실패 분리:

- 문맥 부족: 사용자 재질문
- 권한 거부: 안전 종료
- 비활성 자산: 안전 종료
- package 과다: 후보 축소 또는 범위 재질문

### 단계 R3-12 — Node 1 구현

입력:

- 질문
- role
- `as_of`
- 최소 서비스 정책

출력:

- metric 후보
- dimension
- 기간 표현
- 검색어
- ambiguity
- clarification question

금지:

- DataHub asset 확정
- SQL 생성
- 권한 판정
- 합격 판정

수행:

1. system prompt를 작성한다.
2. typed JSON output을 강제한다.
3. invalid JSON 재처리 정책을 정한다.
4. R1 평가 case로 baseline을 측정한다.
5. prompt version을 기록한다.

### 단계 R3-13 — Node 2 구현

입력:

- 승인 `ContextPackage`만

출력:

- Trino SQL
- 사용 metric·asset·column·JOIN reference
- parameter map

금지:

- Context 밖 table·column
- 여러 statement
- 권한 판정
- SQL 실행
- DB 원문 오류 처리

수행:

1. Trino dialect를 명시한다.
2. hard LIMIT 규칙을 전달한다.
3. 시간 parameter를 직접 받게 한다.
4. SQL과 reference를 함께 출력한다.
5. R2 gold로 source·column·JOIN 정확도를 측정한다.

### 단계 R3-14 — G2 SQL Policy Gate 구현

검사 순서:

1. SQL parsing 성공
2. 단일 statement
3. SELECT/허용 구조
4. DDL·DML·procedure·passthrough 차단
5. `system` catalog 차단
6. Context asset 대조
7. column allowlist
8. 승인 JOIN과 cardinality
9. 시간 함수·parameter
10. 함수 allowlist
11. nesting·complexity
12. hard LIMIT
13. `EXPLAIN`
14. role·mask·resource policy

출력:

- pass/fail
- 정규화 오류 코드
- 수정 가능 범위
- policy version
- evidence

### 단계 R3-15 — Node 2′ 1회 수정

입력:

- 거절 SQL
- 승인 Context
- 정규화 G2 오류 코드
- 수정 가능 범위

금지 입력:

- 원문 DB 오류
- stack trace
- 비밀 policy
- 무제한 대화 이력

수행:

1. Controller에서 repair count를 확인한다.
2. 한 번만 호출한다.
3. 결과를 G2′에 다시 전달한다.
4. 재실패 시 terminal failure로 끝낸다.

test:

- repair 1회 성공
- repair 재실패
- 두 번째 repair 호출 차단

### 단계 R3-16 — R2 Trino Adapter 호출·실행 통제

수행:

1. G2 pass token 또는 decision ID를 요구한다.
2. R2가 제공한 `execute`, `status`, `cancel` interface만 호출한다.
3. G2를 통과하지 않은 요청은 adapter에 전달하지 않는다.
4. timeout·row limit·동시 실행 제한을 요청 계약에 포함한다.
5. query ID와 상태 전이를 기록한다.
6. R2의 source별 오류를 공통 안전 오류 코드로 변환한다.
7. cancellation 결과와 최종 상태를 확인한다.
8. result와 source watermark를 기록한다.
9. 원문 오류는 내부 제한 log로만 보존한다.

금지:

- Trino HTTP client·catalog 설정을 R3가 중복 구현
- G2 통과 표시를 단순 boolean이나 사용자 입력으로 수신
- timeout 후 실행 상태를 확인하지 않고 성공·실패 처리

### 단계 R3-17 — Result Shaper 구현

처리:

- column schema 정규화
- row 상한
- numeric·date format
- table 데이터
- chart 입력
- summary statistic
- masking evidence
- row filter evidence
- sampling evidence
- source status

주의:

- LLM이 chart raw data를 재작성하지 않는다.
- chart spec은 허용 type과 field로 결정론적으로 만든다.

### 단계 R3-18 — G3 Result Check 구현

검사:

1. expected schema
2. row filter evidence
3. mask evidence
4. sampling evidence
5. row·column 상한
6. metric 범위
7. NaN·Infinity·이상치
8. 정상·의심 0건 구분
9. 조건부 checksum
10. source 부분 실패

실패 시:

- Node 3 호출 금지
- artifact 성공 상태 금지
- `RESULT_EVIDENCE_MISSING` 또는 부분 실패 반환

### 단계 R3-19 — Node 3 구현

입력:

- G3 pass `ShapedResult`
- metric·filter·기간·`as_of`
- source list
- sampling·mask·partial 상태

출력:

- 관측 결과
- 기준과 조건
- 해석 한계
- 출처 요약

금지:

- SQL 정답 판정
- 수치 재계산
- chain-of-thought 수신·노출
- 근거 없는 원인 단정

R1의 문구 기준으로 평가한다.

### 단계 R3-20 — Artifact 저장

Artifact 포함:

```text
artifact_id
request_id
question
normalized_question_id
context_release
policy_version
model/prompt version
query_id
source URNs
filters
as_of
shaped result
chart spec
explanation
Gate evidence
watermarks
status
```

수행:

1. 질문·조건·출처가 분리되지 않게 저장한다.
2. result payload와 trace metadata 보존을 분리한다.
3. role별 조회 권한을 검사한다.
4. Report block이 `artifact_id`를 참조하게 한다.

### 단계 R3-21 — SQL Plan Cache

key:

```text
normalized_question
context_release
policy_version
authz_scope
```

수행:

- 권한 중립 SQL만 공통 재사용
- hit 후 G1·G2 재검증
- Context·policy 변경 시 무효화
- template과 cache source를 trace에 기록

### 단계 R3-22 — Result Cache

key:

```text
sql_hash
entitlement_hash
as_of
catalog_watermark_set
row_filter
column_mask
```

저장:

- shaped result
- G3 재검증 증적

검증:

- 다른 role
- 다른 `as_of`
- 다른 mask
- source watermark 변경
- policy 변경

hit도 entitlement 재검사와 G3를 통과한다.

### 단계 R3-23 — Report Integration Contract

R4가 Report 도메인과 API를 구현할 수 있도록 다음 분석 계약만 제공한다.

```text
execute_analysis_block
get_artifact
get_analysis_status
cancel_analysis
AnalysisBlockRequest
AnalysisBlockResult
ArtifactReference
```

수행:

1. `report_definition_id`, `report_version`, `report_run_id`, `block_id`를 trace correlation field로 받는다.
2. job 시작 시 확정된 `as_of`, timezone, Context release, policy version을 검증한다.
3. 실행 전에 G1·G2를 다시 통과하고 결과 후 G3를 통과한다.
4. 성공 시 immutable `artifact_id`와 evidence를 반환한다.
5. 실패·차단·취소·timeout을 공통 오류 코드와 terminal status로 반환한다.
6. R4 consumer fixture와 R3 provider contract test를 같은 version으로 실행한다.
7. R4 router 등록 요청과 migration proposal은 R3가 공통 entrypoint·revision chain에 반영한다.

R3는 Report CRUD·layout·schedule 저장·worker runtime을 구현하지 않는다.

### 단계 R3-24 — Base Model·Fine-tuning 후보 비교

비교 후보:

- Qwen3.5 4B
- Qwen3 4B
- Gemma 3 4B

비교 축:

```text
Base
QLoRA adapter
Node 1 normalization
Node 2 SQL generation
Node 2′ repair
Node 3 explanation
```

수행:

1. R1의 승인 평가셋을 train·validation·test로 고정하고 test는 학습에 사용하지 않는다.
2. R5와 동일 GPU type·region·image·context length·serving option을 고정한다.
3. Base 세 후보를 먼저 측정한다.
4. Base가 수용 기준을 충족하지 못하는 node에만 1회의 bounded LoRA/QLoRA 비교 실험을 적용한다.
5. 같은 prompt·Context·Gate·seed에서 Base와 adapter를 비교한다.
6. accuracy, Gate block rate, invalid SQL, p50/p95, VRAM, 처리량, 실행 비용을 기록한다.
7. 성능 향상이 평가 오염·prompt 변경·Context 변경 때문이 아닌지 확인한다.
8. 제품 채택 모델과 연구 비교 결과를 분리한다.
9. adapter 장애 시 Base로 되돌리는 rollback 조건을 정의한다.

반복 tuning은 첫 비교에서 모델 원인 오류와 유의미한 개선이 확인되고 R1이 별도 승인한 경우에만 새 카드로 진행한다.

제품 채택 원칙:

- 전체 평균보다 필수 30건, 금지 SQL 0건, 증적 누락 0건을 우선한다.
- 24GB에서 수용 기준을 만족하는 후보를 우선하고, 불가능할 때만 48GB 근거를 남긴다.
- R3는 학습·평가 코드를, R5는 GPU·vLLM·checkpoint·비용 증거를 담당한다.

### 단계 R3-25 — Audit·Trace

연결:

```text
request_id
→ time/context_release
→ model/prompt/policy
→ Gate decisions
→ query_id
→ artifact_id
→ report_definition_id/report_run_id
```

민감 원문은 최소 보존하고 mask한다.

### 단계 R3-26 — 평가 자동화

평가:

- Node 1 normalization
- Context URN·JOIN
- Node 2 SQL·result
- Gate allow/block
- Node 3 설명
- end-to-end trace
- DataHub Analytics Agent 기능 기준선

실패 원인 분류:

- 업무 정의
- synthetic data
- metadata
- Context retrieval
- SQL generation
- SQL policy
- connector
- result evidence
- explanation

파인튜닝 전에 metadata·Context·connector 원인을 먼저 제거한다.

Analytics Agent 비교:

1. 동일한 synthetic source·질문·권한·`as_of`를 사용한다.
2. 가능한 기능만 비교하고 지원하지 않는 기능은 `NOT_APPLICABLE`로 기록한다.
3. 질의 성공률, 근거 추적, 정책 차단, latency, 운영 복잡도와 제품 적합성을 기록한다.
4. Analytics Agent를 제품에 채택하는 결정과 비교 기준선으로 사용하는 결정을 분리한다.
5. 버전·설정·실행 증거는 R5, 평가 기준과 채택 판정은 R1, 자동화 코드는 R3가 맡는다.

## 5. 다른 역할과의 병렬 인수인계

| 출력 | 소비자 | 제공 시점 |
|---|---|---|
| OpenAPI example | R4 | 실제 API 이전 |
| Context fixture | R1/R2/R4/R5 | Registry 구현 이전 |
| Gate fixture | R5 | Gate 코드 이전부터 |
| fake model adapter | R5 | RunPod 이전 |
| Artifact fixture | R4 | Query 실행 이전 |
| trace schema | R5/R4 | 각 component 연결 이전 |

선행 작업 지연 시:

- DataHub 대신 고정 URN adapter
- Trino 대신 expected result executor
- vLLM 대신 deterministic fake adapter
- frontend 대신 API integration test

## 6. R3 작업 완료 체크리스트

- [ ] 공통 Pydantic·OpenAPI 계약이 있다.
- [ ] 오류 redaction이 구현됐다.
- [ ] versioned 저장 모델과 migration이 있다.
- [ ] Controller 상태 전이 test가 있다.
- [ ] Context release가 불변이다.
- [ ] G1·G2·G3 positive/negative test가 있다.
- [ ] Node 2′ 호출 상한이 1회다.
- [ ] G3 실패 후 Node 3 호출이 0건이다.
- [ ] Template·Cache가 Gate를 우회하지 않는다.
- [ ] Artifact가 질문·조건·출처·결과를 연결한다.
- [ ] Report 실행 계약이 R4 consumer fixture와 호환된다.
- [ ] R2 Trino adapter 외에 중복 client 구현이 없다.
- [ ] Cache role·시점 오염 test가 있다.
- [ ] 세 Base 모델과 필요한 QLoRA adapter를 동일 조건으로 비교했다.
- [ ] Analytics Agent 기준선과 제품 채택 판정을 구분했다.
- [ ] 전체 trace를 재구성할 수 있다.

## 7. R3 완료 보고 형식

```text
구현한 API와 schema:
Controller 상태 전이:
Context release:
G1/G2/G3 검증:
Node별 model/prompt version:
Trino 실행 결과:
Cache 검증:
Artifact·Report 결과:
평가 결과:
R4에 전달한 contract:
R5에 전달한 test entrypoint:
남은 기술 리스크:
```

## 8. R3 병합 절차와 권장 병합 시점

R3는 공통 OpenAPI·FastAPI 등록·Alembic chain의 단일 작성자이므로 큰 기능을 한 번에 병합하지 않고 계약과 vertical slice를 나눠 병합한다. 전체 Git 절차는 `docs/markdown/collaboration/README.md`를 따른다.

### 공통 절차

1. 배정된 개인 branch에 최신 `dev`를 반영하고 base SHA·contract version을 기록한다.
2. 다른 역할 proposal과 이미 `dev`에 병합된 module을 확인한다.
3. 공통 파일 변경은 consumer impact와 breaking 여부를 적는다.
4. 단위·contract·migration·상태 전이 검증을 실행한다.
5. 사람이 staged diff를 확인한 뒤 개인 branch에 commit·push한다.
6. 관리자가 `dev` 병합 후 API·migration·affected consumer 회귀를 실행한다.
7. R3 병합 직후 R2·R4·R5는 최신 `dev`를 반영해 계약 drift를 막는다.

### 권장 R3 병합 패키지

| 병합 | 여기까지 완료 | 선행 | 병합 직후 소비자 | 필수 검증 |
|---|---|---|---|---|
| R3-M1 / I1 | 공통 Pydantic·OpenAPI·오류, Controller interface, adapter port | R1 계약, R2 interface | R4 mock·R5 CI | schema snapshot, error redaction, consumer contract |
| R3-M2 / I2-A | Router·Template·Context Registry/Builder·G1 | R2 URN fixture | R1·R2·R5 | Context hash·크기, G1 allow/block, 상태 전이 |
| R3-M3 / I2-B | G2·R2 Trino adapter 호출·Shaper·G3·Artifact·Cache | R2-M2 | R4 Chat·Report bridge | Gate 우회 0건, result hash, cache 격리, trace |
| R3-M4 / I3 | Node 1·2·2′·3와 일반 질문 평가 | R1/R2 gold, R5 serving | R4 일반 질문 UI | repair 1회, invalid SQL 차단, 모델/prompt trace |
| R3-M5 / I4 | R4 Report router 등록, migration 선형화, 분석 block contract | R4 Report module proposal | R4 실제 API·R5 worker | endpoint 중복 0건, 단일 migration head, contract test |
| R3-M6 / I5 | 모델 비교·Analytics Agent 기준선, 수용 결함 수정 | R5 고정 환경 | R1·R5 | 고정 평가, 회귀, rollback evidence |

R3-M5 권장 순서:

1. R4의 Report 독립 module·router·migration proposal이 먼저 `dev`에 병합된다.
2. R3가 최신 `dev`를 반영한다.
3. R3가 공통 router 등록과 Alembic revision을 정리한다.
4. R3-M5를 `dev`에 병합한다.
5. R4와 R5가 다시 최신 `dev`를 반영해 실제 API·worker 연결을 완료한다.

병합하지 않는 상태:

- OpenAPI 예제와 실제 response가 다름
- migration head가 둘 이상임
- G2 실패 SQL이 executor까지 도달함
- R2 adapter 대신 vendor client를 중복 구현함
- R4 Report domain 또는 R5 root config를 R3가 직접 수정함
