# DataHub Core Phase 7 Bounded Multi-Turn Gate

## 판정

- 상태: `PASS`
- 판정일: 2026-08-22
- 격리 project: `answervice-phase2b-datahub`
- 기존 `answervice` stack: read-only 상태 확인 외 mutation 명령 미실행
- 현재 실행 stack 배포: `NOT_RUN`
- Phase 8 진입: `허용`

최신 host tree로 격리 Live Acceptance와 전체 host Gate를 다시 실행했다. Golden Dialogue,
candidate canary, activation/rollback, negative safety, 실제 격리 PostgreSQL, 전체 Python·Frontend 및
Compose 정적 검증이 모두 통과했다. Gate threshold를 낮추거나 과거 증거를 현재 PASS에 혼합하지
않았다.

## 봉인 입력과 활성 release

- 이전 product release:
  `ANSWERVICE-PHASE6-SINGLE-ASSET:a870572a2f3dd0f599fd35a64c437252182f8def90dd4dff86532dfcdbf11a50`
- 활성 product release:
  `ANSWERVICE-PHASE7-BOUNDED-MULTITURN:fe9ed6de5260f7d4f547e58b551ff0679ebeb1c5a3f4c857f6fd78bd37f1aeab`
- 활성 generation: `15`
- 활성 projection:
  `runtime-catalog:57ce5c15ed7229fe41d8f4c07f0668ad8caa7ea44f26a5d24a630b7a893f55e7`
- model release: `MODEL-RELEASE-v1.33.1`
- model manifest checksum:
  `eb41b48f5482d0270021c1ad30535b53892b10fa00f12943279e8ef38e92ec13`
- Node 1 normalize prompt: `PROMPT-v1.26.1`
- Node 1 prompt checksum:
  `51923118c1ab4d74181c4f10bd56145d821253b3e6a8bad346ac772e1a762649`
- Gold: `answervice_ko_bounded_multiturn.v1`
- Gold checksum:
  `28c4f67d2a6aef982c70845282977bbde89f991b16d40de3c95ff22f6a8fc0da`
- analysis capability checksum:
  `6ef8dac2334af46dcab4f5ec2868b57b3aa79e48e8d23730cfcabbf2c355072e`
- 대상 asset: `serving.analytics_v4_3.hotel_operations_daily`
- 승인 데이터 범위: `[2025-07-01, 2025-09-01)`
- migration head: `20260822_33`

격리 DB manifest exact read-back에서 product/model/prompt release와 checksum이 위 값과 정확히
일치했다. 현재 DB에는 migration이나 backfill을 적용하지 않았다.

## Live Acceptance

실행 결과는 `PHASE7_BOUNDED_MULTI_TURN_PASSED`다.

- Golden Dialogue exact-match: `3/3`, rate `1.0`
- GD-01: Turn `3`, Run `3`, query `3`, Artifact `3`, View `3`, Report block `0`
- GD-02: Turn `5`, Run `1`, query `1`, Artifact `1`, View `4`, Report block `2`
- GD-03: Turn `2`, Run `1`, query `1`, Artifact `1`, View `1`, Report block `0`
- candidate execution count: `5`
- Node 1 호출: `7`, period recheck 호출: `0`
- Node 2 호출: `0`, Node 3 호출: `6`
- runtime full-scroll: `0`, bounded search: `41`
- source/release evidence 누락: `0`
- candidate canary readiness: `catalog_manifest`, `semantic_release`, `trino_schema` 모두 ready
- active readiness: 동일 3단계 ready
- release receipt: `ACTIVATE 12→13`, `ROLLBACK 13→14`, `ACTIVATE 14→15`

negative Gate도 모두 계약대로 종료됐다.

- duplicate mutation: `0`
- idempotency mismatch 차단: `1`, replay: `1`
- incompatible View 차단: `1`, 추가 query: `0`
- permission snapshot 차단: `1`
- pinned continuation: `1`, release rebinding: `0`
- Report fault 추가 query: `0`, transaction rollback: `1`, retry replay: `1`
- stale head 차단: `1`
- unavailable pinned release 차단: `1`
- 임시 token revoke: `true`, 임시 service account 삭제: `true`

## 구현과 결함 수정

- immutable Conversation wall-clock anchor와 product release pinning
- 성공한 Analysis Turn만을 대상으로 한 최대 2개 source lineage
- `OUT_OF_DATA_RANGE` 직후 절대 기간 수정의 pending intent 1회 복구
- pending Metric은 source/focus가 아니라 DataHub 후보 재검색 힌트로만 사용
- data/view focus의 독립 전이와 blocked Turn의 focus 불변
- Presentation zero-query와 Artifact schema 호환성 typed 차단
- Report Draft/View lineage와 caller transaction 안의 원자적 저장
- CAS, lease, idempotent replay/mismatch, permission snapshot, unavailable pinned release 차단
- frontend stale-head 409 수화와 수동 재전송
- release-bound data availability 및 Conversation 전용 `time_trend` 기본 Artifact 계약

Live 재검증에서 발견한 결함은 threshold 완화 없이 수정하고 같은 runner로 다시 증명했다.

1. blocked Turn의 typed `period_candidates`를 runner가 읽지 않아 성공적인 수정 Turn을 잘못
   실패 처리했다. 정확히 하나의 검증된 candidate만 date로 canonicalize하는 read-back을
   추가했고 성공·모호·비교 경로에는 사용할 수 없게 했다.
2. pinned release negative probe가 Gold에 없는 부가 표현을 써 Node 1 preflight에서 먼저
   차단됐다. 봉인된 GD-01 첫 발화를 재사용해 검사 대상을 release pinning으로 한정했다.
3. 상대 기간의 predecessor 요청에서 model이 직전 기간을 반복했다. 특정 질문 hard-code 없이
   `previous_period`와 명시된 calendar unit의 predecessor/successor 규칙을 Node 1 prompt에
   추가하고 model/prompt release를 함께 올렸다.
4. 최초 Artifact가 aggregate 한 행이라 LINE schema를 만족하지 못했다. Conversation 전용
   기본 operation을 `time_trend`로 봉인하되 direct single-turn 기본 aggregate는 유지했다.
5. 명시적 Report action보다 분석 preflight가 먼저 실행됐다. Presentation/Report action은
   기존 lineage를 검증한 뒤 분석 Node 호출 없이 처리하도록 분리했다.

## Host Gate

- 실제 격리 PostgreSQL Conversation integration: `3 passed`
- 전체 Python suite: `1015 passed, 36 skipped, 8 warnings, 261 subtests passed`
- frontend test: `21/21 passed`
- frontend production build: PASS
- OpenAPI contract: `OPENAPI_CONTRACT_VERIFIED`
- architecture invariant audit: `305 source files`, PASS
- code documentation audit: `347 source files, 64 executable configs`, PASS
- repository integrity audit: `890 files`, PASS
- Python `compileall`: PASS
- Compose root dev/full/split-host, semantic-search, app-postgres override,
  metadata-ingestion 총 6개 조합: PASS
- `git diff --check`: whitespace error `0`건(CRLF 경고만 존재)

skip은 disposable dependency나 opt-in live runtime이 필요한 항목이며 PASS 수에 합산하지 않았다.
Live Acceptance와 실제 격리 PostgreSQL integration을 별도로 실행했으므로 전체 suite의 skip을
live 증거로 오인하지 않는다.

## 자원·격리·정리 상태

- Live 실행 전 host available memory: `7.42 → 7.17 → 7.01 GiB`
- running container memory 합계: `83.82 → 86.11 → 87.19%`
- 격리 GMS/Kafka/App DB: healthcheck 대상 모두 healthy
- target/current container name 교집합: `0`

Compose Gate는 `config --quiet`만 실행해 container를 생성·재시작하지 않았다. Live runner의 임시
token과 service account는 finally 경로와 exact read-back으로 삭제를 확인했다. 이번 Gate가 만든
host test/build 임시 디렉터리는 저장소 내부의 정확한 경로를 확인한 뒤 정리했다. 기존 Docker
volume, 기존 파일·데이터 및 현재 실행 stack은 변경하지 않았다.

## Phase 8 진입 조건

Phase 7 Gate가 모두 충족됐으므로 Phase 8 native semantic shadow 구현·격리 검증에 진입할 수
있다. Phase 8은 native aspect를 candidate/shadow로만 발행하며 현재 DataHub entity, active
pointer 또는 index를 변경하지 않는다.
