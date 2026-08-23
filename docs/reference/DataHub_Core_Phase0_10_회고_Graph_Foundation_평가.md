# DataHub Core Phase 0~10 회고 및 Post-P10 Graph Foundation 평가

- 검토일: 2026-08-23 KST
- 범위: Phase 0A·0B~10의 전략, 현재 source·migration·test, 격리 Gate와 Graph Foundation 제안
- 제외: Neo4j code·dependency·container·volume, Phase 11 이후 capability, 현재 stack 변경

## 1. 결론

Phase 0A~9는 최종 전략의 순서와 책임 경계를 대체로 따랐고 단계별 격리 candidate Gate를
통과했다. 다만 서로 다른 시점의 단계별 PASS를 하나의 배포 release PASS로 해석하면 안 된다.

Phase 10에서는 이를 보완해 current source, migrations, Backend·Frontend images, DataHub, Trino,
전용 App DB, 실제 Browser saved-analysis replay와 전체 host validation을 같은 product release에
결속하는 기술 경로를 만들었다. 이 과정에서 replay가 cache를 재사용하고 저장 당시 정의·현재
권한·receipt를 올바르게 재결속하지 못하던 실제 P0 결함도 발견해 수정했다.

그럼에도 전체 판정은 `BLOCKED`다. 교정 전 P0 Gold의 review 50건, semantic gap blocked 5건,
unsealed 37건은 v2에서 `REVIEW_REQUIRED 55`, semantic gap blocker 0, unsealed 0으로 정리됐다.
그러나 사람 승인과 semantic/product release 결속·제품 반복 관측이 없어 여전히 `scorable=false`다.
PRD P0 Requirement `VERIFIED 0/66`, Release Gate `VERIFIED 0/11`을 oracle 생성이나 기술 성공으로
대신 올릴 수 없다.

| 구분 | 판정 | 의미 |
|---|---|---|
| 전략·책임 경계 | `GOOD` | DataHub SoT, App safety/execution, immutable projection, APP-Gates가 일관됨 |
| Phase 0A~9 단계별 기술 증거 | `PASS — isolated candidate` | 단계 계약·negative·rollback 증거이며 하나의 제품 release 인증은 아님 |
| Phase 10 same-release 기술 경로 | `IMPLEMENTED` | 9개 축을 동일 release로 검증하고 동적 정본은 `.tmp` receipt에 보존 |
| Phase 10 제품 Gate | `BLOCKED` | canonical Gold·PRD 전체 검토와 정량 증거 미완료 |
| Phase 11·Graph 구현 | `NOT_ALLOWED` | Phase 10 제품 `VERIFIED`가 선행조건 |

## 2. 냉정한 Phase별 재판정

| Phase | 재판정 | 한계까지 포함한 해석 |
|---|---|---|
| 0A | `PASS` | v3.4/current host/deployed/final decision을 분리한 문서 Gate다. 제품 기능은 당시부터 `UNVERIFIED`였다. |
| 0B | `PASS` | versioned capability/evidence와 additive migration의 격리 upgrade·rollback은 타당하다. 제품 release 전파 증거는 아니다. |
| 1 | `PASS — isolated candidate` | CAS, hash-before-replay, atomic terminal commit과 recovery를 격리 DB에서 검증했다. 현재 stack은 변경하지 않았다. |
| 2 | `PASS`, 범위 제한 | bounded DataHub lexical candidate, 권한 negative, canary·rollback은 유효하다. 87개 canary가 production default나 대규모 held-out을 대신하지 않는다. |
| 3 | `PASS`, 범위 제한 | pinned Core v1.7 native Metric·별도 `aiContext`를 실제 write/read-back·retire했다. runtime authority 전환 증거는 아니다. |
| 4 | `PASS` | immutable RuntimeCatalogProjection, CAS activation, exact equality와 rollback을 격리 App DB에서 검증했다. |
| 5 | `PASS`, 표본 제한 | bounded Node1 Context, server rebind, injection·stale/mixed-release 차단은 유효하다. Gold 5/5는 광범위 언어 품질 보증이 아니다. |
| 6 | `PASS`, capability 제한 | 8개 AST와 실제 Trino 독립 기준 결과, timeout/cancel/empty/schema drift를 검증했다. 전체 제품 E2E는 아니다. |
| 7 | `PASS`, 범위 제한 | bounded multi-turn 3개 dialogue, presentation zero-query, Report action·rollback을 검증했다. |
| 8 | `PASS` | native semantic shadow와 legacy/native equality·비회귀·rollback을 검증했다. native authority cutover로 과장하지 않았다. |
| 9 | `PASS`, 관계 제한 | DIRECT_JOIN·PREAGGREGATE·SEMI_JOIN과 실제 Trino·negative를 검증했다. 자유 graph 탐색 증거는 아니다. |
| 10 | `BLOCKED` | same-release 기술 경로는 보완됐지만 canonical P0 Gold·PRD `66/66`·Gate `11/11`는 아직 충족되지 않았다. |

Phase 0~9의 강점은 매 단계에 immutable receipt, negative case, activation·rollback을 요구했다는
점이다. 약점은 작은 capability별 표본과 서로 다른 generation의 결과가 많아 제품 전체를 한 번에
증명하지 못했다는 점이다. Phase 10은 후자를 기술적으로 해결했지만 사람 검토가 필요한 제품
정답을 자동 생성하거나 승인할 수는 없다.

## 3. 외부 실행 위생 평가 반영

외부 평가가 언제나 맞는 것은 아니지만 다음 지적은 당시 상태에 근거가 있었다.

- 일부 Gate가 선택 test와 과거 receipt를 중심으로 설명됨
- current full tree, 문서 규칙, repository inventory, stale fixture가 같은 시점에 green이 아니었음
- host pytest cache/basetemp 권한 문제가 재현성을 흐림
- dirty tree를 phase별 commit처럼 표현할 수 없음

긍정적으로 반영한 내용은 다음과 같다.

- current full validation을 fixed 15-command receipt로 만들고 subset 결과와 분리
- 고유 repository basetemp와 cacheprovider 비활성화
- root `AGENTS.md`에 current-source Gate, no-skip/no-history-mixing, rollback 구분 추가
- architecture·documentation·repository integrity·OpenAPI·compileall·Frontend·Compose·diff를
  같은 source receipt 아래 실행
- raw log 대신 command ID·exit code·duration·output checksum만 보존
- 실제 Browser result와 DB query/run/artifact receipt를 exact request로 결속

phase별 commit은 반영하지 않았다. 이것은 평가를 무시한 것이 아니라 사용자의 명시적
`commit/push/PR/branch 변경 금지`가 우선하기 때문이다. 대신 current dirty patch SHA-256을 image와
active manifest에 결속한다. 장기 provenance 관점에서는 signed commit/release tag가 더 낫지만,
현재 승인 범위에서는 의도적인 제한이다.

## 4. Phase 10에 남은 실제 일

기술적으로 더 많은 Docker stack이나 Graph database가 필요한 상태가 아니다. 남은 일은 제품
owner가 canonical P0 Gold를 완성하고 독립 실행을 승인하는 것이다.

1. semantic candidate의 BUSINESS 10개·SUPPORT 4개 metric 의미를 제품 owner가 승인
2. v2 Gold 55건의 intent·안전 결정과 독립 result assertion을 승인된 reviewer로 확정
3. semantic/product release ID와 checksum을 같은 source candidate에 결속해 seal
4. 사전 봉인된 manifest로 전체 P0 제품 관측을 반복 실행하고 threshold 검증
5. Requirement 66개와 Release Gate 11개를 해당 same-release evidence ID에 일대일로 연결해 검토

이 절차 없이 unit/integration test 수, 수동 Browser 성공 한 건, 과거 Phase PASS를 합산해
`VERIFIED`로 바꾸는 것은 Gate 우회다.

## 5. Graph Foundation 제안 평가

제안의 안전 원칙은 좋다. 그러나 현재 규모와 승인된 JOIN 범위에서 Neo4j를 필수 구성요소로 바로
추가하는 것은 근거가 부족하다. DataHub lineage, RuntimeCatalogProjection, Postgres 또는
in-process 탐색으로 해결되지 않는 실제 workload와 순이득을 먼저 보여야 한다. 그렇지 않으면 새
DB, schema migration, 인증·TLS, backup/restore, 관측, 장애 모드를 critical path에 추가할 뿐이다.

### 긍정적으로 채택할 원칙

- DataHub를 유일한 authoring SoT로 유지
- graph는 RuntimeCatalogProjection에서 파생된 단방향 read model로만 사용
- reverse sync와 dual SoT 금지
- raw row, PII 원문, secret, 사용자별 Effective Policy, LLM 추측 관계, 미승인 JOIN 적재 금지
- versioned ontology/release/source checksum과 deterministic invariant
- candidate exact read-back, canonical equality, activation·rollback
- 외부 API가 아니라 Backend 내부의 고수준 parameterized resolver만 노출
- hop·후보·결과·timeout budget과 typed failure
- APP-G1에서 권한·release·cardinality·grain·unit·time 재검증
- 단순 분석은 graph call 0, stale/local scan/LLM 추측 fallback 금지
- graph caching과 prompt caching을 서로 다른 변경·측정으로 분리

### 조건부로만 채택할 항목

| 제안 | 현실적 조정 |
|---|---|
| node/relationship 최소 목록 | 실제 held-out workload에서 필요한 최소 타입만 ADR로 선정 |
| NetworkX validator | deterministic invariant가 계약이며 구현 library는 비교 후 선택 |
| Neo4j Community/Enterprise | graph 필요성과 운영 budget 입증 후 license·기능 ADR에서 결정 |
| `POST-P10-G0`~`G4` | 자동 roadmap이 아니라 각 단계 별도 승인의 후보 runbook으로만 유지 |

### 반영하지 않을 항목

- Neo4j를 지금 필수 플랫폼 구성요소로 확정
- Graph Foundation을 Phase 10과 Phase 11 사이에 자동 삽입
- 측정 전 driver·container·volume·backup 체계를 구현
- 고정된 전체 ontology를 use case보다 먼저 모델링
- 특정 graph database 또는 validator library를 계약으로 고정
- GraphRAG, vector search, LLM Cypher, prompt caching을 한 변경에 묶음

## 6. Graph 재검토 진입 조건

다음을 모두 만족한 뒤에만 Graph Foundation 검토를 다시 연다.

1. Phase 10, P0 Requirement `66/66`, Release Gate `11/11`이 같은 release에서 `VERIFIED`
2. 복합 관계 질문의 독립 held-out workload와 recall·회복률·p95·오류 기준을 사전 봉인
3. DataHub lineage/Search, RuntimeCatalogProjection, Postgres/in-process 대안 기준선 측정
4. graph OFF/ON 순이득과 CPU·RAM·disk·운영 인력 budget 승인
5. graph 장애 시 기존 단순 분석과 graph-dependent 요청의 failure semantics 승인

조건을 충족해도 첫 작업은 ADR과 threat model이다. 이를 통과한 뒤 별도 승인으로 infrastructure와
real integration을 검토한다. 현재 Graph Foundation은 `CONDITIONAL / NOT_STARTED`이며 Phase 11
진행 근거가 아니다.
