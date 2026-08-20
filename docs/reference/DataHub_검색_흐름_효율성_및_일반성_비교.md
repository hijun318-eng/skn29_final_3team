# Answervice DataHub 검색 흐름의 효율성과 일반성 비교

> 조사 기준일: 2026-08-19
>
> 비교 방법: 현재 저장소 코드에 대한 LLM 아키텍처 판단과 DataHub 공식 문서 인터넷 조사를 독립적으로 정리한 뒤 결론을 비교한다.
>
> 주의: 이 문서는 구조적 평가다. 실제 Dataset 수, 요청량, cold/warm latency를 측정한 부하 테스트 결과가 아니므로 운영 성능 수치를 단정하지 않는다.

# 1. 서론

Answervice는 사용자의 자연어 질문을 승인된 DataHub Dataset과 Glossary Term에 연결하고, 권한·join·schema 계약을 검증한 뒤 Trino 읽기 전용 SQL로 실행한다. 현재 기본 `lexical` 모드의 특징은 사용자 질문을 DataHub 검색어로 직접 보내지 않는다는 점이다.

```text
사용자 질문
   ↓
Backend 로컬 Unicode token 추출
   ↓
DataHub에 query="*"로 Dataset·Glossary 전체 목록 요청
   ↓
각 URN의 상세 metadata 조회
   ↓
release manifest·checksum·native governance 검증
   ↓
질문 token과 승인 metadata token의 교집합으로 순위 계산
   ↓
entitlement·join graph·Trino schema 검증
   ↓
SQL Context 생성
```

이 구조가 효율적인지 판단하려면 두 가지 질문을 분리해야 한다.

1. 승인 release 전체가 완전하고 일관적인지 검증하는 **control-plane catalog 검증**으로 효율적인가?
2. 사용자의 질문마다 관련 자산을 빠르게 찾는 **request-time 검색**으로 효율적이고 흔한가?

결론부터 요약하면 다음과 같다.

> 현재 구조는 작은 승인 카탈로그의 완전성·결정성·fail-closed 보장에는 강하지만, 일반적인 대규모 DataHub 대화형 검색 구조는 아니다. 전체 release 검증과 질문별 후보 검색을 같은 요청 경로에서 수행하므로 카탈로그가 커질수록 비용이 선형으로 증가한다.

# 2. 본론

## 2.1 현재 프로젝트의 검색 흐름

### 기본 lexical 모드

현재 `DATAHUB_SEARCH_MODE` 기본값은 `lexical`이다.

```text
1. 질문을 NFKC 정규화·casefold·Unicode token화
2. Dataset 전체 URN 조회: searchAcrossEntities(query="*")
3. Glossary Term 전체 URN 조회: searchAcrossEntities(query="*")
4. 모든 URN의 상세 metadata 조회
5. Dataset·Term·Owner·Domain·Lifecycle·manifest·checksum 검증
6. 질문 token과 metadata token overlap으로 후보 정렬
7. entitlement 필터
8. metric dependency와 join graph 확장
9. 최대 8개 자산 제한과 Trino schema drift 검증
```

DataHub client의 현재 기본 경계는 다음과 같다.

| 항목 | 현재 값 |
|---|---:|
| `searchAcrossEntities` page size | 50 |
| 최대 entity 수 | 10,000 |
| 상세 metadata 동시 조회 | 8 |
| 완전 검증 snapshot TTL | 5초 |
| 요청당 최종 자산 수 | 최대 8 |

5초 안에 동시에 들어온 요청은 single-flight snapshot을 공유한다. 갱신 실패를 만료된 snapshot이나 빈 성공값으로 대체하지 않는다.

### Hybrid 모드

`DATAHUB_SEARCH_MODE=hybrid`에서는 전체 catalog snapshot과 DataHub semantic search를 병렬로 실행한다.

```text
전체 catalog·governance snapshot
             +
semanticSearchAcrossEntities(query=질문 원문)
             ↓
semantic hit 여부 > local token overlap > semantic 순위 > FQN
```

Semantic 검색이 실패하면 lexical 결과만으로 성공 처리하지 않고 fail-closed 한다. 다만 hybrid 모드도 전체 catalog snapshot 비용을 그대로 부담한다.

## 2.2 LLM의 독립 판단

이 절은 외부 문서를 근거로 삼기 전, 현재 코드의 알고리즘·I/O·권한 경계만 보고 내린 판단이다.

### 효율적인 부분

#### 1. 작은 승인 카탈로그에서는 결정적이고 재현 가능하다

질문마다 같은 승인 snapshot을 기준으로 로컬 token 집합 연산을 수행하므로 검색 결과가 외부 검색엔진의 relevance 설정 변화에 덜 흔들린다. 특정 release의 Dataset과 Term 전체 membership을 checksum으로 확인해야 하는 제품에서는 이 결정성이 유용하다.

#### 2. single-flight와 bounded concurrency가 중복 부하를 줄인다

동시에 여러 요청이 snapshot 만료를 만났을 때 하나의 load task를 공유하고, 상세 entity 조회 동시성을 8개로 제한한다. 무제한 fan-out이나 동일 snapshot 중복 조회보다 안전하다.

#### 3. 개인정보 전송 경계가 단순하다

기본 lexical 모드에서는 질문 원문이 DataHub로 전송되지 않는다. DataHub에는 `query="*"`만 보내고 질문과 metadata의 매칭은 Backend 메모리에서 수행한다.

#### 4. 검색과 거버넌스 검증을 한 snapshot으로 묶는다

Dataset 이름이 검색됐다는 이유만으로 SQL에 사용하지 않고 다음 항목을 검증한다.

- Dataset·Glossary 승인 상태
- Owner·Domain·Lifecycle
- release membership·count·checksum
- metric rule
- entitlement
- join graph
- Trino live schema

일반적인 “Top-K를 LLM에 넘긴 뒤 선택”보다 실행 안전성은 높다.

### 비효율적이거나 확장 위험이 있는 부분

#### 1. snapshot 갱신 비용이 catalog 크기에 비례한다

Dataset 수를 `D`, Glossary Term 수를 `T`라고 하면 snapshot 갱신은 개념적으로 다음 비용을 가진다.

```text
URN 목록 pagination
+ Dataset 상세 조회 D건
+ Term 상세 조회 T건
+ 승인 Term status 조회
+ Owner·Domain·Lifecycle 조회
```

검색 후보가 5개만 필요해도 release 전체 상세 metadata를 읽는다. 5초 TTL이 지나면 다음 요청이 이 비용을 다시 지불한다.

#### 2. 질문별 ranking이 O(D)에 가깝다

검증된 snapshot이 warm 상태여도 `_ranked_matches()`는 모든 Dataset의 검색 문자열을 token화하고 질문 token과 교집합을 계산한다. 별도 local inverted index가 없으므로 Dataset 수가 커지면 CPU와 allocation 비용도 선형 증가한다.

#### 3. DataHub 검색엔진의 relevance 기능을 기본 경로에서 활용하지 않는다

현재 local lexical 순위는 주로 exact token overlap 수다. BM25, field boost, phrase/prefix match, analyzer, 검색 통계 같은 DataHub 검색엔진의 기능을 사용하지 않는다. 한국어 합성어, 띄어쓰기, 동의어, 철자 변형에서 recall과 ranking 품질이 제한될 수 있다.

#### 4. 전체 순회와 대화형 검색의 목적이 섞여 있다

release 전체 membership 검증은 배포·활성화·주기적 동기화에서 필요한 control-plane 작업이다. 반면 질문별 검색은 관련 후보만 빠르게 가져오는 request-plane 작업이다. 현재는 두 작업을 동일한 request-time snapshot load에 결합한다.

#### 5. 10,000 entity가 구조적 상한이다

client가 `max_entities=10_000`을 두고 있으므로 Dataset이나 Term 검색 total이 이를 넘으면 실패한다. 이는 안전한 bounded 처리이지만 대규모 catalog 확장 경로는 아니다.

#### 6. 권한 필터 이후 join 확장 자산을 재검증하지 않는다

최초 검색 seed에는 `entitled(context)`를 적용하지만, 이후 metric dependency나 shortest path로 추가되는 중간 Dataset에는 동일 entitlement를 다시 호출하지 않는다. 이는 효율성 문제라기보다 현재 흐름의 권한 완전성 위험이다.

### LLM 판단 결론

> 현재 검색 흐름은 “작고 엄격하게 통제된 runtime catalog를 매 요청 시 검증하는 구조”로는 합리적이지만, Dataset이 증가하는 일반적인 대화형 DataHub 검색 구조로는 비효율적이다. 전체 catalog 검증은 background/control plane으로 분리하고, request path는 query·filter 기반 Top-K 검색과 최종 후보 재검증으로 바꾸는 것이 적절하다.

## 2.3 인터넷 공식 자료 조사

조사는 기술 질문이므로 DataHub 공식 문서만 검색 근거로 사용했다. 현재 공개 문서 페이지는 DataHub 1.6.0으로 표시되며, 이 프로젝트는 DataHub v1.7 경계를 전제로 하므로 exact GraphQL schema와 기능 가용성은 live instance에서 다시 확인해야 한다.

### 공식 자료 1: DataHub의 일반 검색 방식

DataHub Search SDK 공식 문서는 일반적인 검색을 다음 두 방식으로 설명한다.

- query-based search: 이름·설명·column 이름을 keyword로 검색
- filter-based search: platform·environment·entity type·Domain·custom property로 범위 제한
- query와 structured filter를 함께 사용해 더 정밀하게 검색

공식 예시는 `query="sales"`로 관련 URN을 찾거나, `query="forecast"`와 platform/entity type filter를 결합한다. 즉 사용자 검색어를 DataHub에 전달하고 검색엔진이 관련 후보를 제한하는 흐름이 대표 사용법이다. [DataHub Search SDK 공식 문서](https://docs.datahub.com/docs/api/tutorials/sdk/search_client)

### 공식 자료 2: GraphQL 검색 최적화

DataHub GraphQL Best Practices는 다음을 권고한다.

- 필요한 field만 요청해 over-fetching 최소화
- 결과 수를 제한하고 pagination 사용
- 필요한 entity type만 명시
- 복잡하고 nested한 요청은 count를 낮춤
- `searchAcrossEntities`는 얕은 pagination에 사용
- 전체 결과처럼 깊은 순회가 필요하면 `scrollAcrossEntities` 사용

특히 공식 문서는 `search*` API가 약 50 page 미만의 작은 pagination을 위해 설계됐으며 10,000건을 넘는 pagination은 불가능하다고 설명한다. 전체 catalog를 `searchAcrossEntities(query="*")`로 끝까지 읽는 현재 방식은 작은 catalog에서는 동작하지만, 공식적으로 권장되는 deep-scan 방식은 아니다. [DataHub GraphQL Best Practices](https://docs.datahub.com/docs/api/graphql/graphql-best-practices)

### 공식 자료 3: 검색 권한은 가능한 한 검색 시점에 제한

DataHub Search Access Controls 문서는 권한이 있는 entity만 검색 결과에 나타나는 default-deny 모델을 설명한다. 다만 query-time search filtering은 DataHub Cloud 기능이고, self-hosted OSS의 `VIEW_AUTHORIZATION_ENABLED=true`는 entity page gating 또는 post-search masking이며 query-time filtering과 같지 않다고 명시한다. [DataHub Search Access Controls](https://docs.datahub.com/docs/features/feature-guides/search-access-controls)

이 점은 Answervice가 Backend에서 별도 entitlement를 검사하는 이유를 뒷받침한다. 그러나 권한 필터는 최종 검색 seed뿐 아니라 join dependency와 직접 URN 상세 조회까지 동일하게 적용되어야 한다.

### 공식 자료 4: AI 검색도 범위를 먼저 좁힌다

DataHub의 Ask DataHub 공식 문서는 metadata graph, Glossary, Domain, ownership, lineage, usage, 품질 정보를 함께 사용한다고 설명한다. 또한 View를 선택하면 특정 Domain, 소유 팀 또는 curated data product로 검색 범위를 제한해 더 빠르고 관련성 높은 답변을 얻을 수 있다고 안내한다. [Ask DataHub 공식 문서](https://docs.datahub.com/docs/features/feature-guides/ask-datahub)

이는 “전체 catalog를 매 질문마다 모두 상세 조회한 뒤 로컬 교집합 계산”보다 “승인된 scope를 먼저 적용하고 관련 후보를 검색한 뒤 metadata graph로 보강”하는 흐름이 일반적임을 보여준다.

### 인터넷 조사 결론

> DataHub에서 흔히 권장되는 대화형 검색은 query와 structured filter로 후보를 좁히고, 필요한 entity type과 결과 수만 가져온 뒤 상세 metadata를 보강하는 구조다. 전체 catalog 검증이 필요하면 `scrollAcrossEntities` 같은 안정적인 전체 순회 API를 별도 작업에서 사용해야 한다. 따라서 Answervice의 governance 검증 목표는 타당하지만, 이를 모든 질문의 검색 경로에 결합한 방식은 일반적인 권장 흐름과 다르다.

## 2.4 LLM 판단과 인터넷 조사 결론 비교

| 비교 항목 | LLM의 코드 기반 판단 | 인터넷 공식 자료의 결론 | 종합 판정 |
|---|---|---|---|
| 전체 catalog snapshot | 작은 승인 catalog의 무결성 검증에는 유리 | 전체 순회는 `scroll*`; `search*` deep pagination은 비권장 | control plane에서는 유지 가치가 있으나 request path에서는 분리 필요 |
| 질문별 후보 검색 | 모든 Dataset local scan은 규모에 따라 비효율 | query + structured filter + 제한된 결과가 대표 방식 | 현재 방식은 흔한 대화형 검색 구조가 아님 |
| 상세 metadata 조회 | 매 snapshot 갱신 시 D+T 수준의 호출 fan-out | 필요한 field와 결과 수를 제한하고 over-fetching 최소화 | 후보 Top-K 후 상세 조회가 더 일반적 |
| lexical ranking | exact token overlap은 단순·결정적이지만 recall 한계 | DataHub 검색은 query와 searchable metadata를 활용 | DataHub lexical retrieval 또는 local inverted index 활용 검토 |
| semantic/hybrid | 의미 검색을 병렬 결합한 방향은 일반적이나 전체 snapshot 비용 유지 | AI 검색은 metadata graph와 scoped view를 함께 사용 | hybrid 자체는 일반적이고, scope-first 구조가 더 적합 |
| 권한 | Backend entitlement 검사는 self-hosted 환경에서 필요 | OSS는 Cloud와 같은 query-time access filtering이 없음 | 앱 권한 필터는 유지하되 후보·join·상세 조회 전체에 동일 적용 |
| cache | 5초 single-flight는 중복 요청 완화 | client caching과 결과 제한 권고 | 단기 완화책이며 전체 scan 비용의 근본 해결은 아님 |
| 실패 정책 | checksum·schema drift·semantic 장애 fail-closed는 강점 | 공식 access control도 explicit grant 기반 default deny 지향 | 안전성 방향은 일치 |

두 결론은 핵심적으로 일치한다.

```text
일치하는 판단
- governance validation은 필요함
- 권한은 검색과 상세 조회 전체에 일관되게 적용해야 함
- 전체 catalog scan과 질문별 검색은 목적이 다름
- 사용자 요청 경로에서는 scope와 후보 수를 먼저 줄이는 편이 일반적임
- 현재 5초 cache만으로는 catalog 증가 시 확장 문제를 해결하지 못함
```

차이는 강조점에 있다.

- LLM 판단은 코드의 checksum·single-flight·로컬 ranking·join 확장까지 분석해 현재 구조가 작은 catalog에서 유용한 이유와 권한 재검증 결함을 발견했다.
- 인터넷 자료는 DataHub가 공식적으로 제공하는 query/filter/scroll/access-control 패턴을 근거로 현재 흐름이 일반적인 검색 사용법과 다르다는 점을 확인했다.

## 2.5 권장 목표 구조

현재 구조의 안전성을 버리지 않고 효율을 높이려면 control plane과 request plane을 분리하는 것이 적절하다.

### Control plane: release 전체 검증

```text
DataHub publish 완료
   ↓
scrollAcrossEntities 또는 versioned manifest의 stable membership 조회
   ↓
Dataset·Term·Owner·Domain·Lifecycle 전체 read-back
   ↓
checksum·count·schema·governance 검증
   ↓
검증된 immutable catalog snapshot 생성
   ↓
active release pointer 전환
```

특징:

- 사용자 질문과 분리된 background/activation 작업
- stable URN sort와 scroll 사용
- release 단위 cache namespace
- 전체 검증이 완료되기 전 runtime 노출 금지
- 변경 event 또는 명시적 release activation 때 갱신

### Request plane: 질문별 검색

```text
인증 principal·permission snapshot
   ↓
승인 release·Domain·entity type scope
   ↓
DataHub lexical/semantic query 또는 검증된 local search index
   ↓
bounded Top-K URN
   ↓
후보 상세 metadata·Glossary 조회
   ↓
entitlement 재검증
   ↓
metric dependency·join path 확장
   ↓
확장된 모든 자산 entitlement 재검증
   ↓
Trino schema drift 확인
   ↓
Typed Context
```

### 단계적 개선 우선순위

1. **권한 완전성 우선:** join dependency와 shortest-path 중간 자산까지 `entitled(context)`를 다시 확인한다.
2. **측정 추가:** Dataset·Term 수, snapshot HTTP 호출 수, cold/warm p50·p95, zero-result·Top-K recall을 계측한다.
3. **전체 순회 API 수정:** release 검증이 deep pagination을 요구하면 `searchAcrossEntities` 대신 stable sort의 `scrollAcrossEntities`를 검토한다.
4. **control/request plane 분리:** 완전 snapshot은 release activation에서 만들고 요청 경로에서는 이미 검증된 snapshot identity만 확인한다.
5. **후보 검색 개선:** query + entity type + release/Domain/custom property filter로 bounded candidate를 찾는다.
6. **검색 품질 검증:** 한국어 띄어쓰기·조사·동의어·오탈자·의미 contrast를 포함한 held-out set으로 lexical, semantic, hybrid를 비교한다.
7. **운영 전환 조건:** 실제 catalog 규모와 부하 시험에서 새 구조가 권한 누출 없이 latency·recall 기준을 통과한 뒤 전환한다.

## 2.6 흔히 사용되는 흐름인지에 대한 최종 비교

| 흐름 요소 | 흔한 정도 | 평가 |
|---|---|---|
| DataHub ingestion으로 metadata 수집 | 흔함 | 표준적인 사용 |
| Glossary·Domain·Owner·Lineage로 후보 보강 | 흔함 | 표준적인 governance 검색 |
| query와 structured filter로 후보 제한 | 흔함 | DataHub 공식 예시와 일치 |
| Top-K 후 상세 metadata hydration | 흔함 | 일반적인 검색/RAG 패턴 |
| lexical + semantic hybrid retrieval | 점점 일반적 | scope·권한·reranking 설계가 필요 |
| Backend에서 추가 entitlement 검사 | self-hosted에서는 합리적 | OSS query-time filtering 한계를 보완 |
| 매 질문마다 `query="*"`로 전체 catalog 상세 조회 | 흔하지 않음 | 작은 catalog 또는 검증 도구에는 가능 |
| 전체 release checksum을 매 요청 검색과 결합 | 흔하지 않음 | control-plane 검증으로 분리하는 편이 적절 |
| exact token overlap만으로 전체 Dataset 순위화 | 소규모 custom system에서 가능 | 대규모 DataHub 검색의 대표 흐름은 아님 |

# 3. 결론

## 3.1 LLM 판단의 결론

현재 Answervice 검색 흐름은 잘못된 구조라고 단정할 수 없다. 승인 release 전체를 읽고 checksum, Glossary, native governance, entitlement, join, Trino schema를 fail-closed로 검증하는 방식은 **정확성과 재현성을 우선한 작은 runtime catalog**에서는 실용적이다.

그러나 검색 효율만 보면 다음 비용이 있다.

- snapshot 만료 후 전체 Dataset·Term 상세 재조회
- 매 질문마다 전체 Dataset local token scan
- 10,000 entity 상한
- DataHub lexical relevance 기능 미활용
- hybrid에서도 전체 snapshot 비용 유지

따라서 catalog가 증가하거나 동시 요청이 많아지면 효율적인 구조로 보기 어렵다.

## 3.2 인터넷 조사의 결론

DataHub 공식 문서에서 흔히 제시하는 흐름은 다음과 같다.

```text
query + structured filter
   ↓
제한된 entity type과 결과 수
   ↓
관련 URN 후보
   ↓
필요한 상세 metadata 조회
```

전체 결과 순회가 필요할 때는 `searchAcrossEntities`의 deep pagination 대신 `scrollAcrossEntities`가 권장된다. AI 검색도 View, Domain, owner, data product 같은 scope를 먼저 적용해 관련성과 속도를 높인다.

따라서 현재 Answervice의 매 요청 전체 catalog 방식은 DataHub의 흔한 대화형 검색 흐름이라고 보기 어렵다.

## 3.3 두 결론을 합친 최종 판정

> **현재 구조는 governance 무결성 검증에는 강하지만, 검색 효율과 일반성 측면에서는 소규모·과도기형 구조다.**

LLM의 코드 분석과 인터넷 공식 자료 조사는 모두 다음 개선 방향에 동의한다.

```text
전체 release 검증
→ background/control plane으로 분리

질문별 검색
→ 권한 scope + query/filter + bounded Top-K

최종 실행
→ 후보와 join 확장 전체의 entitlement 재검증
  + Glossary·checksum·Trino schema 검증
```

즉 유지해야 할 것은 checksum·승인·권한·schema의 fail-closed 원칙이고, 바꿔야 할 것은 이를 모든 사용자 질문의 전체 catalog scan과 결합한 실행 위치다.

## 3.4 최종 한 문장

> **Answervice의 DataHub 검색은 작은 승인 catalog에서는 안전하고 재현 가능하지만 일반적인 대규모 검색 흐름은 아니며, 전체 catalog 검증과 질문별 Top-K 검색을 분리해야 효율성·일반성·권한 완전성을 함께 확보할 수 있다.**

## 참고한 공식 자료

- [DataHub Search Client SDK Tutorial](https://docs.datahub.com/docs/api/tutorials/sdk/search_client)
- [DataHub GraphQL Best Practices](https://docs.datahub.com/docs/api/graphql/graphql-best-practices)
- [DataHub Search Access Controls](https://docs.datahub.com/docs/features/feature-guides/search-access-controls)
- [Ask DataHub](https://docs.datahub.com/docs/features/feature-guides/ask-datahub)
