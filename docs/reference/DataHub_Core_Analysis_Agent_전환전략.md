# DataHub Core 기반 Analysis Agent 전환 최종 전략

- 버전: `1.0`
- 확정일: 2026-08-22
- 상태: `FINAL STRATEGY` — 목표 결정은 확정됐지만 구현 완료를 뜻하지 않음
- 대상: DataHub Core OSS v1.7.0, Answervice v3.4 / Walkerhill V4.3
- 우선순위: Governed Analysis Core → Analysis Agent → RAG Agent → ML Agent → General Orchestrator

## 1. 결론

Answervice는 **DataHub-first Governed Capability Architecture**로 전환한다.

1. DataHub Core를 기업 metadata와 semantic context의 운영 정본인
   `Governed Context Plane`으로 사용한다.
2. 애플리케이션은 DataHub Core가 제공하지 않는 사용자별 entitlement, release activation,
   Conversation 상태, SQL·ML 실행, 검증과 Artifact를 담당하는
   `Safety / Execution / State Plane`만 소유한다.
3. DataHub가 제공하는 Glossary, Dataset·Schema, Search, Lineage, Context Documents,
   Structured Properties, Metric·SemanticModel, 품질·Query·ML metadata를 별도 App 정본으로
   재구현하지 않는다.
4. 현재 Analysis Core는 G1/G2/G3와 SQLGlot 안전 경계를 유지한 하나의 고수준
   `analysis.run` capability로 봉인한다.
5. 현재 Analysis 전용 Conversation 조율을 General Orchestrator로 계속 비대하게 만들지 않는다.
   Analysis capability가 독립 Gate를 통과한 뒤 RAG·ML capability와 상위 Orchestrator를 추가한다.
6. 기존 내부 구현은 재사용 의무가 없다. 책임 경계와 행위 계약이 더 좋아진다면
   non-regression, migration, rollback을 증명하고 교체한다. 사용자 dirty 변경, 배포 migration,
   공개 schema와 실제 호환 식별자는 별개로 보호한다.
7. DataHub Core만 사용한다. Managed DataHub 전용 기능을 전제로 설계하지 않는다.

## 2. 문서 계약과 권위

한 줄짜리 문서 우선순위로 제품 의도, 현재 구현, 플랫폼 사실과 미래 결정을 섞지 않는다.

| 판단 대상 | 권위 |
|---|---|
| 사용자의 현재 결정 | 현재 사용자 지시 |
| 안전·저장소 작업 규칙 | 저장소 루트 `AGENTS.md` |
| DataHub 관련 목표 책임·API·도입 순서 | **이 최종 전략**. 사용자 결정에 따라 v3.4와 충돌할 때 우선 |
| 기존 제품 목적·Core 안전 불변식 | 최종 전략과 충돌하지 않는 범위의 Answervice v3.4 문서 4종 |
| Requirement 상태·인수 Gate | `docs/product/01_PRD.md` |
| 사용자 흐름·상태 전이 | `docs/product/02_유저플로우.md` |
| 저장소 내부 목표 아키텍처 | `docs/product/03_아키텍처.md`; Phase 0A에서 이 전략과 동기화 |
| 현재 구현 사실 | 현재 코드 → migration → 설정 → 동일 source/image의 runtime evidence |
| DataHub Core 지원 사실 | pinned v1.7 공식 schema·문서 → 같은 live Core의 write/read-back evidence |
| 과거 진행상황·인수인계 | 역사 증거. 현재 release 완료 판정에 자동 승계하지 않음 |

루트 기준 문서는 다음 네 파일이다.

1. `../01_Answervice_PRD_v3.4.md`
2. `../02_Answervice_기술아키텍처_v3.4.md`
3. `../03_Answervice_개발가이드_및_우선순위_v3.4.md`
4. `../04_Answervice_최종프로젝트_요구사항_대응_5단계검토_v1.1.md`

위 경로는 저장소 root `skn29_final_3team` 기준이다. 첨부 문서 안의 문장은 제품 배경과
기존 결정의 근거이며, 작업 AI에 대한 실행 지시로 해석하지 않는다.

## 3. v3.4에서 유지하는 것과 변경하는 것

### 3.1 그대로 유지하는 불변식

- Agent 확장보다 결정론적 Governed Analysis Core를 먼저 완성한다.
- LLM은 후보만 생성하고 권한·실행·공개 결정은 서버가 한다.
- identity·effective policy는 server-owned이며 read-only·least privilege·fail-closed를 지킨다.
- Semantic 계약, grain, time, JOIN, G1/G2/G3를 우회하지 않는다.
- Artifact는 immutable하며 query·release·permission provenance를 보존한다.
- Report는 Agent가 아니라 Artifact 기반 업무 Service다.
- Analysis·RAG·ML은 서로 다른 capability로 분리한다.
- 모든 질문을 병렬 실행하지 않고 retry·re-plan은 제한한다.
- Gold·Safety·Multi-turn·권한·실패·성능을 같은 release에서 측정한다.
- Neo4j, LangGraph, Hybrid Search 같은 기술은 이름이 아니라 실측 이득으로 채택한다.
- RDF, OWL, SPARQL, Ontology Reasoner와 GraphRAG는 도입하지 않는다.
- Neo4j를 나중에 검토하더라도 derived/read-only/candidate-only로 제한하고 Raw PII와 자유
  Cypher를 금지하며 Semantic Contract/G1 재검증과 Policy fail-closed를 유지한다.

### 3.2 DataHub-first로 바꾸는 결정

| v3.4 기준 | 최종 결정 | 이유 |
|---|---|---|
| DataHub + PostgreSQL Semantic Registry를 공동 정본으로 둠 | 신규 semantic authoring은 DataHub Core로 수렴. App에는 immutable 실행 projection·receipt만 유지 | 중복 정본과 관리 UI를 줄이고 DataHub 기능을 우선 사용 |
| 요청 runtime은 Local Snapshot 중심 | 질문 후보는 DataHub bounded Search, 실행은 active immutable projection 사용 | relevance 검색과 release 결정성을 분리 |
| `semantic.resolve`를 App MCP Tool로 노출 | 내부 `Context Gateway` operation으로 유지하고 공개 Tool로 복제하지 않음 | DataHub search/entity/schema 기능 중복 방지 |
| MCP Tool 7개를 목표 계약으로 고정 | 현재·목표·조건부 Tool을 분리하고 실제 미배포 이름은 재설계 가능 | 문서 목표와 호환 계약 혼동 방지 |
| Neo4j를 P1 필수 부분 적용 | Analysis critical path에서 제외. DataHub graph·lineage·search의 정량 gap이 증명될 때만 별도 실험 | 현재 규모에서 운영·동기화 비용 대비 이득 미증명 |
| RAG 문서 corpus를 별도 준비 | DataHub Context Documents의 URN/version/association을 문서 정본으로 사용 | 문서 정본 재구현 방지 |
| RAG retrieval은 pgvector 우선 | DataHub lexical/semantic retrieval을 먼저 평가하고, 미달 시 DataHub 문서 버전에 결속된 파생 pgvector 허용 | 권위와 검색 index 책임 분리 |
| Single-turn 뒤 Multi-turn 기능 구현 | 전체 Golden Dialogue는 뒤에 두되 CAS·idempotency·transaction·release pinning은 모든 신규 production 경로의 선행 Safety Foundation으로 이동 | 현재 기본 Conversation 경로의 live 안전 결함 |
| 2026-09-03까지 모든 P1 요소를 압축 구현 | 날짜가 아니라 이전 Phase Gate로 진입을 통제 | 거짓 완료와 동시 리스크 방지 |

`docs/product/*`는 Phase 0A에서 위 변경과 동기화한다. 루트 v3.4 원문은 baseline으로 보존하고
차이를 감사 문서에 명시한다. 과거 문서를 현재 진행률 근거로 사용하지 않는다.

## 4. 2026-08-22 현재 상태 스냅샷

이 절은 최종 설계가 아니라 이번 전략 작성 시점의 관측이다. 다음 실행은 값을 다시 읽고,
다른 source·image·release의 증거를 합치지 않는다.

증거 상태는 다음 enum만 사용한다.

```text
CURRENT_HOST
IMPLEMENTED_HOST_UNDEPLOYED
DEPLOYED_UNVERIFIED
CURRENT_LIVE_OBSERVED
IMPLEMENTED_PARTIAL
NOT_PUBLISHED
UNVERIFIED
HISTORICAL_EVIDENCE
PLANNED
CONDITIONAL
BLOCKED
```

| 영역 | 현재 판정 | 근거와 한계 |
|---|---|---|
| Git | `CURRENT_HOST` | `daesung`, HEAD `8379911`, 감사 시작 시 dirty 29건. 문서 수정 후 다시 캡처 필요 |
| 실행 stack | `CURRENT_LIVE_OBSERVED` | Backend·Frontend·Trino·DataHub GMS·App PostgreSQL은 실행/health 확인 |
| 배포 provenance | `UNVERIFIED` | Backend image에 source commit·dirty patch digest가 없어 현재 host 변경과 동일 source인지 증명 불가 |
| host DataHub Search | `IMPLEMENTED_HOST_UNDEPLOYED` | `lexical_shadow`, `datahub_lexical`, bounded `searchAcrossEntities`, RRF와 test가 dirty tree에 존재 |
| live Search mode | `CURRENT_LIVE_OBSERVED` | 기본값 `lexical`, TTL snapshot 기반. Search API capability 자체는 live read-only 확인 |
| DataHub indexing/publish health | `UNVERIFIED` | GMS read는 정상이나 Actions container 재시작 누적 514회가 관측됨. active release의 search-index coverage·read-after-write freshness는 별도 증명 필요 |
| semantic/hybrid | `UNVERIFIED` | DataHub semantic overlay 소스는 있으나 live는 OpenSearch 2.19.3이며 ES 8.18.2/Ollama overlay가 실행되지 않음 |
| active semantic release | `CURRENT_LIVE_OBSERVED` | Dataset 51, Glossary Term 10, compiled Metric 14, Dimension 3, JOIN edge 0 |
| native DataHub Metric | `NOT_PUBLISHED` | live `METRIC` entity 0. 현재 shadow check는 production authority가 아님 |
| product release receipt | `IMPLEMENTED_PARTIAL` | host에 checksum receipt 코드가 있으나 live image와 Conversation·Turn·Context·Run·Artifact·View·Report 전체에 영속되지 않음 |
| MCP `analysis.get_run@1.0.0` | `DEPLOYED_UNVERIFIED` | live registry enabled, migration·router 존재. 이번 감사의 인증 호출은 미실행 |
| Conversation | `IMPLEMENTED_PARTIAL` | API·UI·DB는 사용 중이나 정식 Alembic 소유, hash-before-replay, 필수 CAS, atomic terminal commit, release pin과 crash reconcile 미완료 |
| 다중 자산 JOIN | `BLOCKED` | planner·guard는 존재하지만 typed compiler는 한 asset만 선언하고 active release JOIN edge가 0 |
| 현재 Browser E2E | `UNVERIFIED` | 과거 smoke와 실행 중 stack을 현재 dirty source의 same-release E2E로 승계할 수 없음 |

진행상황 문서의 8/12·8/13·8/17 성공 기록은 유용한 역사 자료지만 현재 완료 근거가 아니다.
현재 live DB에서 오래된 비terminal command/run, 만료 lease, `product_release_id`가 없는 Artifact도
관측됐다. 따라서 Conversation Safety와 durable release evidence는 Search production cutover와
새 Browser `VERIFIED` 선언의 선행조건이다.

## 5. 목표 구조

```text
                         General Chat UI
                               │
                 General Orchestrator (Analysis 이후)
           route · subject · budget · state · evidence synthesis
                 ┌─────────────┼─────────────┐
                 │             │             │
            analysis.run    rag.answer    ml.predict
                 │             │             │
          Analysis Agent    RAG Agent     ML Agent
                 │             │             │
                 └─────────────┼─────────────┘
                               │
                    Controlled Context Gateway
       entitlement · typed projection · release · timeout · audit
                               │
                        DataHub Core v1.7
      Glossary · Dataset/Schema · Search · Lineage · Documents
       Metric/AI Context · SemanticModel · Query · Quality · ML metadata

 Analysis → typed plan/compiler → SQLGlot G2 → Trino → G3 → Artifact
 RAG      → document retrieval → citation verifier → Evidence
 ML       → approved model serving → evaluation/provenance → Evidence
```

`Context Gateway`는 P0에서 새 microservice가 아니다. modular monolith 내부 port·adapter와
정책 경계다. 모든 Agent가 DataHub GraphQL/MCP를 제각각 호출하지 않고 같은 entitlement,
release, timeout, projection과 audit를 재사용한다.

## 6. 책임 경계와 DataHub Core 채택 범위

### 6.1 DataHub Core가 소유할 것

| 영역 | DataHub 객체·기능 | 단계 |
|---|---|---|
| 기업 용어 | Business Glossary, Term 관계·owner·관련 자산 | `NOW` |
| 물리 자산 | Dataset, SchemaField, platform identity, description | `NOW` |
| 조직·분류 | Domain, Owner, Tag, lifecycle | `NOW` |
| 검색 | `searchAcrossEntities`, entity query, `scrollAcrossEntities` | `NOW / SHADOW CUTOVER` |
| 추가 계약 | Structured Properties | `NOW`, 새 필드는 live probe 후 |
| 계보 | table·column·pipeline Lineage | `NOW` |
| 문서 | Context Documents, version, related assets | `NOW AUTHORING / RAG LATER` |
| 지표 문맥 | Metric, 별도 `aiContext` aspect | `EARLY SHADOW` |
| 논리 모델 | SemanticModel, semantic field, relationship/cardinality | `LATER SHADOW` |
| 사용 예시 | Query entity/history | `LATER`, source capability와 PII redaction 필요 |
| 품질 | 외부 Assertion run/result metadata | `LATER`, Core가 검사를 실행한다고 가정하지 않음 |
| ML | MLModel/Group/Feature/Table/Deployment metadata | `ML PHASE` |
| Agent inventory | aiAgent/agentSkill/API/Service metadata | `LATER METADATA ONLY` |
| read-only MCP | 내부 Context transport 후보 | `SHADOW`, model 직접 노출 금지 |

### 6.2 애플리케이션이 소유할 것

- 사용자·객체·행·열 entitlement와 permission snapshot
- DataHub 응답 schema 검증, 최소 typed projection과 prompt injection 방어
- `product_release_id`와 data/semantic/model/prompt/policy/migration receipt
- release compiler, activation pointer, canary, rollback과 durable evidence manifest
- Conversation, Turn, focus, CAS, lease, idempotency, recovery와 transaction
- Node1 후보 출력의 active release 재검증
- `RuntimeContextPackage`, `AnalysisPlan`, JOIN 전략과 query policy
- deterministic SQL compiler, SQLGlot AST 검증, Trino 실행과 cancel/budget
- Safe Artifact, Evidence, ViewSpec, Report lineage
- 승인 ML task의 실제 inference
- General Orchestrator의 route, fan-out/fan-in, partial semantics와 합성

App의 compiled projection은 DataHub와 경쟁하는 authoring 정본이 아니다. DataHub aspect를
하나의 immutable 실행 release로 변환한 파생물이며, 정의·별칭·관계를 별도 관리하는 UI나
DB를 만들지 않는다.

### 6.3 Core에서 사용할 수 없는 것으로 간주할 것

- Ask DataHub와 DataHub Agents runtime
- Managed Agent Registry UI/workflow
- query-time Search Access Controls와 enhanced usage-aware ranking
- Cloud 전용 cross-platform query mining
- Cloud native monitor·anomaly detection·Health Dashboard
- 자동 approval workflow·context generation/evaluation

Core의 Search는 사용자별 query-time ACL을 제공한다고 가정하지 않는다. Search hit의 URN/type
외 metadata는 entitlement 확인 전에 model, 공개 trace와 사용자에게 노출하지 않는다.

## 7. DataHub API, Search와 BM25 정책

### 7.1 API별 사용 결정

| API/operation | 최종 용도 |
|---|---|
| GraphQL `searchAcrossEntities` | 사용자 질문의 bounded lexical 후보 검색 |
| GraphQL entity query | 권한·release를 통과한 Dataset·Term·Metric·관계 상세 조회 |
| GraphQL `scrollAcrossEntities` | release compiler의 전체 membership·정합성 검증. 질문 relevance 판단 금지 |
| `semanticSearchAcrossEntities` | lexical 평가 미달과 semantic 운영 Gate를 모두 통과한 뒤 조건부 사용 |
| Rest.li `/entitiesV2`/aspect read | GraphQL 미노출 exact current aspect 검증 |
| OpenAPI v3/generic patch | 새 authoring·association 갱신. live capability와 동기 read-back 검증 후 사용 |
| DataHub MCP | 동일 Gateway 뒤의 내부 read-only transport 후보. LLM·Frontend 직접 접근 금지 |
| MCP mutation | runtime 비활성 |

질문 runtime은 다음 순서를 따른다.

```text
질문
 → 승인 label·alias로 bounded query variants 생성
 → DataHub searchAcrossEntities top-K
 → URN/type 단계 entitlement + active release membership filter
 → RuntimeCatalogProjection에서 최소 상세 Context 투영
 → Node1InterpretationContext
 → Node1 candidate
 → active release + entitlement + semantic contract 재검증
```

release 생성은 질문 runtime과 분리한다.

```text
Git/PR desired state 또는 승인 authoring
 → 최소권한 DataHub publisher
 → full scroll + exact aspect read-back
 → Trino schema fingerprint
 → immutable RuntimeCatalogProjection compile
 → checksum/product receipt
 → shadow equality + canary + rollback rehearsal
 → atomic active pointer 전환
```

### 7.2 검색 mode와 전환

```text
lexical baseline
 → lexical_shadow
 → held-out retrieval·권한 negative·latency Gate
 → datahub_lexical
 → lexical gap이 증명될 때만 semantic/hybrid Gate
```

- `lexical`: active snapshot 어휘로 local lexical candidate를 고른다.
- `lexical_shadow`: production 선택은 유지하고 DataHub lexical Search를 관측한다.
- `datahub_lexical`: DataHub Search rank를 production 후보 신호로 사용하며 실패를 숨기지 않는다.
- `hybrid`: 현재 구현에서는 semantic search 호출로 이어진다. readiness receipt 없이는 활성화하지 않는다.

조건부 Gate S1 전에는 `DATAHUB_SEARCH_MODE=hybrid`, semantic overlay
bootstrap, embedding publish와 semantic index cutover를 금지한다.

### 7.3 BM25 결정

BM25는 별도 App 기능이나 새 검색엔진으로 구현하지 않는다.

- 지금의 우선 과제는 **DataHub lexical retrieval을 shadow 평가하는 것**이다.
- 같은 release의 DataHub index/mapping/config가 실제 BM25 사용을 증명할 때만 결과 보고서에서
  `BM25`라고 부른다. 그 전에는 `DataHub lexical retrieval`이라고 쓴다.
- Top-1, Recall@K, MRR/nDCG, negative closure와 p50/p95가 부족하면 query planner,
  analyzer·field boost·DataHub ranking 설정을 먼저 검토한다.
- 별도 App BM25 index는 만들지 않는다.
- BM25/lexical/semantic 검색은 후보 recall만 개선한다. 계산식, grain, JOIN, 시간축과 권한
  정확성은 Semantic 계약과 compiler가 해결한다.

## 8. Semantic 계약, release와 AI Context

### 8.1 권위 모델

- Glossary Term: 기업 개념, 정의, owner, 관련 자산과 기업 용어 alias
- Metric: 계산식·binding, 단위, 집계·reduction, grain, time, 허용 dimension
- 별도 `aiContext` aspect: `synonyms`, `instructions`, `examples`, `customInstructions`
- SemanticModel: 논리 Dataset, dimension·measure, relationship·cardinality
- Structured Properties: native field로 표현하기 어려운 typed governance
- Lineage: provenance와 impact 근거. JOIN predicate나 허용 계약이 아님
- Query entity: 관측 예시. 실행 권위가 아님
- Context Document: 설명 근거. KPI 계산 권위가 아님

DataHub v1.7.0에서 `aiContext`는 `metricInfo.aiContext` 중첩 필드가 아니라 별도 aspect다.
`MetricInfo`는 pinned v1.7 기준 schemaVersion 4다. `aiContext` 필드에 검색 annotation이 있다는
근거도 없으므로 native AI Context 채택이 Search recall을 자동 개선한다고 약속하지 않는다.

현재와 목표의 synonym 권위를 섞지 않는다.

| 의미 범위 | 현재 migration source | 목표 authority |
|---|---|---|
| 기업 개념·용어 alias | DataHub Glossary description/custom properties | DataHub Glossary의 승인된 개념·용어 metadata |
| Metric·SemanticModel·SchemaField 해석 synonym/example | Glossary/custom property와 App canonical compile 결과 | capability Gate를 통과한 대상 entity의 별도 DataHub `aiContext` aspect |
| 계산식·grain·집계·time | App canonical contract와 DataHub read-back | 검증된 DataHub native aspect를 source로 삼는 immutable 실행 projection |

현재 별칭·정의는 이미 DataHub에서 live read-back되는 운영 metadata이므로 capability 결정 전의
명시적 migration source로 사용할 수 있다. native AI Context가 pinned Core에서 미지원이면 그
부재 증거와 재검토 조건을 기록하고 임시 source를 유지하되, 이를 목표 native authority 달성으로
보고하지 않는다. `BLOCKED_ENV`이면 자동으로 임시 source를 선택하지 않고 환경을 해소하거나
사용자가 승인한 risk exception을 기록한다.

`instructions`와 `customInstructions`는 승인됐더라도 비신뢰 metadata다. system prompt에 직접
합치지 않고 allowlist, 길이, schema, injection 검사를 통과한 data field로만 선택 투영한다.

### 8.2 immutable 실행 projection

현재 `CanonicalSemanticRelease`라는 구현 이름은 교체할 수 있다. 반드시 유지해야 하는 것은
다음 책임이다.

- immutable release ID와 stable logical entity identity
- DataHub URN·aspect version·membership
- source/catalog/manifest/canonical checksum
- Trino schema fingerprint
- label·definition·synonym·unit·time·status의 Node1 projection
- metric·dimension·join·policy의 Runtime projection
- activation receipt, canary 결과, rollback pointer

현재 native Metric shadow의 URN에 catalog hash가 들어가 release마다 논리 identity가 바뀌는
문제는 authority cutover 전에 해결한다. stable Metric identity와 versioned release membership을
분리하거나, 명시적인 active/retirement filter를 둔다.

`CatalogSnapshotLoader`는 즉시 삭제하지 않는다. out-of-band compiler의 completeness,
checksum equality, activation CAS, runtime shadow 비교와 rollback을 증명한 뒤 full read-back을
release job으로만 이동한다. 주된 위험은 metadata/release stale, TTL, N+1과 장애 결속이며,
사용자 entitlement 자체를 snapshot이 소유한다고 표현하지 않는다.

## 9. Node1, Analysis와 JOIN 계약

### 9.1 Node1

Node1은 자연어를 typed candidate로 구조화할 뿐 실행 권위가 아니다.

`Node1InterpretationContext.v1` 최소 필드:

- DataHub URN, canonical ID/name, label
- 승인 definition과 synonyms
- unit, aggregation, time semantics
- 허용 dimension/filter와 짧은 positive/negative example
- approval/quality 상태
- product/semantic release와 checksum
- retrieval evidence와 permission receipt

Node1은 projection 밖 ID, 권한 밖 ID, 다른 release ID를 선택할 수 없다. 결과는 서버가 active
release에서 다시 결속한다. native AI Context capability 결정을 먼저 내리고, projection compiler가
선택한 검증된 native source 또는 명시적 DataHub Glossary migration source만 사용한다.

```text
Node1InterpretationContext  = 자연어 해석용 최소 후보
RuntimeContextPackage      = 권한·자산·Metric·JOIN·time이 확정된 Analysis 실행 계약
```

두 Context를 합치거나 RAG·ML까지 담는 거대한 공통 ContextPackage를 만들지 않는다.

### 9.2 SQL과 복잡 질문

우선순위:

1. deterministic typed compiler
2. 필요한 범위에만 제한된 Node2 candidate
3. G2와 동일 SQLGlot AST 검증
4. 최대 1회의 bounded repair
5. 불명확·미지원이면 clarification 또는 typed failure

현재 저장소에는 `DIRECT_JOIN`, `PREAGGREGATE`, `SEMI_JOIN` 정책, logical plan과 fan-out/grain
guard가 존재하지만 typed compiler는 `max_physical_assets=1`, `join_plans=[]`다. 기존 코드를
유지할지는 구현 품질로 결정하되 다음 행위 계약은 유지한다.

- 승인 relationship과 exact join field만 사용
- cardinality, 양쪽 grain, additivity와 fan-out을 검증
- `DIRECT_JOIN`, `PREAGGREGATE`, `SEMI_JOIN`별 deterministic SQLGlot AST 생성
- many-to-many, 혼합 time mode, 승인 relation 부재는 추측 실행하지 않음
- 실제 Trino result oracle로 중복 집계 0건을 증명

복잡 질문 지원은 자연어 예시가 아니라 operation, metric 수, physical asset 수, join strategy,
time mode와 multi-turn dependency의 capability matrix로 선언한다.

## 10. Conversation과 durable evidence

Conversation은 이미 기본 Browser 요청 경로에 있으므로 후순위 UI 기능이 아니다. Search나
Node1 production cutover 전에 최소 Safety Foundation을 닫는다.

필수 계약:

- 수기 DDL을 새 Alembic revision이 소유하며 배포된 과거 revision은 수정하지 않음
- client는 idempotency key와 payload를 보내며, 서버가 확정한 path·subject·permission·release를
  포함해 authoritative payload를 canonicalize/hash한다. 저장 hash와 replay 전에 비교하고,
  client 제공 hash가 있더라도 참고값으로만 취급
- head를 바꾸는 command는 mandatory `expected_head_turn_id`와 CAS 사용
- Run terminal, immutable Turn, focus, head advance, command terminal과 lease release의 원자적
  commit 또는 검증된 recoverable outbox 계약
- `RequestContext.conversation_id`, path identity, owner, permission snapshot을 서버가 결속
- Conversation에 `product_release_id`를 pin하고 Turn·Run·Artifact·View·Report로 전파
- stale RUNNING/RECEIVED, expired lease와 orphan query를 멱등 terminalize하는 reconciler
- 과거 Artifact에 release가 없으면 새 release로 조용히 재해석하지 않음

Safety Foundation 뒤 same-asset 분석을 안정화하고, 이어서 slot inheritance, clarification resume,
focus, presentation zero-query, report action과 Golden Dialogue를 확장한다.

## 11. Capability와 멀티에이전트 계약

### 11.1 현재·목표 Tool 상태

| 식별자 | 현재 상태 | 최종 결정 |
|---|---|---|
| `analysis.get_run@1.0.0` | live registry enabled, router 구현, 이번 인증 호출 미검증 | 호환 식별자로 유지. 대체 시 versioned deprecation 필요 |
| `/analysis` + `analysis.run` permission | HTTP use case 존재 | P0 통과 뒤 같은 application use case를 MCP high-level Tool로 봉인 |
| `artifact.get` | v3.4 목표, 미배포 | `analysis.get_run`과 중복·consumer 필요성을 확인한 뒤 조건부 추가 |
| `semantic.resolve` | v3.4 목표, 미배포 | 공개 Tool로 만들지 않고 Context Gateway 내부 operation으로 사용 |
| `graph.resolve` | v3.4 목표, 미배포 | Neo4j conditional Gate 전 목표 capability가 아님 |
| `rag.search` | v3.4 목표, 미배포 | retrieval 내부 operation. 외부 high-level capability는 `rag.answer` |
| `ml.predict` | 미배포 | ML Gate 후 승인 task만 추가 |
| `report.add_block` | 미배포 | 기존 Report Service를 우회하지 않는 wrapper 필요 시 추가 |

DataHub search/entity/schema/lineage/document operation을 같은 의미의 App MCP Tool로 복제하지
않는다. 필요하면 Context Gateway 뒤 GraphQL/Rest.li adapter 또는 DataHub read-only MCP를 쓴다.

### 11.2 공통 envelope

`CapabilityInvocation.v1`:

- request/conversation/turn ID
- capability와 typed payload
- effective subject와 permission snapshot
- product release와 capability release vector
- source Turn·Artifact refs
- deadline, token/tool/query budget
- idempotency key. admission 뒤 서버가 계산한 canonical hash는 immutable internal envelope에 기록

`CapabilityResult.v1`:

- `SUCCEEDED | PARTIAL | BLOCKED | FAILED | CANCELLED`
- typed reason code와 clarification
- Artifact/Evidence refs
- coverage, warnings, release와 permission receipt

Evidence는 `OBSERVED_DATA`, `DOCUMENTED_CONTEXT`, `MODEL_PREDICTION`, `DERIVED_INFERENCE`를
구분한다. Agent 사이에는 raw 전체 context가 아니라 immutable reference만 전달한다.

### 11.3 후속 Agent

- RAG: DataHub Context Documents가 문서 정본이다. lexical/semantic document retrieval이
  평가에 미달할 때만 DataHub URN/version에 결속된 파생 pgvector index를 허용한다.
- ML: DataHub는 model/feature/training lineage metadata를 소유하고 App은 승인 inference를
  실행한다. 첫 task는 baseline보다 나은지 검증한 forecast 하나로 제한한다.
- General Orchestrator: route, budget, state, permission 재검증, bounded fan-out/fan-in과 evidence
  synthesis만 소유한다. capability 내부 계산과 Gate를 우회하지 않는다.

## 12. 최종 실행 로드맵

Phase는 날짜가 아니라 Exit Gate 의존 순서다. 한 실행에서는 하나의 Phase 또는 아래에 번호가
붙은 하나의 명시적 subphase만 처리한다. subphase Gate의 검토·필요 승인을 건너뛰어 다음
subphase로 이어서 실행하지 않는다.

일괄 자동 진행을 승인받은 실행은 Gate 통과 보고 뒤 사용자 응답을 기다리지 않을 수 있다.
그러나 각 numbered Phase의 국소 Gate 외에 현재 host tree 전체 검증도 다음 Phase의 필수
선행조건이다. 정적 정책, 전체 Python suite, frontend test/build, Compose 전개와
`git diff --check` 중 하나라도 실패하면 격리 Acceptance가 PASS여도 다음 Phase로 진행하지
않는다. Phase 전용 subset은 결함 위치를 좁히는 증거일 뿐 전체 회귀를 대체하지 못한다.
system 임시 디렉터리 권한은 제품 실패와 분리하기 위해 고유한 저장소 내부 `--basetemp`를
사용하고, 생성한 정확한 임시 경로만 검증 후 정리한다.

격리 live Gate 전후에는 current/target typed resource 교집합 0, target health, Docker Engine
응답과 host/Docker memory를 read-only로 측정한다. 현재 31.64GiB host와 15.44GiB Docker
한도에서는 host available memory가 4GiB 미만이거나 실행 container 합계가 Docker 한도의
90%를 넘으면 `BLOCKED_RESOURCE`로 중단한다. OOM, `no route to host`, unhealthy target도 같은
중단 조건이다. Acceptance runner는 하나씩 실행하며 Phase 6~10을 위해 두 번째 full DataHub
stack을 추가하지 않는다.

### Phase 0A — 기준·현재·목표 정합화 (`ACTIVE`)

- v3.4 4종, `docs/product/*`, 현재 host, deployed image, migration, live DataHub/App DB를 분리
- `v3.4 목표 ↔ current host ↔ deployed live ↔ DataHub-first 결정` matrix 작성
- DataHub/App authority, API/Search/MCP, Tool current/target, JOIN/Conversation capability 확정
- semantic overlay 문서와 기존 eval 계보 감사
- `docs/product/*`의 DataHub 관련 drift를 최소 수정

Gate: 모든 결정에 코드·문서·runtime 중 맞는 증거 유형이 있고 미확인을 완료로 쓰지 않음.

### Phase 0B — 공통 compatibility·evidence 계약

- `CapabilityInvocation/Result/EvidenceRef` versioned schema
- product release receipt의 Conversation·Turn·Context·Run·Artifact·View·Report 영속 계약
- source commit, dirty patch, image, migration, model, catalog를 묶는 evidence manifest
- 공개 identifier compatibility test

Gate: 기존 API/MCP 결과 non-regression과 schema migration/rollback 계약.

### Phase 1 — Conversation Safety Foundation

- Alembic 소유권, hash-before-replay, mandatory head CAS
- terminal atomicity 또는 recoverable outbox
- stale command/run/lease와 orphan query reconciler
- Conversation release pin과 permission/path identity

Gate: stale nonterminal 0, crash-point fault injection, duplicate query/Turn 0, 신규 요청의 path와
`RequestContext.conversation_id` 일치, Turn↔Run↔Artifact lineage 100%, permission/release receipt가
Conversation·Turn·Run·Artifact로 전파되고 release 없는 신규 Artifact 0.

### Phase 2 — DataHub lexical Search shadow와 production 결정

#### 2A — shadow

- bounded query planner와 `searchAcrossEntities`
- `lexical_shadow` 배포, permission negative closure, timeout/cancel/task 상한
- 하나의 canonical retrieval evaluator와 독립 한국어 held-out Gold Set

Gate 2A: unauthorized metadata 노출 0, baseline non-regression, Top-1/Recall@K/MRR·p95 측정,
shadow 실패가 production 선택에 영향 0.

2A 결과를 검토하고 production 변경 승인을 받은 뒤 2B를 별도 `ACTIVE_PHASE`로 실행한다.

#### 2B — canary와 cutover

- active release의 search-index coverage와 read-after-write 또는 동등 freshness receipt
- DataHub Actions 안정 관측, `datahub_lexical` canary, cancel/timeout/fail-closed 검증
- `PROMOTE | HOLD | REJECT` 결정과 이전 `lexical` mode로의 명시적 rollback rehearsal

Gate 2B: `PROMOTE`는 canary non-regression과 권한 negative 0을 통과한 뒤 default 전환까지
완료한 상태다. `HOLD`는 bounded tuning·재평가 동안 Phase 2에 남고, `REJECT`는 근거와 대안에
대한 사용자 architecture 결정을 요구한다. 둘 다 DataHub Search 전환 완료로 보고하지 않는다.

### Phase 3 — native Metric·AI Context capability 결정

#### 3A — pinned schema와 live capability probe

- pinned DataHub v1.7 schema에서 Metric 계산식 필드와 별도 `aiContext` aspect를 확인
- publish/read-back API, stable logical URN, release membership·retirement, rollback 경로 확인
- 결과를 `SUPPORTED | UNSUPPORTED_IN_PINNED_CORE | BLOCKED_ENV` 중 하나로 봉인

Gate 3A는 결과별로 다르다.

- `SUPPORTED`: 같은 pinned Core version의 schema·API와 승인된 shadow write/read-back 증거 필요
- `UNSUPPORTED_IN_PINNED_CORE`: pinned schema/entity registry의 부재 또는 미지원 증거로 종료하고,
  Phase 4에서 명시적 DataHub Glossary migration source를 허용
- `BLOCKED_ENV`: live 판단을 완료한 것이 아니므로 Phase 4 자동 진입 금지. 환경을 해소하거나
  사용자 승인 risk exception과 제한된 migration 경로를 별도 기록

3A 결과와 필요한 DataHub mutation 승인을 검토한 뒤, `SUPPORTED`일 때만 3B를 별도
`ACTIVE_PHASE`로 실행한다.

#### 3B — 지원된 범위의 shadow/equality

- 지원된 native Metric/`aiContext`만 stable identity로 shadow publish
- 기존 계산 계약·synonym/example과 equality 및 Search 영향·prompt injection을 별도 측정
- authority activation 없이 read-back, retirement와 rollback을 검증

Gate 3B: aspect read-back·identity·checksum equality, 권한 negative, injection 우회 0,
rollback 성공. 3A가 `UNSUPPORTED_IN_PINNED_CORE`이면 3B를 skip하고 migration source와 재검토
조건을 기록한다. `BLOCKED_ENV`이면 3B와 Phase 4를 block하고 승인된 risk exception만 예외로 둔다.

### Phase 4 — immutable RuntimeCatalogProjection cutover

- Phase 3 `SUPPORTED` 범위는 검증된 native aspect를 우선 사용하고,
  `UNSUPPORTED_IN_PINNED_CORE` 범위만 명시적 DataHub Glossary migration source로 compile.
  `BLOCKED_ENV`는 사용자 승인 risk exception 없이는 activation 금지
- full scroll/read-back을 out-of-band release compiler로 이동
- Trino fingerprint, checksum equality, activation CAS, canary와 rollback
- Conversation·Turn·Context·Run·Artifact·View·Report에 product receipt 전파
- 현재 loader와 shadow 비교 후에만 runtime full snapshot 제거

Gate: source-selection manifest 존재, membership/equality 100%, mixed release 0, rollback rehearsal,
cold/warm readiness evidence.

### Phase 5 — Analysis Node1 grounding

- RuntimeCatalogProjection의 label·definition·synonym·unit·time으로
  `Node1InterpretationContext.v1` 생성
- entitlement 후 최소 projection과 active release 재결속
- AI Context instruction/example은 allowlist·schema·length·injection Gate 뒤 선택 투영

Gate: projection 밖 실행 0, joint slot 기준 통과, injection 우회 0, source authority와 release
evidence 누락 0.

### Phase 6 — 동일 serving asset single-turn 분석

- aggregate, breakdown, trend, top/bottom N, period comparison
- 동일 asset 복수 Metric·ratio
- deterministic compiler 우선, 명확화와 unsupported closure

Gate: sealed SQL AST·Trino result oracle, cancel/timeout/empty/schema drift, same-release Artifact.

### Phase 7 — bounded multi-turn과 Artifact flow

- slot provenance, clarification resume, focus와 source Turn
- presentation zero-query, Report action
- Golden Dialogue와 refresh/retry/권한 회수/release 변경 negative

Gate: Turn·Run·query·Artifact 수와 transaction/lineage가 계약에 일치.

### Phase 8 — 나머지 DataHub native semantic shadow

- pinned capability probe에서 확인된 MetricInfo 계산식 필드와 Structured Properties 확대
- SemanticModel, semantic field, relationship/cardinality
- legacy/native compiled projection equality와 rollback

Gate: 전체 aspect read-back, checksum/identity, 검색·Node1·SQL·결과 non-regression.

### Phase 9 — 다중 자산 deterministic JOIN compiler

1. one-to-one/many-to-one `DIRECT_JOIN`
2. `PREAGGREGATE`
3. `SEMI_JOIN`
4. 검증된 mixed time mode

Gate: 승인 edge만 사용, 중복 집계 0, 전략별 SQLGlot AST와 실제 Trino Gold 결과,
many-to-many·불명확 경로 차단.

### Phase 10 — P0 same-release 봉인

- PRD P0 Gate, release activation/rollback, Gold/Safety/Failure/Quant/Evidence
- 현재 source/image/model/DataHub/Trino/App DB/Browser를 하나의 manifest로 연결

Gate: 해당 Requirement만 `VERIFIED`; skip·historical evidence 혼합 0.

### Phase 11 — `analysis.run` capability 봉인

- direct API와 Tool이 같은 use case 호출
- `analysis.get_run@1.0.0` compatibility
- permission/release/budget/idempotency/cancel/audit

Gate: API/Tool 결과 동등, G1/G2/G3 우회 0.

### Phase 12~14 — RAG, ML, General Orchestrator

- Phase 12 RAG: Context Documents, citation, retrieval·injection·ACL Gate
- Phase 13 ML: approved forecast, baseline, version/freshness/uncertainty Gate
- Phase 14 Orchestrator: 단일 capability부터 시작해 제한된 DAG와 partial semantics

각 Agent가 독립 Gate를 통과하기 전 placeholder Agent나 자동 fan-out을 만들지 않는다.

### 조건부 Gate S1 — DataHub semantic/hybrid Search

진입 조건은 Phase 2의 독립 held-out 결과에서 lexical recall/latency gap이 증명되고, semantic
운영비와 개인정보 처리 범위가 승인된 경우다.

- pinned index mapping/index alias와 embedding·query model digest 일치
- active release vector population/coverage와 read-after-write freshness receipt
- DataHub Actions 안정성, cold/warm readiness, p50/p95와 lexical 대비 품질 이득
- entitlement/permission negative, index rollback과 lexical 복귀 rehearsal

Gate S1: 위 증거를 same-release manifest로 봉인하고 모두 통과한 뒤에만 `hybrid`를 canary로
활성화한다. `FAIL` 또는 `BLOCKED`면 lexical을 유지하며 기본 Phase 진행을 막지 않는다.

### 그 밖의 조건부 확장

- Neo4j/`graph.resolve`: Phase 10이 같은 product release에서 `VERIFIED`된 뒤에도 DataHub
  graph·lineage·Search와 RuntimeCatalogProjection만으로 독립 held-out relation-path recall,
  회복률 또는 latency가 사전 기준을 반복해서 못 넘고, Postgres/in-process 검증 같은 더 단순한
  대안보다 별도 graph read model의 순이득이 큰 경우에만 ADR과 별도 spike를 연다.
  첫 단계는 기술·edition 선택이 아니라 workload, OFF/ON 기준선, 운영 budget, failure semantics를
  봉인하는 문서 Gate다. 이 Gate 전에는 Neo4j code·container·volume·dependency를 추가하지 않는다.
- 채택하더라도 `DataHub authoring SoT → immutable RuntimeCatalogProjection → versioned read-only
  candidate graph → 내부 고수준 resolver → APP-G1 재검증`의 단방향만 허용한다. reverse sync,
  dual SoT, Raw row·PII·secret·사용자별 Effective Policy·LLM 추측 관계, 외부 raw Cypher와 자유
  형식 Cypher 실행은 금지한다.
- graph projection은 schema/release/source checksum을 고정하고 deterministic invariant 검증,
  candidate exact read-back, canonical equality, activation·rollback을 통과해야 한다. 특정 검증
  라이브러리는 미리 의무화하지 않고 현재 계약을 가장 작게 구현하는 수단을 선택한다.
- 내부 resolver는 allowlist된 parameterized query template, 최대 hop·후보·결과·timeout budget,
  release/checksum 결속과 typed failure를 강제한다. Graph 결과는 실행 후보일 뿐이며 권한,
  cardinality, grain, unit, time 계약을 APP-G1에서 다시 검증한다. 단순 분석에는 Graph 호출을
  추가하지 않고, Graph 장애를 stale projection·전체 local scan·LLM 추측으로 숨기지 않는다.
- LangGraph: explicit async orchestration이 상태·resume·fan-out 복잡도에서 실제 한계를 보일 때만

평가 근거와 수용·보류 결정은
[Phase 0~10 회고 및 Post-P10 Graph Foundation 평가](DataHub_Core_Phase0_10_회고_Graph_Foundation_평가.md)에
기록한다.

## 13. 평가와 운영 Gate

### 13.1 canonical eval 계보

`evals/metric_retrieval.py`와 runner를 기본 확장 경계로 사용한다. 더 나은 evaluator로 교체할 수
있지만 같은 Phase에서 기존 manifest·metric·historical comparability를 migration하고 과거
경로를 retire한다. 서로 다른 threshold와 Gold Set을 가진 병렬 평가 체계는 두지 않는다.

catalog에서 자동 생성한 probe는 자기일관성 test다. 독립 작성·봉인한 한국어 질문을
held-out 자연어 품질 증거로 별도 운영한다.

### 13.2 필수 telemetry

- DataHub Search p50/p95, request/variant/candidate 수
- entitlement 전후 후보·거부 수
- Top-1, Recall@K, MRR/nDCG, negative closure
- clarification, unsupported, metadata unavailable 비율
- Node1 joint slot/release/schema 위반
- deterministic compile, Node2, repair 비율
- Trino latency, scanned data, row/result budget와 cancel
- stale command/run/lease, reconciler와 idempotency conflict
- permission denial, release/checksum mismatch
- capability별 cost와 전체 Turn latency

### 13.3 보안·운영

- DataHub GraphQL, Rest.li, OpenAPI, MCP를 Frontend나 model에 직접 노출하지 않는다.
- analysis/rag/ml read principal과 publisher를 최소권한으로 분리한다.
- runtime mutation Tool은 끈다.
- 질문, DataHub description/AI Context/Document, source/result 문자열은 비신뢰 입력이다.
- 검색 metadata는 entitlement 전 prompt·공개 trace·응답에 넣지 않는다.
- DataHub/Search 실패를 stale snapshot, local JSON, mock, 빈 성공이나 전체 local scan으로 숨기지 않는다.
- 기존 pinned release 사용이 명시적으로 허용될 때만 `DEGRADED/STALE`와 evidence를 노출한다.
- current source와 다른 image의 health/readiness를 현재 변경의 E2E 증거로 사용하지 않는다.

## 14. 현실적 위험

- DataHub는 비어 있는 definition·owner·grain·relationship을 자동으로 만들어 주지 않는다.
- Core v1.7 Metric/SemanticModel/AI Context는 live capability와 운영 성숙도를 shadow로 확인해야 한다.
- DataHub Search 결과가 좋아져도 JOIN·계산·시간 오류는 그대로 남을 수 있다.
- Core Search의 query-time ACL 부재 때문에 App entitlement layer는 제거할 수 없다.
- strict validation은 초기 성공률을 낮추고 clarification/unsupported를 늘릴 수 있다. 잘못된 성공과
  구분해 측정한다.
- Multi-Agent는 accuracy를 자동으로 높이지 않으며 latency, 비용, route 오류와 partial failure를
  늘린다.
- 현재 DataHub Actions 반복 재시작 관측은 GMS read health와 indexing/publish health를 분리해
  평가해야 함을 보여 준다.
- v3.4 일정은 현재 진행률 증거가 아니며 Gate 실패 시 기능 수를 줄인다.

## 15. 명시적으로 하지 않을 것

- App의 별도 glossary·lineage·document·ML registry
- DataHub catalog 전체를 두 번째 authoring 정본으로 복제
- 별도 App BM25 검색엔진
- DataHub MCP의 model 직접 노출 또는 runtime mutation
- native Metric/SemanticModel·semantic/hybrid 즉시 production 전환
- 승인되지 않은 자유 JOIN, raw SQL, 자유 Cypher Tool
- 모든 Agent가 공유하는 거대한 ContextPackage
- Analysis 내부 Stage를 여러 Agent로 분해
- RAG·ML placeholder와 검증 전 자동 fan-out
- P0에서 microservice, queue, 범용 Agent framework 도입
- Neo4j를 체크리스트 목적으로 선도입
- 과거 release나 screenshot을 현재 `VERIFIED` 증거로 승계

## 16. 최종 성공 조건

- DataHub와 App 사이 중복 semantic authoring 정본이 없음
- 권한 밖 metadata·data 노출 0
- silent fallback과 mixed release 0
- 동일 요청의 subject/release/result 재현성
- 신규 Conversation·Turn·Context·Run·Artifact·View·Report에 durable product receipt가 존재
- 지원 Golden Set의 SQL AST와 실제 결과 oracle 일치
- 미지원 관계·질문의 안전한 차단
- Conversation idempotency/CAS/atomicity/recovery Gate 통과
- 각 Agent가 독립 평가·배포·rollback 경계를 가짐
- Orchestrator가 capability 내부 Gate를 우회하지 못함
- 관측 데이터·문서 근거·모델 예측·파생 추론이 끝까지 분리됨

## 17. 공식 자료와 저장소 근거

- [DataHub Search](https://docs.datahub.com/docs/how/search)
- [Search Access Controls](https://docs.datahub.com/docs/features/feature-guides/search-access-controls)
- [Business Glossary](https://docs.datahub.com/docs/glossary/business-glossary)
- [Structured Properties](https://docs.datahub.com/docs/features/feature-guides/properties/overview)
- [Metrics and Semantic Models](https://docs.datahub.com/docs/features/feature-guides/metrics-and-semantic-models)
- [Context Documents](https://docs.datahub.com/docs/features/feature-guides/context/context-documents)
- [Lineage](https://docs.datahub.com/docs/features/feature-guides/lineage)
- [DataHub MCP](https://docs.datahub.com/docs/features/feature-guides/mcp)
- [Agent Context Kit](https://docs.datahub.com/docs/dev-guides/agent-context/agent-context)
- [DataHub Core v1.7 `AiContext` schema](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-models/src/main/pegasus/com/linkedin/common/AiContext.pdl)
- [DataHub Core v1.7 `MetricInfo` schema](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-models/src/main/pegasus/com/linkedin/metric/MetricInfo.pdl)

필수 저장소 참고:

- `docs/reference/DataHub_Core_공식사용_BP_조사.md`
- `docs/reference/BI_범용질문_시맨틱_확장설계.md`
- `docs/reference/멀티턴_발화이해_BP_벤치마크.md`
- `infrastructure/database/datahub/SEMANTIC_SEARCH.md`
- `infrastructure/database/datahub/SEMANTIC_AUTHORING.md`

`DataHub_Core_공식사용_BP_조사.md`의 `metricInfo.aiContext`, schemaVersion 5, AI Context 검색
자동 인덱싱 문구는 pinned v1.7 사실과 다르므로 이 전략의 8절과 공식 schema를 우선한다.
