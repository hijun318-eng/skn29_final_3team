# DataHub Core Phase 0A 현행 정합성 감사

## 1. 결론과 범위

| 항목 | 판정 |
|---|---|
| 기준 시각 | 2026-08-22 KST |
| 활성 범위 | `Phase 0A` 문서·현행 정합성 감사만 |
| Phase 0A Gate | `PASS` |
| 제품 기능 판정 | `UNVERIFIED` — 이 문서는 배포·기능 인증서가 아니다 |
| 다음 Phase | 사용자 승인 전 `PLANNED` |

Phase 0A Gate는 v3.4 목표, 현재 host, 현재 deployed/live, 최종 DataHub-first 결정을 분리하고
제품 문서의 충돌을 동기화했다는 뜻이다. Search 전환, native semantic 발행,
RuntimeCatalogProjection, Conversation 보강, JOIN, MCP, RAG·ML은 구현하거나 활성화하지 않았다.

이번 감사의 권위 입력은 다음과 같다.

- 최종 전환 계약: [DataHub Core Analysis Agent 전환 전략](DataHub_Core_Analysis_Agent_전환전략.md)
- 실행 범위: [DataHub Core Analysis Agent 전환 실행 프롬프트](DataHub_Core_Analysis_Agent_전환_실행프롬프트.md)
- 제품 계약: [PRD](../product/01_PRD.md), [사용자 흐름](../product/02_유저플로우.md),
  [아키텍처](../product/03_아키텍처.md)
- v3.4 baseline:
  [PRD v3.4](../../../01_Answervice_PRD_v3.4.md),
  [기술 아키텍처 v3.4](../../../02_Answervice_기술아키텍처_v3.4.md),
  [개발 가이드 v3.4](../../../03_Answervice_개발가이드_및_우선순위_v3.4.md),
  [5단계 검토 v1.1](../../../04_Answervice_최종프로젝트_요구사항_대응_5단계검토_v1.1.md)

제외 범위는 Backend·Frontend·infrastructure production code, migration, DataHub mutation,
DB cleanup/backfill, container build/restart/recreate, search mode 변경, 외부 API 호출, commit·push다.

### 증거 상태

| 상태 | 이 문서에서의 의미 |
|---|---|
| `CURRENT_HOST` | 현재 dirty working tree에서 정적으로 확인 |
| `IMPLEMENTED_HOST_UNDEPLOYED` | host 구현은 있으나 배포 image와 불일치 |
| `DEPLOYED` | 실행 container/image에 존재함을 확인 |
| `LIVE_READ_ONLY` | 실행 환경을 변경하지 않는 조회로 관측 |
| `LIVE_AUTHENTICATED` | 인증된 실제 호출까지 관측 |
| `UNVERIFIED` | 같은 release의 요구 수준 증거 없음 |
| `HISTORICAL_EVIDENCE` | 과거 기록이며 현재 완료 증거가 아님 |
| `PLANNED` | 최종 전략의 후속 Phase 목표 |
| `CONDITIONAL` | 별도 정량 Gate를 통과할 때만 도입 |
| `BLOCKED` | 선행 Gate나 안전 결함 때문에 진행 불가 |

## 2. 시작 snapshot과 배포 관측

### Repository snapshot

| 항목 | `CURRENT_HOST` 관측 |
|---|---|
| 작업 위치 | `C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team` |
| branch / HEAD | `daesung` / `83799119a34e6e3ec48035b05427a1b0c3b756cb` |
| 파일 수 | `rg --files` 기준 815개 |
| working tree | 기존 수정·미추적 파일 다수 존재; 모두 보존 |
| 접근 경고 | `.tmp_pytest_native_metric_*` 두 경로와 사용자 전역 Git ignore 접근 거부; 삭제·정리하지 않음 |

Phase 0A 시작 전 `AGENTS.md`, DataHub/Search/모델/eval/test 파일, `docs/README.md` 등에
기존 변경이 있었다. 제품 문서 세 파일은 clean이었고, `docs/README.md`의 기존 전략 링크 변경은
보존한 채 감사 링크만 추가했다.

### Deployed/live snapshot

| 항목 | 관측 | 증거 상태 |
|---|---|---|
| Backend | healthy, image `sha256:27e5046d…`, 2026-08-21 생성, restart 0 | `LIVE_READ_ONLY` |
| Frontend | healthy, 별도 image | `LIVE_READ_ONLY` |
| Trino | 483, healthy | `LIVE_READ_ONLY` |
| App PostgreSQL | 16.13, healthy | `LIVE_READ_ONLY` |
| DataHub GMS | v1.7.0, healthy | `LIVE_READ_ONLY` |
| DataHub Actions | v1.7.0-slim, 실행 중이나 restart count 527 | `LIVE_READ_ONLY` |
| DataHub active release | `walkerhill-v4.3-sql-20260815-derived.1-retirement-20260820.1-iceberg-analyst.4-runtime-v2.20260820.4`; catalog checksum `747097cdb…`, canonical checksum `724ea6…`; 51 asset, 10 required Term, 14 metric, 3 dimension, join 0 | `LIVE_READ_ONLY` |
| 검색 backend | OpenSearch 2.19.3; ES 8.18/Ollama semantic overlay container 없음 | `LIVE_READ_ONLY` |
| Backend search mode | `DATAHUB_SEARCH_MODE=lexical` | `LIVE_READ_ONLY` |
| Backend readiness | App DB, migration, Trino, DataHub transport, catalog manifest, model 등 `ready` | `LIVE_READ_ONLY` |
| source provenance | image label에 commit·dirty patch digest 없음; host 핵심 파일 hash와 배포 파일 불일치; deployed image에 `datahub_query_plan.py`, `runtime_release.py` 없음 | `UNVERIFIED` |
| model contract | host `MODEL-RELEASE-v1.32.0`, deployed `v1.31.0` | `BLOCKED` |
| App DB migration | host head와 live `governance.alembic_version` 모두 `20260820_28`; Conversation 수기 DDL은 chain 밖 | `LIVE_READ_ONLY` |

healthy 상태는 실행 중인 image의 상태일 뿐 현재 dirty source 변경의 E2E 증거가 아니다.

## 3. 네 축 비교표

| 주제 | v3.4 목표 | 현재 host 구현 | 현재 deployed/live | 최종 DataHub-first 결정 | 근거 | 담당 Phase |
|---|---|---|---|---|---|---|
| DataHub/App/Semantic Registry authority | DataHub Glossary와 별도 Rule/Semantic Registry를 결합 | DataHub release와 App canonical metric/rule bundle이 함께 권위를 가짐 | 51 Dataset, 10 required Term, 14 compiled metric의 active release; App rule 실행 | 새 semantic authoring SoT는 DataHub Governed Context Plane. App은 entitlement, release activation/receipt, Conversation, SQL/ML 실행, G1/G2/G3, Artifact만 소유. 기존 Registry는 이행 입력 후 퇴역 | strategy §2~3; [governance runtime](../../app/backend/app/adapters/governed_data_platform.py) | 0A 결정, 3~5 이행 |
| 질문 Search와 release full read-back | Node 1이 Registry/Glossary를 조회하고 local snapshot 활용 | `searchAcrossEntities` bounded 후보와 `scrollAcrossEntities` 전체 열거 경로가 분리됨 | `searchAcrossEntities` 호출 capability는 관측; 배포된 Scroll 경로 provenance는 미확인, live 기본은 App `lexical` | 질문은 bounded Search로 URN/type만 얻고 entitlement와 active release membership 뒤 최소 투영. release compiler만 full Scroll·exact read-back 수행 | [DataHub client](../../app/backend/app/adapters/datahub_catalog.py), live read-only probe | 2, 4, 5 |
| GraphQL/Search/Scroll/Rest.li/OpenAPI/MCP | GraphQL 중심 metadata, MCP는 Agent tool 경계 | GraphQL Search/Scroll/entity/semantic Search, Rest.li status read, OpenAPI aspect publish adapter 존재 | GraphQL Search와 entity read 관측; mutation·MCP DataHub 노출은 실행하지 않음 | Search=후보 발견, Scroll=release membership, GraphQL entity=필요 field, Rest.li/OpenAPI=aspect exact read/write-back. DataHub MCP는 model에 직접 노출하지 않음 | [catalog adapter](../../app/backend/app/adapters/datahub_catalog.py), [DataHub HTTP client](../../infrastructure/database/datahub/http_client.py) | 0B capability schema, 2~4 |
| Metric, AI Context, SemanticModel, Structured Properties | Glossary와 App semantic contract 중심, native semantic은 보강 후보 | native Metric shadow code가 있으나 catalog hash를 URN path에 넣고 `metricInfo`·lineage만 발행; 별도 `aiContext` 없음 | native `METRIC` entity 0; `aiContext`/SemanticModel capability 미검증 | pinned v1.7 `MetricInfo`는 schemaVersion 4이고 AI Context는 별도 `aiContext` aspect. stable identity와 retirement를 먼저 증명한 지원 capability만 shadow 채택 | [native metric shadow](../../infrastructure/database/datahub/native_metric_shadow.py), strategy §4 | 3 선행, 8 후속 |
| RuntimeCatalogProjection과 product receipt | semantic release manifest와 local snapshot | host `runtime_release.py`가 model/runtime/catalog receipt를 응답·Context에 일부 결속하나 durable DB 전파 없음 | live DB에 `product_release_id`, `permission_snapshot_id`, `semantic_release_id` column 없음 | DataHub full read-back+Trino fingerprint에서 immutable RuntimeCatalogProjection을 compile하고 equality/canary/rollback 후 product receipt로 활성화 | [runtime release](../../app/backend/app/runtime_release.py), live schema query | 4 |
| Node1InterpretationContext와 RuntimeContextPackage | Approved Context 하나를 Node 1/2가 공유 | 후보 Search와 full snapshot projection이 한 governance engine 안에 공존 | deployed host 변경과 불일치; 두 package의 durable receipt 없음 | Node 1에는 bounded minimal context만 제공. 서버가 candidate reference를 entitlement/release/projection에 재결속한 뒤 Node 2용 RuntimeContextPackage 생성 | [query governance](../../app/backend/app/adapters/query_governance.py) | 5 |
| Conversation, Turn, idempotency, CAS, transaction, recovery | 원자적 Run+Turn, required idempotency/CAS, bounded multi-turn | command/lease/Turn 구현은 있으나 key·expected head 선택적, replay 전에 saved hash 미비교, hash 범위 부족, RequestContext path 결속·reconciler 미완료 | 242 Conversation, 541 Turn, 596 command; 오래된 RUNNING 7, RECEIVED/CLARIFYING 48, expired lease 3. Analysis request 295건 모두 conversation_id NULL | 서버가 path·subject·permission·release를 canonicalize/hash하고 저장 hash 비교 후 replay. required CAS, terminal transaction, recovery, durable lineage가 선행 | [orchestrator](../../app/backend/app/services/conversation/orchestrator.py), [manual DDL](../../infrastructure/database/sql/app/01_bounded_multi_turn.sql), live DB query | 1 |
| same-asset compiler와 multi-asset JOIN | 승인 Serving과 제한된 다중 asset Node 2 | SQLGlot planner/guard는 있으나 typed capability `max_physical_assets=1`, `join_plans=[]` | active release join 0 | Phase 6은 same-asset만. JOIN은 승인 edge, cardinality/grain/fan-out, logical plan, deterministic emitter, Trino oracle가 모두 있는 경우만 지원 | [data platform port](../../app/backend/app/ports/data_platform.py), compiler/guard static audit | 6, 9 |
| MCP Tool current/target | 고정 7 Tool: analysis/artifact/semantic/graph/rag/ml/report | router/migration은 `analysis.get_run@1.0.0`만; `/analysis` permission `analysis.run`은 HTTP capability | live registry enabled tool 1개, role `analyst`; 인증 live call은 audit write 때문에 `NOT_RUN` | 호환 Tool은 유지. `analysis.run`은 Phase 11 고수준 Tool, `semantic.resolve`는 내부 Gateway op, `rag.answer` 채택. 나머지는 planned/conditional | [MCP router](../../app/backend/app/api/mcp_router.py), [migration 12](../../app/backend/migrations/versions/20260812_12_mcp_tool.py) | 0B, 11~14 |
| RAG document authority와 retrieval index | `rag.search`와 별도 문서 Evidence | 제품 RAG Tool/authority 구현 없음 | registry/router에 RAG Tool 없음 | DataHub Context Documents가 문서 권위. `rag.answer`가 citation 포함 답을 반환. pgvector 등 별도 index는 retrieval gap이 증명될 때만 파생본으로 허용 | strategy §8 | 12 |
| Neo4j, semantic/hybrid, BM25 | Neo4j read-only projection과 semantic 검색을 P1 후보로 배치 | semantic overlay와 `hybrid` branch 소스 존재; Neo4j runtime 없음 | OpenSearch만 실행, semantic/hybrid 비활성, Actions restart 불안정 | 기본은 DataHub lexical retrieval. BM25 적용 사실은 index/config evidence 전에는 주장 금지. semantic/hybrid는 Gate S1, Neo4j/`graph.resolve`는 정량 graph gap 때만 | [semantic search 설계](../../infrastructure/database/datahub/SEMANTIC_SEARCH.md), live container/env | 2, S1 조건부 |
| eval과 evidence manifest | required30/gold120 및 same-release evidence | `metric_retrieval.v2`가 catalog-derived 자기일관성과 negative closure를 분리; 독립 한국어 held-out 검색 Gold는 없음 | 현재 host와 다른 image이므로 host eval 결과를 live 결과로 사용 불가 | 기존 계보를 `EXTEND`. catalog-derived probe와 독립 held-out Gold를 하나의 versioned evidence 계약에서 별도 집계하고 병렬 threshold를 두지 않음 | [metric retrieval](../../evals/metric_retrieval.py), [runner](../../evals/metric_retrieval_runner.py) | 0B 계약, 2·3·5 실행 |

## 4. Current/target capability matrix

| Capability | 현재 상태 | 최종 target | 결정·Gate |
|---|---|---|---|
| DataHub lexical question retrieval | `IMPLEMENTED_HOST_UNDEPLOYED`; live `lexical` | bounded `searchAcrossEntities` → entitlement/release filter | Phase 2의 shadow receipt 후 `PROMOTE`·`HOLD`·`REJECT` |
| Release membership/read-back | host Scroll 구현, deployed provenance `UNVERIFIED` | full Scroll + exact entity/aspect read-back + Trino fingerprint | Phase 4 equality·activation·rollback |
| DataHub semantic/hybrid | host branch 존재, live 비활성 | 기본 경로가 아니라 조건부 보강 | Gate S1 실패 시 lexical 유지 |
| Native Metric | host shadow만, live count 0 | stable identity를 가진 native Metric shadow | Phase 3 capability probe와 retirement rehearsal |
| 별도 `aiContext` aspect | `UNVERIFIED` | 승인 synonym/instruction/example만 발행·read-back | Phase 3; 자유 텍스트는 untrusted |
| SemanticModel/나머지 native semantic | `UNVERIFIED` | 유효성이 입증된 capability만 shadow | Phase 8 |
| Structured Properties | Dataset release metadata에 일부 사용 | DataHub-owned governed attributes, exact read-back | Phase 3/4 capability별 판정 |
| RuntimeCatalogProjection | 없음; host receipt 일부만 | immutable derived execution projection | Phase 4 |
| Node1 grounding | full governance loader와 결합 | 최소 Node1InterpretationContext, server rebind | Phase 5 |
| same-asset 분석 | host compiler capability 1 asset | 결정론적 단일 asset vertical slice | Phase 6 |
| bounded multi-turn | 구현 일부, safety Gate 미통과 | required idempotency/CAS/recovery 위 동작 | Phase 1 후 Phase 7 |
| multi-asset JOIN | `BLOCKED` | 정책+logical plan+SQLGlot emitter+oracle가 있는 승인 JOIN | Phase 9 |
| product receipt | host 응답 수준 일부; durable columns 없음 | code/image/model/data/projection/permission을 end-to-end 결속 | Phase 0B schema, Phase 4 durable projection |
| RAG | 없음 | DataHub Context Documents 기반 `rag.answer` | Phase 12 |
| ML | 없음 | 승인 task만 `ml.predict` | Phase 13 |
| General Orchestrator | 없음 | bounded fan-out/fan-in; Core Gate 우회 금지 | Phase 14 |
| Neo4j | 없음 | 정량 graph gap이 있을 때만 파생 read model | `CONDITIONAL` |

## 5. MCP current/target 감사

| Identifier / surface | Registry/router 구현 | Live | 최종 결정 |
|---|---|---|---|
| `analysis.get_run@1.0.0` | migration과 router allowlist에 존재 | enabled 1건, role `analyst`; 인증 호출은 `NOT_RUN` | 호환 identifier `KEEP`; 제거 시 versioned deprecation 필수 |
| HTTP `/analysis`의 `analysis.run` permission | HTTP use-case capability이며 MCP Tool 등록이 아님 | HTTP route는 deployed, 이번 유료/쓰기 호출 `NOT_RUN` | HTTP permission과 MCP identifier를 계속 분리 |
| `analysis.run` MCP | 없음 | 없음 | Phase 11 `PLANNED`; 결정론적 Analysis Core만 감쌈 |
| `artifact.get` | 없음 | 없음 | `CONDITIONAL`; `analysis.run` 응답으로 충분한지 먼저 검증 |
| `semantic.resolve` | 없음 | 없음 | 외부 Tool이 아니라 내부 Context Gateway operation으로 `REPLACE` |
| `graph.resolve` | 없음 | 없음 | Neo4j Gate 통과 때만 `CONDITIONAL` |
| `rag.search` | 없음 | 없음 | v3.4 목표 이름은 `RETIRE`; 외부 capability는 `rag.answer` |
| `rag.answer` | 없음 | 없음 | Phase 12 `PLANNED`; citation과 권한 적용 답변 |
| `ml.predict` | 없음 | 없음 | Phase 13 `PLANNED` |
| `report.add_block` | 없음 | 없음 | Report Service 위 고수준 wrapper가 필요할 때만 `CONDITIONAL` |

인증된 `analysis.get_run` live call은 session/tool audit row를 만들 수 있어 Phase 0A의 read-only
범위를 넘으므로 실행하지 않았다. migration·router·live registry 조회는 서로 다른 증거로 남겼다.

## 6. Search, AI Context, projection 상세

### Search mode와 실패 의미

| mode | host branch | live | 실패 의미 |
|---|---|---|---|
| `lexical` | App canonical projection의 기존 lexical resolve | 기본값 | 기존 경로 유지 |
| `lexical_shadow` | bounded DataHub lexical Search를 background 비교; 최대 task 수 제한 | 미배포 | shadow 실패가 사용자 결과를 바꾸지 않음 |
| `datahub_lexical` | planned query 최대 3개, bounded top-K, entitlement 뒤 후보 사용 | 미배포 | Search/metadata 실패 시 fail-closed |
| `hybrid` | DataHub semantic Search와 RRF 결합 | 비활성 | semantic dependency 실패 시 fail-closed; 자동 lexical 성공 전환 없음 |

`searchAcrossEntities`는 질문 후보 발견에만 쓰며 반환된 URN/type에 App entitlement와 active
release membership을 먼저 적용한다. `scrollAcrossEntities`는 질문마다 호출하지 않고 release
compiler가 전체 멤버십을 고정할 때만 사용한다. DataHub query-time ACL에 기대지 않는다.

OpenSearch가 실행 중이라는 사실만으로 DataHub lexical retrieval이 BM25라는 결론을 내릴 수
없다. mapping, analyzer, similarity, query DSL과 실제 index receipt가 없으므로 이 문서에서는
`DataHub lexical retrieval`이라고만 부른다. DataHub Actions restart count 527 때문에 index
freshness와 read-after-write도 `UNVERIFIED`다.

### Native semantic과 release projection

- 현재 Glossary label·alias·definition은 release loader가 DataHub entity를 다시 읽어 App
  canonical bundle과 대조한다.
- native Metric shadow는 `metricInfo`, dataset/field upstream, metric relationship을 만들지만
  runtime cutover를 금지한다. URN path에 전체 catalog hash를 넣으므로 release마다 business
  identity가 바뀌고 retirement가 누적될 수 있다. Phase 3에서 stable URN/retirement를 다시
  설계해야 한다.
- pinned DataHub v1.7의 `MetricInfo`는 schemaVersion 4다. AI Context는
  `metricInfo.aiContext`가 아니라 별도 `aiContext` aspect다. write/read-back과 GraphQL 노출은
  아직 capability probe를 통과하지 않았다.
- `CatalogSnapshotLoader`는 Phase 4 전까지 즉시 삭제하지 않는다. Phase 4가 out-of-band
  RuntimeCatalogProjection equality, canary, activation receipt, rollback을 증명한 뒤 runtime
  hot path를 projection으로 전환하고 loader 역할을 compiler/read-back 경계로 축소한다.

## 7. Conversation Safety 감사

| 점검 항목 | 관측 | 영향 | Phase 1 Exit Gate |
|---|---|---|---|
| DDL 소유권 | `chat.conversations`, `turns`, `turn_commands`, `view_specs`는 수기 SQL이며 Alembic chain에 없음 | 재현·rollback 불명확 | versioned migration이 전체 schema를 소유하고 clean upgrade/rollback 검증 |
| idempotency key | Backend가 누락 key를 UUID로 생성; Frontend command/retry가 동일 key를 보내지 않음 | 네트워크 retry가 중복 command/query 가능 | client는 key+payload만 보내고 모든 retry에서 같은 key 유지 |
| canonical hash/replay | 기존 command를 먼저 반환하고 저장 hash 비교가 없음; hash는 message와 optional expected head만 포함 | 같은 key의 다른 권한·path·release payload replay 가능 | 서버가 path conversation, subject, permission snapshot, release, 확정 route를 포함해 hash하고 saved hash 비교 후 replay |
| CAS | `expected_head_turn_id`가 optional이며 없으면 검사 생략 | stale tab write 허용 | 최초 head sentinel을 포함해 모든 head-changing command에 required CAS |
| transaction | Turn/head/command/lease commit은 한 transaction이나 Analysis/Artifact 생성은 바깥에서 진행 | terminal 결과와 Turn 사이 unknown outcome | Run terminal, Artifact/View, Turn, head, command, lease를 recovery 가능한 단일 terminal contract로 결속 |
| RequestContext | router가 path ownership은 확인하지만 `RequestContext.conversation_id`에 path를 결속하지 않음 | 내부 호출에서 confused-deputy 위험 | path와 RequestContext가 동일 conversation임을 entry에서 고정 |
| recovery | expired lease/stale command/run reconciler 없음 | 영구 RUNNING/RECEIVED와 orphan query | startup/periodic reconciler와 fault-injection에서 orphan/stale 0건 |
| release/permission lineage | live schema에 product/permission/semantic release column 없음; Analysis request의 conversation_id가 모두 NULL | 재현·권한 증거 불완전 | Conversation→Turn→Run→Artifact/View/Report에 product receipt와 permission snapshot durable 결속 |

영향 Requirement는 `CONV-001~010`, `AUTH-002~003`, `FAIL-006`, `OPS-001`, `OPS-004`,
`P0-GOLDEN-DIALOGUE`, `P0-FAILURE`다. Phase 0A에서는 stale row 정리, backfill, migration 적용을
하지 않았다.

## 8. JOIN과 eval 결정

### JOIN

현재 relationship 후보와 SQLGlot planner/guard 존재는 multi-asset 실행 지원 증거가 아니다.
host typed capability는 `max_physical_assets=1`, `join_plans=[]`이고 active release join은 0이다.

Phase 9 Exit Gate는 다음 다섯 층을 한 release receipt로 요구한다.

1. DataHub에서 read-back한 승인 relationship edge
2. cardinality, grain, fan-out, temporal/identity policy
3. versioned logical join plan
4. plan 밖 AST를 만들 수 없는 deterministic SQLGlot emitter와 APP-G2
5. 실제 Trino result oracle, negative fan-out/권한 test, rollback

하나라도 없으면 `BLOCKED`이며 same-asset Phase 6 경로를 유지한다.

### Eval lineage

결정은 `EXTEND`다. `evals/metric_retrieval.py` v2는 exact catalog 자기일관성, definition token
overlap, negative closure를 이미 명시적으로 분리하므로 폐기하지 않는다. 다만 이 probe는
catalog에서 질문과 정답을 함께 파생하므로 한국어 paraphrase 품질을 증명하지 못한다.

Phase 0B Exit Gate에서 하나의 versioned manifest에 `catalog_derived`와
`independent_held_out_ko` dataset kind, source/checksum, metric 이름, threshold, 승인자를 고정한다.
Phase 2·3·5가 같은 scorer/manifest에 관측을 추가한다. 별도 evaluator와 병렬 threshold를 만들지
않고, metric 의미 변경이 필요하면 version migration과 historical comparability 표를 먼저
승인한다.

## 9. 결함, 담당 Phase와 Gate

| ID | 결함/간극 | 상태 | 담당 Phase | Exit Gate |
|---|---|---|---|---|
| P0A-01 | deployed image에 commit/dirty provenance가 없고 host hash와 불일치 | `BLOCKED` | 0B | versioned capability/evidence schema가 image digest·commit·dirty 상태·model contract를 결속 |
| P0A-02 | live는 `lexical`; host Search mode 변경은 미배포 | `IMPLEMENTED_HOST_UNDEPLOYED` | 2 | shadow 품질·latency·failure receipt와 `PROMOTE`·`HOLD`·`REJECT`; promote 시 canary→default→rollback |
| P0A-03 | DataHub Actions 불안정, index freshness·BM25 설정 미확인 | `UNVERIFIED` | 2 / S1 | lexical freshness SLO 확인; semantic 산출물은 별도 S1, 실패 시 lexical 유지 |
| P0A-04 | native Metric 0, 별도 `aiContext` capability 미확인, shadow URN identity 불안정 | `BLOCKED` | 3 | pinned v1.7 schema probe, stable identity, exact read-back, retirement rehearsal, 채택/기각 결정 |
| P0A-05 | immutable RuntimeCatalogProjection과 durable product receipt 없음 | `PLANNED` | 4 | full read-back+Trino fingerprint equality, canary, activation, rollback |
| P0A-06 | Node 1 최소 context와 Node 2 runtime package가 분리되지 않음 | `PLANNED` | 5 | bounded context, server rebind, injection/entitlement/quality Gate |
| P0A-07 | Conversation idempotency/CAS/transaction/recovery/release lineage 결함 | `BLOCKED` | 1 | 7절의 모든 Phase 1 Exit Gate와 L4 fault injection |
| P0A-08 | same-asset만 가능하며 JOIN policy/plan/oracle 없음 | `BLOCKED` | 9 | 8절의 5층 JOIN receipt |
| P0A-09 | MCP live tool은 `analysis.get_run@1.0.0` 하나뿐 | `PLANNED` | 11~14 | tool별 versioned schema, RequestContext, auth, audit, failure semantics |
| P0A-10 | RAG authority/Tool/index 없음 | `PLANNED` | 12 | DataHub Context Documents read-back, citation/ACL Gold; index는 gap 때만 |
| P0A-11 | catalog-derived eval만 있고 독립 retrieval Gold 없음 | `BLOCKED` | 0B, 2·3·5 | 단일 manifest/scorer에 두 dataset kind와 사전 봉인 threshold |
| P0A-12 | host/deployed model release가 v1.32/v1.31로 다름 | `BLOCKED` | 0B | model/prompt/schema/runtime compatibility receipt 일치 |

### Phase 2와 조건부 Gate S1

Phase 2는 shadow 실행만으로 끝나지 않는다. 품질·negative closure·p95·freshness·오류율과
rollback 가능성을 사전 threshold로 비교해 `PROMOTE | HOLD | REJECT`를 기록한다. `PROMOTE`일
때만 candidate canary, default 전환, 이전 `lexical` 경로 rollback rehearsal을 순서대로 수행한다.

Gate S1은 semantic/hybrid가 lexical 대비 유의미한 retrieval 품질 개선을 보이고, embedding
model/revision, mapping/analyzer, document fingerprint, full index/read-after-write receipt,
DataHub Actions 안정성, ACL 후처리, failure/rollback을 모두 봉인할 때만 열린다. 실패·미검증이면
`DATAHUB_SEARCH_MODE=lexical`을 유지한다. S1은 Phase 2를 자동 통과시키지 않는다.

## 10. 기존 구현 처리 결정

| 대상 | 결정 | 근거/종료 조건 |
|---|---|---|
| DataHub GraphQL entity/Search/Scroll client | `KEEP` | API 역할을 분리하고 Phase 2/4 receipt로 배포 검증 |
| `CatalogSnapshotLoader` | `REFACTOR` | Phase 4 전 유지; 이후 release compiler/read-back으로 축소, hot path projection 전환 |
| Search mode branch와 query planner | `KEEP` | host 구현을 재작성하지 않고 Phase 2에서 fail semantics·배포 provenance 검증 |
| App Semantic Registry의 새 authoring SoT 역할 | `REPLACE` | DataHub-supported governed authoring으로 이행; App에는 immutable compiled projection만 |
| catalog-hash native Metric URN | `REFACTOR` | Phase 3 stable identity와 retirement Gate 없이는 publish 금지 |
| 수기 Conversation DDL | `RETIRE` | Phase 1 Alembic migration 소유권·clean upgrade 후 제거 |
| Conversation orchestrator/repository | `REFACTOR` | required key/CAS/hash/transaction/recovery를 기존 경계에 보강 |
| `analysis.get_run@1.0.0` | `KEEP` | live 호환 identifier; versioned deprecation 전 제거 금지 |
| 외부 `semantic.resolve` Tool 목표 | `REPLACE` | 내부 Context Gateway operation으로만 유지 |
| `rag.search` 목표 이름 | `RETIRE` | citation 포함 `rag.answer`로 대체 |
| Neo4j critical path | `RETIRE` | graph gap 정량 Gate를 통과하면 별도 conditional ADR로 재도입 |
| `metric_retrieval.py` 계보 | `REFACTOR` (`EXTEND`) | 기존 metric을 보존하고 독립 held-out dataset을 같은 manifest/scorer에 추가 |

## 11. 실행한 명령과 redacted evidence

| 구분 | 명령/조회 | 결과 |
|---|---|---|
| Static | `Get-Location`, `git branch --show-current`, `git rev-parse HEAD`, `git status --short --branch`, 관련 `git diff`, `rg --files` | 2절 snapshot; 기존 dirty 변경 보존 |
| Static | `rg`로 Search mode/API, MCP migration/router, Conversation, JOIN, eval, native Metric 경로 확인 | 3~10절에 반영 |
| Live read-only | `docker compose ps`, container/image inspect, Backend `/health`·`/ready`, 환경 key 조회 | healthy deployed stack, live `lexical`, source provenance 부재 |
| Live read-only | host/deployed 핵심 source·model manifest hash 비교 | host Search/runtime receipt 파일 불일치; host v1.32 vs deployed v1.31 |
| Live read-only | App PostgreSQL schema·aggregate query | Alembic head/current `20260820_28`; Conversation/command/run count와 stale 상태 확인 |
| Live read-only | DataHub active release loader와 GraphQL Search/entity probe | 51 asset, 10 required Term, 14 metric, 3 dimension, join 0, native Metric 0 |
| Live read-only | MCP registry query | `analysis.get_run@1.0.0` enabled, role `analyst` |

secret, token, credential, 원문 개인정보와 민감 SQL literal은 기록하지 않았다.

## 12. 실행하지 않은 검증과 증거 분리

| 검증 | 상태 | 이유/선행조건 |
|---|---|---|
| unit/contract test | `NOT_RUN` | Phase 0A는 문서-only이며 기존 dirty production/test 변경을 이번 결과로 인증하지 않음 |
| 현재 host image build·deploy E2E | `NOT_RUN` | build/recreate/deploy는 제외 범위; 현재 image provenance가 host와 다름 |
| 브라우저 L3/L4 E2E | `NOT_RUN` | 같은 product release 봉인과 사용자 승인 필요 |
| 인증 MCP live call | `NOT_RUN` | session/tool audit write가 생길 수 있어 read-only 범위를 넘음 |
| DataHub publish/AI Context/native Metric | `NOT_RUN` | Phase 3 이전 mutation 금지 |
| semantic overlay·hybrid | `NOT_RUN` | Gate S1 산출물과 안정성 evidence 없음 |
| migration/cleanup/backfill/reconciler | `NOT_RUN` | Phase 1 범위이며 live state 변경 금지 |
| JOIN Trino oracle | `NOT_RUN` | approved edge/plan이 없고 Phase 9 이전 |

과거 handoff, screenshot, HTML visualization과 이전 성공 기록은 모두
`HISTORICAL_EVIDENCE`로만 읽었다. 이번 static 문서 검증, live read-only 관측, 미실행 E2E를
서로 합쳐 제품 `VERIFIED`로 판정하지 않았다.

## 13. Phase 0A Gate 체크

| 조건 | 결과 |
|---|---|
| v3.4/current host/deployed live/final decision 분리 | `PASS` |
| DataHub-first 제품 문서 동기화 | `PASS` |
| current/target/conditional MCP와 호환 identifier 분리 | `PASS` |
| Search/Scroll/entity/Rest.li/OpenAPI/MCP 용도 분리 | `PASS` |
| BM25 무증거 선언 방지 | `PASS` |
| semantic overlay 구현과 live 상태 분리 | `PASS` |
| 별도 `aiContext` aspect, pinned schemaVersion 4 정정 | `PASS` |
| native semantic Phase 3이 projection Phase 4·Node1 Phase 5보다 선행 | `PASS` |
| Phase 2 `PROMOTE`·`HOLD`·`REJECT`, canary/default/rollback | `PASS` |
| 조건부 Gate S1과 실패 시 lexical 유지 | `PASS` |
| Conversation/Projection/JOIN/eval 번호 Phase와 Exit Gate | `PASS` |
| 기존 dirty 변경 보존 | `PASS` |
| static/live/historical 증거 분리 | `PASS` |
| 상대 link 존재와 `git diff --check` | `PASS` |

Phase 0A 문서 rollback은 이 감사 파일과 이번에 추가한 제품 문서 delta만 되돌리는 것으로
가능하다. 기존 사용자 변경과 production code는 건드리지 않았다. Phase 0B는 이 Gate 결과를
사용자가 승인하고, capability/evidence schema 범위를 별도로 명시한 뒤에만 시작한다.
