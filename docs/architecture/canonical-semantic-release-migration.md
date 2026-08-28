# Canonical Semantic Release 점진 전환 기준선

## 결정

새로운 semantic graph 원본을 만들지 않는다. 현재 publication bundle과
`src/data/governance_contract.py`의 manifest·checksum을 저장소 중립 wire 계약으로 유지하고,
Backend가 검증된 active release를 `CanonicalSemanticRelease` 불변 typed graph로 컴파일한다.

두 계약의 역할은 다음과 같이 분리한다.

- `CanonicalSemanticRelease`: 전체 active release의 asset·Metric·Dimension·JOIN과 checksum
- `RuntimeContextPackage`: 사용자 권한과 질문 범위로 축소된 요청 단위 subgraph

DataHub Dataset custom properties는 현재 Legacy transport이자 runtime authority다. DataHub
v1.7 native Metric shadow adapter는 같은 검증 bundle에서 공개 BUSINESS Metric만 투영하지만,
발행·재조회가 끝나도 runtime authority를 자동 전환하지 않는다. 향후 Native reader가 동일 bundle을
재구성하고 Legacy 결과와 canonical checksum이 같을 때만 release 단위 전환 후보가 된다.

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
- 질문 해석 전에 DataHub의 lexical·semantic 증거로 승인 자산을 순위화하는 기존 2-pass 순서를
  유지한다. 검색 hit가 요청 자산 상한을 넘을 때 전체 검색을 실패시키거나 자산을 임의 절단하지
  않고, 각 seed의 Metric·Dimension dependency와 승인 JOIN 경로가 완전한 component만 순위대로
  원자적으로 추가한다. 편입된 node 전체의 entitlement·policy·calendar 계약을 다시 검증한다.
- 후보 검색과 실행 권위를 typed port로 분리했다. 첫 pass는 실행 parameter를 바인딩하거나 Trino
  `information_schema`를 조회하지 않고, 권한 필터를 통과한 후보와 active release의 catalog·canonical
  checksum receipt를 Node 1에 제공한다. Node 1의 Metric·Dimension 선택 뒤에는 candidate payload를
  신뢰하지 않고 같은 receipt의 전체 `CanonicalSemanticRelease`에서 operand·source asset·필드와
  공통 승인 JOIN 경로를 다시 계산한다. 선택된 최소 subgraph만 principal 권한과 live schema를
  재검증하며, 병렬 edge나 동률 최단 경로처럼 관계 의미가 하나로 확정되지 않으면 임의 선택하지 않는다.
- 후보 이후 release receipt가 바뀐 경우는 재시도 가능한 catalog 충돌, 실행 node 권한 부족은
  비노출 자산 부재, 승인 JOIN·공통 dimension·grain 부재는 semantic contract 오류로 구분한다.
  분석 오류 화면도 이 구분을 사용해 사용자 입력 부족과 서비스·거버넌스 문제를 섞지 않는다.
- Node 1 후보는 Dataset component의 모든 Metric을 그대로 전달하지 않는다. DataHub Glossary의
  label·alias·definition과 Dataset lexical/semantic rank로 BUSINESS Metric 선택지를 bounded ranking하고,
  ratio operand는 `candidate_selectable=false`인 실행 의존성으로만 보존한다. 확정된 멀티턴 Metric은
  질문 문자열에 재삽입하지 않고 active release의 Metric→Dataset 관계로 후보 seed를 찾는다.
- Legacy와 향후 Native shadow 결과가 같은지 source 종류를 제외하고 비교하는 checksum·section diff를 추가했다.
- 팬아웃 정책은 질문 문구가 아니라 Measure 위치, JOIN 방향, JOIN equality key를 포함하는
  asset grain/unique key 집합, 승인된 공통 grain binding으로 `DIRECT_JOIN`, `PREAGGREGATE`,
  `SEMI_JOIN`, `REJECT`를 결정한다.
- 기존 `AnalysisPlanStage` 앞에서 `ANSWERVICE-ANALYSIS-PLAN-v2` 논리 계획을 컴파일한다.
  출력 Metric 1~4개, 연산 enum, asset별 물리 Dimension, 기간 parameter, query strategy와
  edge별 팬아웃 결정을 Context package hash에 결합하며 SQL plan cache key에도 포함한다.
- Node 1 active contract를 `MODEL-v1.20.0`으로 올려 질문당 BUSINESS Metric 1~4개,
  `analysis_operation`, `result_limit`을 typed slot으로 전달한다. 기존 단일
  `selected_metric_id`는 한 개일 때만 채워지는 호환 projection이며, 대화 저장·상속은
  `metric_ids` 전체를 보존한다. 직전의 확정 기간과 결과 형태는 최소 typed 컨텍스트인
  `previous_period`와 `previous_result_shape`로만 전달한다. 결과 형태가 생략된 후속 질문은
  operation을 `null`로 반환해 직전 shape를 보존하고, 명시된 shape만 교체한다. active
  range 지표가 확정됐지만 기간 슬롯만 비면 동일 원문을 `interpretation_recheck`로 정확히
  한 번 재검토하고, 두 번째도 비면 기본 기간을 만들지 않고 typed 명확화로 닫는다.
  선택된 분석의 결과 형태가 비정상적으로 비면 같은 원문을 해당 슬롯에 한해 한 번만
  재검토하며, 서버가 질문 문구를 파싱해 임의 연산으로 대체하지 않는다. active
  release manifest는 `MODEL-RELEASE-v1.31.0`, Node 1 prompt는 `PROMPT-v1.25.0`이며 특정
  호텔 질문 해석기가 아니라 supplied governed BI metadata만 사용하는 범용 역할로 고정했다.
  Node 3 prompt `PROMPT-v1.2.5`는 시작 포함 경계와 종료 미포함 경계의 한국어 표현을
  각각 `부터`, `전까지`로 분리해 결과 문구가 기간 계약과 어긋나지 않게 한다.
- SQL Guard는 실제 AST가 사용한 JOIN edge를 각 v2 Metric의 `allowed_join_ids`와 대조하고,
  같은 edge에 대해 논리 계획과 동일한 팬아웃 결정표를 다시 실행한다. 필요한
  `PREAGGREGATE`나 `SEMI_JOIN` 형태가 실제 AST에 없으면 `GRAIN_VIOLATION`으로 닫는다.
- SQL Guard는 논리 계획의 연산도 AST와 재대조한다. `aggregate`, `breakdown`,
  `period_comparison`의 출력 grain과 `time_trend`의 시간 GROUP/오름차순 정렬,
  `top_n`·`bottom_n`의 첫 출력 Metric 정렬 방향, 차원 순서의 안정적 tie-breaker와 정확한
  LIMIT이 다르면 실행하지 않는다.
- JOIN이 없는 승인 `VIEW_REUSE` 계획은 `ANSWERVICE-TYPED-SQL-v1.1.0` 컴파일러가 질문
  원문을 다시 보지 않고 SQLGlot AST로 생성한다. 단일 공통 시간 필드와 필터 scope가 확인된
  집계·분해·추이·순위·기간 비교 및 동일 scope 복수 Metric·ratio를 지원하며, 생성 결과도
  기존 G2가 다시 파싱·검증·바인딩한다. `latest_snapshot`은 서버 `as_of` 기준일 전의 실제
  source time 최댓값을 scalar subquery로 선택하며, 질문의 기간을 cutoff로 임의 변환하지 않는다.
  이 구조 범위 밖은 기존 Node 2+G2 경로를 유지한다.
- 2026-08-21 로컬 배포 스택의 실제 DataHub·Trino 경로에서 단일 `VIEW_REUSE` 집계 smoke를
  실행했다. 응답 trace는 Node 1 → `typed_sql_compiler` → G2 → Trino → G3 → Node 3 순서였고
  Node 2·repair 호출 없이 G1/G2/G3를 모두 통과했다. UI 결과는 active release의 기간·호텔
  필터와 Trino 집계값을 표시했고 브라우저 console 오류·경고는 0건이었다. 이는 단일 live
  smoke 증거이며 전체 Metric·연산 조합의 정확도·지연 회귀를 대신하지 않는다.
- Node 2에는 전체 계산 범위인 `metric_ids`와 사용자 출력인 `output_metric_ids`를 분리해
  전달한다. SUPPORT operand는 SQL 검증·reduction 원본에만 유지하고 API table·chart에는
  BUSINESS Glossary Term이 결합된 Metric만 노출한다.
- 기존 runtime v2 root shape을 변경하지 않고, asset별 Dimension/Time 의미는
  `ANSWERVICE-ANALYSIS-CAPABILITY-v1` sidecar 계약으로 분리했다. 현재 14개 후보 뷰의
  sidecar는 review-only이며 active DataHub release에는 아직 발행하지 않았다.
- planning capability 전체를 거대한 Dataset custom property로 다시 복제하지 않는다. DataHub v1.7이
  native로 지원하는 BUSINESS Metric identity와 Metric→Dataset·SchemaField·Metric 관계만 native
  aspect로 투영하고, SUPPORT operand와 permission·grain·fan-out·query policy는 checksum-bound
  canonical execution contract에 남긴다. 근거 모델은 DataHub v1.7의
  [`MetricInfo`](https://github.com/datahub-project/datahub/blob/v1.7.0/metadata-models/src/main/pegasus/com/linkedin/metric/MetricInfo.pdl)와
  [`MetricUpstreams`](https://github.com/datahub-project/datahub/blob/v1.7.0/metadata-models/src/main/pegasus/com/linkedin/metric/MetricUpstreams.pdl)다.
- `author_native_metric_shadow.py`는 전체 scoped catalog를 읽되 manifest에 정확히 속한 active release만
  재구성한다. 따라서 base-ingested 미승인 후보는 제외하지만 `answervice.*` property가 일부라도 있는
  partial release는 숨기지 않고 실패한다. active 구성원은 live Trino schema fingerprint도 다시 대조한다.
- 2026-08-21 실제 DataHub v1.7 read-only probe에서 native `METRIC` entity가 사용 가능하고 기존
  Metric은 0개임을 확인했다. live `analytics_v4_3` check는 active BUSINESS Metric 10개,
  SUPPORT Metric 4개, native aspect 72개, Dataset edge 10개, SchemaField edge 14개,
  Metric derivation edge 2개를 계산했다. 상태는 `CHECKED_NOT_PUBLISHED`이며 live mutation과 runtime
  cutover는 수행하지 않았다.
- `evals/catalog_regression.py`는 후보 SQL checksum, capability sidecar와 Backend의 실제
  연산/time mode snapshot을 결합해 자연어·정답 SQL 없는 구조 회귀 행렬을 생성한다.
  현재 BUSINESS Metric 44개의 단일 조합 1,179건과 모든 Metric pair 946건, 총 2,125건이다.
  cross-asset pair 888건은 관계를 추측하지 않고 `JOIN_GRAPH_REQUIRED`로 차단한다.
- `evals/metric_retrieval_runner.py`는 active release의 BUSINESS Glossary label·alias·definition과
  SUPPORT·Dimension 폐쇄 probe를 만들고, 별도로 봉인한 한국어 Gold를 같은 release receipt의
  `lexical`·`lexical_shadow`·`datahub_lexical` 경로에서 함께 측정한다. 전체 식별자 일치, 질문
  전체의 definition 포함, 승인 문구 힌트, 일반 Unicode token overlap을 서로 다른 강도의 증거로
  판정한다. Phase 2A는 baseline뿐 아니라 실제 후보 `datahub_lexical`에도 catalog 계약과
  heldout 품질 하한을 적용하므로, 응답 성공과 지연시간만으로 오답 후보가 통과할 수 없다.
  2026-08-25 analyst live release의 경로별 90개 probe에서 exact·definition·한국어 heldout의
  top-1·recall@5·MRR과 negative closure가 모두 1.0이었고, 후보 p95는 76.953ms,
  infrastructure 오류와 권한 밖 Metric 노출은 0이었다. precision@5는 공유 용어 때문에 여러
  합법 후보가 남을 수 있으므로 사람 검토 Gold 없이 release 차단 임계값으로 고정하지 않는다.
- review-only 후보는 관측 파일이 있어도 채점하지 않는다. 업무 승인, `runtime_source=true`,
  동일 candidate checksum의 active release read-back 증거가 모두 있어야 scorer가 열린다.

## 의도적으로 열지 않은 기능

- JOIN edge 자체의 role/domain entitlement는 현재 metadata에 없으므로 endpoint 권한에서
  임의 유도하지 않는다. 다만 기존 v2 Metric의 `allowed_join_ids` whitelist는 실제 AST에서 강제한다.
- cardinality 선언이나 table 단위 boolean만으로 uniqueness를 입증했다고 보지 않는다.
  JOIN equality field 집합이 검증된 unique/grain key 전체를 포함해야 한다.
- allocation expression·basis 계약이 없으므로 one-side Measure를 many-side Dimension으로
  분해하는 계획과 many-to-many JOIN은 거부한다.
- 다중 asset `VIEW_COMPOSE`·`RAW_APPROVED_DETAIL`과 `DIRECT_JOIN`·`PREAGGREGATE`·
  `SEMI_JOIN` 물리 형태는 아직 typed plan에서 결정론적으로 생성하지 않는다. 현재 컴파일러는
  단일 승인 Serving View 경계만 열며, JOIN 경로는 LLM SQL 앞의 논리 계획과 뒤의 AST Guard가
  동일 팬아웃 결정을 강제하는 전환 상태다.
- `latest_snapshot`의 typed plan·SQLGlot 생성·G2 AST 검증·서버 기준일 binding·G3/API/UI
  증거 경로는 구현했다. 다만 active DataHub v2 reader가 해당 계약을 발행·재조회한 release는
  아직 없으므로 review-only 후보가 이 코드만으로 운영 실행 범위에 들어오지는 않는다. Context는
  지표 선택 전에 기간 누락을 차단하지 않고 선택 Metric의 승인 time mode를 확인한 뒤 `range`만
  기간을 요구한다. 대화가 `range`에서 `latest_snapshot`으로 전환되면 직전 기간도 상속하지 않는다.
- Node 1에 전달되는 용어 선택지는 compact Metric projection으로 줄였지만, 그 projection을 만들기
  위한 내부 첫 pass는 아직 Dataset semantic search와 최대 8개 자산의 완전한 dependency component를
  사용한다. 현재 Dataset semanticContent가 연결 Glossary text를 이미 포함하고 live catalog-generated
  retrieval Gate가 전부 통과했으므로, 별도 Glossary semantic API 호출은 근거 없이 추가하지 않았다.
  Native Metric은 아직 미발행이므로 검색 권위가 아니다. 서로 다른 calendar/time mode 후보를 함께
  회수한 뒤 선택 후 단일 시간 계약으로 좁히는 구조도 아직 열지 않았다. 실행 dependency를 잘라낸
  단순 top-N이나 calendar 임의 병합은 하지 않는다.
- DataHub native mutation, `METRICS_ENABLED`, Trino ACL/principal, Redis, Legacy property 삭제는 변경하지 않았다.

## 전체 CatalogSnapshot이 남는 이유

전체 snapshot은 사용자 질문마다 LLM에 넣기 위한 데이터가 아니다. active release의 누락 Dataset/Term,
혼합 checksum, soft-deleted entity, schema drift를 검출하는 publish/readiness/reconciliation 입력이다.
질문 실행은 검증 완료된 `CanonicalSemanticRelease` projection과 그 요청 subgraph를 사용한다.

## 다음 Gate

1. 완료한 catalog-generated retrieval Gate를 배포 release마다 재실행하고, 별도 사람 검토 Gold에서
   자연어 paraphrase·복합 지표 표현의 top-1/recall 저하가 관측될 때만 Glossary lexical search 또는
   read-back 완료 Native Metric 관계를 추가 증거로 연다. 현재 42개 canonical probe 결과만으로 자연어
   정확도를 주장하지 않는다. 혼합 calendar/time mode는 단일 `calendar_id` Node 1 계약을 먼저 Metric
   선택과 기간 해석의 두 typed 단계로 분리한 뒤에만 열며, 실행에서는 하나의 호환 시간 계약만 허용한다.
2. active release native Metric shadow를 별도 publish identity로 발행하고 read identity의 Rest.li aspect와
   GraphQL 관계 read-back을 통과시킨다. 이는 runtime cutover 승인이 아니다.
3. candidate Metric의 base grain·additivity를 승인한 뒤 canonical release로 컴파일한다. planning
   capability 전체를 별도 JSON 문서로 DataHub에 복제하지 않고, native 지원 영역과 execution-only
   정책을 분리한다.
4. 구조 Gate가 표시한 `TIME_GRAIN_CONTRACT_REQUIRED`, `COMPARISON_WINDOW_CONTRACT_REQUIRED`,
   혼합 time mode의 `TIME_MODE_NOT_IMPLEMENTED`, `JOIN_GRAPH_REQUIRED`를 업무 승인 계약과
   실행 구현으로 줄인다. 단일 `latest_snapshot` 조합은 더 이상 executor 미구현으로 차단하지 않는다.
5. 구조 Gate와 분리된 사람 검토 Gold로 Node 1 자연어 해석과 실제 Node 1→G3 결과 정확도를 측정한다.
6. `latest_snapshot` 후보의 query policy·DataHub read-back·active release 연결을 승인한 뒤
   같은 release에서 실제 Trino 결과와 UI 증거를 검증한다. 다중 asset의 `DIRECT_JOIN`·
   `PREAGGREGATE`·`SEMI_JOIN` SQL은 승인 edge·key·cardinality가 갖춰진 범위부터 typed plan으로
   결정론적으로 생성한다. 단일 `VIEW_REUSE` 집계 live smoke는 통과했지만, 전체 Metric·연산
   조합의 결과 정확도·지연 회귀는 별도 Gate로 계속 입증한다.
7. edge role/domain entitlement를 별도 정책으로 추가하고 node·column·Metric·edge 교집합을 검증한다.
8. 한 도메인 Native reader와 Legacy canonical equality를 통과시킨다.
9. release 단위 cutover 전 실제 DataHub·Trino·Backend·Playwright E2E를 같은 release ID로 실행한다.

## Live 검증 환경 계약

로컬 단위 테스트와 외부 플랫폼 검사는 같은 것으로 계산하지 않는다. 실제 검증 runner에는
`TEST_REAL_DATA_PLATFORM=1`, canonical `DATAHUB_READ_*`, DataHub/Trino URL·CA·runtime credential을
프로세스 환경으로 주입한다. 배포 상태 Gate에는 `ANSWERVICE_RUNTIME_URL`을 별도로 주입하며,
`/readiness`의 전체 dependency가 `ready`여야 통과한다. 비밀값은 저장소 파일이나 테스트
인자에 복사하지 않고 배포 secret 또는 gitignored 운영 `.env`에서 실행 시점에만 전달한다.

```powershell
python evals/metric_retrieval_runner.py `
  --phase2a-gold-manifest evals/metric_retrieval_gold/answervice_ko_retrieval.v2.json
```
