# Canonical Semantic Graph 기반 DataHub 점진 전환 통합 평가

> 작성일: 2026-08-20
>
> 코드 기준: 현재 작업 트리, Git HEAD `14fab5d1`
>
> 문서 목적: 기존 DataHub 구조 평가와 추가 제안인 Canonical Semantic Graph, 질문 등급, JOIN 권한, Release 전환 전략을 하나의 실행 가능한 목표 구조로 통합
>
> 증거 범위: 저장소 코드·설정, DataHub 1.7 및 Trino 공식 문서, Pinterest 공개 실사용 사례
>
> 증거 한계: live DataHub·Backend·Trino E2E 및 부하 측정을 수행한 결과가 아니므로 production-ready 판정 문서는 아님

---

## 1. 서론

### 1.1 배경

현재 프로젝트는 DataHub의 Dataset·Schema·Domain·Owner·Glossary를 사용하면서, 실행에 필요한 Metric·JOIN·시간·권한 계약을 Dataset custom properties의 `metric_rules`, `join_graph`, `time_rules`, `entitlements` 등에 저장한다. Backend는 DataHub의 active release 전체를 읽어 질문과 관련된 Dataset을 검색하고, 권한 필터와 JOIN subgraph 확장을 거쳐 SQL Context를 만든다.

이 구조는 이미 다음 안전장치를 갖고 있다.

- Dataset과 Metric별 Role·PII 권한 검사
- equality JOIN key와 cardinality 검사
- temporal JOIN predicate 검사
- fan-out 방지를 위한 pre-aggregation grain 검사
- Metric별 `allowed_join_ids` 검사
- release·manifest·semantic·Trino schema checksum 검사
- SQLGlot AST 기반 read-only SQL 검증

그러나 DataHub 네이티브 Metric/Semantic Model이 도입되면 기존 custom property와 새 Entity가 동시에 존재할 수 있다. SQL 생성기와 SQL Guard가 두 형식을 직접 이해하게 만들면 이중 정책 엔진이 생기고, 같은 관계가 서로 다른 값으로 발행될 위험이 있다.

### 1.2 통합 결론

**가장 안전한 전략은 Backend 내부에 versioned `Canonical Semantic Graph`를 먼저 만들고, 기존 JSON과 DataHub native metadata를 각각 Canonical Graph로 변환한 뒤 Release 단위로 원본을 점진 전환하는 것이다.**

다음 접근은 피해야 한다.

- 기존 JSON을 먼저 제거하고 DataHub native 기능에 즉시 의존
- legacy JSON과 native graph를 동시에 수정 가능한 운영 원본으로 유지
- Native Lineage를 분석 JOIN 승인 근거로 사용
- DataHub 검색 결과를 Backend entitlement 검사 없이 LLM에 전달
- Metric expression 또는 JOIN key를 LLM이 새로 생성하도록 허용
- 권한 거부·checksum 불일치·미승인 JOIN을 legacy 값으로 우회

### 1.3 추가 제안에 대한 판정 요약

| 추가 제안 | 판정 | 반영 방식 |
|---|---|---|
| Canonical Semantic Graph 선도입 | 채택 | 모든 runtime consumer가 이 계약만 읽도록 전환 |
| DataHub native graph shadow 발행 | 채택 | 실행에는 사용하지 않고 동등성 비교부터 수행 |
| 도메인별 전체 Release 전환 | 채택 | Dataset 단위 혼합 전환 금지 |
| 승인 Metric 밖 Measure 임시 분석 | 조건부 채택 | 현재 P0 밖의 별도 capability로 승인·표시·감사 필요 |
| Raw exploration | 보류 | PII·Trino principal·resource policy 확정 후 P2로 도입 |
| 권한 교집합에 JOIN edge 포함 | 채택 | Dataset 권한만으로 JOIN 승인 금지 |
| DataHub 장애 시 이전 Release 사용 | 현재 계약에서는 미채택 | 권위 있는 immutable replicated release를 별도 ADR로 승인한 경우만 재검토 |
| 질문 시 전체 snapshot 제거 | 채택 | release 생성·감사 경로와 request 경로를 분리 |

---

## 2. 본론

### 2.1 목표 처리 흐름

```text
사용자 질문
  ↓
인증된 사용자 Role·Domain·Capability 확인
  ↓
권한 범위 내 Metric·Measure·Dimension·Semantic Model 후보 검색
  ↓
후보에 대한 exact entitlement 검사
  ↓
Canonical Semantic Graph에서 필요한 subgraph만 구성
  ├─ Dataset / Dimension / Measure / Metric
  ├─ JOIN edge / cardinality / grain
  ├─ temporal predicate / pre-aggregation
  └─ Metric·Measure·Column·edge permission
  ↓
질문의 기간·지표·차원·필터·비교·정렬 slot 확정
  ↓
결정론적 SQL Plan
  ↓
SQLGlot AST Guard + 서버 소유 parameter binding
  ↓
Trino 최종 접근 제어와 실행
  ↓
결과·근거·release·lineage·권한 receipt 저장
```

이 흐름에서 LLM은 질문 해석과 후보 SQL 표현을 도울 수 있지만, Metric 계산식·JOIN key·권한·최종 실행 여부를 결정하지 않는다.

### 2.2 저장 위치별 책임

| 위치 | 권위 있는 책임 | 두지 말아야 할 책임 |
|---|---|---|
| DataHub Dataset | 물리·논리 Dataset identity, schema, field, owner, domain, glossary, lifecycle | 질문별 SQL Plan |
| DataHub Metric Entity | 공인 Metric 이름·정의·expression·semantic model 연결·governance | 사용자별 최종 실행 승인 |
| Semantic Model | Dataset 구성, 의미적으로 허용된 relationship, cardinality, dimension/measure 문맥 | temporal·preaggregation 등 프로젝트 전용 정책의 임의 기본값 |
| Semantic Model Dataset field | `DIMENSION`, `MEASURE`, `FILTER` 의미 주석과 expression | 독립 Entity라고 가정한 별도 identity |
| Native Lineage | 데이터 출처, 변환 흐름, 영향 분석 | 분석 JOIN 허용 여부 |
| Structured Property | 승인 상태, 분류, additivity, release ID처럼 단순하고 검색 가능한 typed 값 | 큰 중첩 Graph·predicate 문서 |
| AnswerService typed Aspect | temporal JOIN, preaggregation, Metric-edge 제한, edge permission, policy version/checksum | 물리 schema의 복제 |
| Release Registry | Entity·Aspect·Trino schema checksum과 active pointer | 질문별 임시 Context |
| Backend | 검색, entitlement 교집합, subgraph, SQL Plan·AST 검증 | 실제 데이터 저장소 ACL을 대체 |
| Trino | catalog/schema/table/column/row 접근, read-only, resource 제한 | Metric 의미 해석 |

#### DataHub 1.7 모델에 대한 정정

추가 제안에서는 Dimension과 Measure를 DataHub native entity로 표현했지만, DataHub 1.7 공식 문서상 핵심 최상위 Entity는 `Metric`과 `Semantic Model`이다. Dimension·Measure·Filter는 Semantic Model이 노출하는 logical Dataset field의 의미 주석으로 설명된다. 따라서 Canonical Graph에서는 Dimension·Measure를 독립 node로 정규화할 수 있지만, DataHub 저장 adapter는 이를 무조건 독립 Entity URN으로 가정하면 안 된다. [DataHub Metrics & Semantic Models](https://docs.datahub.com/docs/features/feature-guides/metrics-and-semantic-models)

### 2.3 Canonical Semantic Graph의 역할

Canonical Semantic Graph는 DataHub의 새 기능 이름이 아니라 **Backend 내부의 단일 typed runtime 계약**이다. 저장 형식이 legacy JSON인지 DataHub native Entity인지와 관계없이 SQL 생성기와 Guard에 동일한 구조를 제공한다.

```text
Legacy Dataset customProperties ─┐
                                ├─ Adapter → Canonical Semantic Graph
DataHub native Entity/Aspect ───┘
                                             ↓
                   Search / Context / Planner / SQL Guard
```

#### 최소 계약 범위

| 영역 | 필수 정보 |
|---|---|
| Graph header | contract version, release ID, source kind, generated-at, checksum |
| Asset node | Dataset URN/FQN, schema version, grain, key, domain, owner, lifecycle |
| Field node | physical type, semantic role, PII, aggregation capability, glossary |
| Metric node | Metric URN/ID, visibility, expression AST evidence, grain, required filter, permission |
| Measure node | source field/expression, allowed aggregation, unit, additivity, permission |
| Dimension node | source field/expression, allowed filter/group behavior, PII |
| JOIN edge | endpoints, kind, equality conditions, cardinality, direction |
| Edge policy | temporal condition, preaggregation, permission, allowed Metric/Measure |
| Query policy | dialect, read-only, functions, catalogs, limit, parameter contract |
| Evidence | source URN/aspect version, semantic checksum, Trino schema checksum |

Canonical Graph는 raw JSON dictionary가 아니라 versioned schema로 검증된 immutable object여야 한다. consumer는 source-specific key를 읽지 않고 canonical field만 사용해야 한다.

#### 단일 원본 규칙

| 전환 단계 | runtime 권위 원본 | native graph 역할 |
|---|---|---|
| 도입 전 | legacy custom properties | 없음 |
| shadow 단계 | legacy custom properties | 비교용 read-only shadow |
| Release cutover 후 | DataHub native Entity + typed Aspect | runtime 원본 |
| migration 완료 후 | DataHub native Entity + typed Aspect | 유일한 운영 원본 |

shadow 단계에서 두 경로를 동시에 발행하더라도 runtime 원본은 항상 하나만 지정한다.

### 2.4 현재 `join_graph`의 예비 분류

현재 코드에서 확인한 edge 필드는 다음과 같다.

| 현재 필드 | 의미 | 목표 위치 |
|---|---|---|
| `id` | release 안에서 edge 식별 | Canonical edge ID + source relationship URN |
| `left`, `right` | Dataset endpoint | Semantic Model relationship + Canonical edge |
| `kind` | JOIN 종류와 방향 | native 표현 가능 여부 PoC 후 relationship 또는 typed Aspect |
| `cardinality` | one-to-one, many-to-one 등 | Semantic Model relationship |
| `equality_conditions` | 승인 JOIN column 쌍 | Semantic Model relationship, 부족하면 typed Aspect |
| `temporal_conditions` | event time과 validity interval | AnswerService typed Aspect |
| `preaggregation.required` | JOIN 전 선집계 필요 여부 | AnswerService typed Aspect |
| `preaggregation.grain` | 선집계 grain | AnswerService typed Aspect |
| `preaggregation.keys` | 선집계 key | AnswerService typed Aspect |
| Metric `allowed_join_ids` | Metric별 허용 edge | AnswerService typed Aspect |
| Dataset/Metric roles | 자산·Metric 권한 | native governance reference + typed policy |

현재 주요 사용처도 분리되어 있다.

- metadata 발행·계약 검증: `metadata_contract.py`, `metric_governance_contract.py`
- DataHub runtime parsing: `datahub_metadata.py`
- 검색 후 관계 확장: `query_governance.py`, `query_join_graph.py`
- Context 정규화: `runtime_contracts.py`, `contract.py`
- Metric별 Graph 축소: `metric_execution_scope.py`
- SQL AST JOIN 검증: `sql_guard/join_semantics.py`
- release reconstruction/checksum: `release_manifest.py`

이 표는 예비 inventory다. 0단계 완료를 선언하려면 production·publication·verification·test 전체에서 각 field의 read/write 위치와 checksum 포함 여부를 기계적으로 전수 조사해야 한다.

### 2.5 승인된 Metric 밖 질문의 3등급 처리

#### 등급 1: 승인 Business Metric

- DataHub Metric Entity 또는 현재 승인 Metric Rule의 공인 expression 사용
- 승인된 Dimension·JOIN·time·permission 계약만 사용
- 일반 사용자에게 제공 가능한 기본 분석 경로
- 결과에 Metric URN, 정의, owner, release/checksum을 근거로 표시

이 경로는 현재 P0 제품 계약과 가장 잘 맞는다.

#### 등급 2: 승인 Measure 기반 임시 분석

공식 Business Metric이 없어도 이미 승인된 Measure를 허용 aggregation으로 계산하는 경로다. 예를 들어 `room_charge_amount`가 Measure로 승인되고 `SUM`이 허용되어 있다면 임시 합계를 만들 수 있다.

다만 “승인 Metric 밖 질문”을 허용한다는 이유로 계산식을 자유 생성해서는 안 된다. 최소 조건은 다음과 같다.

- Measure source field/expression이 승인됨
- `SUM`, `COUNT`, `AVG` 등 Measure별 allowed aggregation이 선언됨
- grain·unit·null·currency·time semantics가 선언됨
- 사용할 Dimension과 JOIN edge가 승인됨
- Metric이 아니라는 상태가 응답·artifact·report에 명확히 표시됨
- 공식 Metric과 이름이 충돌하거나 공식 KPI처럼 저장·재사용되지 않음
- 결과 재현을 위해 canonical plan과 release/checksum을 저장함
- ratio, 통합매출, 이벤트 효과, VOC처럼 업무 판단이 필요한 조합은 `REVIEW_REQUIRED`로 차단함

현재 제품 문서는 미승인 Metric을 fail-closed하도록 정의한다. 따라서 이 등급은 기존 P0 동작을 조용히 바꾸는 수정이 아니라, `AD_HOC_MEASURE_ANALYSIS` 같은 별도 capability와 승인 정책을 갖는 후속 범위로 도입해야 한다.

#### 등급 3: Raw exploration

- 별도 권한을 가진 사용자만 허용
- 가능하면 원천 table보다 승인된 serving view 우선
- raw Dataset·Column·JOIN edge·filter가 모두 허용된 경우만 Context에 포함
- PII column은 차단 또는 Trino row filter/column mask 적용
- SQL Guard와 Trino access control을 모두 통과해야 실행
- query timeout, scan limit, row limit, concurrency/resource group 필요
- 결과를 공식 Metric과 동일한 신뢰도로 표시하지 않음

현재 Trino가 공용 `answervice_runtime` principal을 사용하므로 앱 사용자별 raw 권한을 Trino가 직접 구분하지 못한다. 사용자/group/role 매핑 또는 capability별 최소권한 principal이 마련되기 전에는 이 등급을 production에 활성화하면 안 된다.

### 2.6 권한 교집합 모델

최종 실행 가능 범위는 다음 교집합이다.

```text
authenticated user role/domain/capability
∩ Dataset entitlement
∩ Column entitlement 및 PII policy
∩ Metric/Measure entitlement
∩ Semantic relationship validity
∩ JOIN edge permission
∩ temporal/preaggregation policy
∩ raw exploration capability
∩ Trino principal ACL
```

#### 권한 검사 순서

1. 사용자 identity와 Role·Domain·capability를 서버에서 확정한다.
2. 검색 전에 가능한 범위에서 permission-aware index namespace를 제한한다.
3. 검색 결과의 Dataset·Metric·Measure·Dimension entitlement를 exact 검사한다.
4. 허용된 seed만 Canonical Graph에서 확장한다.
5. 경유 Dataset·Column·edge를 포함한 전체 subgraph를 다시 exact 검사한다.
6. 권한 밖 node와 edge는 LLM Context에 넣지 않는다.
7. 생성 SQL이 exact subgraph만 사용하는지 AST로 검증한다.
8. Trino가 별도 ACL로 실제 접근을 다시 거부 또는 허용한다.

A와 B Dataset을 각각 볼 수 있어도 `A.customer_id = B.customer_id`가 식별 가능성을 높인다면 edge permission에서 별도로 차단할 수 있어야 한다. 권한 거부에는 legacy JSON, stale cache, 다른 edge로의 자동 우회를 허용하지 않는다.

### 2.7 Native Lineage와 JOIN Graph의 분리

| 구분 | Native Lineage | Semantic relationship / edge policy |
|---|---|---|
| 질문 | 어디서 생성되어 어디로 흐르는가 | 분석에서 어떻게 결합해도 되는가 |
| 용도 | 출처, 영향 분석, evidence | SQL JOIN 계획과 검증 |
| 자동 승인 | 불가 | 명시적 승인 관계만 가능 |
| cardinality | 필수 아님 | 필수 |
| temporal/preaggregation | 표현 목적이 아님 | 실행 정책으로 필수 가능 |
| 권한 | metadata 조회 권한 | Dataset·Column·Metric·edge 권한 교집합 |

Lineage edge가 존재한다는 이유만으로 Canonical JOIN edge를 생성하면 안 된다. lineage에서 후보를 발견할 수는 있지만 owner 검토와 relationship/policy 발행 전에는 실행 불가능한 후보여야 한다.

### 2.8 Release와 fallback 정책

#### Release 단위

```text
Semantic Release
├─ release ID / predecessor checksum
├─ Dataset·Schema 전체
├─ Semantic Model·Relationship 전체
├─ Metric·Measure·Dimension 전체
├─ Typed policy aspects 전체
├─ 권한 및 query policy
├─ Trino schema/access-policy checksum
└─ canonical graph checksum
```

Dataset 하나만 새 구조로 읽고 나머지는 legacy로 읽는 혼합 Release는 허용하지 않는다. shadow 비교가 모두 통과한 도메인 Release의 active pointer만 원자적으로 변경한다.

#### 허용되지 않는 fallback

- 권한 거부를 legacy entitlement로 재시도
- native Graph에 없는 JOIN edge를 legacy `join_graph`에서 보충
- checksum·schema drift를 이전 값으로 숨김
- temporal/preaggregation 위반을 단순 JOIN으로 강등
- 미승인 Metric expression을 Measure 조합으로 가장
- DataHub 장애 시 만료된 process snapshot으로 성공 응답

#### DataHub 장애 시 이전 Release 사용 제안에 대한 판단

현재 프로젝트의 권위 문서는 DataHub refresh 실패 시 stale/local fallback 없이 `METADATA_UNAVAILABLE`로 닫도록 명시한다. 그러므로 단순히 “직전 검증 Release였으므로 사용”하는 fallback은 현재 계약과 충돌한다.

이 동작을 바꾸려면 별도 ADR에서 다음을 모두 충족하는 **권위 있는 replicated active-release read model**을 정의해야 한다.

- DataHub publish/read-back으로 생성된 immutable artifact
- release ID, predecessor, 모든 source URN/aspect version/checksum 포함
- 서명 또는 신뢰 가능한 service identity의 발행 receipt
- 명시적 유효기간과 폐기 조건
- current active pointer의 원자적 복제
- DataHub 복구 후 exact reconciliation
- 장애 중 허용되는 질문·데이터 민감도·최대 지속 시간
- 감사 log와 운영 책임자

이 조건이 승인되면 이는 “legacy JSON fallback”이 아니라 DataHub의 권위 있는 release를 복제한 별도 read model이다. 현재 문서와 코드가 그대로인 동안에는 DataHub 장애를 typed error로 처리해야 한다.

### 2.9 단계별 전환 전략

#### 0단계: 계약과 현황 고정

작업:

- `join_graph`, Metric Rule, time, entitlement, query policy 전체 field inventory
- field별 writer, reader, validator, checksum, test 추적
- native relationship / typed Aspect / Backend-only field 분류
- versioning, predecessor, rollback, retirement 규칙 ADR 작성
- 현재 생성 SQL과 typed error golden evidence 확보

완료 기준:

- 현재 field 100%에 목표 위치와 권위 owner가 지정됨
- orphan·unused·duplicate field가 구분됨
- 권한과 rollback 규칙에 미결정 항목이 없음

#### 1단계: Canonical Graph 도입

```text
Legacy JSON → LegacyGraphAdapter → Canonical Semantic Graph
```

작업:

- versioned canonical types와 validator 작성
- 기존 JSON adapter 작성
- Search, Context, Planner, SQL Guard의 source-specific 참조 제거
- canonical checksum과 legacy checksum 동등성 테스트

완료 기준:

- 기존 대표 질문과 programmatic archetype의 SQL AST가 동일
- 기존 typed error code와 권한 거부 결과가 동일
- 모든 JOIN edge·Metric·policy checksum이 동일
- Trino·Iceberg schema와 query 결과에 변경이 없음

#### 2단계: DataHub native shadow 발행

```text
Legacy custom properties ──→ Legacy Adapter ─┐
                                             ├─ Canonical Graph Comparator
Native Entity + Typed Aspect → Native Adapter ┘
```

비교 항목:

- Dataset·field 집합
- Metric·Measure·Dimension 정의
- JOIN endpoints·key·kind·cardinality
- temporal condition·preaggregation
- Metric별 allowed edge·permission
- release·source aspect version·checksum

완료 기준:

- native 경로는 실행에 사용되지 않음
- 전체 release exact equality 통과
- 차이는 사람이 읽을 수 있는 typed diff로 출력
- 불일치 release는 cutover 불가

#### 3단계: 도메인 Release 전환

작업:

- 도메인의 전체 Semantic Release를 한 번에 활성화
- active pointer CAS와 predecessor checksum 검사
- read-back 후 canonical checksum 재검증
- cutover 전후 query/authorization negative test

rollback:

- 데이터·권한 계약이 바뀌지 않은 직전 검증 release로 active pointer를 명시적으로 복구
- 권한·checksum 오류를 요청 중 자동 fallback하지 않음
- rollback도 감사 가능한 운영 transition으로 기록

#### 4단계: 범용 질문과 2-Pass 검색

Pass 1:

- 현재 사용자 권한 범위에서 Semantic Model, Metric, Measure, Dimension 후보 검색
- 상위 후보 수는 고정값을 맹목적으로 사용하지 않고 recall·latency 평가로 결정
- DataHub 1.7 universal Metric search가 불완전하면 active release에서 재생성 가능한 경량 index 사용

Pass 2:

- 후보의 승인 정의만으로 metric/measure, period, dimension, comparison, filter, sort, Top-N slot 확정
- 동률이나 의미 변경 가능성이 있으면 사용자에게 확인
- 질문 원문을 SQL policy에 전달하지 않음

지원 범위는 특정 문장이 아니라 다음 typed operation으로 정의한다.

- 집계
- 기간별 추이
- 전기·전년 비교
- 차원별 분해
- 순위와 Top-N
- 비중
- 복수 Metric
- 허용된 다중 JOIN
- 별도 capability의 Measure 기반 임시 분석

#### 5단계: request snapshot과 legacy 축소

```text
전체 DataHub catalog
  ↓ publish/change 시 검증
Active Release Canonical Graph
  ↓ 권한 projection과 검색 index 생성
요청 시 필요한 subgraph만 조회
```

전체 snapshot은 다음 목적으로만 유지한다.

- Release 완전성 검사
- 고아 Dataset/Metric/relationship 탐지
- checksum 및 감사 evidence 생성
- 복구·reconciliation

마지막 도메인이 전환되고 rollback 보존 기간이 끝난 뒤에만 Dataset별 `join_graph` 복제와 legacy adapter를 제거한다.

### 2.10 검증 전략

#### 개발 중 빠른 검증

- Canonical schema contract test
- Legacy/Native adapter unit test
- canonicalization determinism test
- field 누락·중복·unknown key test
- SQL AST와 typed error 회귀 test

#### Release 전환 검증

- 전체 Graph exact equality와 checksum
- Dataset·Column·Metric·Measure·edge 권한 negative test
- lineage-only edge 실행 거부 test
- temporal JOIN interval과 fan-out/preaggregation test
- native aspect 누락·schema drift·checksum mismatch fail-closed test
- active pointer CAS와 rollback transition test

#### 도메인 완료 검증

- 실제 DataHub publish/read-back
- 실제 Backend 인증 principal
- 실제 Trino 허용·거부 principal
- Frontend 결과·근거·임시 분석 표시
- E2E latency와 검색 recall
- DataHub 장애, timeout, cancellation, release race

#### 필수 보안 불변식

| 불변식 | 기대 결과 |
|---|---|
| Lineage만 있고 approved relationship이 없음 | JOIN 거부 |
| Dataset 둘은 허용되지만 edge는 금지 | Context 노출과 SQL 실행 모두 거부 |
| Column 또는 PII 권한 없음 | LLM 입력에도 포함하지 않음 |
| temporal predicate 누락 | SQL Guard 거부 |
| many-side 선집계 누락 | fan-out 위험으로 거부 |
| native와 legacy checksum 불일치 | cutover 거부 |
| 권한 거부 후 legacy fallback 시도 | 금지 |
| 미승인 계산식 생성 | Metric/Measure resolver에서 거부 |
| DataHub refresh 실패와 cache 만료 | `METADATA_UNAVAILABLE` |

### 2.11 LLM 평가와 인터넷 조사 비교

| 쟁점 | LLM 아키텍처 평가 | 공식 문서·실사용 조사 | 통합 판단 |
|---|---|---|---|
| Canonical Graph | source 형식과 runtime consumer를 분리하는 데 효과적 | DataHub는 Entity/Aspect schema-first 모델을 사용 | 선도입 권장 |
| Native Metric/Semantic Model | 장기 원본으로 적합 | DataHub 1.7에서 제공되지만 Beta | shadow 검증 후 전환 |
| Dimension/Measure | Canonical node로 정규화 가능 | DataHub에서는 logical Dataset field annotation 중심 | adapter에서 차이를 흡수 |
| 관계 subgraph | 최소 Context와 권한 안전성에 유리 | Pinterest도 관련 table과 검증된 JOIN 패턴을 선별 | 채택 |
| 전체 snapshot 제거 | request latency와 노출 범위 개선 | 대규모 사례는 별도 검색/index 계층 사용 | release 검증 경로에는 유지 |
| 3등급 질문 처리 | 활용도는 높지만 신뢰도 경계 필요 | DataHub는 정의를 catalog하며 계산 실행은 외부 계층 책임 | capability와 표시를 분리해 조건부 도입 |
| OSS 검색 권한 | Backend exact filter 필요 | OSS query-time Search Access Control 미지원 | 필수 유지 |
| Trino 최종 권한 | 공용 principal로는 사용자별 방어선 미완성 | Trino는 user/group/role, row filter, column mask 지원 | principal/ACL 강화 선행 |

DataHub 공식 문서는 Metric/Semantic Model을 Beta로 제공하지만 universal Search와 MCP 검색은 향후 범위로 설명한다. 따라서 native Entity 전환과 request 검색 전환을 하나의 단계로 묶지 않아야 한다. [DataHub Metrics & Semantic Models](https://docs.datahub.com/docs/features/feature-guides/metrics-and-semantic-models)

Self-hosted OSS의 `VIEW_AUTHORIZATION_ENABLED`는 query-time search filtering을 제공하지 않으므로 permission-aware index가 있더라도 Backend exact entitlement 검사가 최종 기준이어야 한다. [DataHub Search Access Controls](https://docs.datahub.com/docs/features/feature-guides/search-access-controls)

Pinterest는 DataHub 기반 PinCat을 metadata 원본으로 사용하면서 별도 table/query index, 검증된 JOIN·filter·aggregation 패턴, Presto `EXPLAIN`을 조합한다. DataHub 하나에 모든 검색과 실행 정책을 맡기지 않는다는 점이 이 전환안과 유사하다. [Pinterest Engineering 실사용 사례](https://medium.com/pinterest-engineering/unified-context-intent-embeddings-for-scalable-text-to-sql-793635e60aac)

Trino는 file, OPA, Ranger 등의 system access control과 user/group/role 기반 규칙, row filter, column mask를 지원한다. 현재 프로젝트의 공용 runtime principal보다 세밀한 최종 방어선 구현이 가능하다. [Trino Security Overview](https://trino.io/docs/current/security/overview.html), [Trino File-based Access Control](https://trino.io/docs/current/security/file-system-access-control.html)

### 2.12 운영 결정 전 미확정 항목

이 문서는 구조 방향을 제시하지만 다음 값이 없으므로 성능·가용성 설계를 확정하지 않는다.

- read/write 비율과 1년 후 p99 QPS
- tenancy 모델
- 동기·비동기 경계와 cache 갱신 방식
- PII/PHI/PCI 등 데이터 민감도 등급
- p50/p95/p99 검색·Graph 구성·전체 분석 latency 목표
- uptime/SLO와 error budget 책임자
- Release Registry와 Canonical projection의 RPO/RTO
- Raw exploration의 scan·동시성·timeout 한도

도입 전 현재 request 경로의 baseline을 측정하고 숫자 기준을 ADR에 추가해야 한다. 권한 누출, 미승인 edge 실행, checksum 혼합, AST 우회는 성능 목표와 무관하게 허용치 0건으로 둔다.

---

## 3. 결론

### 3.1 LLM 평가 결론

Canonical Semantic Graph 선도입은 추가 제안에서 가장 가치가 높은 부분이다. 기존 JSON과 DataHub native graph 사이에 단일 typed 계약을 두면 Search·Context·SQL Planner·Guard가 저장 형식 변화에서 분리되고, shadow 비교와 도메인별 cutover가 가능해진다.

승인 Metric 밖 질문을 Measure 기반으로 처리하는 것도 활용도를 높일 수 있다. 그러나 현재 P0의 “미승인 Metric fail-closed” 원칙을 약화해서는 안 된다. 승인된 Measure·aggregation·grain·Dimension·edge만 사용하고 결과를 비공식 임시 분석으로 표시하는 별도 capability로 도입해야 한다. Raw exploration은 Trino 사용자별 권한과 PII 정책이 준비된 뒤의 범위다.

### 3.2 인터넷 조사 결론

DataHub 1.7의 native Metric/Semantic Model은 목표 구조와 맞지만 Beta이고 universal search가 완성된 상태는 아니다. OSS 검색 권한도 Backend 필터를 대체하지 못한다. Pinterest 사례 역시 DataHub 기반 카탈로그와 별도 검색/index 및 SQL 검증 계층을 조합한다. 인터넷 조사 결과는 DataHub에 즉시 전부 위임하는 방식보다 Canonical Graph와 재생성 가능한 검색 projection을 사이에 두는 점진 전환을 지지한다.

### 3.3 최종 결론

**통합 권고안은 `Legacy → Canonical Graph → Native shadow → Release cutover → request 경량화 → legacy 제거` 순서다.**

가장 먼저 진행할 개발 묶음은 다음 세 가지다.

1. 현재 `join_graph`, Metric, time, entitlement field와 모든 사용처를 전수 목록화한다.
2. versioned Canonical Semantic Graph 계약과 checksum 규칙을 정의한다.
3. Legacy JSON Adapter와 Graph 동등성·SQL AST·typed error 회귀 테스트를 구현한다.

이 단계에서는 사용자 동작, 생성 SQL, Trino query, Iceberg schema를 바꾸지 않는다. 이후 native 발행은 read-only shadow로 시작하며 전체 Semantic Release가 동등할 때만 원본을 전환한다.

추가 제안 중 유일하게 그대로 수용할 수 없는 부분은 현재 계약 아래의 DataHub 장애 fallback이다. 별도의 권위 있는 replicated release 설계가 승인되기 전에는 DataHub·catalog·checksum 문제를 typed error로 닫아야 한다. 이 원칙과 Trino 최종 권한 집행을 지키면 Canonical Graph 전략은 기존 기능을 보존하면서 DataHub native 모델로 이동하는 가장 안전한 경로다.

---

## 참고 자료

- [DataHub Metrics & Semantic Models](https://docs.datahub.com/docs/features/feature-guides/metrics-and-semantic-models)
- [DataHub Search Access Controls](https://docs.datahub.com/docs/features/feature-guides/search-access-controls)
- [DataHub Custom Properties Overview](https://docs.datahub.com/docs/features/feature-guides/properties/overview)
- [DataHub Metadata Model](https://github.com/datahub-project/datahub/blob/master/docs/modeling/metadata-model.md)
- [DataHub Entity Registry](https://github.com/datahub-project/datahub/blob/master/metadata-models/src/main/resources/entity-registry.yml)
- [Trino Security Overview](https://trino.io/docs/current/security/overview.html)
- [Trino System Access Control](https://trino.io/docs/current/security/built-in-system-access-control.html)
- [Trino File-based Access Control](https://trino.io/docs/current/security/file-system-access-control.html)
- [Pinterest Engineering: Unified Context-Intent Embeddings for Scalable Text-to-SQL](https://medium.com/pinterest-engineering/unified-context-intent-embeddings-for-scalable-text-to-sql-793635e60aac)
- [Pinterest Engineering: How We Built Text-to-SQL at Pinterest](https://medium.com/pinterest-engineering/how-we-built-text-to-sql-at-pinterest-30bad30dabff)
