# DataHub Core Phase 10 P0 Same-Release Gate

## 판정

`BLOCKED` — 2026-08-23 KST

Phase 10의 same-release 기술 검증 경로와 P0 Gold·semantic 사람 승인은 완료됐다. generation 34에서
source, migration, Backend·Frontend candidate image, DataHub, Trino, App DB, 실제 Browser replay,
host validation과 승인된 Gold를 하나의 product release로 결속·봉인했다. 실제 제품 반복 평가는
55건×2회 중 17건×2회인 34개 관측까지 실행됐고, 공식 exact 계약 기준 일치 관측은 0개였다.
그중 7개 case는 기대 `ALLOW`가 두 번 모두 `BLOCK`으로 관측됐으며 이후 새 Conversation 생성이
실패해 평가가 중단됐다. 따라서 110개 전체 receipt와 PRD Requirement·Release Gate 재판정은
생성하지 않았고 제품 Gate를 통과시키지 않는다.
Phase 0B~9의 과거 receipt, skip, test-double 또는 다른 generation의 성공 결과를 Phase 10 증거로
합치지 않으며 Phase 11 이후에는 진입하지 않는다.

동적으로 바뀌는 source patch, image digest, generation, request ID와 receipt checksum은 이 문서에
복사하지 않는다. 최종 실행의 정본은 다음 검증기가 같은 실행에서 생성·재검증하는 `.tmp` receipt다.

- `infrastructure/acceptance/phase10_candidate_release.py`
- `infrastructure/acceptance/phase10_candidate_services.py verify`
- `infrastructure/acceptance/phase10_browser_receipt.py`
- `infrastructure/acceptance/phase10_host_validation.py`
- `infrastructure/acceptance/phase10_p0_review_approval.py`
- `infrastructure/acceptance/phase10_p0_release_seal.py`
- `infrastructure/acceptance/phase10_p0_product_eval.py`
- `infrastructure/acceptance/phase10_p0_same_release.py`

## 격리 토폴로지

새 DataHub나 PostgreSQL stack을 하나 더 만들지 않았다. 승인된 Compose project
`answervice-phase2b-datahub` 안에서 기존 격리 DataHub와 PostgreSQL을 재사용하고, Phase 10 전용
DB·role·candidate service만 추가했다.

| 구성요소 | 경계 |
|---|---|
| 기존 `answervice` stack | read-only, restart/recreate/migration/mutation 없음 |
| 격리 DataHub | `https://127.0.0.1:38081`, 임시 최소권한 identity만 사용 |
| 격리 PostgreSQL | `127.0.0.1:55440`, 전용 DB `phase10_p0_same_release_acceptance` |
| DB roles | migration 전용 `phase10_migrator`, runtime 전용 `phase10_runtime` |
| 기존 Trino | `https://127.0.0.1:18443`, read-only query와 fingerprint 검증 |
| candidate Backend | project 내부 임시 service, host `127.0.0.1:48000` |
| candidate Frontend | project 내부 임시 service, host `127.0.0.1:43000` |

candidate service는 검증할 때만 생성하고, 완료 후 container와 임시 DataHub account/token만 exact
식별해 제거한다. 격리 기반 DataHub·PostgreSQL resource와 volume은 유지한다.

## same-release 기술 Gate

다음 9개 축이 모두 같은 immutable manifest와 source receipt를 가리킬 때만 기술 증거를
`VERIFIED`로 판정한다.

1. source commit/dirty patch receipt
2. Backend candidate image digest
3. Frontend candidate image digest
4. model manifest checksum
5. DataHub native semantic exact read-back
6. Trino catalog fingerprint와 nonterminal query 0
7. 전용 App DB migration chain과 active product manifest
8. 실제 Browser→HTTP→Backend→Trino→App DB saved-analysis replay
9. 같은 source에 대한 고정 host-validation 명령 집합

`phase10_p0_same_release.py`는 target project와 DB를 exact 고정하고 다음을 fail-closed로 확인한다.

- active pointer, immutable manifest checksum, lease와 source/model/migration/image 일치
- Browser receipt의 request, 새 Trino query, `cached=false`, terminal run, artifact
- RUN·ARTIFACT의 product/permission/semantic receipt와 binding 일치
- candidate container의 Compose project, health, image ID, readiness와 active release 일치
- historical evidence `0`, skipped evidence `0`
- BLOCKED 결과까지 canonical `assessment_sha256`로 무결성 검증

## 구현 과정에서 발견해 수정한 P0 결함

실제 Browser saved-analysis replay에서 기존 구현이 새 실행의 핵심 계약을 보장하지 못하는 문제를
찾았다. 단순 테스트 보강이 아니라 runtime 경로를 수정했다.

- replay 요청이 저장 당시 정의인 `replayDefinition`을 사용하도록 변경
- 현재 active product release와 server-side permission snapshot을 새 실행에 재결속
- replay가 이전 result cache를 사용하지 않고 새 Trino query를 실행하도록 `require_fresh_query` 추가
- terminal receipt가 불완전하면 analysis run 시작을 거부
- 새 RUN과 ARTIFACT에 product·permission·semantic receipt/binding을 기록하고 exact read-back
- Frontend가 일반 분석 API가 아니라 replay 전용 API를 호출하도록 변경

실제 Chromium 흐름에서는 저장 분석을 다시 실행해 완료 화면과 근거 패널을 확인하고, Browser에
노출된 결과를 동일 request의 DB terminal state·새 Trino query·artifact와 결속한다. cookie, trace,
network dump, raw row, SQL literal 또는 credential은 receipt에 보존하지 않는다.

## 승인·봉인·제품 반복 평가

기술 축이 모두 green이어도 아래 canonical 제품 증거가 자동으로 생기지는 않는다.

- P0 Requirement: `66`, `VERIFIED 0`
- P0 Release Gate: `11`, `VERIFIED 0`
- 교정 전 P0 Gold v1: `55` cases
  - `REVIEW_REQUIRED 50`, semantic gap으로 `BLOCKED 5`
  - 결과가 seal되지 않은 ALLOW case `37`
- 교정 P0 Gold v2 candidate: `55` cases
  - STRUCTURED `30`, SAFETY `15`, MULTI_TURN `10`
  - `ALLOW 35`, `BLOCK 20`, query가 실행된 oracle `35`
  - reviewer `urn:li:corpGroup:answervice_runtime_stewards`
  - `APPROVED 55`, semantic gap blocker `0`, 결과 미봉인 `0`
  - repository 원본은 release ID를 넣지 않은 `DRAFT`로 유지
- semantic review candidate: BUSINESS `10`, SUPPORT `4`, 전 항목 `APPROVED`
- 승인 시각: `2026-08-23T15:34:19+09:00`

사람 검토는 더 이상 blocker가 아니다. repository 원본에 product release ID를 넣으면 source hash와
release ID가 순환하므로, `phase10_p0_release_seal.py`가 새 active release와 현재 source가 일치한 뒤
외부 `.tmp/phase10-p0-sealed-v2` bundle에 semantic/product release를 결속한다. 이 bundle만
`VALID_SEALED_GOLD`와 `scorable=true`가 될 수 있다.

`phase10_p0_product_eval.py`는 해당 bundle과 active generation을 exact lease로 고정하고 실제 후보
API `127.0.0.1:48000`에서 55건을 각각 두 번 새 Conversation으로 실행한다. 기대값은 제품 응답
정규화에 입력하지 않으며, 중단 시 같은 lease의 완료 `(case_id, attempt)`만 재사용한다. 55/55
정확도와 55/55 반복 결정성이 아니면 receipt를 `BLOCKED`로 기록한다. analyst credential은 메모리
로그인에만 쓰고 출력·receipt·질문별 증거에 기록하지 않으며 비밀번호를 변경하지 않는다.

generation 34 실행에서는 P0-S-001~P0-S-017의 두 반복이 저장됐다. 34개 모두 route, resolved
request, query strategy, asset/join, decision/error, result assertion을 함께 보는 exact 계약과
불일치했다. 특히 P0-S-007·010·011·012·015·016·017은 기대 `ALLOW`와 달리 `SQL_POLICY_BLOCKED`,
`CONTEXT_INCOMPLETE` 또는 `CONTEXT_SOURCE_FAILED`로 차단됐다. 이어지는 P0-S-018 Conversation
생성 전에 제품 경로가 실패했으므로 남은 관측을 성공으로 추정하거나 부분 결과로 정식 110개
receipt를 만들지 않았다.

따라서 ANL-011·QA-002·QA-004·P0 정량 Gate는 승인 사실만으로 통과하지 않는다.
v2는 잘못 차단한 same-view multi-metric 3건, 기간이 빠진 multi-turn 2건, 미등록 metric·민감
dimension taxonomy와 event/booking-time dimension gap을 교정했다. 35개 ALLOW는 independent
read-only Trino aggregate 값 또는 canonical result hash를 고정했고, 20개 BLOCK은 query를 실행하지
않는다. 같은 product release에 외부 봉인한 뒤 제품 관측 반복 결과가 사전 봉인된 기준을 만족해야
하며, 이를 과거 capability별 소표본, unit test 또는 수동 성공 1건으로 대체하지 않는다.

VOC oracle은 제품 runtime compiler 식을 재사용하지 않는다. review PK와 analysis review
UNIQUE/FK가 보장하는 리뷰당 1행을 근거로 `AVG(rating_overall)` 동치식을 사용하고, 원천
`crm_voc_reviews`에서 평점·기간·허용 dimension의 비식별 aggregate만 읽는다. 원문·제목·회원키·
관련 ID·리뷰 ID·제출시각은 SQL 생성 단계에서 차단하고 receipt에는 SQL·raw row·credential을
남기지 않는다. 격리 DataHub와의 RAM 경쟁 중에는 해당 격리 container만 일시 정지하며 기존
`answervice` stack은 변경하지 않는다.

## 실행 위생 반영

외부 평가의 핵심 지적 중 유효한 부분은 “문서의 PASS와 현재 전체 tree의 PASS를 혼동하지 말라”는
것이었다. 다음을 현재 Gate 계약에 반영했다.

- root `AGENTS.md`에 numbered Phase Gate 실행 규칙 추가
- subset test와 current full Gate를 분리하고 최종 판정에는 current full receipt만 사용
- repository 내부 고유 pytest basetemp와 cacheprovider 비활성화로 host cache 권한 영향 제거
- OpenAPI, documentation, architecture, repository integrity, compileall, 전체 pytest, Frontend
  test/build, 6개 Compose config와 `git diff --check`를 고정된 15개 명령으로 실행
- 각 명령은 ID·exit code·duration·output SHA-256만 receipt에 기록하고 raw log는 보존하지 않음
- migration upgrade뿐 아니라 rollback·replay 검증 범위를 명시적으로 구분
- Gate를 낮추거나 과거 실행·skip을 현재 성공으로 승계하지 않음

평가 실행 당시에는 사용자가 Git commit·push·PR·branch 변경을 명시적으로 금지했으므로 dirty
source 자체를 canonical patch SHA-256으로 봉인했다. 이후 인계 시점의 별도 승인에 따라 runtime,
acceptance, 핵심 회귀 테스트와 Gate 문서를 review 가능한 커밋으로 정리한다. 로컬 `.tmp` receipt,
Browser 출력, 임시 principal·token·lease는 커밋하지 않는다.

## 최종 결정

Phase 10은 제품 수준에서 `BLOCKED`다. result oracle과 사람 승인, generation 34 same-release 결속,
host validation과 실제 Browser replay는 완료됐지만 제품 반복 관측이 exact 계약을 만족하지 못했다.
봉인 뒤 추가된 관련 없는 Node2 문서도 current source receipt를 바꿨으므로 generation 34와 현재 tree를
같은 source로 주장하지 않는다. 사용자 파일은 이동·삭제·ignore 처리하지 않았다. candidate
Backend·Frontend, 임시 DataHub account/token, 임시 analyst principal과 candidate lease는 정확히
식별해 제거했고 격리 기반 stack만 후속 재평가를 위해 유지한다.

다음 제품 수정은 새 source·image·product release로 봉인하고 55건×2회 전체 평가부터 다시
증명해야 한다. PRD `66/66`, Release Gate `11/11`도 그 동일 release의 완전한 receipt가 생기기 전에는
`VERIFIED`로 올리지 않는다. RAM, Docker 수, Oracle Database 또는 candidate 기술 경로를 제품
적합성 부족과 혼동하지 않는다. 기술 검증, 사람 승인, 실제 제품 평가 결과를 분리해 보존하며 실패
시 Gate를 낮추지 않는다.

Phase 11과 Graph Foundation 구현은 시작하지 않는다.
