# Answervice 단계별 구현 가이드

| 항목 | 내용 |
|---|---|
| 문서 목적 | 팀원이 “지금 무엇을 만들고 어떤 검증을 통과해야 다음으로 가는지” 판단하는 실행 가이드 |
| 진행 방식 | 의존성 순서에 따라 작은 수직 slice를 완성하고 확장 |
| 첫 큰 목표 | 사람이 작성한 Gold SQL로 Golden Scenario의 3 Source 정답 결과 생성 |
| 최종 목표 | 질문부터 Analysis·Report·Trace까지 이어지는 Golden E2E |
| 관련 시각 자료 | [단계별 구현 Visual](04_Answervice_단계별_구현_Visual.html) |

## 1. 먼저 기억할 원칙

```text
정답 데이터·Gold SQL
→ Metadata·Binding·Rule
→ Context·Gate
→ AI
→ 저장·사용자 화면
→ E2E·Release
```

AI부터 시작하지 않는다. AI가 사용할 데이터, 실행 경로, 업무 규칙과 정답 결과를 먼저 만든다.

각 단계는 다음 네 질문으로 끝낸다.

1. 목표: 끝나면 무엇이 가능해야 하는가?
2. 입력: 시작 전에 무엇이 준비돼야 하는가?
3. 산출물: 코드·Schema·Rule·Test 중 무엇을 남기는가?
4. Exit Gate: 어떤 자동 또는 수동 검증을 통과해야 하는가?

## 2. 전체 로드맵

| Stage | 목표 | 핵심 산출물 | Exit Gate |
|---|---|---|---|
| 0 | 실행 골격 | Backend, Frontend, App DB, Compose | health·build·DB connection |
| 1 | Golden 데이터와 정답 | 3 Source seed, Gold SQL/Result | Trino 3 Source 결과 일치 |
| 2 | 전체 데이터 기반 | 5 catalog, DataHub, Binding | 5 Source search·binding health |
| 3 | Trusted Context | Rule, Permission, Context, G1 | AI 없이 G1 `PASS` |
| 4 | AI SQL 경로 | GPT Interpreter, sLLM benchmark, G2 | 대표 질문 SQL 생성·검증 |
| 5 | 안전한 결과 | Query Executor, G3, Shaper, Narrator | Safe Result 숫자 충실도 |
| 6 | 업무 자산화 | Analysis, Report | 재실행·과거 Run 보존 |
| 7 | 사용자 흐름 | Chat, Saved Analysis, Report UI | UI로 Golden Scenario 수행 |
| 8 | 품질·배포 | E2E, security, CI, manifest | 재현 가능한 Demo |

## Stage 0. 실행 골격 만들기

### 목표

팀원이 같은 명령과 Version으로 최소 애플리케이션을 실행한다.

### 작업

1. 기존 Repository 구조를 확인하고 필요한 경계만 만든다.
2. Python / Node / package / container Version을 고정한다.
3. FastAPI `/health`와 React/Vite 기본 화면을 실행한다.
4. App PostgreSQL과 Alembic migration을 연결한다.
5. `.env.example`에는 key 이름만 기록하고 Secret을 넣지 않는다.
6. Docker Compose에 healthcheck와 명시적 image tag를 둔다.
7. README에 실제 실행·종료·초기화 절차를 적는다.

### 산출물

- Backend·Frontend 최소 실행 코드
- App DB 초기 migration
- Compose와 `.env.example`
- 최소 smoke test

### Exit Gate

- Backend health 응답
- Frontend build와 화면 표시
- App DB migration·connection 성공
- 새 환경에서 README 절차 재현

### 아직 하지 않을 것

DataHub 전체 구성, sLLM 학습, GPT prompt 최적화, Report UI.

## Stage 1. Golden 데이터와 Trino 정답 만들기

### 목표

AI 없이 Golden Scenario의 정답을 계산한다.

> 지난달 골드 회원의 객실 매출과 F&B 매출을 지점별로 비교해줘.

### 입력

- `as_of`, timezone과 “지난달” 계산 규칙
- 객실·멤버십·F&B 최소 Schema
- room/fnb revenue 계산 정의
- 고객 Identity 연결과 회원 등급 유효 기간

### 작업

1. 객실 PostgreSQL: `reservations`
2. 멤버십 SQL Server: `members`, `member_grade_history`, `customer_identity_map`
3. F&B MySQL: `orders`
4. 취소·환불, null, 중복, 등급 이력 경계 사례를 seed에 포함한다.
5. seed는 고정 random seed와 data snapshot Version으로 재생성 가능하게 한다.
6. Trino 3 catalog를 연결하고 Source별 query를 확인한다.
7. 사람이 검토한 Gold SQL과 Expected Result를 만든다.

### Exit Gate

- Source DB에서 기본 count·sum 확인
- Trino에서 Source별 select 성공
- 2 Source와 3 Source JOIN 성공
- Gold SQL 결과가 독립 계산한 Expected Result와 일치
- date/timezone/decimal/null mapping 확인

### 주의

`LIMIT`은 scan 비용을 통제하지 않는다. 이 단계부터 timeout과 query stats를 기록한다.

## Stage 2. 5 Source·DataHub·Asset Binding 연결

### 목표

질문에 필요한 데이터 자산을 찾고 실제 Trino 경로로 연결한다.

### 작업

1. 시설 ClickHouse와 연회 PostgreSQL을 추가한다.
2. Trino 5 catalog 연결 smoke test를 만든다.
3. DataHub에서 5 Source Metadata를 ingestion한다.
4. Dataset URN, table/column description, domain/tag/sensitivity를 확인한다.
5. App DB에 `AssetBinding`을 만든다.
6. DataHub URN ↔ Trino FQN을 등록한다.
7. Binding health test로 실제 table 존재와 column signature를 확인한다.

### 최소 Binding Schema

```text
binding_id
datahub_urn
logical_source
trino_catalog / schema / table / fqn
status
binding_version
verified_at
```

### Exit Gate

- Backend가 “객실 매출” 관련 Dataset URN을 검색
- Permission 범위 밖 후보가 Context에 들어가지 않음
- 활성 URN에서 정확한 Trino FQN 반환
- 5 Source가 논리적으로 구분
- DataHub UI screenshot이 아니라 API와 integration test로 증명

## Stage 3. Business Rule·Permission·Context·G1

### 목표

AI 없이도 수동 Business Request를 승인 Context로 바꾼다.

### 작업

1. `room_revenue`, `fnb_revenue` Metric Rule
2. 객실 ↔ identity map ↔ 멤버십/F&B JOIN Rule
3. `previous_month` Time Rule
4. PMS ↔ member ↔ POS Identity Rule
5. MVP RBAC: `admin`, `analyst`, `viewer`
6. Pydantic Contract 작성
7. Context Builder와 G1 구현

### Pydantic 예시

```python
from typing import Literal

from pydantic import BaseModel, Field


class Filter(BaseModel):
    field: str
    op: Literal["eq", "in", "gte", "lte"]
    value: str | int | float | list[str]


class BusinessAnalysisRequest(BaseModel):
    metrics: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    period_rule: str
    analysis_type: Literal["comparison", "trend", "summary"]
```

허용 Metric·Dimension은 등록된 ID로 추가 검증한다.

### G1 검사

- Metric·Dataset·Binding 존재
- 승인 JOIN graph 존재
- Time Rule 계산 가능
- 사용자 Asset·Column 권한 존재
- Rule/Binding 활성 Version

### Exit Gate

- 수동으로 만든 Golden Request가 Approved Context를 생성
- G1 정상 case `PASS`
- missing/permission/ambiguity case는 정형 상태로 차단
- G1 실패 시 sLLM 호출 0회

## Stage 4. GPT Interpreter·sLLM·G2

### 목표

자연어 질문을 구조화하고, 승인 Context 안에서만 SQL을 만들며, 안전한 SQL만 실행 후보로 보낸다.

### GPT Interpreter

1. Output Schema를 먼저 고정한다.
2. Golden 질문과 모호한 질문 fixture를 만든다.
3. GPT 응답을 Pydantic으로 검증한다.
4. Metric/JOIN/실제 날짜 결정은 Backend에 남긴다.

### sLLM

1. [sLLM 평가 문서](02_Answervice_sLLM_모델_학습_평가.md)의 후보 smoke gate를 실행한다.
2. Gold Test와 실행 환경을 동결한다.
3. 같은 Context·decoding으로 Base benchmark를 실행한다.
4. 학습 전 error attribution을 완료한다.

### G2

- 단일 read query와 허용 AST만 통과
- Approved Context 밖 자산·컬럼 차단
- 승인되지 않은 JOIN·함수 차단
- DDL/DML/CALL 차단
- `system.execute`, connector `query`, SQL Server `procedure` 차단
- parse 실패와 알 수 없는 AST는 fail-closed

### Exit Gate

- Golden 질문 → Business Request 정확
- 후보별 Result Accuracy·latency·VRAM 기록
- 정상 Gold SQL 허용
- 준비한 dangerous corpus 전부 차단
- G2 실패 수정은 최대 1회, 두 번째 실패 종료

“dangerous SQL 100% 차단”은 준비한 corpus 범위의 결과로만 표현한다.

## Stage 5. Query Executor·G3·Safe Result·Narrator

### 목표

G2를 통과한 SQL만 실행하고, 안전하게 정리한 결과만 사용자와 GPT에 전달한다.

### Query Executor

- Trino 전용 사용자와 Source read-only 계정
- timeout·cancellation·resource group
- query ID와 source error mapping
- output row/column/payload cap

### G3와 Shaper

```text
Raw Result (Backend 내부)
→ Schema / Size / Distinct Key / JOIN Amplification
→ Metric Invariant / Expected Range / Sensitive Data
→ 필요한 행·열 선택
→ Mask / Redact
→ Safe Result
```

G3는 업무 정답을 보증하지 않는다. Gold Result 비교는 별도 E2E 평가에서 수행한다.

### Narrator

GPT에는 Safe Result, 질문, Metric, 기간, Evidence만 전달한다. 전체 Raw Result, Secret, 불필요한 개인정보와 전체 Schema를 전달하지 않는다.

### Exit Gate

- G2 통과 SQL만 query endpoint에 도달
- 민감·과대·증폭 결과가 UI/GPT로 나가지 않음
- 설명의 숫자·기간이 Safe Result와 코드 비교로 일치
- timeout/cancellation/source failure 상태가 구분됨

## Stage 6. Analysis 저장·재실행과 Report

### 목표

검증된 분석을 일회성 채팅에서 반복 가능한 업무 자산으로 바꾼다.

### Analysis

```text
AnalysisDefinition
→ AnalysisRun
→ AnalysisResult
```

구현 순서:

1. Definition과 Parameter Schema 저장
2. Run마다 `as_of`, 실제 기간, 사용자와 Version 저장
3. SQL/query ID/Gate 상태와 Evidence 저장
4. 기간 Parameter 변경 후 새 Run 생성
5. 재실행 때 현재 Permission·Rule로 G1/G2 재검증
6. 과거 Run/Result 보존

### Report

```text
ReportDefinition
→ ReportBlock (AnalysisDefinition 참조)
→ ReportRun
→ BlockRun (AnalysisRun 참조)
```

MVP:

- Block 추가·위치·크기·visualization 저장
- 공통 `report_as_of` 수동 실행
- `SUCCESS / PARTIAL_SUCCESS / FAILED`
- 실패 Block과 마지막 성공 결과를 명확히 구분

### Exit Gate

- 지난달 Definition을 이번 달 Parameter로 재실행
- 새 Run 생성, 과거 Run 불변
- Rule 비호환이면 재실행 차단 또는 새 Version 요구
- Report 일부 실패 시 과거 결과를 최신처럼 표시하지 않음

## Stage 7. Frontend 사용자 흐름

### 구현 순서

1. Chat/Analysis: 질문 → stage → 결과 → Evidence → 저장
2. Saved Analysis: 목록 → Run history → Parameter → 재실행
3. Report: Block 추가 → 수동 실행 → Block status → 과거 Run

먼저 API Contract와 loading/error/empty/blocked state를 연결한다. 화면이 Backend 권한과 Gate를 우회해 상태를 임의 결정하지 않게 한다.

### Exit Gate

사용자가 Backend API를 몰라도 Golden Scenario를 질문하고, 근거를 확인하고, 저장·재실행하고, Report에 추가할 수 있다.

## Stage 8. E2E·Security·CI·Demo

### Golden E2E

```text
질문 → Interpreter → Context → G1 → Resolver → sLLM
→ G2 → Trino → G3 → Safe Result → Narrator
→ Analysis → 재실행 → Report → Trace
```

### 최상위 평가

- Gold Result와 최종 Shaped Result 비교
- Source DB write 성공 0건
- 권한 없는 민감정보 노출 0건
- Run/Version/Query ID Trace 완전성

실제 write negative test는 합성 데이터가 있는 폐기 가능한 환경에서만 실행하고 전후 checksum과 audit log를 확인한다.

### CI 계층

| 시점 | 실행 |
|---|---|
| PR | lint/type/unit/contract/G1·G2·G3/security corpus |
| Integration | App DB/DataHub/5 Source/Trino/2·3 Source query |
| Release candidate | migration/security/Golden E2E/영향받은 AI eval |
| Demo 이후 | health/smoke와 Release Manifest 확인 |

### Exit Gate

- README와 고정 Version으로 새 환경 재현
- test 결과 artifact와 Release Manifest 존재
- 실제 통과한 image digest·model/rule/data Version 기록
- 실패한 검증을 `Pass`로 표현하지 않음

## 3일 시작 계획

### Day 1 — 정답의 기반

- Golden Scenario의 Metric·기간·Identity 정의
- 3 Source 최소 Schema와 seed
- 각 Source 직접 query

### Day 2 — 통합 정답

- Trino 3 catalog 연결
- Gold SQL 작성
- Expected Result 독립 계산과 비교

### Day 3 — 안전·재현 기반

- read-only 계정과 timeout
- data snapshot / Gold case Version
- 2/3 Source integration test

이 세 단계가 끝나기 전에는 sLLM 학습을 시작하지 않는다.

## 중간 점검표

### 데이터·Metadata

- [ ] 5 Source와 5 Trino catalog가 실행된다.
- [ ] 2/3 Source Gold query가 재현된다.
- [ ] DataHub에서 5 Source Dataset이 검색된다.
- [ ] 활성 Asset Binding이 실제 FQN과 일치한다.

### Trusted Core

- [ ] Metric/JOIN/Time/Identity Rule이 Version으로 관리된다.
- [ ] Permission-filtered Context가 생성된다.
- [ ] G1/G2/G3 상태와 실패 코드가 있다.
- [ ] Trino와 Source DB read-only가 검증됐다.

### AI

- [ ] Interpreter Output Schema가 고정됐다.
- [ ] sLLM 후보 eligibility와 Base benchmark가 있다.
- [ ] System Error와 Model Error가 구분된다.
- [ ] Narrator는 Safe Result만 받는다.

### 업무·검증

- [ ] Analysis 재실행이 현재 G1/G2를 다시 통과한다.
- [ ] 과거 Analysis/Report Run이 보존된다.
- [ ] Golden E2E Result Accuracy가 측정됐다.
- [ ] security corpus와 실제 read-only 검증 결과가 있다.

## 결과가 틀렸을 때 확인 순서

```text
1. Seed / Gold Result
2. Source type·timezone·data freshness
3. DataHub Metadata
4. Asset Binding
5. Metric / JOIN / Time / Identity Rule
6. Permission / Approved Context
7. GPT Interpreter
8. sLLM SQL
9. G2 policy
10. Trino connector / execution
11. G3 / Result Shaper / comparator
```

SQL 결과가 틀렸다고 곧바로 sLLM을 수정하지 않는다. 첫 실패 단계와 root cause를 확인한 뒤 해당 계층을 고친다.
