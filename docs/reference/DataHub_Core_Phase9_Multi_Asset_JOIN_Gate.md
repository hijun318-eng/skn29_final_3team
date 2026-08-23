# DataHub Core Phase 9 Multi-Asset JOIN Gate

## 판정

- 상태: `PASS`
- 판정일: 2026-08-23
- 격리 project: `answervice-phase2b-datahub`
- 격리 DataHub: `https://127.0.0.1:38081`
- 격리 App DB: `phase4_runtime_catalog_acceptance` (`127.0.0.1:55440`)
- 읽기 전용 Trino: `https://127.0.0.1:18443`
- 기존 `answervice` stack: read-only 상태 확인 외 mutation 명령 미실행
- 현재 실행 stack 배포: `NOT_RUN`
- Phase 10 진입: `허용`

실제 grain·cardinality 증거가 있는 `many_to_one` edge 하나만 canonical release에 추가하고,
`DIRECT_JOIN`, `PREAGGREGATE`, `SEMI_JOIN`을 동일 AnalysisPlan·SQLGlot AST·Trino 실행 경로로
검증했다. 전략별 제품 결과는 독립 작성한 기준 SQL 결과와 exact match했고, many-to-many,
복수 최단 경로, mixed time mode는 typed error로 닫혔다.

이 문서의 “독립 기준 SQL”은 테스트 기준 결과를 뜻한다. Oracle Database, Oracle service,
Oracle driver를 추가하거나 사용하지 않았다. 실행 구성은 PostgreSQL, Trino, DataHub 그대로다.

## 활성 release와 projection

- 이전 product release:
  `ANSWERVICE-PHASE8-NATIVE-SEMANTIC:54fea8cb1bd876e75401fa2feb9042b9f669b2204639867ce2ed7d5552a238f1`
- 활성 product release:
  `ANSWERVICE-PHASE9-MULTI-ASSET-JOIN:d536b1ad528377d529e287901ee8f1c172a2966309044983d25aa2f8e6e8bbaa`
- 최종 active generation: `21`
- catalog release:
  `walkerhill-v4.3-sql-20260815-derived.1-retirement-20260820.1-iceberg-analyst.4-runtime-v2.20260820.4-phase9-joins.1`
- catalog SHA-256:
  `695fe466056ee0e115eba39c985a1264f818faa960b8ba7d97da5f0f7ef4f2ed`
- canonical SHA-256:
  `528870fc6a989ed14e3b9324c9e7ed72824357548812bc53ec9570ce08f35480`
- runtime projection SHA-256:
  `467c9ad215b60e2601112e6e0aafe26e376f17961478f42ba9170a7f658fec17`
- native relationship read-back SHA-256:
  `22df6ffd34ecee9f09d5f3f45486f5e55681fafc5cbfc6b2f33338d0ebceca17`
- Analysis capability SHA-256:
  `435dcbdaeb64508b9a48c6affde4fc4da398ad66a87541f6aaf9cbe29fa8384f`
- sealed Gold SHA-256:
  `87daff0f3b0a1bd427fb6d2547ffd1094ee576ccb71a3acee74e61f200bc6287`
- AnalysisPlan/compiler:
  `ANSWERVICE-ANALYSIS-PLAN-v3` / `ANSWERVICE-TYPED-SQL-v1.2.0`

## Live Acceptance

실행 결과는 `PHASE9_MULTI_ASSET_JOIN_PASSED`다.

| Case | 전략 | fanout 근거 | 행 | AST SHA-256 | 결과 SHA-256 |
|---|---|---|---:|---|---|
| `MA-J-001` | `DIRECT_JOIN` | `UNIQUE_ONE_SIDE` | 3 | `691565fc9c7ef0af1015a1c17b1b0a387c2960ec2a3dbc3df2f3dfa306f3f77c` | `a7219b8aadb7264a89856efa6fd5ee25934d77aa8ad52ddc83a0981dab2f12b8` |
| `MA-J-002` | `PREAGGREGATE` | `MULTI_FACT_COMMON_GRAIN` | 3 | `ed6345effc34b0073f117e5eca0134d9018dce6e1806bb53c11869b7096c521d` | `070a6da9b357ae75c1bd75548ddf914b7ec1f899c6a3f41d42c53cf21c4ab3d2` |
| `MA-J-003` | `SEMI_JOIN` | `FILTER_ONLY_MANY_SIDE` | 1 | `cf59e8b28dc430381e431fd19af160041fc9d20ba9b9c0346b6bbc977f68b26d` | `d9295bba3249e805988b3a50c5237f5312ed330c01b47fda5b81f4df58b83abf` |

- 전략별 제품 결과/독립 기준 SQL exact match: `3/3`
- duplicate aggregation: `0`
- unapproved edge: `0`
- Node 1 호출: `0`
- Node 2 호출: `0`
- 단일 Metric 결과 설명용 Node 3 호출: `2`
- 본 분석 SQL 실행: `3`
- candidate/active readiness:
  `catalog_manifest=ready`, `semantic_release=ready`, `trino_schema=ready`
- full-scroll runtime 호출: `0`
- native relationship: `1`
- target membership: legacy Dataset `51`, native semantic Dataset `4`, Glossary Term `10`

복수 Metric case는 Node 3를 호출하지 않고 G3가 승인한 모든 Metric과 rows로 결정론적 요약을
만든다. 따라서 model Gate는 세 case 모두 Node 3를 요구하지 않고, Node 1/2 0건과 단일 Metric
두 case의 Node 3 정확히 2건을 강제한다.

## Fail-closed와 rollback

- `many_to_many` → `FANOUT_UNSAFE`
- ambiguous shortest path → `JOIN_PATH_UNAVAILABLE`
- mixed time mode → `INVALID_METADATA`
- activation receipt: `ACTIVATE 18→19`
- rollback receipt: `ROLLBACK 19→20`
- 최종 activation receipt: `ACTIVATE 20→21`
- rollback 뒤 legacy/native metadata exact 복원 및 재발행 read-back: `PASS`

Metric이 허용한 edge의 교집합만 계획에 남고, 최단 경로가 둘 이상이면 ID 정렬로 임의 선택하지
않는다. filter-only many side는 물리 JOIN으로 행을 늘리지 않고 correlated `EXISTS`로 컴파일한다.

## Gate가 발견해 수정한 결함

첫 live 실행에서 `MA-J-003`의 상속 필터가 초기 bounded 검색 후보에 없다는 이유로 조용히
제거됐다. 상속 filter field를 동일 release receipt의 권한·JOIN·live schema에 먼저 재결속하고,
모든 predicate가 검증되지 않으면 부분 성공 없이 닫도록 수정했다. AST Gate를 낮추거나 Gold SQL을
바꾸지 않았다.

필터가 보존된 뒤에는 값 존재 확인용 bounded query가 본 분석보다 먼저 실행됐다. 기존 lifecycle
binding이 이 보조 query를 main attempt로 기록해 실제 SEMI_JOIN query를 두 번째 submission으로
거부하는 문제가 드러났다. 보조 query는 같은 capability·deadline·cancel 규칙을 유지하되 task-local
lifecycle sink만 분리하고, 종료 시 원래 sink를 복원하도록 수정했다.

관련 host 회귀 묶음은 `135 passed`, `9 subtests passed`다. 이는 Phase 9 변경 범위의 static/unit
계약 증거이며, 저장소 전체 host 검증과 Browser를 포함한 P0 same-release 봉인은 Phase 10에서 별도로
수행한다.

## 격리 자원과 정리 상태

- target/current container name 교집합: `0`
- 격리 GMS, Kafka, MySQL, OpenSearch, App DB: healthcheck 대상 모두 healthy
- Docker VM memory limit: `15.44 GiB`
- 사전 확인 target memory: Kafka 약 `512 MiB`, OpenSearch 약 `1.18 GiB`, GMS 약 `1.79 GiB`
- target 전용 JVM heap: Kafka `256 MiB`, OpenSearch `512 MiB`
- 임시 read token revoke: `true`
- 임시 service account 삭제: `true`

초기 Trino 지연은 host RAM 부족이 아니라 Docker VM 안에서 격리 Kafka/OpenSearch의 기본 heap이
만든 memory pressure였다. `answervice-phase2b-datahub` overlay의 두 target service heap만 낮췄고,
현재 `answervice` container·network·volume은 재시작·재생성·변경하지 않았다.

## Phase 10 진입 조건

Phase 9 Gate가 충족됐으므로 Phase 10 P0 same-release 봉인에 진입한다. Phase 10은 현재 host tree를
새로 검증하고 source, image, model, DataHub, Trino, App DB, Browser evidence를 같은 release
manifest에 연결해야 한다. 과거 Phase PASS, skip, mock 또는 서로 다른 release의 결과를 섞어
Requirement를 `VERIFIED`로 올리지 않는다. Phase 11 `analysis.run` capability는 이번 승인 범위가 아니다.
