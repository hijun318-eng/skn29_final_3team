# DataHub Core Phase 6 Single-Asset Analysis Gate

## 판정

- 상태: `PASS`
- 판정일: 2026-08-22
- 격리 project: `answervice-phase2b-datahub`
- 기존 `answervice` stack: read-only 상태 확인 외 mutation 명령 미실행
- 현재 실행 stack 배포: `NOT_RUN`
- 다음 Phase: 전체 host-tree Gate green을 확인했으므로 Phase 7 진입 허용

generation 7의 Phase 5 projection을 고정 입력으로 사용해 동일 serving asset의 aggregate,
breakdown, trend, top/bottom N, period comparison, 복수 Metric과 ratio를 결정론적 SQL로
실행했다. 봉인 SQLGlot AST와 실제 read-only Trino oracle 8건이 모두 일치했고,
cancel/timeout/empty/schema drift/clarification/unsupported closure와 same-release Artifact
영속화를 격리 DB에서 검증했다.

## 구현 경계

- 단일 serving asset: `serving.analytics_v4_3.hotel_operations_daily`
- 봉인 Gold: `answervice_ko_single_asset.v1`, 8건
- deterministic compiler: `ANSWERVICE-TYPED-SQL-v1.1.0`
- Node 1·Node 2 호출: 0건, Node 3 결과 설명만 허용
- App 소유 versioned analysis capability sidecar는 active catalog checksum과 단일 asset에 결속
- 기간 비교 parameter는 capability에 명시된 asset에만 추가하며 DataHub native schema로 가장하지 않음
- ratio의 독립 BUSINESS operand Term도 실행 Context 계보에 포함
- query lifecycle은 placeholder SQL이 아닌 parameter-bound exact SQL hash에 결속
- product release는 active pointer 재검증 뒤 Context·Run·Query·Artifact에 전파

## 격리 Acceptance 증거

- status: `PHASE6_SINGLE_ASSET_ANALYSIS_PASSED`
- exact SQL AST/Trino result: `8/8`, exact rate `1.0`
- operation coverage: aggregate, breakdown, time trend, top N, bottom N, period comparison
- 복수 Metric: `room_revenue + fnb_revenue`
- ratio: `revpar = room_revenue / available_room_nights`
- candidate 실행: 9건(봉인 Gold 8 + empty 1)
- bounded DataHub Search: 35건, runtime full scroll: 0건
- clarification: `CLARIFICATION_REQUIRED`, query 0, Artifact 0
- unsupported ratio period comparison: `BLOCKED`, query 0, Artifact 0
- cancelled: `CANCELLED`, 실행 1, Artifact 0
- timeout: `FAILED`, cancel 1, Artifact 0
- empty: `SUCCEEDED`, 정규화 row 0, Artifact 1
- schema drift: `FAILED`, query 0, Artifact 0
- persistence: request 15, query 10, Artifact 10, Artifact release binding 10, success 10
- candidate canary readiness: catalog/semantic/Trino 모두 ready, pointer unchanged
- active replay: Gold `SA-H-001` exact
- Gold checksum: `7a070b4d68cbf9a45c86c48a8c6c239c3f72d3b0728fc709a6951d320dcb9811`
- analysis capability checksum: `b18cd323b454216489673f4f772ae4b256eebd7a4e750ab27efd01ae204844c6`
- activation receipts: `ACTIVATE 7→8`, `ROLLBACK 8→9`, `ACTIVATE 9→10`
- final active generation: 10
- final product release:
  `ANSWERVICE-PHASE6-SINGLE-ASSET:a870572a2f3dd0f599fd35a64c437252182f8def90dd4dff86532dfcdbf11a50`
- temporary token revoke/service account delete: true/true

## 전체 host-tree 회귀 증거

- Python 전체 suite: `995 passed, 36 skipped, 8 warnings, 261 subtests passed`
- Frontend test: `21 passed`
- Frontend production build: PASS
- architecture audit: `305 source files`, PASS
- code documentation audit: `346 source files, 64 executable configs`, PASS
- repository integrity audit: `884 files`, PASS
- Python `compileall`: PASS
- OpenAPI/integrity 집중 suite: `19 passed, 9 subtests passed`
- Compose merge/config: root dev/full/split-host, semantic-search, app-postgres override,
  metadata-ingestion 총 6개 조합 PASS
- `git diff --check`: whitespace error 0건(CRLF 경고만 존재)

처음 integrity audit은 신규 versioned analysis capability JSON이 runtime JSON 허용 목록에 없어
실패했다. 해당 파일을 catalog-bound sealed capability 계약으로 명시 분류하고 회귀 테스트를 추가한
뒤 전체 audit을 다시 통과했다. Gate를 낮추거나 파일을 제외하지 않았다.

## 실행 중 발견·수정한 결함

- active product receipt가 실행 asset과 Artifact까지 전파되지 않던 경로를 active pointer
  재검증 뒤 server-side 결속하도록 수정
- durable lifecycle은 executable SQL을 해시하지만 terminal Artifact 저장은 placeholder SQL을
  해시하던 불일치를 exact executable SQL로 통일
- active DataHub time metadata에 comparison window가 없던 기능 공백을 catalog-bound App
  capability 계약으로 보완하고, 계약 불일치는 fail-closed 처리
- ratio numerator가 독립 BUSINESS Metric이면 출력 ratio Term만 전달되어 G1이 닫히던 문제를
  실행 scope 전체 BUSINESS Glossary evidence 보존으로 수정
- ratio period comparison을 metric ambiguity가 아니라 typed unsupported strategy로 분류
- empty fixture의 1900년이 ClickHouse Date 지원 범위 밖이던 오류를 1970년의 실제 empty
  구간으로 교체

## 한계와 다음 Gate

이 문서는 격리 candidate와 host-tree 회귀 기준의 Phase 6 `PASS`이며 현재 실행 stack의
same-release 배포 증거가 아니다. Phase 7은 generation 10 product release를 고정 입력으로 bounded multi-turn,
clarification resume, focus/source Turn, presentation zero-query, Report action과
refresh/retry/권한 회수/release 변경 negative를 검증해야 한다.
