# DataHub Core Phase 3 Native Metric·AI Context Capability Gate

- 판정 시각: 2026-08-22 (Asia/Seoul)
- 격리 project: `answervice-phase2b-datahub`
- DataHub image/model: pinned Core `v1.7.0`
- 대상 release: `walkerhill-v4.3-sql-20260815-derived.1-retirement-20260820.1-iceberg-analyst.4-runtime-v2.20260820.4`
- catalog checksum: `747097cdb520f117471ab7ec1f0ceb3c1380494c507b5f3750fac7f22da4de49`
- canonical checksum: `724ea6e3af16d1893705b0c43e941ed8d6f54e409061841333d0bbdb7a1aebad`

## 결론

- Phase 3A capability decision: `SUPPORTED`
- Phase 3B shadow/equality Gate: `PASS`
- runtime authority activation: `false`
- Phase 4 자동 진입: 허용
- 현재 실행 `answervice` stack: 변경·재배포하지 않음

Pinned schema와 같은 격리 Core에서 native `Metric`의 계산식과 별도 `aiContext` aspect를
write/read-back했다. stable identity의 10개 BUSINESS Metric을 shadow 발행하고 REST·GraphQL
equality, 검색 영향, 권한 negative, injection negative, retirement와 restore를 검증했다.
애플리케이션의 후보 entity type은 계속 `DATASET`, `GLOSSARY_TERM`뿐이며 native Metric을
실행 authority로 활성화하지 않았다.

## 격리 경계와 충돌 검사

모든 Compose 명령은 명령행 project `-p answervice-phase2b-datahub`를 사용했다. 판정 직전
Docker label과 실제 resource type/name을 다시 비교했다.

- 기존 `answervice`: container 23, network 2, volume 13, 총 38 identity
- 격리 대상: container 6, network 1, volume 3, 총 10 identity
- exact resource identity 교집합: 0
- 격리 GMS: `127.0.0.1:38081 -> 8443`
- 격리 management: `127.0.0.1:34319 -> 4319`
- Phase 3B 전후 전체 Docker resource identity delta: 0

현재 DataHub `28081`과 Trino `18443`은 active release 재구성용 read-only source로만
사용했다. 모든 publish·retirement·restore는 격리 GMS `38081`에만 수행했다.

## Phase 3A — pinned schema와 live capability

같은 pinned image 안의 entity registry와 PDL, GraphQL introspection, 실제 write/read-back을
결합했다.

- `MetricInfo`: schemaVersion 4
- 계산식: `MetricInfo.expression.dialects[]`의 `DialectExpression(dialect, expression)`
- AI Context: `metricInfo.aiContext`가 아닌 별도 `aiContext` aspect, schemaVersion 1
- AI Context 필드: `synonyms`, `instructions`, `examples`, `customInstructions`
- GraphQL: `Metric.info.expression`과 `Metric.aiContext` 확인
- schema receipt SHA-256: `71111e8c4cf6ec7022c2442964af8c76d6a59b3d663e88d0c155a13e04822a4f`

Stable probe URN은 다음과 같다.

`urn:li:metric:(urn:li:dataPlatform:datahub,answervice.capability_probe,phase3a_metric_v1)`

- stable URN SHA-256: `e72defe616fe80eece86352e85ee5d7a9777d1efbb52013f7dfb90b2b86779d5`
- release membership receipt SHA-256: `99a15323f96a239467e5bc8ca87c4819f686fbe170570934af4a63c6fd5ae88a`
- active → retired → restored → final retired exact read-back: 통과
- capability probe 최종 상태: retired

Pinned Core에는 이 release의 native membership을 완결적으로 표현하는 aspect가 확인되지
않았다. 따라서 membership 판정은 `EXTERNAL_MANIFEST_REQUIRED`로 봉인하고, immutable external
membership checksum과 명시적 `status.removed` filter를 함께 사용한다. 이 제한을 숨기거나
native release authority가 완성됐다고 보고하지 않는다.

## Phase 3B — stable shadow와 equality

Release마다 바뀌는 catalog hash를 URN에서 제거하고 logical path
`answervice.business_metrics`를 사용했다. release membership은 stable identity와 분리해 외부
checksum manifest로 결속했다.

- native BUSINESS Metric: 10
- native ANSI SQL expression: 10
- native `aiContext`: 10
- projection SHA-256: `4df5aef169e7268c5c16123465f6e4bf0a7a180940cef429d5b6ddff765df6ae`
- release membership SHA-256: `743de868ebcc8e9015a2e1acdfc4f73727b03814a86f7ee91aabd749d932303a`
- REST aspect equality: 100%
- GraphQL identity/equality: 100%, 10/10
- final `status.removed`: `false`
- runtime authority activated: `false`

계산식은 active canonical contract의 ANSI SQL만 발행했다. AI Context는 승인된 Glossary alias만
`synonyms`로 투영했으며 `instructions`, `examples`, `customInstructions`를 임의로 만들지 않았다.
GraphQL이 생략된 optional field를 `null`로 반환하는 경우만 정규화하고, 예상하지 않은 non-null
instruction/example은 equality 실패로 닫는다. 모든 native 자유 텍스트는 control character,
prompt/system instruction marker와 길이 제한을 통과해야 한다.

직접 Metric Search 측정 결과:

| 항목 | 결과 |
|---|---:|
| Metric name 검색 | 10/10, coverage 100% |
| `aiContext` alias 검색 | 3/10 |
| retirement 후 name hit | 0 |
| restore 후 name hit | 10 |
| injection negative candidate | 0 |

`aiContext` PDL에 Search annotation이 확인되지 않았으므로 alias hit 3/10을 자동 index 지원이나
recall 개선으로 해석하지 않는다. Phase 3은 native equality와 영향 측정까지만 봉인한다.

## 권한·검색 non-regression

Native shadow restore 후 Phase 2의 봉인 Gold canary 87개를 격리 target에서 다시 실행했다.

- status: `CANARY_PASSED`
- application candidate entity types: `DATASET`, `GLOSSARY_TERM`
- native Metric candidate exposure: 0
- unauthorized metadata exposure: 0
- candidate infrastructure error: 0
- production diff: 0
- 한국어 held-out Top-1 / Recall@5 / MRR: `0.9 / 1.0 / 0.95`
- DataHub warm p50 / p95 / max: `89.381 / 180.453 / 761.119ms`
- temporary read token revoked: true
- temporary service account deleted: true
- Docker resource identity delta: 0

## 실패·복구 기록

Gate를 낮추지 않고 다음 실패를 격리 target 안에서 수정·재검증했다.

1. Metric에 지원되지 않는 lifecycle `APPROVED`를 발행해 HTTP 422가 발생했다. 첫 ADR Metric은
   partial 상태였고 즉시 explicit retirement로 정리했다. Metric status는 지원되는
   `removed`만 사용하도록 수정했다.
2. GraphQL의 생략 optional AI Context 필드가 `null`로 반환돼 strict dict equality가 timeout됐다.
   발행된 shadow는 cleanup retirement했고, expected field equality와 unexpected non-null 거부를
   분리했다.
3. 일반 transport failure가 한 번 발생했다. attempted URN을 모두 retirement한 뒤 HTTP contract
   실패는 재시도하지 않고, idempotent GET/GraphQL/UPSERT의 정확한 generic transport failure만
   최대 3회 bounded retry하도록 제한했다.
4. 최종 멱등 재실행에서 publish/read-back/search/retirement/restore 전체가 통과했다.

실패 과정에서도 현재 stack mutation, volume 조작, authority activation은 없었다.

## Actions 관측

Phase 3 종료 시 격리 GMS, Kafka, MySQL, OpenSearch와 Actions는 모두 `running`, restart count 0이다.
Actions 프로세스에는 doc propagation pipeline만 실행 중이고 `ingestion_executor`는 명시적으로
비활성이다. 다만 Phase 3의 대량 MCL 직후 doc propagation consumer가 Kafka session timeout으로
재조인하면서 관측 시점에 inactive member와 lag가 있었다. GMS 내부 index consumer와 Phase 3
Search, Phase 2 canary는 직접 통과했으므로 Phase 3 native equality Gate를 막지는 않지만,
Phase 4 release activation 전 bounded 재관측 항목으로 남긴다. 컨테이너를 재시작해 상태를
숨기지 않았다.

## 실행한 검증

- pinned image entity registry/PDL 추출 후 임시 파일 정리
- GraphQL introspection과 stable probe REST/GraphQL exact read-back
- 격리 native shadow publish → equality → search → retirement → restore
- 격리 Phase 2 Gold canary 87개 재실행
- `python -m pytest tests/data/test_phase3a_datahub_capability.py tests/data/test_phase3b_native_metric_shadow.py tests/data/test_datahub_native_metric_shadow.py tests/data/test_datahub_metadata_publication.py tests/backend/test_datahub_search_retrieval.py tests/backend/test_governed_data_platform.py tests/ai/test_metric_retrieval.py -q`
  - 112 passed, 3 skipped, 18 subtests passed
- `git diff --check`
  - whitespace error 0

## Phase 4 진입 조건

Phase 3의 `SUPPORTED` 범위는 검증된 native `metricInfo.expression`과 별도 `aiContext`를 우선
source로 사용한다. Release membership은 외부 checksum manifest와 `status.removed` filter를
반드시 유지한다. Phase 4에서는 full scroll/read-back을 out-of-band compiler로 옮기고,
membership/equality 100%, Trino fingerprint, activation CAS, mixed release 0, cold/warm readiness,
canary와 rollback을 증명하기 전 runtime authority를 전환하지 않는다.
