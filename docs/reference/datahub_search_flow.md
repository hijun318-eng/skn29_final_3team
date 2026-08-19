# DataHub 검색 구조와 Answervice 적용 방식

이 문서는 DataHub의 일반 검색 개념을 현재 Answervice 코드에 대입해 설명하는 참고 자료다. 제품 요구와 완료 상태의 권위 원본은 [`docs/product/01_PRD.md`](../product/01_PRD.md), 컴포넌트 책임과 신뢰 경계의 권위 원본은 [`docs/product/03_아키텍처.md`](../product/03_아키텍처.md)다.

## 먼저 구분할 것

DataHub는 원천 DB의 실제 행 값을 복사해 검색하는 시스템이 아니라 Dataset, Column, Description, Domain, Owner, Glossary, Lineage 같은 **메타데이터를 수집·관리하는 카탈로그**다. Answervice에서도 역할 경계는 같다.

```text
DataHub = 어떤 자산을 어떤 의미·권한·관계로 사용할 수 있는지 찾고 검증
Trino   = 승인된 자산의 실제 업무 데이터를 읽기 전용 SQL로 조회
App DB  = 분석 Run, Context, query ID, lineage, artifact, 보고서 상태를 저장
```

따라서 DataHub에서 `객실매출`을 검색하는 것은 매출 숫자를 얻는 단계가 아니다. `객실매출`의 승인된 정의, 계산 규칙, 단위, 연결 Dataset·Column과 권한 계약을 찾는 단계다. 실제 값은 이후 Trino query가 반환한다.

## 일반 개념과 프로젝트의 대응

| 일반 DataHub 개념 | Answervice에서의 사용 |
|---|---|
| Connector / Ingestion | PMS(PostgreSQL), POS(MySQL), CRM(MSSQL), 시설(ClickHouse)의 runtime schema와 Trino serving table/view를 DataHub에 발행한다. 연회는 별도 PostgreSQL recipe를 사용한다. |
| Dataset / SchemaField | Trino FQN과 승인 column 집합으로 변환되며 SQL allowlist와 schema drift 검사의 입력이 된다. |
| Glossary Term | metric label·alias·정의뿐 아니라 단위, 집계·reduction 규칙, owner, Domain, 승인 lifecycle을 가진 운영 의미 계약이다. |
| Domain | 질문에서 추측하는 분류가 아니라 DataHub에 발행된 업무 영역이며 entitlement 및 metric-Dataset 일관성 검증에 사용한다. |
| Owner / Lifecycle | 승인 주체와 `APPROVED` 상태를 검증한다. 삭제되었거나 미승인인 Term은 runtime 성공 경로에 포함하지 않는다. |
| URN | DataHub entity 식별자다. Trino에서 사용하는 `catalog.schema.relation` FQN과 구분하며 Context와 lineage에는 둘의 연결을 보존한다. |
| Lineage / Join graph | serving view lineage는 수집된 계보이고, runtime join graph는 별도로 승인·발행된 실행 계약이다. 둘 다 모델이 임의 table 조합을 만들 수 있는 근거가 아니다. |
| GraphQL | Dataset·Glossary 검색과 상세 metadata read-back에 사용한다. |
| Rest.li aspect | DataHub v1.7에서 Glossary lifecycle·상태처럼 GraphQL만으로 exact 검증할 수 없는 native aspect의 권위 있는 read-back에 사용한다. |

## 메타데이터 등록 흐름

현재 recipe의 source 범위는 다음과 같다.

```text
PMS PostgreSQL ─────┐
POS MySQL ──────────┤
CRM MSSQL ──────────┤
시설 ClickHouse ────┼─> DataHub ingestion ─> Dataset·Column metadata
연회 PostgreSQL ────┤
Trino serving ──────┘                         + view/column lineage
```

- source recipe는 고정 질문이나 고정 table 답안이 아니라 현재 runtime schema를 읽는다.
- serving recipe는 Trino table/view와 view·column lineage를 수집하고 `information_schema`는 제외한다.
- source 접속, catalog discovery, DataHub 발행 중 하나라도 실패하거나 결과가 비면 준비 완료로 간주하지 않는다.
- ingestion이 만든 물리 metadata와 runtime metric governance 발행은 책임이 다르다. 업무 판단이 필요한 metric은 승인 전 `REVIEW_REQUIRED`이며 runtime metadata로 사용하지 않는다.
- 발행 완료는 단순 mutation 성공이 아니라 `--check` 사전검증, 최소권한 publish, 전체 live read-back과 checksum 일치까지 포함한다.

## 검색 모드

| 모드 | 설정 | DataHub로 질문 전송 여부 |
|---|---|---|
| `lexical` (기본) | `DATAHUB_SEARCH_MODE` 미설정 | ❌ 질문은 Backend 밖으로 나가지 않음 |
| `hybrid` | `DATAHUB_SEARCH_MODE=hybrid` | ⭕ 질문 원문이 semantic 검색으로 전송 |

## lexical 모드 (기본) 흐름

### 1단계 — 질문 토큰 추출 (Backend 로컬)

```text
"지난달 객실매출 알려줘"
→ NFKC 정규화 + casefold + 토큰화 + 한국어 조사 제거
→ {"지난달", "객실매출", "알려", "줘"}        ← 메모리에만 존재, DataHub 전송 없음
```

### 2단계 — DataHub 카탈로그 읽기 (질문과 무관)

```text
병렬 ①  searchAcrossEntities(query: "*")       → dataset URN 목록 전체
병렬 ②  searchAcrossEntities(query: "*")       → glossary term URN 목록 전체
        + 각 URN의 상세 aspect 조회 (동시 8개 제한)
```

- `query: "*"` = "전체 줘" — 질문 단어로 검색하는 게 아님
- Dataset·Glossary 검색은 `total/start/count` pagination을 끝까지 검증하며 중복 URN, 잘린 응답, entity type 불일치를 거부
- TTL 5초 single-flight 캐시: 같은 만료 시점의 동시 요청은 하나의 read-back을 공유하고, 갱신 실패를 오래된 성공값으로 대체하지 않음
- Dataset, Term, native Owner·Domain·Lifecycle와 release manifest의 membership·count·checksum을 다시 계산해 일치한 snapshot만 사용

### 3단계 — 순위 계산 (Backend 로컬 집합 연산)

```text
질문 토큰 {"객실매출", ...}
        ∩
asset 토큰 {dataset name·description·컬럼명, 용어 label+aliases+definition}
        = overlap 개수 → 순위
```

- 용어 어휘는 DataHub Glossary Term에서 런타임에 읽어 구축 (정적 키워드 사전 없음)
- 도메인은 질문에서 추출하지 않음 → 인증 context와 entitlement 비교용
- 현재 점수는 BM25가 아니라 `semantic hit 여부`, exact token overlap 수, semantic 순위, FQN의 결정적 순서로 계산

### 4단계 — 검색 후처리

```text
선택 asset → entitlement 필터 (join 확장 이전)
           → join graph 연결 자산 확장 (요청당 ≤8개)
           → Trino information_schema drift 검증
           → runtime_asset 변환 → Node2 SQL 생성 → G2 정책 검증 → Trino 실행
```

권한 필터를 join 확장보다 먼저 적용하는 이유는 비권한 자산의 이름·schema·관계가 후보 확장 과정에서 노출되는 것을 막기 위해서다. 선택된 Dataset들은 같은 policy version, time metadata, query policy를 가져야 하며 하나의 bounded join context를 만들 수 없으면 실패한다.

## hybrid 모드 차이점

```text
병렬 ①  카탈로그 스냅샷 로드 (lexical과 동일, 질문 무관)
병렬 ②  semanticSearchAcrossEntities(query: "지난달 객실매출 알려줘")
        ← 질문 원문을 가공 없이 통째로 전송
        → DataHub가 임베딩 유사도로 hit 목록+순위 반환

최종 순위 = semantic hit 여부 > 토큰 overlap 개수 > semantic 순위 > FQN
```

- 임베딩 계산은 전부 DataHub 측에 위임 (Backend에 임베딩 코드 없음)
- semantic 엔진 장애 시 토큰 경로로 대체하지 않고 fail-closed

`hybrid`는 단순 성능 옵션이 아니다. 질문 원문이 DataHub semantic endpoint로 전송되는 별도 데이터 경계다. 운영에서 활성화하려면 semantic capability, 전송 정책, 같은 release의 overlay와 read-back 증거가 함께 준비되어야 한다.

## 첨부 문서의 검색엔진 설명을 적용할 때의 주의점

DataHub 내부 검색은 Elasticsearch/OpenSearch 계열의 analyzer, 역색인, postings list, BM25·field boost 등을 사용할 수 있다. 이 설명은 DataHub 자체의 lexical search를 이해하는 데 유용하지만 **현재 Answervice 기본 검색 알고리즘의 설명은 아니다**.

| 첨부 문서의 일반 흐름 | 현재 Answervice `lexical` 모드 |
|---|---|
| 질문을 `searchAcrossEntities(query: 질문)`로 전송 | `query: "*"`로 전체 Dataset·Term URN을 읽으며 질문은 전송하지 않음 |
| DataHub/OpenSearch가 BM25로 Top-K 반환 | Backend가 승인 metadata의 Unicode token 교집합으로 결정적 순위 계산 |
| Top-K URN만 상세 조회 | bounded pagination으로 runtime-governed catalog 전체를 검증한 뒤 5초 snapshot 재사용 |
| LLM이 후보 Dataset을 자유롭게 최종 선택 | entitlement, metric dependency, 승인 join graph, 최대 8개, Trino schema 일치 조건으로 서버가 Context를 제한 |

따라서 FST, BlockTree, postings list 같은 검색엔진 내부 구현을 Answervice의 보안·정확성 계약으로 삼지 않는다. 우리 계약에서 중요한 것은 검색 결과 자체보다 그 결과가 승인 release, Glossary 규칙, 권한, join, schema와 정확히 일치하는지다.

## 검색 이후 분석 실행 흐름

```text
인증 principal·요청 context
        ↓
질문 token 또는 hybrid semantic evidence
        ↓
DataHub 전체 catalog·Glossary·native governance read-back
        ↓
release manifest·membership·checksum 검증
        ↓
질문과 metadata의 후보 매칭
        ↓
entitlement 선필터
        ↓
승인 join graph·metric dependency로 bounded Context 구성
        ↓
Trino information_schema와 DataHub schema drift 검사
        ↓
Node 2가 Context 안에서만 parameterized read-only SQL 생성
        ↓
SQLGlot AST 기반 G2 정책 검증·서버 소유 값 바인딩
        ↓
Trino 실행
        ↓
query ID·source URN·metric·기간·join·artifact lineage 저장
```

DataHub 검색 성공만으로 SQL 실행을 허용하지 않는다. 다음 중 하나라도 발생하면 빈 성공값, 정적 JSON, 과거 snapshot, mock 결과로 우회하지 않고 typed error로 닫는다.

- 승인된 runtime-governed Dataset 또는 metric Term 부재
- 질문과 일치하는 자산 부재 또는 현재 principal의 entitlement 부재
- Dataset·Term·Domain·Owner·Lifecycle·checksum·release manifest 불일치
- 선택 자산의 policy, time, query contract 불일치
- 승인 join graph로 연결할 수 없거나 최대 자산 수 초과
- DataHub schema와 live Trino `information_schema` drift
- `hybrid` 모드에서 semantic capability 장애

## 검색 결과와 증거의 수명

- 5초 catalog snapshot은 네트워크 read 최적화일 뿐 분석 결과 cache가 아니다.
- 분석 Run은 사용한 Context release, permission snapshot, source URN, Trino query ID를 별도로 고정해야 한다.
- 저장 분석이나 보고서 재실행은 과거 숫자를 복사하지 않고 현재 권한·Glossary·binding을 다시 검증해 새 query와 artifact를 만든다.
- DataHub health endpoint가 응답한다는 사실만으로 readiness가 되지 않는다. 인증된 catalog read-back과 실제 Trino service principal의 terminal query가 같은 release에서 확인되어야 한다.

## 구현과 운영 완료 상태의 구분

이 문서는 현재 source의 동작을 설명하며 live 제품 완료를 선언하지 않는다. `docs/product/01_PRD.md` 기준으로 DataHub 전체 pagination snapshot, native governance, semantic search 호출 경계와 checksum 재구성 코드는 존재하지만, live semantic overlay와 완전한 release scope의 동일-release 검증은 아직 완료되지 않았다. 따라서 다음 표현은 실제 L2/L3/L4 증거가 생기기 전에는 사용하지 않는다.

- “DataHub Glossary 운영 연동 완료”
- “semantic search production 활성화 완료”
- “DataHub→Trino 실제 E2E PASS”
- “모든 source와 serving release가 일치함”

## 핵심 요약

- **DataHub는 카탈로그(메타데이터 원본) 역할** — 질문 검색 엔진이 아님 (기본 모드)
- **질문 단어와의 매칭·순위는 전부 Backend의 Python 집합 연산**
- 질문 문자열이 DataHub로 가는 건 hybrid 모드의 semantic 검색뿐
- 검색된 자산은 권한·release·Glossary·join·Trino schema 검증을 통과해야만 SQL Context가 됨
- DataHub의 실제 행 값 검색과 SQL 실행은 역할 밖이며 실제 값 조회는 Trino가 담당

## 코드 위치

| 파일 | 위치 | 역할 |
|---|---|---|
| `app/backend/app/adapters/query_governance.py` | `search_assets()` L58, `_ranked_matches()` L319, `_unicode_tokens()` L345 | 검색 엔진 본체 |
| `app/backend/app/adapters/datahub_catalog.py` | `semantic_search()` L240, `_search()` L258 | DataHub GraphQL 호출 |
| `app/backend/app/adapters/catalog_snapshot.py` | `load()` L66 | 스냅샷 캐시·조립 |
| `app/backend/app/adapters/governed_data_platform.py` | L56 | 검색 모드 결정 (`DATAHUB_SEARCH_MODE`) |
