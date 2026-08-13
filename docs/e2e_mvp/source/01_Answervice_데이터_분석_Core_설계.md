# Answervice 데이터·분석 Core 설계

| 항목 | 내용 |
|---|---|
| 설계 목표 | AI의 언어 처리 능력과 시스템의 권한·규칙·실행 통제를 분리해 재현 가능한 분석 흐름 구성 |
| 제어 방식 | 명시적 상태와 제한된 분기를 가진 Deterministic Orchestrator |
| 핵심 경계 | Approved Context, G1, G2, G3, read-only query, immutable run history |
| 관련 시각 자료 | [Core 아키텍처 Visual](01_Answervice_Core_아키텍처_Visual.html) |

> 이 문서의 `Asset Binding`, `Business Rule`, `G1/G2/G3`는 Answervice가 정의한 구성요소다. DataHub 또는 Trino가 같은 이름의 기능을 자동 제공한다는 뜻이 아니다.

## 1. 설계 원칙

1. GPT는 질문 해석과 결과 설명을 맡는다.
2. sLLM은 승인된 Context 안에서 신규 Trino SQL 초안을 만든다.
3. 권한·Metric·JOIN·기간 계산·실행 여부는 Backend가 결정한다.
4. DataHub는 구조적 Metadata를 제공하고, 업무 규칙은 별도 Rule Layer가 관리한다.
5. DataHub Dataset URN과 Trino FQN은 명시적인 Asset Binding으로 연결한다.
6. G1·G2·G3는 서로 다른 시점과 위험을 통제한다.
7. 검증된 Analysis를 재사용하되, 재실행 때 현재 권한과 정책을 다시 검증한다.
8. Run과 Result는 append-only 이력으로 보존한다.
9. 파싱할 수 없거나 정책으로 설명할 수 없는 입력은 허용하지 않는다.
10. Multi-Agent와 LangGraph는 MVP 의존성이 아니다.

## 2. 요청 한 건의 전체 구조

```text
User
  ↓
API / Authentication / request_id
  ↓
GPT Question Interpreter
  ↓
Business Analysis Request
  ↓
Permission scope ─┐
DataHub Metadata ─┼→ Context Builder → Approved Context
Asset Binding ────┤
Business Rules ───┘
  ↓
G1 Context Gate
  ↓
Analysis Resolver
  ├─ Reuse candidate → 저장된 Definition/SQL을 현재 정책으로 재검증
  └─ New → sLLM → Trino SQL Draft
  ↓
G2 SQL Policy Gate
  ↓
Trino Query Executor → Source DB read-only accounts
  ↓
Raw Result (통제된 Backend 내부)
  ↓
G3 Result Validation → Shaping / Masking / Redaction
  ↓
Safe Result → UI / GPT Narrator / Report
  ↓
Analysis Definition / Run / Result + Trace
```

Orchestrator는 AI 모델이 아니다. 단계, 분기, timeout, retry, cancellation과 최종 상태를 명시적으로 관리하는 애플리케이션 모듈이다.

## 3. 데이터 계층

### 3.1 논리 Source와 물리 DBMS

| Source | DBMS | 주요 연결 포인트 |
|---|---|---|
| 객실 | PostgreSQL | 예약·투숙·객실 매출·취소 |
| F&B | MySQL | 주문·결제·환불·고객 참조 |
| 멤버십 | SQL Server | 회원·등급 이력·고객 식별자 매핑 |
| 시설 | ClickHouse | 시설 이용·점검 이벤트 |
| 연회 | PostgreSQL | 행사 예약·고객·매출 |

질문은 필요한 1~3개 Source만 사용한다. 5개 catalog 연결은 통합 환경의 smoke test이며 5-way JOIN을 기본 분석 패턴으로 삼지 않는다.

합성 데이터에는 다음 경계 사례를 의도적으로 포함한다.

- 시스템별 고객 ID 차이
- 회원 등급 유효 기간
- 취소·환불과 음수 금액 정책
- 중복·누락·null
- Source별 갱신 시각 차이
- 잘못된 N:M JOIN으로 생기는 결과 증폭

### 3.2 Schema, Metadata, Rule, Context의 차이

| 계층 | 질문 | 예 |
|---|---|---|
| Schema | 데이터가 물리적으로 어떻게 생겼는가? | table, column, type, key |
| Structural Metadata | 데이터가 어디 있고 무엇을 뜻하는가? | description, owner, domain, tag, lineage |
| Business Rule | 업무에서 어떻게 계산·연결하는가? | metric, join, time, identity |
| Permission | 현재 사용자가 무엇을 사용할 수 있는가? | allowed domain/asset/column |
| Approved Context | 이 질문에 사용할 최소 승인 정보는 무엇인가? | 위 정보의 질문별 부분집합 |

## 4. DataHub와 Asset Binding

### 4.1 DataHub의 역할

DataHub OSS는 다음 구조적 Metadata의 수집과 검색에 사용한다.

- Database / Schema / Table / Column
- Description / Domain / Owner
- Tag / Sensitivity
- 필요 시 Lineage

DataHub가 최종 Metric, 승인 JOIN, 사용자 Permission이나 SQL 실행을 결정하지 않는다. DataHub UI가 보이는 것만으로 통합 완료로 판단하지 않고, 실제 요청의 Context와 Evidence에 Dataset URN이 연결되는지 검증한다.

### 4.2 Asset Binding

DataHub와 Trino는 자산 식별자가 다르다.

```text
DataHub Dataset URN
        ↓
Asset Binding
        ↓
Trino catalog.schema.table
```

최소 필드:

| 필드 | 의미 |
|---|---|
| `binding_id` | 내부 식별자 |
| `datahub_urn` | DataHub Dataset URN |
| `logical_source` | 객실·F&B 등 업무 Source |
| `trino_catalog/schema/table` | 실행 경로 구성요소 |
| `trino_fqn` | 전체 실행 경로 |
| `status` | `ACTIVE`, `INACTIVE`, `INVALID` |
| `binding_version` | 변경 추적 Version |
| `verified_at` | Metadata와 실제 경로를 마지막으로 대조한 시각 |

원칙:

- 활성 Binding이 없는 Asset은 신규 SQL Context에서 제외한다.
- Dataset 이름이나 Trino catalog가 바뀌면 Binding을 재검증한다.
- 동일 DBMS라도 논리 Source와 database가 다르면 Binding을 분리한다.
- Run에는 사용한 Binding ID와 Version을 기록한다.

## 5. Business Rule과 Permission

### 5.1 Metric Rule

Metric은 단순 이름이 아니라 계산 계약이다.

```yaml
metric_id: room_revenue
aggregation: sum
measure: rooms.public.reservations.room_amount
time_field: stay_date
filters:
  - canceled = false
currency: KRW
version: metric-room-revenue-v1
```

### 5.2 JOIN Rule

최소 관리 항목은 left/right asset, key, cardinality, temporal 조건, null 처리, 허용 상태와 Version이다. 승인되지 않은 업무 JOIN을 sLLM이 새로 만들 수 없게 한다.

### 5.3 Time Rule

`previous_month`, `last_3_months` 같은 상대 기간은 Backend가 `as_of`와 timezone을 기준으로 `[start, end)` 범위로 계산한다. 자연어 모델이 실제 날짜를 계산하지 않는다.

### 5.4 Identity Rule

```text
PMS guest_id ↔ member_no ↔ POS customer_ref
```

승인된 매핑 테이블과 유효 기간을 사용한다. 문자열 유사도로 고객을 임의 연결하지 않는다.

### 5.5 Permission

MVP는 RBAC으로 시작한다.

```text
User → Role → Allowed Domain / Asset / Column
```

Permission은 다음 세 지점에서 겹쳐 적용한다.

1. Metadata 후보를 만들 때 허용 범위를 제한한다.
2. G1에서 요청에 필요한 자산 사용 권한을 확인한다.
3. G2와 Trino access control에서 실제 SQL 경로를 다시 확인한다.

Context 필터 하나만으로 보안을 완료했다고 보지 않는다.

## 6. 질문 해석과 Approved Context

### 6.1 Business Analysis Request

GPT의 출력은 자유 문장이 아닌 Schema 검증 가능한 값이다.

```json
{
  "metrics": ["room_revenue", "fnb_revenue"],
  "dimensions": ["branch"],
  "filters": [{"field": "membership_grade", "op": "eq", "value": "gold"}],
  "period": {"rule": "previous_month"},
  "analysis_type": "comparison"
}
```

GPT가 물리 테이블, Metric 정의, JOIN, Permission 또는 실제 날짜를 결정하지 않는다. 요청이 모호하거나 등록되지 않은 개념을 포함하면 `NEED_CLARIFICATION`으로 전환한다.

### 6.2 Context Builder

Context Builder 처리 순서:

1. 요청 Schema 검증
2. Role 기반 후보 범위 제한
3. 관련 DataHub Asset 검색
4. 활성 Asset Binding 확인
5. Metric Rule 연결
6. 승인 JOIN graph 탐색
7. Time Rule로 기간 계산
8. Identity/temporal 조건 결합
9. 필요한 table/column만 남김
10. 사용 Version과 Evidence 기록

출력은 sLLM 입력과 G1 근거를 겸하는 `Approved Context Package`다.

## 7. G1 — Context Gate

G1은 SQL을 만들기 전에 다음을 검사한다.

- 요청한 Metric과 Dimension이 등록돼 있는가
- 기간을 `as_of` 기준으로 계산할 수 있는가
- 필요한 Dataset과 활성 Binding이 있는가
- Source 사이에 승인 JOIN 경로가 있는가
- 현재 사용자에게 필요한 Asset·Column 권한이 있는가
- 사용하려는 Rule/Binding Version이 활성 상태인가

대표 상태:

```text
PASS
NEED_CLARIFICATION
BLOCKED_PERMISSION
MISSING_METRIC
MISSING_DATASET
MISSING_BINDING
MISSING_JOIN_RULE
```

G1이 `PASS`가 아니면 sLLM을 호출하지 않는다.

## 8. Analysis Resolver와 sLLM Contract

### 8.1 재사용 판단

재사용 key 후보:

- Metric / Dimension
- Filter Schema와 Parameter type
- Period Rule
- Analysis Type
- Source / Join Graph
- Definition 상태와 호환 가능한 Rule Version

재사용은 과거 SQL을 무조건 다시 실행하는 경로가 아니다. 현재 권한·활성 Binding·Rule로 Context를 다시 만들고 G1·G2를 다시 통과한 뒤 새 Run을 생성한다. 호환되지 않으면 새 Version 또는 신규 분석으로 전환한다.

### 8.2 sLLM Runtime Contract

```text
Structured Business Request
+ Approved Context Package
→ { sql, used_assets, used_metrics }
```

sLLM은 자유 Schema 탐색, Metric·JOIN 창작, Permission 판단, SQL 실행과 결과 검증을 하지 않는다.

G2 실패 후 수정은 정형 오류와 허용된 Context만 전달해 최대 1회 허용한다. 두 번째 실패는 종료 상태로 기록한다.

## 9. G2 — SQL Policy Gate

### 9.1 SQLGlot과 프로젝트 정책

SQLGlot은 SQL을 AST로 분석하는 도구이며 보안 경계 전체가 아니다.

```text
SQLGlot parse
+ Answervice AST allowlist
+ Asset/Column permission
+ Metric/JOIN/Time policy
= G2 decision
```

파싱 실패, 복수 statement, 알 수 없는 AST node나 dialect 불일치는 차단한다.

### 9.2 허용·차단 기준

허용 기준:

- 단일 read query
- Approved Context에 포함된 catalog/schema/table/column
- 승인 JOIN과 Metric 표현
- 허용된 함수와 query complexity

명시 차단:

- `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- `CREATE`, `ALTER`, `DROP`
- `CALL`, connector procedure
- `system.execute(...)`
- connector passthrough `query(...)`
- SQL Server `procedure(...)`
- 권한 밖 자산·컬럼과 승인되지 않은 JOIN

`query(...)`가 읽기만 수행할 수 있더라도 내부 SQL이 Trino의 일반 분석을 우회하므로 MVP 사용자 경로에서는 차단한다.

### 9.3 실행 계층 방어

G2 통과 뒤에도 다음을 적용한다.

- Trino 사용자와 catalog access control
- Source DB read-only 계정
- query timeout, resource group, cancellation
- 결과 row/column/payload cap
- query ID와 source error 기록

`LIMIT`만으로 scan 비용이나 실행 시간을 통제할 수 없다는 점을 명시한다.

## 10. Trino Query Layer

Trino는 5개 catalog를 하나의 SQL 인터페이스로 조회한다.

필수 통합 검증:

1. 각 Source 단독 조회
2. 대표 2 Source JOIN
3. Golden Scenario 3 Source JOIN
4. date/timezone/decimal/null/type mapping
5. read-only와 connector 우회 경로 차단
6. timeout·cancellation·row cap
7. Source 장애와 query ID 추적
8. single/2-source/3-source latency와 scanned data 실측

Federated JOIN은 query-time 데이터 이동이 발생할 수 있다. connector pushdown, 통계, 네트워크와 join order를 실측하고 큰 테이블을 무조건 교차 JOIN하지 않는다.

## 11. G3 — Result Validation Gate

G3는 결과가 업무 정답임을 보증하지 않는다. 사용자·GPT·Report에 내보내기 전 마지막 정형 검사를 담당한다.

| 검사 | 예 |
|---|---|
| Result Schema | 기대 column과 type 일치 |
| Row/Column/Payload Size | UI·GPT 전달 한도 |
| JOIN Amplification | join 전후 row 수와 distinct business key 변화 |
| Metric Invariant | 합계 관계, 음수 허용 정책, 비율 범위 |
| Empty Result | 정상 0건과 Context 오류 후보 구분 |
| Sensitive Data | 금지 column/pattern 노출 |

대표 상태:

```text
PASS
EMPTY_RESULT
SCHEMA_MISMATCH
JOIN_AMPLIFICATION
RANGE_VIOLATION
BLOCKED_SENSITIVE_DATA
RESULT_TOO_LARGE
```

G2에서 민감 Column 조회 자체를 막는 것이 우선이며 G3 masking은 최후의 출력 방어다. Raw Result는 G3 이전에 외부 GPT나 UI로 보내지 않는다.

## 12. Result Shaper와 Narrator

```text
Raw Result
→ G3
→ 필요한 column/row 선택
→ masking / redaction
→ type·정렬·chart spec 정규화
→ Safe Result
→ GPT Narrator / UI / Report
```

Narrator는 Safe Result의 숫자와 기간을 그대로 사용하고, 근거 없는 인과관계를 만들지 않는다. 숫자 충실도는 코드로 비교하고, LLM judge만으로 평가하지 않는다.

## 13. 저장 모델

### 13.1 Analysis Definition

분석의 의미와 재실행 가능한 Parameter Schema를 보관한다.

- canonical semantic request
- metrics / dimensions / filter schema
- period rule / analysis type
- owner / version / status

### 13.2 Analysis Run

이번 실행의 실제 조건과 근거를 보관한다.

- user / request_id / as_of / resolved period
- parameter values
- context / binding / rule / policy / model Version
- 실행 SQL 또는 안전하게 redaction한 SQL 기록
- G1/G2/G3 결과
- Trino query ID / freshness / timestamps / status

### 13.3 Analysis Result

- result schema / shaped result
- chart spec / explanation
- evidence / provenance
- validation result

Run과 Result는 덮어쓰지 않는다. 보존 기간과 접근 권한은 데이터 민감도에 따라 별도 정책으로 설정한다.

## 14. Report Core

Report는 `Analysis Definition`을 참조하는 Block의 묶음이다. `report_as_of` 하나로 각 Block의 상대 기간을 계산하고 새 `Analysis Run`을 만든다.

상태는 `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`로 구분한다. 실패 Block에 과거 결과를 이번 결과처럼 표시하지 않으며, 화면에 실패 원인과 마지막 성공 시각을 분리해 보여준다.

## 15. Orchestrator 상태와 Trace

최소 단계:

```text
RECEIVED
→ INTERPRETING
→ BUILDING_CONTEXT
→ G1_CHECK
→ RESOLVING
→ GENERATING_SQL (신규일 때만)
→ G2_CHECK
→ QUERYING
→ G3_CHECK
→ SHAPING
→ NARRATING
→ PERSISTING
→ SUCCEEDED | BLOCKED | FAILED | CANCELLED
```

Trace에는 `request_id`, stage, duration, retry, status, error code, 사용 Version과 query ID를 기록한다. Secret, 불필요한 개인정보, 전체 민감 Raw Result와 private chain-of-thought는 저장하지 않는다.

## 16. Core 완료 기준

대표 질문으로 다음을 증명한다.

- Permission 범위의 3 Source Metadata와 Binding 검색
- Metric/JOIN/Time/Identity Rule 적용
- G1 통과와 재사용/신규 분기
- 신규 경로의 sLLM SQL 생성과 G2 통과
- Trino 3 Source read-only 조회
- G3와 Safe Result 생성
- GPT 설명의 숫자·기간 충실도
- Analysis 저장과 기간 변경 재실행
- Report 수동 실행과 과거 Run 보존
- request_id에서 결과까지 이어지는 Trace

다음 문서: [02. sLLM 모델·학습·평가](02_Answervice_sLLM_모델_학습_평가.md)
