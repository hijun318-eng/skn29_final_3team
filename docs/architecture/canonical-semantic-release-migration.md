# Canonical Semantic Release 점진 전환 기준선

## 결정

새로운 semantic graph 원본을 만들지 않는다. 현재 publication bundle과
`src/data/governance_contract.py`의 manifest·checksum을 저장소 중립 wire 계약으로 유지하고,
Backend가 검증된 active release를 `CanonicalSemanticRelease` 불변 typed graph로 컴파일한다.

두 계약의 역할은 다음과 같이 분리한다.

- `CanonicalSemanticRelease`: 전체 active release의 asset·Metric·Dimension·JOIN과 checksum
- `RuntimeContextPackage`: 사용자 권한과 질문 범위로 축소된 요청 단위 subgraph

DataHub Dataset custom properties는 현재 Legacy transport다. 향후 DataHub native
Metric/Semantic Model adapter도 동일 bundle을 재구성해야 하며, 두 결과의 canonical checksum이
같을 때만 release 단위 전환 후보가 된다.

## 확인된 writer·reader·validator

| 계약 | 현재 writer/원본 | 현재 reader | 검증 경계 | canonical 책임 |
|---|---|---|---|---|
| Release manifest·checksum | `src/data/governance_contract.py`, DataHub publication | `release_manifest.py` | 전체 membership·count·semantic hash exact 검증 | source adapter가 검증 후 bundle 재구성 |
| Asset schema·grain·entitlement | semantic authoring bundle, Dataset aspects/custom properties | `datahub_metadata_*` | DataHub read-back·Trino schema fingerprint | `CanonicalAsset` |
| Metric 계산·공개·권한 | `metric_rules`, Glossary Term | `datahub_metric_governance.py` | v1/v2 exact shape·Term 일치·role/PII | `CanonicalMetric` |
| Dimension binding | bundle `dimensions` | Dataset 공통 property | asset·column 참조 검증 | `CanonicalDimension` |
| JOIN topology·cardinality·temporal/preaggregation | bundle `join_graph` | 기존에는 모든 Dataset의 복제 JSON | 공통 graph 일치·`GovernedJoin`·SQL AST Guard | `GovernedJoin` 재사용, release adjacency 생성 |
| Time·parameter·query policy | versioned bundle | Context runtime contracts | 공통 정책·typed parameter·read-only SQL | bundle identity에 보존, 요청 projection에서 축소 |
| Live schema | Trino `information_schema` | `TrinoSchemaInspector` | release fingerprint exact 비교 | canonical activation 외부 gate로 유지 |

## 이번 적용 범위

- 기존 root key 집합을 `SEMANTIC_RELEASE_KEYS` 하나로 통합했다.
- Legacy DataHub snapshot을 manifest 검증 후 canonical release로 변환하는 production adapter를 추가했다.
- `QueryGovernanceEngine`은 같은 cached snapshot을 한 번만 canonical release로 컴파일한다.
- readiness도 실제 요청과 동일한 canonical compile gate를 통과해야 `ready`가 된다.
- 실제 검색 경로의 JOIN 탐색은 Dataset별 `join_graph` JSON을 다시 조립하지 않고, 컴파일된
  `GovernedJoin` tuple을 사용한다.
- Legacy와 향후 Native shadow 결과가 같은지 source 종류를 제외하고 비교하는 checksum·section diff를 추가했다.
- 팬아웃 정책은 질문 문구가 아니라 Measure 위치, JOIN 방향, JOIN equality key를 포함하는
  asset grain/unique key 집합, 승인된 공통 grain binding으로 `DIRECT_JOIN`, `PREAGGREGATE`,
  `SEMI_JOIN`, `REJECT`를 결정한다.
- 기존 `AnalysisPlanStage` 앞에서 `ANSWERVICE-ANALYSIS-PLAN-v1` 논리 계획을 컴파일한다.
  출력 Metric 1~4개, 연산 enum, asset별 물리 Dimension, 기간 parameter, query strategy와
  edge별 팬아웃 결정을 Context package hash에 결합하며 SQL plan cache key에도 포함한다.
- Node 1 active contract를 `MODEL-v1.17.0`으로 올려 질문당 BUSINESS Metric 1~4개,
  `analysis_operation`, `result_limit`을 typed slot으로 전달한다. 기존 단일
  `selected_metric_id`는 한 개일 때만 채워지는 호환 projection이며, 대화 저장·상속은
  `metric_ids` 전체를 보존한다.
- SQL Guard는 실제 AST가 사용한 JOIN edge를 각 v2 Metric의 `allowed_join_ids`와 대조하고,
  같은 edge에 대해 논리 계획과 동일한 팬아웃 결정표를 다시 실행한다. 필요한
  `PREAGGREGATE`나 `SEMI_JOIN` 형태가 실제 AST에 없으면 `GRAIN_VIOLATION`으로 닫는다.
- SQL Guard는 논리 계획의 연산도 AST와 재대조한다. `aggregate`, `breakdown`,
  `period_comparison`의 출력 grain과 `time_trend`의 시간 GROUP/오름차순 정렬,
  `top_n`·`bottom_n`의 첫 출력 Metric 정렬 방향, 차원 순서의 안정적 tie-breaker와 정확한
  LIMIT이 다르면 실행하지 않는다.
- Node 2에는 전체 계산 범위인 `metric_ids`와 사용자 출력인 `output_metric_ids`를 분리해
  전달한다. SUPPORT operand는 SQL 검증·reduction 원본에만 유지하고 API table·chart에는
  BUSINESS Glossary Term이 결합된 Metric만 노출한다.
- 기존 runtime v2 root shape을 변경하지 않고, asset별 Dimension/Time 의미는
  `ANSWERVICE-ANALYSIS-CAPABILITY-v1` sidecar 계약으로 분리했다. 현재 14개 후보 뷰의
  sidecar는 review-only이며 active DataHub release에는 아직 발행하지 않았다.

## 의도적으로 열지 않은 기능

- JOIN edge 자체의 role/domain entitlement는 현재 metadata에 없으므로 endpoint 권한에서
  임의 유도하지 않는다. 다만 기존 v2 Metric의 `allowed_join_ids` whitelist는 실제 AST에서 강제한다.
- cardinality 선언이나 table 단위 boolean만으로 uniqueness를 입증했다고 보지 않는다.
  JOIN equality field 집합이 검증된 unique/grain key 전체를 포함해야 한다.
- allocation expression·basis 계약이 없으므로 one-side Measure를 many-side Dimension으로
  분해하는 계획과 many-to-many JOIN은 거부한다.
- SQL Generator는 아직 typed plan에서 AST를 결정론적으로 생성하지 않는다. 현재 단계는
  LLM SQL 앞의 논리 계획과 뒤의 AST Guard가 같은 결정을 강제하는 전환 경계다. 즉,
  복수 Metric과 범용 연산 계약은 활성화됐지만 생성 성공률은 catalog-generated eval로
  별도 입증해야 한다.
- `latest_snapshot`은 후보 capability에 명시했지만 active runtime read-back과 전용 SQL AST
  생성·검증이 없으므로 실행 경로에서는 의도적으로 차단한다.
- DataHub native 발행, `METRICS_ENABLED`, Trino ACL/principal, Redis, Legacy property 삭제는 변경하지 않았다.

## 전체 CatalogSnapshot이 남는 이유

전체 snapshot은 사용자 질문마다 LLM에 넣기 위한 데이터가 아니다. active release의 누락 Dataset/Term,
혼합 checksum, soft-deleted entity, schema drift를 검출하는 publish/readiness/reconciliation 입력이다.
질문 실행은 검증 완료된 `CanonicalSemanticRelease` projection과 그 요청 subgraph를 사용한다.

## 다음 Gate

1. candidate Metric의 base grain·additivity를 승인하고 capability sidecar를 DataHub에 발행·read-back한다.
2. 공개 Metric×허용 Dimension×연산 조합을 catalog에서 생성해 Node 1→G3 회귀율을 측정한다.
3. `latest_snapshot`과 공통 연산 SQL을 typed plan에서 SQLGlot AST로 결정론적으로 생성한다.
4. edge role/domain entitlement를 별도 정책으로 추가하고 node·column·Metric·edge 교집합을 검증한다.
5. 한 도메인 Native shadow publish/read-back과 Legacy canonical equality를 통과시킨다.
6. release 단위 cutover 전 실제 DataHub·Trino·Backend·Playwright E2E를 같은 release ID로 실행한다.
