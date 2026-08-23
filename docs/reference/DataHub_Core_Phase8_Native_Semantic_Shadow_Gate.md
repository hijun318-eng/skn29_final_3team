# DataHub Core Phase 8 Native Semantic Shadow Gate

## 판정

- 상태: `PASS`
- 판정일: 2026-08-22
- 격리 project: `answervice-phase2b-datahub`
- 격리 DataHub: `https://127.0.0.1:38081`
- 격리 App DB: `phase4_runtime_catalog_acceptance` (`127.0.0.1:55440`)
- 기존 `answervice` stack: read-only 상태 확인 외 mutation 명령 미실행
- 현재 실행 stack 배포: `NOT_RUN`
- native semantic runtime authority 전환: `false`
- Phase 9 진입: `허용`

Pinned DataHub Core v1.7의 실제 PDL과 격리 GMS validator를 기준으로 SemanticModel,
semantic field, Structured Properties, Metric 계산식 및 relationship/cardinality 표면을
shadow 발행했다. 전체 aspect exact read-back, legacy/native compiled surface equality,
검색·Node 1·SQL·Trino 결과 비회귀와 activation/rollback rehearsal이 모두 통과했다.

## 활성 release와 projection

- 이전 product release:
  `ANSWERVICE-PHASE7-BOUNDED-MULTITURN:fe9ed6de5260f7d4f547e58b551ff0679ebeb1c5a3f4c857f6fd78bd37f1aeab`
- 활성 product release:
  `ANSWERVICE-PHASE8-NATIVE-SEMANTIC:54fea8cb1bd876e75401fa2feb9042b9f669b2204639867ce2ed7d5552a238f1`
- 활성 generation: `18`
- 활성 runtime projection:
  `runtime-catalog:57ce5c15ed7229fe41d8f4c07f0668ad8caa7ea44f26a5d24a630b7a893f55e7`
- native semantic projection/read-back SHA-256:
  `d7730f08e4a21ec46fca7fb1bc2ec781bc40cb523aa82c24704bbee3d0cbc4eb`
- legacy/native semantic surface SHA-256:
  `40524e5ffe1d6fea09358ab83a1db2ec0017b6662e9ed1a8dabf53a9e113a358`
- native release membership SHA-256:
  `0aa5d10b75f1b4cb6d4cc05ecd226b394d4c0d81cd270803c291b206a8ff8ff5`

Phase 8 product release는 새 native semantic receipt를 봉인하지만, 실행 권위는 기존
checksum-bound RuntimeCatalogProjection에 남아 있다. Native entity가 Backend의 canonical
Metric·grain·JOIN·time policy를 대체했다고 선언하지 않는다.

## Live Acceptance

실행 결과는 `PHASE8_NATIVE_SEMANTIC_SHADOW_PASSED`다.

- native entity: `40`
- native aspect: `230`
- logical Dataset: `4`
- semantic field: `22`
- BUSINESS native Metric: `10`
- Structured Property definition: `3`
- 실제 release relationship: `0`
- REST aspect exact equality: `100%`
- legacy/native compiled surface equality: `100%`
- full-scroll runtime 호출: `0`
- bounded Search 호출: `8`
- release activation receipt: `ACTIVATE 15→16`, `ROLLBACK 16→17`,
  `ACTIVATE 17→18`

현재 canonical release에는 승인 JOIN edge가 없으므로 실제 relationship을 꾸며 넣지 않았다.
Pinned GMS가 `N_ONE` cardinality를 수용하고 exact read-back하는지는 비활성 acceptance 전용
3개 probe entity로 별도 증명한 뒤 모두 retire했다.

## Rollback과 비회귀

- Phase 8 신규 SemanticModel·logical Dataset·SchemaField retire: `27`
- 검색 hit 전이: `1 → 0 → 1`
- Phase 3 MetricInfo 복원·exact read-back: `10`
- rollback 뒤 Phase 8 aspect 재발행·exact read-back: PASS
- Node 1 Gold `N1-H-001`: 선택 Metric `room_revenue`, 연산 `aggregate`,
  기간 `2025-08-01`, asset `1`, model 호출 `1`로 전후 동일
- SQL Gold `SA-H-001` AST SHA-256:
  `91a7cf3809c2657c8087dce688d8217b85efaa2e03c709304e047a1096b69525`
- Trino result exact-match: `true`
- Trino row count: `1`

검색, Node 1, deterministic SQL AST와 실제 Trino 결과는 shadow 발행 전후 exact-match였다.
과거 결과나 현재 stack의 다른 image를 이번 PASS 증거로 사용하지 않았다.

## Pinned v1.7 검증에서 반영한 사실

- `SemanticModelInfo`는 pinned schema version `5`를 사용한다.
- `SemanticField.aggregationFunction`은 enum wrapper가 아닌 문자열 wire value다.
- Structured Property `version`은 PDL 주석 예시와 달리 격리 GMS validator가 요구한
  14자리 숫자 `20260822000000`으로 발행한다.
- Structured Property primitive value는 raw 문자열이 아니라
  `{"string": value}` union wrapper다.
- Native Metric `MetricInfo`에는 계산식과 SemanticModel 결속을 발행하되, SUPPORT operand와
  실행 policy는 canonical release에 유지한다.

초기 live probe 두 번은 위 wire 계약 차이를 발견해 실패했다. 두 실행 모두 active pointer를
변경하기 전에 종료됐고, 생성한 native entity를 retire하고 Phase 3 Metric shape를 복원했으며
임시 token과 service account를 삭제한 뒤 수정·재검증했다. Gate를 낮추지 않았다.

## 격리·자원·정리 상태

- 격리 GMS, Kafka, MySQL, OpenSearch, App DB: healthcheck 대상 모두 healthy
- target/current container name 교집합: `0`
- 실행 전 host available memory: 약 `6.96 GiB`
- C: free space: 약 `60.4 GiB`
- 임시 read token revoke: `true`
- 임시 service account 삭제: `true`

기존 container·network·volume과 현재 DataHub entity, active pointer 및 index는 변경하지 않았다.
RAM은 현재 Gate를 막는 상태가 아니며, 후속 작업도 같은 격리 stack 안에서 bounded timeout과
정리 경로를 유지한다.

## Phase 9 진입 조건

Phase 8 Gate가 충족됐으므로 Phase 9 multi-asset deterministic JOIN compiler 구현·격리 검증에
진입한다. Phase 9는 실제 grain·cardinality 증거가 있는 승인 edge만 release에 추가하고,
`DIRECT_JOIN`, `PREAGGREGATE`, `SEMI_JOIN` 각각을 SQLGlot AST와 실제 Trino Gold 결과로
증명해야 한다. many-to-many와 복수 최단 경로처럼 해석이 불명확한 경우는 계속 차단한다.
