# DataHub Core 공식 사용법·BP 조사 (2026-08-21)

조사 대상: DataHub Core OSS **v1.7.0** (우리 compose가 고정한 `acryldata/datahub-gms:v1.7.0` 등). 근거는 docs.datahub.com 현행 문서와 저장소 실제 코드 대조다. 이 문서는 참고 자료이며 제품 계약이 아니다. 실제 채택은 `AGENTS.md`와 `docs/product/*` 판정을 따른다.

## 1. 현재 우리 방식 (코드 근거)

| 영역 | 현재 구현 | 위치 |
|---|---|---|
| write 경로 | Rest.li `POST /aspects?action=ingestProposal` (httpx 직접) | `infrastructure/database/datahub/http_client.py:98` |
| read 경로 | `GET /entitiesV2/{urn}` + GraphQL `searchAcrossEntities` 교차검증 | `http_client.py:112`, `metadata_graphql.py` |
| 연관 갱신 | aspect 전체 upsert + 순차 read-modify-write | `metadata_aspects.py`, AGENTS.md 규칙 |
| metric | 네이티브 `metric` entity (`metricKey`/`metricInfo`/`metricUpstreams`/`metricRelationships`) | `native_metric_shadow.py:103` |
| governance 상태 | `customProperties` + 자체 review 계약 (DRAFT/REVIEW_REQUIRED/APPROVED) | `metric_review_contract.py`, `metric_review_decision.py` |
| lineage | 자체 SQLGlot AST 해석 | `release_datahub_queries.py`, `policy_compiler.py` |
| semantic search | 별도 `semantic-elasticsearch` + Ollama 임베딩 인덱스 | `dataset_semantic_index.py`, `compose.semantic-search.yml` |
| 후보 랭킹 | Python 어휘 overlap + semantic rank 결합 | `app/backend/app/adapters/query_search_evidence.py:26` |
| SDK 의존 | 없음 (httpx + PyYAML + sqlglot) | `requirements.authoring.txt` |

요약: metric entity를 네이티브로 쓰는 건 이미 공식 모델과 일치. 나머지는 상당 부분 **DataHub 1.7이 네이티브로 제공하는 것을 자체 구현**하고 있다.

## 2. 도입 가치가 큰 것 (우선순위 순)

### A. `metricInfo.aiContext` + `metricInfo.expression` — 즉시 채택 권장

v1.7 `metricInfo`(schemaVersion 5)에는 우리가 지금 안 쓰는 필드가 있다.

- `expression`: `MetricExpression` — 여러 dialect의 SQL 표현식
- `semanticModel`: 소유 SemanticModel URN (`ModeledBy`, 검색 facet 구동)
- `created` / `lastModified`: `AuditStamp` (actor 포함, `createdAt`/`lastModifiedAt`로 검색 인덱싱)

그리고 별도 `aiContext` aspect (metric / semanticModel / schemaField에 붙음, "OSI ai_context shape"):

| 필드 | 용도 |
|---|---|
| `synonyms` | 별칭·약어 (한국어 발화 매칭) |
| `instructions` | 모델이 이 지표를 어떻게 해석할지 지침 |
| `examples` | 근거용 예시 값·사용 패턴 |
| `customInstructions` | 자유 형식 추가 지침 |

**우리 문제와 직결**: `evals/metric_retrieval.py` 정확도 게이트, `metric_resolver.py` 후보 축소가 지금 자체 별칭/토큰 처리로 돌아간다. 별칭을 DataHub 권위 aspect로 옮기면 AGENTS.md의 "운영 원본은 DataHub" 규칙에 더 맞고, ES 검색 인덱싱도 공짜로 붙는다. 지금 `customProperties`에 들어간 AI 힌트가 있으면 `aiContext`로 이관.

주의: `aiContext`는 신뢰할 수 없는 자유 텍스트가 아니라 **승인된 governance 값**으로만 발행해야 한다. 승인 절차 없이 모델이 쓴 문구를 넣으면 prompt injection 표면이 된다.

### B. `semanticModel` entity + `semanticFieldAnnotation` — 우리 Context registry와 정확히 겹침

v1.7의 SemanticModel은 우리가 `schema_context`로 자체 구성하는 것과 같은 모델이다.

- URN: `urn:li:semanticModel:(platform, path, id)` — 환경 독립 identity
- `semanticModelInfo.relationships`: 논리 dataset 간 **join path** (from-alias, to-alias, join columns)
- 논리 dataset은 그냥 `dataset` entity + `subTypes: Semantic Model Dataset` + `semanticModelProperties{alias, semanticModel}`
- 컬럼은 표준 `schemaField` + `semanticFieldAnnotation`:
  - `type`: `DIMENSION` / `MEASURE` / `FILTER` / `OTHER`
  - `expression`: dialect별 SQL
  - `aggregationFunction`: `SUM`, `COUNT_DISTINCT` 등
  - `dimension.isTime`: 시간 차원 표시 (기간 필터용)
- lineage 체인: `Metric → 논리 Dataset → 물리 Dataset`(논리 dataset의 `upstreamLineage`), 컬럼 단위는 `fineGrainedLineages`

즉 우리가 typed context로 넘기는 asset·field·join·time·aggregation이 **전부 표준 aspect 자리**를 갖고 있다. 채택하면 join/시간축/집계 규칙이 자체 JSON 계약이 아니라 live read-back 가능한 카탈로그 값이 된다.

비용은 작지 않다(논리 dataset URN 체계 + 기존 bundle 매핑). 단계적으로: ① `metricInfo.semanticModel` 포인터부터, ② `semanticFieldAnnotation`(isTime, aggregationFunction), ③ 논리 dataset 분리 순.

### C. Structured Properties — `customProperties` governance 값 대체

`customProperties`는 타입 없는 문자열 맵이고 검색 필터가 약하다. Structured Property는:

- 네임스페이스 URN (`io.acryl.privacy.retentionTime` 같은 dot 표기), 전역 유일
- `valueType`, `cardinality`(SINGLE/MULTIPLE), `allowedValues`(값별 설명), `entityTypes`, `immutable`
- metric 포함 대부분 entity에 부착 가능, ES 필터/facet 자동
- `datahub properties list` / OpenAPI v3로 정의 조회 가능 = 계약 read-back이 쉬움

우리 review 상태(`REVIEW_REQUIRED` 등), grain, entitlement scope, source digest는 `allowedValues` 있는 structured property가 정답 형태다. `immutable: true`는 checksum류에 그대로 맞는다.

단, **승인 워크플로 자체를 DataHub로 넘기지는 말 것**. OSS에는 우리가 요구하는 predecessor checksum 재제시/전체 read-back 게이트가 없다. 상태 값 저장 위치만 표준화한다.

### D. OpenAPI v3 + generic patching — write 경로 현대화

현행 문서 기준:

- OpenAPI **v2 entity/relationship API는 deprecated**, `/openapi/v3/entity`, `/openapi/v3/relationship` 권장
- Rest.li `ingestProposal`은 살아있지만 신규 작업 권장 경로는 아님
- **Generic Patching**: v3에서 임의 aspect에 JSON Patch 적용. 배열 원소를 키로 add/remove:
  ```json
  {"op": "add", "path": "/tags/urn:li:platformResource:source1/urn:li:tag:tag1",
   "value": {"tag": "urn:li:tag:tag1", "attribution": {...}}}
  ```
  Rest.li 전통 patch는 `SUPPORTED_TEMPLATES` aspect에만 되지만, v3 generic patch는 범용.
- `EmitMode` (1.1.0+): `SYNC_PRIMARY` / `SYNC_WAIT` / `ASYNC` / `ASYNC_WAIT` — primary storage 동기 커밋 여부를 선택. `--verify` read-back 전에 ES 인덱싱 지연으로 흔들리는 문제를 계약으로 못박을 수 있다.
- `async=true`여도 GMS는 **수락 전에** schema/authorization/aspect validator를 돌리고 위반은 403/422로 동기 거부한다. 다만 이후 처리 실패는 Failed MCP 토픽으로 가고 호출자에게 안 온다 → 우리 fail-closed 요구엔 동기 모드가 맞다.

**직접 이득**: AGENTS.md의 "동일 dataset read-modify-write association은 순차 실행" 규칙은 patch를 쓰면 규칙 자체가 필요 없어진다(`glossaryTerms` 원소 add/remove). 손실 갱신 위험을 코드 규율이 아니라 서버 의미론으로 막는 게 낫다.

### E. `query` entity — release SQL을 카탈로그 1급 객체로

`queryProperties` + `querySubjects`로 SQL을 발행하면:

- dataset ↔ query 양방향 탐색 (dataset에서 "이 자산을 쓰는 질의" 목록)
- 읽기 권한이 **subject dataset에서 파생**: 모든 subject에 권한 없으면 query 전체가 숨겨짐, subject 없는 query는 fail-closed로 숨김 — 우리 entitlement 모델과 방향이 같다
- 쓰기는 모든 subject dataset에 `Edit Dataset Queries`/`Edit Entity` 필요 → publish principal 최소권한 설계에 그대로 맞음

우리 release SQL은 지금 카탈로그 밖에 있다. 보고서 근거·lineage 추적 요구를 생각하면 발행 가치가 있다.

### F. Business Glossary YAML 소스 — 부분 채택

공식 경로는 `datahub-business-glossary` ingestion 소스 (`file:` + `enable_auto_id`). 우리 자체 발행기와 겹치지만 하나는 중요하다:

> `enable_auto_id: true` — GUID URN 생성. **비ASCII 문자 term에는 필수.**

기본값(false)은 특수문자를 지우고 이름 기반 경로 URN을 만들기 때문에 한국어 용어에서 충돌·깨짐 위험이 있다. 우리 term id 생성 규칙이 이 조건을 만족하는지 확인할 것 (`semantic_authoring.py`, `metric_contract.py`).

전면 이관은 권장 안 함 — 우리는 `--check` → 멱등 upsert → `--verify` 전량 read-back 게이트가 있고, 표준 recipe에는 그 게이트가 없다.

## 3. 도입하지 말 것 / 우리 방식 유지가 나은 것

### DataHub MCP Server (`mcp-server-datahub`) — production 경로 금지, 개발 도구로만

2025-03 출시, OSS/Cloud 모두 지원. 도구: `search`(`/q` 문법), `get_entities`, `list_schema_fields`, `get_lineage`, `get_lineage_paths_between`, `search_documents`, `get_me`.

매력적이지만 우리 제품에 넣으면 **모델이 카탈로그를 직접 조회**하게 된다. AGENTS.md의 "권한·실행·공개 여부를 model이 결정하지 않는다", "typed context만 전달" 규칙과 정면 충돌. 서버가 소유한 Context 구성 단계를 우회하는 순간 entitlement 필터가 모델 판단으로 내려간다.

→ 개발자가 카탈로그를 탐색하는 로컬 도구로만 사용. 백엔드 분석 흐름에는 넣지 않는다.

### Data Contracts / Assertions — Cloud 기능, 대체 불가

문서 경로가 `managed-datahub/observe/*`다. OSS에서 우리가 필요한 수준(예측 검증, 승인 receipt, checksum 게이트)을 제공하지 않는다. 현재 release bundle checksum 게이트 유지.

### OSS 검색은 벡터 검색이 아니다 — 우리 semantic 인덱스 유지, 단 lexical은 이관 가능

OSS 검색은 Elasticsearch 키워드(`/q` 문법) + **검색 커스터마이즈 YAML**이다: `queryRegex`로 프로파일 선택, `boolQuery` 통과, `functionScore`로 중요도 가중, `customProperties`/`tags`/`terms`/`domain` 필드 사용 가능.

- 유지: `semantic-elasticsearch` + Ollama 임베딩 (OSS에 동등물 없음)
- 이관 검토: `query_search_evidence.ranked_matches`의 Python 어휘 overlap 랭킹. 이건 ES가 훨씬 잘하는 일이고, DataHub 검색 커스터마이즈로 옮기면 우리 코드에서 랭킹 로직이 사라진다. 다만 랭킹이 권한 필터 앞에 오면 안 되므로 순서 계약 확인 필요.

### acryl-datahub Python SDK 전면 도입 — 하지 말 것, 단 SQL 파서는 예외

공식 문서는 Python/Java SDK를 최우선 권장하지만, 백엔드에 SDK를 넣으면 무거운 의존성 트리가 런타임 릴리스 경계로 들어온다. httpx 직접 호출 유지가 맞다.

**예외**: `datahub.sql_parsing.sqlglot_lineage`. sqlglot 기반이지만 스키마 인지 처리를 추가해 컬럼 lineage 정확도 97–99%라고 문서화돼 있다. 우리는 같은 일을 자체 구현 중이다. 이미 `acryldata/datahub-ingestion:v1.7.0` 컨테이너를 쓰고 있으므로 **lineage 생성만 그 컨테이너 안에서** 돌리면 백엔드 의존성을 안 늘리고 정확도를 얻는다.

알려진 한계(우리 SQL이 해당되는지 확인 필요): `MERGE INTO` 컬럼 lineage 미지원, 컬럼 리스트가 SELECT와 안 맞는 `INSERT INTO` 미지원, `WHERE`/`GROUP BY`/`JOIN`/`HAVING` 참조 컬럼은 lineage에 미포함.

### dbt / Cube 등 외부 시맨틱 레이어 도입 — 불필요

우리 metric governance가 이미 있다. DataHub SemanticModel entity가 그 표현 자리를 제공하므로 별도 시맨틱 레이어 제품을 끼울 이유가 없다.

## 4. 권장 실행 순서

1. **`aiContext` 발행** (A) — 범위 작고 metric retrieval 정확도에 바로 연결. `evals/metric_retrieval.py` 게이트로 전후 비교.
2. **OpenAPI v3 + generic patch로 write 이관** (D) — 연관 갱신 손실 위험 제거, AGENTS.md 순차 실행 규칙 폐기. `EmitMode` 동기 모드로 `--verify` 안정화.
3. **governance 값 → structured properties** (C) — `customProperties` 문자열 계약 제거, 검색 필터 확보.
4. **`metricInfo.expression` + `semanticModel` 포인터** (B 1단계).
5. `query` entity 발행 (E), 논리 dataset 분리 (B 2·3단계) — 범위 크므로 별도 릴리스.

각 단계 검증은 기존 순서 유지: `--check` → 멱등 upsert → `--verify` 전량 live read-back, 그리고 AGENTS.md 완료 전 명령 세트.

## 5. 미검증 위험

- 이 조사는 **문서 대조만** 했다. v1.7.0 실제 인스턴스에서 `aiContext`, `semanticFieldAnnotation`, generic patch, `EmitMode`를 read-back으로 확인하지 않았다. 채택 전 각 aspect가 우리 GMS 빌드의 EntityRegistry에 실제 등록돼 있는지 `--check`로 먼저 확인해야 한다.
- GraphQL이 `aiContext` / `semanticFieldAnnotation`을 노출하는지 미확인. 노출 안 되면 Rest.li/OpenAPI aspect exact 검증만으로 게이트를 구성해야 한다 (AGENTS.md의 v1.7 read-back 권위 범위 규칙과 동일).
- `enable_auto_id` 한국어 term 이슈는 우리 현행 term URN 생성 코드에서 아직 확인 안 함.

## 참고

- [DataHub APIs and SDKs Overview](https://docs.datahub.com/docs/api/datahub-apis)
- [OpenAPI Guide (generic patching)](https://docs.datahub.com/docs/api/openapi/openapi-usage-guide)
- [Emitting Patch Updates](https://docs.datahub.com/docs/advanced/patch)
- [Metric entity](https://docs.datahub.com/docs/generated/metamodel/entities/metric)
- [Semantic Model entity](https://docs.datahub.com/docs/generated/metamodel/entities/semanticmodel)
- [Query entity](https://docs.datahub.com/docs/generated/metamodel/entities/query)
- [Structured Properties](https://docs.datahub.com/docs/api/tutorials/structured-properties)
- [Business Glossary source](https://docs.datahub.com/docs/generated/ingestion/sources/business-glossary)
- [SQL Parsing](https://docs.datahub.com/docs/lineage/sql_parsing)
- [Search](https://docs.datahub.com/docs/how/search)
- [Access Policies](https://docs.datahub.com/docs/authorization/access-policies-guide)
- [DataHub MCP Server](https://docs.datahub.com/docs/features/feature-guides/mcp)
