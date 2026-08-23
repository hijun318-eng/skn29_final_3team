# DataHub Core Phase 5 Node1 Grounding Gate

## 판정

- 상태: `PASS`
- 판정일: 2026-08-22
- 격리 project: `answervice-phase2b-datahub`
- 기존 `answervice` stack: mutation 명령 미실행
- 현재 실행 stack 배포: `NOT_RUN`
- 다음 Phase: host-tree Gate가 계속 green인 경우 Phase 6 진입 허용

generation 4의 active `NATIVE_PRIORITY` projection을 입력으로 최소
`Node1InterpretationContext.v1`을 만들고, model 선택을 같은 release와 source authority에
server-side로 다시 결속했다. 봉인 Gold 5건, projection 밖 요청, metadata instruction
injection, stale/mixed release, activation·rollback과 cleanup을 격리 환경에서 검증했다.

## 구현 경계

- Node1에 공개하는 label·definition·synonym·unit·time·dimension을 bounded typed 계약으로 제한
- BUSINESS Metric마다 native Metric URN과 exact source authority 결속
- metric별 승인 dimension 교집합만 허용하고 물리 column 존재만으로 권한을 확대하지 않음
- ratio candidate는 승인된 두 operand의 공통 dimension만 전달
- instruction/example은 schema·길이·제어문자·injection allowlist를 통과한 값만 선택 투영
- model output은 candidate identifier만 제시하며 실행 asset·field·release는 server가 재결속
- stale release, projection 밖 metric/dimension, source evidence 누락은 실행 전에 fail-closed

## 격리 Acceptance 증거

- status: `PHASE5_NODE1_GROUNDING_PASSED`
- 봉인 Gold: 5/5 exact, joint-slot rate 1.0, threshold 1.0
- aggregate: `room_revenue`, `revpar`, `voc_average_rating`,
  `total_operating_revenue_krw`
- breakdown: `fnb_revenue` by `hotel_code`
- projection 밖 요청: rejection 1, execution 0, rebind attempt 0
- metadata injection: rejection 1, bypass 0
- release mismatch: rejection 1
- source/release evidence 누락: 0
- runtime full scroll: 0, bounded Search: 15
- 성공 실행 server rebind: 6
- mixed-release stale block/execution: 1/0
- product receipt binding: 7종
- model release: `MODEL-RELEASE-v1.33.0`
- manifest checksum: `6dfdd7551a58466c1222cf7b5dda5392f27353242a75899cef07e9aa38ec5429`
- activation receipts: `ACTIVATE 4→5`, `ROLLBACK 5→6`, `ACTIVATE 6→7`
- final active generation: 7
- final product release:
  `ANSWERVICE-PHASE5-NODE1:5db05f8e2558aba22e10d9423e9092235aa6a930bf9d3c520f93b6d296e18d4e`
- temporary token revoke/service account delete: true/true

격리 DB 독립 read-back에서 generation 7의 product release, Phase 5 activation receipt 3개,
7종 binding 7개와 idle connection 0을 확인했다. credential 원문은 출력하거나 파일에
기록하지 않았다. target MySQL current-aspect read-back은 `Phase 2B Acceptance` 임시 account
0, 정리 대상이 아닌 Catalog Reader/Publisher 2, access-token entity/aspect 0을 확인했다.

종료 시 resource 상태는 current container 23, target container 7, exact identity 교집합 0이다.
Docker container memory 합계는 약 13.09/15.44GiB(84.8%), Windows available memory는
4.83/31.64GiB였다. 위 4GiB/90% 중단선은 통과했지만 여유가 작으므로 Phase 6 이후 runner는
하나씩 실행하고 새 full DataHub stack을 추가하지 않는다.

## Host-tree 실행 위생 보정

격리 Acceptance 직후 제공받은 독립 평가를 재현한 결과, host tree는 실제로 red였다. Gate를
낮추지 않고 다음 문제를 수정했다.

- Phase 4 refactor가 legacy readiness의 manifest 검증을 canonical compile 실패 뒤로 숨긴 회귀:
  catalog manifest와 semantic compiler 단계를 독립적으로 보고하도록 복구
- active schema `MODEL-v1.21.0`과 training example의 `MODEL-v1.20.0` 불일치 4건: v1.21로 이행
- 공개 validator/worker와 DataHub Actions/retired SQL의 한국어 책임 문서화 누락 13건 보완
- frontend Vite test의 공용 HMR port 충돌 경고: 파일 단위 test concurrency를 1로 고정
- cancellation lifecycle test의 host scheduler 의존 0.2초 대기: Event semantics는 유지하고
  scheduler budget만 1초로 조정, 20회 반복 통과

최종 현재 tree 검증은 다음과 같다.

- 전체 Python: `983 passed, 36 skipped, 261 subtests passed`
- documentation: `346 source files, 64 executable configs` 통과
- architecture: `305 source files` 통과
- repository integrity: `878 files` 통과
- OpenAPI contract: `OPENAPI_CONTRACT_VERIFIED`
- Python compileall: 통과
- frontend test: `21 passed`, port 충돌 경고 0
- frontend production build: 통과
- Compose root dev/full/split-host/semantic/app-postgres/metadata-ingestion 6조합: 통과
- `git diff --check`: 통과

skip은 disposable DB나 opt-in live runtime이 필요한 항목이며 PASS에 합산하지 않는다.

## 평가 반영 범위와 제외

- Phase 단위 commit 권고는 합리적이지만 사용자가 commit·push·branch 변경을 명시적으로
  금지했으므로 적용하지 않았다.
- 현재 `AGENTS.md` 축약은 Phase 전략 작성 전 dirty 변경이라 소유자를 확정할 수 없다. 기존
  사용자 변경 보존 원칙에 따라 임의 복원하지 않고, 필수 전체 검증 목록을 이 실행 프롬프트와
  전략의 교차 Phase Gate에 명시했다.
- Phase 2의 held-out 표본과 상대 latency 회귀 지적은 유효한 한계로 기록했다. 봉인된 절대
  latency threshold가 없었다는 평가는 사실과 달라 source `PROMOTE`를 소급 철회하지 않았다.
- 현재 stack 배포·migration·DataHub pointer 변경은 사용자 금지 범위이므로 수행하지 않았다.

## Phase 6 인계 조건

Phase 6는 generation 7 product release와 Node1 manifest를 고정 입력으로 사용한다. same-asset
SQL AST와 Trino oracle, timeout/cancel/empty/schema drift, Artifact receipt를 격리 환경에서
검증하며, 종료 전 위 host-tree 전체 Gate를 다시 통과해야 한다.
