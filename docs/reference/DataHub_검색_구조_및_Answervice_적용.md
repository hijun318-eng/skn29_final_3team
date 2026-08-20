# DataHub 검색 구조 및 핵심 개념과 Answervice 적용

> 문서 성격: DataHub 일반 개념을 Answervice의 현재 구현과 비교해 설명하는 참고 자료
>
> 제품 요구사항과 완료 상태의 권위 원본: [`docs/product/01_PRD.md`](../product/01_PRD.md)
>
> 아키텍처와 신뢰 경계의 권위 원본: [`docs/product/03_아키텍처.md`](../product/03_아키텍처.md)

# 1. 서론

DataHub는 PostgreSQL, MySQL, MSSQL, ClickHouse, Trino 등 여러 데이터 시스템에 존재하는 **데이터 자산의 메타데이터를 수집하고 검색·관리하는 플랫폼**이다. 여기서 메타데이터란 실제 매출액이나 고객명 같은 업무 데이터 자체가 아니라 Dataset 이름, Column, 데이터 타입, 설명, Owner, Domain, Glossary, Lineage처럼 데이터를 이해하고 사용할 때 필요한 정보다.

예를 들어 원천 DB에 다음과 같은 예약 데이터가 있다고 하자.

```text
reservation

reservation_id | customer_id | total_amount
------------------------------------------------
1              | 100         | 300000
2              | 101         | 250000
```

DataHub가 주로 관리하는 것은 `300000`, `250000` 같은 실제 행 값이 아니라 다음과 같은 정보다.

```text
Dataset
- reservation

Columns
- reservation_id
- customer_id
- total_amount

Column Description
- total_amount: 승인된 예약 금액 컬럼

Domain
- 호텔 예약

Glossary Term
- 객실매출

Owner / Lifecycle
- 담당 조직 / APPROVED
```

따라서 DataHub가 답하는 핵심 질문은 다음과 같다.

> “우리 조직에 어떤 데이터가 있고, 어디에 있으며, 어떤 의미와 사용 조건을 가지는가?”

Answervice에서는 이 역할을 한 단계 더 엄격하게 사용한다. DataHub 검색 결과를 단순 추천 목록으로 소비하지 않고, 자연어 질문을 **승인된 업무 용어·자산·컬럼·관계·권한 계약**에 연결하는 근거로 사용한다. 실제 값 조회는 DataHub가 아니라 Trino가 담당하고, 분석 이력과 결과·보고서는 App DB에 저장한다.

```text
DataHub = 자산의 의미·위치·관계·승인·권한 계약을 제공
Trino   = 승인된 자산의 실제 행을 읽기 전용 SQL로 조회
App DB  = Analysis Run, Context, query ID, lineage, artifact, 보고서 상태 저장
```

이 구분은 중요하다. 사용자가 “지난달 객실매출을 알려줘”라고 질문했을 때 DataHub가 매출 숫자를 반환하는 것이 아니다. DataHub는 `객실매출`의 승인된 정의와 연결 자산을 제공하고, Backend가 이를 안전한 SQL Context로 만든 뒤 Trino가 숫자를 계산한다.

# 2. 본론

## 2.1 일반적인 DataHub 구조와 Answervice 구성

일반적인 DataHub 구조는 다음과 같이 이해할 수 있다.

```text
여러 데이터 시스템
        │
        │ Connector / Ingestion
        ▼
      DataHub
        ├─ GMS
        ├─ Metadata Store
        ├─ Search Index
        └─ Event 처리 구성요소
        │
        │ GraphQL / Rest.li
        ▼
 Backend / Client
```

Answervice에 대입하면 source와 serving 경계가 더 구체적이다.

```text
PMS PostgreSQL ─────┐
POS MySQL ──────────┤
CRM MSSQL ──────────┤
시설 ClickHouse ────┼─> DataHub ingestion ─> Dataset·Column metadata
연회 PostgreSQL ────┤
Trino serving ──────┘                         + view/column lineage
                                                   │
                                                   ▼
                                            Answervice Backend
                                                   │
                             승인 Context + SQLGlot 정책 검증
                                                   │
                                                   ▼
                                                 Trino
```

원본 문서의 S3는 DataHub가 지원할 수 있는 일반 예시지만, 현재 Answervice runtime recipe의 직접 대상은 PMS, POS, CRM, 시설, 연회 source와 Trino serving이다.

## 2.2 Connector와 Ingestion

일반 DB connector와 DataHub connector의 차이는 다음과 같다.

```text
일반 DB library
= DB에 접속하고 SQL을 실행

DataHub connector
= source에 접속
 + schema·table/view·column·type·description 등 metadata 수집
 + DataHub entity/aspect 형식으로 변환
 + DataHub에 발행
```

Answervice의 ingestion recipe에는 다음 원칙이 적용된다.

- source별 읽기 전용 계정을 사용한다.
- 고정 질문의 답을 위한 table 목록을 production 코드에 복제하지 않는다.
- source의 현재 runtime schema를 발견해 발행한다.
- Trino serving recipe는 table/view와 view·column lineage를 수집한다.
- `information_schema` 같은 시스템 metadata는 업무 Dataset에서 제외한다.
- source 연결, catalog discovery 또는 DataHub sink 발행이 실패하면 준비 완료로 간주하지 않는다.
- 발행 credential과 Backend의 runtime read credential을 분리한다.

여기서 ingestion 성공과 runtime governance 승인은 같은 의미가 아니다. 물리 Dataset과 Column이 DataHub에 등록됐더라도 metric의 grain, 집계 방식, 시간 기준, entitlement가 승인되지 않았다면 분석용 운영 Context로 사용할 수 없다.

## 2.3 Dataset, SchemaField, URN과 Trino FQN

DB의 Table이나 View는 DataHub에서 주로 Dataset으로 표현되고, Column은 SchemaField로 표현된다.

```text
Dataset
└─ reservation
   ├─ reservation_id
   ├─ customer_id
   ├─ total_amount
   └─ check_in_date
```

Answervice에서는 자산 식별자를 두 종류로 구분한다.

```text
DataHub URN
= DataHub entity의 고유 식별자
예: urn:li:dataset:(...)

Trino FQN
= SQL에서 사용하는 catalog.schema.relation 식별자
예: <catalog>.<release_schema>.<relation>
```

URN과 FQN은 서로 대체할 수 없다. Backend는 승인된 DataHub Dataset의 URN, Trino FQN, Column 집합을 하나의 runtime asset 계약으로 연결한다. 이후 SQL은 Context에 포함된 FQN과 Column만 사용할 수 있고, 결과 근거에는 source URN을 보존한다.

다음은 개념 예시이며 실제 운영 자산 이름을 고정한 것이 아니다.

```text
DataHub URN
urn:li:dataset:(urn:li:dataPlatform:trino,
                serving.<release_schema>.room_revenue,
                PROD)

Trino FQN
serving.<release_schema>.room_revenue

승인 Column
- business_date
- hotel_id
- room_revenue
```

## 2.4 Domain, Glossary, Owner와 Lifecycle

Domain은 자산이 속한 큰 업무 영역이고 Glossary Term은 자산이나 지표가 업무적으로 무엇을 의미하는지 설명한다.

```text
Domain
= 어느 업무 영역인가?

Glossary Term
= 업무적으로 무엇을 뜻하며 어떻게 계산하는가?
```

호텔 데이터의 개념 예시는 다음과 같다.

```text
호텔 운영 Domain
├─ 객실
├─ 식음
├─ 연회
└─ 시설

고객 Domain
├─ 고객 기본정보
├─ 고객 등급
└─ VOC
```

```text
Glossary Term: 객실매출
- label
- aliases
- definition
- unit
- aggregation / reduction rule
- owner
- domain
- approval lifecycle
```

일반 DataHub 설명에서는 Glossary를 업무 용어 사전으로만 소개하는 경우가 많다. Answervice에서는 Glossary가 SQL 생성에 전달되는 **운영 metric 계약**이라는 점이 더 중요하다. Term 이름이 같더라도 연결 Dataset, 계산 grain, 시간 규칙 또는 단위가 다르면 같은 metric으로 임의 병합하지 않는다.

또한 Backend는 질문 문장에서 Domain을 추측해 권한을 부여하지 않는다. DataHub에 발행된 Domain과 현재 인증 principal의 entitlement를 비교한다. 미승인 또는 삭제된 Term, Owner·Domain·Lifecycle이 불완전한 Term은 runtime 성공 경로에 들어갈 수 없다.

## 2.5 Lineage와 승인 Join Graph의 차이

Lineage와 join 계약은 관련 있지만 같은 개념은 아니다.

```text
Lineage
= source Dataset이 serving View에 어떻게 흘러왔는지 나타내는 계보

Governed Join Graph
= 분석 SQL에서 어떤 자산·컬럼 관계를 사용할 수 있는지 정한 실행 계약
```

Answervice의 Trino serving ingestion은 view lineage와 column lineage를 수집한다. 반면 runtime join graph는 승인된 release metadata로 별도 관리된다. Lineage에 두 Dataset의 연결이 보인다는 이유만으로 모델이 임의 JOIN을 생성할 수 있는 것은 아니다.

## 2.6 GraphQL Query, Mutation, Resolver와 Rest.li

DataHub는 GraphQL API를 통해 Dataset과 Glossary Term을 검색하고 상세 metadata를 조회할 수 있다.

```graphql
query Search($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    total
    start
    count
    searchResults {
      entity {
        urn
        type
      }
    }
  }
}
```

GraphQL 용어를 정리하면 다음과 같다.

- Query: metadata 조회에 사용한다.
- Mutation: metadata 생성·수정 같은 변경에 사용한다.
- Resolver: GraphQL 요청을 DataHub 내부 처리와 연결하며 DataHub가 구현한다.
- Input Object: `query`, `types`, `start`, `count` 같은 입력 계약이다.

Answervice Backend는 DataHub 내부 Resolver를 구현하지 않는다. 인증된 DataHub API를 호출하는 client 역할을 한다.

다만 DataHub v1.7에서 모든 native governance field가 GraphQL 하나로 exact 검증되는 것은 아니다. Answervice는 Dataset·Term identity와 주요 metadata는 GraphQL로 읽고, Glossary lifecycle과 entity status처럼 권위 범위가 다른 값은 Rest.li aspect read-back으로 교차검증한다. 로컬 기본값이나 mock 응답으로 빠진 값을 보충하지 않는다.

## 2.7 DataHub의 일반 Lexical Search 구조

일반적인 DataHub lexical search는 실제 DB 행이 아니라 검색 가능한 metadata를 대상으로 한다.

```text
검색 대상 예
- Dataset name
- Dataset description
- Column name
- Column description
- Tag
- Glossary Term
- Owner
- Domain
```

DataHub가 사용하는 검색엔진 내부에서는 metadata가 검색 Document로 변환될 수 있다.

```json
{
  "urn": "urn:li:dataset:(...)",
  "name": "room_revenue",
  "description": "호텔 객실 매출 분석용 Dataset",
  "fieldPaths": ["business_date", "hotel_id", "room_revenue"],
  "glossaryTerms": ["객실매출"],
  "domains": ["호텔 운영"]
}
```

검색엔진은 analyzer로 문자열을 token으로 나누고 역색인을 만든다.

```text
일반 Document 구조
Document → 여러 Term

역색인 구조
Term → 해당 Term이 포함된 Document 목록
```

예를 들면 다음과 같다.

```text
room       → Doc1, Doc4
revenue    → Doc1, Doc7
customer   → Doc2, Doc9
```

Lucene 계열 검색엔진은 Term Dictionary, BlockTree, FST, Postings List를 이용해 후보 Document를 찾고 BM25, exact/prefix/phrase match, field boost 등을 조합해 관련도 순위를 계산할 수 있다.

```text
검색어
  ↓ Analyzer
Token
  ↓ Term Dictionary / FST
Postings List
  ↓ Boolean 조건
후보 Document
  ↓ BM25 + Boost
Top-K URN
```

이 설명은 DataHub 자체 검색엔진을 이해할 때 유용하다. 그러나 다음 절에서 설명하듯 현재 Answervice 기본 `lexical` 모드는 이 BM25 Top-K 흐름을 질문 검색에 직접 사용하지 않는다.

## 2.8 Answervice 기본 lexical 검색의 차이

현재 기본 설정은 `DATAHUB_SEARCH_MODE=lexical`이다. 이 모드에서 사용자 질문은 DataHub 검색 query로 전송되지 않는다.

| 일반적인 DataHub 질문 검색 | Answervice 기본 `lexical` 모드 |
|---|---|
| `searchAcrossEntities(query: "객실 매출")` | `searchAcrossEntities(query: "*")` |
| 검색엔진이 BM25로 Top-K 반환 | Backend가 승인 metadata와 질문 token의 교집합으로 순위 계산 |
| Top-K URN만 상세 조회 가능 | runtime-governed catalog 전체를 pagination하고 상세 metadata 검증 |
| 검색 결과를 LLM이 자유롭게 선택 가능 | entitlement·metric dependency·join graph·자산 수·schema 조건으로 서버가 제한 |

기본 lexical 흐름은 다음과 같다.

```text
사용자 질문
"지난달 객실매출을 호텔별로 보여줘"
        │
        ▼
Backend 로컬 token 처리
NFKC 정규화 + casefold + Unicode token화 + 제한적 한국어 조사 분리
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
DataHub Dataset 전체 URN 조회     Glossary Term 전체 URN 조회
query: "*"                        query: "*"
        │                              │
        └───────────┬──────────────────┘
                    ▼
Dataset·Term·Owner·Domain·Lifecycle 상세 read-back
                    ▼
release manifest·membership·count·checksum 검증
                    ▼
질문 token ∩ 승인 metadata token
                    ▼
후보 순위
```

Dataset 쪽 비교 어휘에는 Dataset name·description·FQN·Column name, 연결된 Glossary의 label·aliases·definition, 해당 Dataset dimension aliases가 포함된다. 특정 호텔 질문이나 특정 metric을 위한 정적 정답 SQL·질문별 JSON·고정 keyword map을 운영 원본으로 사용하지 않는다.

## 2.9 Catalog Snapshot, Pagination과 상세 조회

원본 문서에서는 보통 “검색엔진이 Top-K URN을 반환하고 필요한 URN만 batch 조회한다”고 설명한다. 현재 Answervice의 기본 모드는 완전한 runtime release 검증을 위해 다른 전략을 사용한다.

- Dataset과 Glossary Term 목록을 `total`, `start`, `count` 기반으로 끝까지 pagination한다.
- 응답의 중복 URN, 잘못된 entity type, 잘린 page, 최대 entity 수 초과를 거부한다.
- 각 URN의 상세 metadata를 동시성 최대 8개로 조회한다.
- 이는 단일 `batchGet` 호출이 아니라 bounded concurrent fetch다.
- 검증된 snapshot만 5초 동안 single-flight cache로 재사용한다.
- 갱신 실패 시 만료된 snapshot을 성공값으로 재사용하지 않는다.

5초 cache는 DataHub read 비용을 줄이는 metadata cache이지 분석 결과 cache가 아니다. 과거 KPI나 query 결과를 현재 결과처럼 반환하지 않는다.

## 2.10 Hybrid Semantic Search

`DATAHUB_SEARCH_MODE=hybrid`에서는 catalog snapshot과 함께 DataHub semantic endpoint를 호출한다.

```text
병렬 1
Dataset·Glossary 전체 catalog snapshot load

병렬 2
semanticSearchAcrossEntities(
  query: "지난달 객실매출을 호텔별로 보여줘"
)
```

최종 후보 순위는 개념적으로 다음 증거를 조합한다.

```text
semantic hit 여부
> local token overlap 수
> semantic 결과 순위
> FQN 결정적 순서
```

Hybrid 모드의 주의점은 다음과 같다.

- 임베딩 생성과 semantic index 검색은 DataHub 측에 위임한다.
- Backend에 별도 embedding fallback을 두지 않는다.
- semantic capability 장애를 lexical 성공으로 가장하지 않고 fail-closed 한다.
- 질문 원문이 DataHub semantic endpoint로 전송되므로 별도의 데이터 전송 경계다.
- semantic overlay, 전송 정책, release checksum과 live read-back이 함께 검증된 경우에만 운영 활성화를 판단한다.

## 2.11 Domain, Glossary와 Query를 결합하는 실제 방식

일반적인 검색 예시는 다음처럼 질문에서 Query, Domain, Glossary를 추출해 하나의 DataHub filter로 전달할 수 있다.

```text
Query    = 객실 매출
Domain   = 호텔 운영
Glossary = 객실매출
```

하지만 현재 Answervice 기본 lexical 모드는 질문에서 Domain을 추측해 DataHub filter를 만들지 않는다.

```text
질문 token
        ∩
Dataset·Glossary의 승인 어휘
        ↓
일치 후보
        ↓
DataHub에 발행된 Domain·Owner·Lifecycle 검증
        ↓
인증 context의 entitlement 선필터
```

이 설계는 “호텔”이라는 단어가 질문에 있다는 이유만으로 호텔 Domain 권한을 부여하는 오류를 막는다. Domain은 검색 편의용 label인 동시에 runtime 권한과 metric 일관성을 검증하는 governance metadata다.

## 2.12 검색 결과가 SQL Context가 되는 과정

검색된 Dataset은 즉시 SQL 생성에 사용되지 않는다. 다음 검증을 모두 통과해야 한다.

```text
검색 후보
   ↓
현재 principal의 entitlement 필터
   ↓
승인 metric dependency 확인
   ↓
승인 join graph로 연결 가능한 자산만 확장
   ↓
요청당 최대 8개 자산으로 제한
   ↓
동일 policy version·time metadata·query policy 확인
   ↓
DataHub schema와 Trino information_schema 일치 검증
   ↓
Typed Runtime Context 구성
```

권한 필터는 join 확장 전에 적용한다. 그래야 비권한 Dataset의 이름, Column, 관계가 join 탐색 과정에서 노출되지 않는다.

선택된 자산이 하나의 승인 join graph로 연결되지 않거나 metric Dataset이 없거나 8개 제한을 넘으면 Context 생성을 거부한다. LLM은 승인되지 않은 table·column·join을 추가할 수 없다.

## 2.13 SQL 생성·실행과 결과 근거

Context 생성 후 분석은 다음 순서로 진행된다.

```text
Typed Runtime Context
        ↓
Node 2가 Context 안에서 parameterized read-only SQL 생성
        ↓
SQLGlot AST 기반 G2 정책 검증
        ↓
placeholder expected set exact match
        ↓
서버 소유 typed 값을 AST transform으로 바인딩
        ↓
Trino service principal로 실행
        ↓
결과 schema·행 수·근거 검증
        ↓
query ID·source URN·metric·기간·join·artifact lineage 저장
```

DataHub 검색은 이 중 Context의 근거를 제공하는 단계다. SQL 안전성을 보증하는 최종 장치는 아니다. SQL은 별도로 한 개의 읽기 전용 statement인지, 승인된 자산과 Column만 사용하는지, scan/result/timeout 상한을 지키는지 검증한다.

## 2.14 호텔 업무 질문 적용 예시

다음은 현재 구조를 이해하기 위한 개념 예시다. 실제 Dataset명, metric 정의와 SQL은 live 승인 release에서 읽어야 하며 아래 예시를 정답으로 고정하지 않는다.

### 사용자 질문

```text
"지난달 객실매출을 호텔별로 비교해줘"
```

### 1단계: 질문 해석과 검색 증거

```text
질문에서 보존할 의미
- metric 후보: 객실매출
- 기간: 지난달
- 비교 차원: 호텔
```

기본 lexical 모드에서는 질문 token을 Backend 메모리에서 만들고, DataHub에는 `query: "*"`로 catalog를 요청한다. `객실매출`과 일치하는 어휘는 DataHub Glossary의 승인 Term에서 찾는다.

### 2단계: 자산·권한·관계 검증

```text
승인 Glossary Term
        ↓
연결 Dataset·metric rule
        ↓
현재 사용자 entitlement
        ↓
호텔 dimension과의 승인 join graph
        ↓
Trino live schema 일치
```

권한이 없는 호텔 자산이나 미승인 매출 Term은 후보에서 제외하거나 typed error로 종료한다. 질문에 “호텔”이 있다는 이유만으로 권한을 넓히지 않는다.

### 3단계: Context와 SQL

Backend는 개념적으로 다음 정보를 가진 Context를 만든다.

```text
Context
- context release
- policy version
- metric definition·unit·aggregation
- approved asset URN·Trino FQN·columns
- hotel dimension
- approved join IDs
- absolute time range
- permission snapshot
- query limits
```

Node 2는 이 Context 밖의 table이나 column을 사용할 수 없다. `지난달`은 서버가 소유한 기준 시각에 따라 절대 시작·종료 시각으로 확정되고 parameter로 바인딩된다.

### 4단계: 결과와 근거

Trino 실행 결과에는 별도로 다음 근거를 연결한다.

```text
- 사용 metric과 정의
- 조회 기간
- source URN
- 사용 join
- Trino query ID
- context/policy release
- artifact checksum
```

따라서 화면의 숫자와 보고서는 단순 LLM 문장이 아니라 동일한 server artifact와 lineage에서 렌더링할 수 있다.

## 2.15 실패 시 처리

다음 상황은 성공처럼 우회하지 않고 typed error로 닫는다.

- 승인된 runtime-governed Dataset 또는 Glossary Term이 없음
- 질문과 일치하는 승인 자산이 없음
- 현재 principal에게 일치 자산 권한이 없음
- Dataset·Term·Domain·Owner·Lifecycle 관계가 불완전함
- release manifest membership·count·checksum이 불일치함
- Dataset과 metric rule 또는 Glossary 정의가 충돌함
- 선택 자산의 policy, time, query contract가 서로 다름
- 승인 join graph로 bounded Context를 구성할 수 없음
- DataHub schema와 live Trino schema가 다름
- hybrid 모드의 semantic capability가 응답하지 않음

이때 mock 응답, 정적 Context JSON, 과거 snapshot, 미리 계산한 KPI, 고정 SQL을 fallback으로 사용하지 않는다.

## 2.16 주요 키워드와 프로젝트 의미

| 키워드 | 일반 의미 | Answervice에서 특히 중요한 점 |
|---|---|---|
| Metadata | 데이터에 대한 정보 | SQL Context와 근거의 입력이며 실제 행 값이 아님 |
| Connector | metadata 수집기 | source별 읽기 전용 계정과 실패 전파가 필요 |
| Dataset | Table/View에 대응하는 자산 | URN과 Trino FQN·Column allowlist를 함께 보존 |
| SchemaField | Dataset Column metadata | live Trino schema drift 검증 대상 |
| URN | DataHub entity ID | SQL FQN과 구분하고 lineage에 보존 |
| Domain | 업무 영역 | 질문 추측값이 아니라 발행된 governance와 entitlement 근거 |
| Glossary Term | 업무 용어와 정의 | metric rule·unit·owner·승인 lifecycle을 포함한 운영 계약 |
| Lineage | 데이터 흐름 계보 | 승인 join graph와 동일하지 않음 |
| Lexical Search | 문자열 기반 검색 | 기본 모드는 DataHub BM25가 아니라 Backend token overlap |
| Semantic Search | 의미 유사도 검색 | hybrid에서만 질문 원문을 DataHub로 전송 |
| Inverted Index | Term에서 Document를 찾는 색인 | DataHub 내부 일반 검색 구조이며 기본 Backend ranking은 아님 |
| BM25 | 문서 관련도 점수 | 현재 기본 lexical ranking에 직접 사용하지 않음 |
| Top-K | 상위 K개 검색 결과 | SQL에 사용할 Dataset 수와 다르며 현재 Context는 최대 8개 |
| Catalog Snapshot | 특정 시점 metadata 묶음 | 완전 검증 후 5초 재사용하며 stale 성공 fallback 금지 |
| Context Release | 함께 사용 가능한 의미 계약 버전 | Dataset·Term·policy·checksum이 하나의 release로 일치해야 함 |
| Entitlement | 현재 principal의 접근 권한 | join 확장 전에 적용해 metadata 노출도 차단 |

## 2.17 현재 구현과 운영 완료 상태의 구분

현재 source에는 다음 경계가 구현돼 있다.

- Dataset·Glossary 전체 pagination
- 상세 metadata의 bounded concurrent read-back
- native Owner·Domain·Lifecycle 교차검증
- release manifest membership·count·checksum 재계산
- 기본 lexical과 선택적 hybrid 검색 모드
- entitlement 선필터와 bounded join Context
- Trino `information_schema` drift 검증
- DataHub·Trino 실패의 fail-closed 처리

그러나 코드가 있다는 사실과 live 운영 완료는 다르다. 제품 PRD 기준으로 live semantic overlay, 완전한 release scope, 동일 release의 DataHub→Trino→Browser E2E 증거는 아직 완료로 선언할 수 없다. 실제 검증 전에는 다음과 같이 표현하지 않는다.

- “DataHub Glossary 운영 연동 완료”
- “semantic search production 활성화 완료”
- “모든 source와 serving release 일치 완료”
- “실제 DataHub→Trino E2E PASS”

# 3. 결론

DataHub 검색 구조에서 가장 중요한 점은 **DataHub가 실제 DB의 모든 행 값을 검색하는 시스템이 아니라 데이터 자산의 metadata를 검색하고 관리하는 시스템**이라는 것이다.

일반적인 DataHub lexical search는 Dataset 이름, 설명, Column, Glossary, Domain 같은 metadata를 검색 Document로 만들고 analyzer, 역색인, Term Dictionary, Postings List, BM25와 boost를 이용해 관련 자산의 URN을 빠르게 찾는다.

```text
Metadata
   ↓
Search Document
   ↓
Analyzer / Token
   ↓
Inverted Index
   ↓
BM25 + Boost
   ↓
Top-K URN
```

Answervice의 현재 기본 lexical 모드는 이 일반 흐름과 다르다. 질문을 DataHub lexical query로 직접 보내지 않고, `query: "*"`로 runtime-governed Dataset과 Glossary를 완전하게 읽어 release를 검증한 뒤 Backend 로컬 token 교집합으로 후보를 정한다. Hybrid 모드에서만 질문 원문을 DataHub semantic search로 전송한다.

```text
사용자 질문
   ↓
Backend 로컬 token 또는 hybrid semantic evidence
   ↓
DataHub Dataset·Glossary·native governance read-back
   ↓
release manifest·checksum 검증
   ↓
질문과 승인 metadata 매칭
   ↓
entitlement 선필터
   ↓
승인 join graph·metric dependency
   ↓
Trino schema drift 검증
   ↓
Typed Runtime Context
   ↓
SQLGlot 정책을 통과한 읽기 전용 SQL
   ↓
Trino 실제 값 조회
   ↓
query ID·URN·metric·기간·lineage가 연결된 artifact
```

따라서 우리 프로젝트에서 DataHub의 가치는 단순히 “검색이 빠르다”는 데 있지 않다. 자연어 질문이 어떤 업무 정의와 데이터 자산에 연결됐는지 설명하고, 승인되지 않은 자산·컬럼·관계·권한으로 SQL이 확장되지 않도록 제한하며, 결과와 보고서에 재현 가능한 근거를 남기는 데 있다.

최종적으로 한 문장으로 정리하면 다음과 같다.

> **Answervice는 DataHub를 metadata 검색엔진이자 runtime governance의 권위 원본으로 사용하고, 검색된 Dataset과 Glossary를 release·권한·join·schema 계약으로 검증한 뒤에만 Trino 읽기 전용 분석 Context로 전달한다.**
