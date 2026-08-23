# DataHub Core Phase 2 Search Gate

- 판정 시각: 2026-08-22 (Asia/Seoul)
- 대상 release: `walkerhill-v4.3-sql-20260815-derived.1-retirement-20260820.1-iceberg-analyst.4-runtime-v2.20260820.4`
- catalog checksum: `747097cdb520f117471ab7ec1f0ceb3c1380494c507b5f3750fac7f22da4de49`
- canonical checksum: `724ea6e3af16d1893705b0c43e941ed8d6f54e409061841333d0bbdb7a1aebad`

## 결론

- Phase 2A: `PASS`
- Phase 2B: `PASS`
- cutover decision: `PROMOTE`
- source default: `datahub_lexical`
- 현재 실행 stack: 변경·재배포하지 않음
- Phase 3 자동 진입: 허용

Phase 2A의 shadow·권한·품질·latency Gate와 Phase 2B의 격리 candidate 발행, index
coverage·freshness, Actions 안정성, canary non-regression, 권한 negative closure와 rollback
rehearsal을 모두 통과했다. source와 Compose의 기본 mode는 `datahub_lexical`로 전환했다.
사용자가 동결한 현재 실행 stack과 현재 `.env`는 변경하지 않았으므로 이 판정은 source
cutover 결정이며 현재 실행 instance의 배포 완료를 뜻하지 않는다.

## Phase 2A 증거

독립 한국어 Gold는 active catalog 자동 probe와 분리해 먼저 작성하고 canonical SHA-256으로
봉인했다.

- manifest: `evals/metric_retrieval_gold/answervice_ko_retrieval.v1.json`
- dataset: `answervice_ko_retrieval.v1`
- SHA-256: `7c257717eb153d9ef8b4d0203cda0050ef3721e580a40bc7e261a1f77e3c055d`
- 전체 probe: 87개
  - catalog exact 42
  - catalog definition 10
  - 독립 한국어 positive 15(calibration 5, held-out 10)
  - negative 20(독립 한국어 4 포함)

최종 one-off read-only canary 결과:

| 지표 | `lexical` baseline | `datahub_lexical` candidate |
|---|---:|---:|
| catalog exact Top-1 / Recall@5 / MRR | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| catalog definition Top-1 / Recall@5 / MRR | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| 한국어 held-out Top-1 | 0.8 | 0.9 |
| 한국어 held-out Recall@5 | 1.0 | 1.0 |
| 한국어 held-out MRR | 0.883333 | 0.95 |
| negative closure | 1.0 | 1.0 |
| unauthorized metadata exposure | 0 | 0 |
| infrastructure error | 0 | 0 |
| warm p95 | 18.931ms | 220.12ms |

`lexical_shadow`의 87개 production 결과는 `lexical`과 완전히 같아 diff 0이었다.
DataHub 요청은 probe 전체에서 159개였고 probe별 query variant는 최대 3, 검색 결과 window는
20, 공개 candidate는 최대 24로 제한됐다. shadow 오류·timeout·capacity·shutdown cancel,
검색 밖 release membership, entitlement negative, query syntax injection은 unit/integration
test에서 fail-closed를 확인했다.

## 구현 경계

- `searchAcrossEntities`는 `DATASET`, `GLOSSARY_TERM`만 단일 bounded page로 조회한다.
- DataHub Search는 후보 자산 범위를 정하고, 그 범위 안에서만 승인된 label·alias·definition
  lexical evidence가 Metric 순위를 정한다.
- Search가 찾지 않은 자산, join 확장으로만 들어온 자산, 권한 밖 자산은 selectable 후보가
  될 수 없다.
- exact alias가 없는 질문의 query hint는 active release label·alias에서만 만들며 서로 다른
  Unicode token 관계가 두 개 이상이어야 한다. 단일 공통어와 ASCII 부분문자열은 허용하지
  않는다.
- 검색 실패는 `datahub_lexical`에서 typed failure로 닫고, `lexical_shadow`에서는 production
  선택과 분리한다.

## 실행한 검증

- `python -m pytest tests/backend/test_datahub_search_retrieval.py tests/backend/test_governed_data_platform.py tests/ai/test_metric_retrieval.py -q`
  - 67 passed, 3 skipped, 6 subtests passed
- 봉인 Gold comparative runner를 현재 DataHub에 read-only one-off container로 실행
  - 최종 status `PASSED`
  - production diff 0
  - unauthorized exposure 0
  - candidate infrastructure error 0
- 확대 window 50 canary도 실행했으나 Recall 결함을 해결하지 않아 기본값으로 채택하지 않음

## Phase 2B 격리 인수 결과

명령행 project name을 항상 `-p answervice-phase2b-datahub`로 지정했다. 실행 전 Compose
dry-run에는 격리 Actions 한 개만 recreate 대상으로 나타났고, 이름에서
`answervice-phase2b-datahub` 외 기존 `answervice` resource 참조는 0이었다.

- GMS API: `127.0.0.1:38081 -> 8443`
- GMS management: `127.0.0.1:34319 -> 4319`
- Frontend 예약 mapping: `127.0.0.1:39002 -> 9002`(이번 Gate에서는 시작하지 않음)
- network: `answervice-phase2b-datahub_datahub-network`
- volumes: `answervice-phase2b-datahub_datahub-kafka-data`,
  `answervice-phase2b-datahub_datahub-mysql-data`,
  `answervice-phase2b-datahub_datahub-opensearch-data`
- 현재 `answervice` resource: container 23, network 2, volume 13의 identity가 격리 Actions
  recreate 전후 동일

active release bundle만 재구성해 격리 GMS에 발행했다. 현재 Trino의 active release 밖 물리
asset 14개는 candidate membership에 포함하지 않았다.

- Dataset 51개, schema field 578개, Glossary Term 10개, governance entity 8개
- candidate aspect 422개 exact read-back
- Dataset Search coverage 100%, Glossary Search coverage 100%
- checksum-bound publish-to-verify freshness 26,279ms
- release ID, catalog checksum, canonical checksum exact match
- 임시 service account와 1시간 token은 메모리에서만 사용하고 canary·rollback 후 token revoke와
  account 삭제 확인

봉인 Gold와 active catalog를 결합한 격리 canary 87개 결과:

| 지표 | `lexical` baseline | 격리 `datahub_lexical` candidate |
|---|---:|---:|
| catalog exact Top-1 / Recall@5 / MRR | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| catalog definition Top-1 / Recall@5 / MRR | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| 한국어 held-out Top-1 | 0.8 | 0.9 |
| 한국어 held-out Recall@5 | 1.0 | 1.0 |
| 한국어 held-out MRR | 0.883333 | 0.95 |
| negative closure | 1.0 | 1.0 |
| unauthorized metadata exposure | 0 | 0 |
| production diff | 0 | 0 |
| candidate infrastructure error | 0 | 0 |
| p50 / p95 / max | 해당 rollback 결과 참조 | 87.618 / 156.348 / 173.467ms |

명시적 `lexical` rollback은 catalog probe 68개를 통과했고 DataHub question-search 요청은
0이었다. exact·definition Top-1/Recall@5/MRR와 negative closure는 모두 1.0,
contamination은 0, latency p50/p95/max는 13.307/18.935/23.186ms였다.

Actions에는 private CA를 `curl`, Python client, Kafka와 Schema Registry가 모두 사용하도록
고정했다. Phase 2 Search에 불필요한 remote ingestion executor는 명시적 opt-in으로 바꾸고
기본값을 `false`로 두었다. 격리 Actions만 recreate한 뒤 확인한 결과는 다음과 같다.

- status `running`, restart count 0, bounded 연속 관측 212초 이상
- `datahub_doc_propagation_action`의 MetadataChangeLog·PlatformEvent partition active member 2,
  total lag 0
- retained `ingestion_executor` consumer group은 active member 0이며 신규 `RUN_INGEST`, plugin
  install 또는 executor-running log 0
- startup 이후 Actions error·traceback·DNS·TLS failure 0

source default 전환과 failure semantics는 unit/integration test로 확인했다.

- `QueryGovernanceAdapter`와 `GovernedDataPlatformAdapter` 기본값: `datahub_lexical`
- Backend Compose fallback: `datahub_lexical`
- timeout과 capacity 초과: fail-closed
- caller cancel, shutdown 시 pending shadow task cancel 전파
- rollback mode: `lexical`
- 관련 전체 회귀: 97 passed, 3 skipped, 18 subtests passed

## 사후 실행 위생 재평가

Phase 5 종료 뒤 현재 host tree 전체 회귀를 복구하는 과정에서 Phase 2 판정도 다시 검토했다.

- 한국어 held-out positive는 10건이고 Top-1 증가는 0.8→0.9로 정답 1건 차이다. 이는 봉인한
  기술 Gate의 통과 증거이지만 통계적 유의성이나 일반적인 한국어 품질 향상을 주장할 표본은
  아니다.
- candidate warm p95 220.12ms는 baseline 18.931ms보다 약 11.6배 느리다. 다만 Gold에 결과를
  보기 전에 봉인한 절대 상한 `max_candidate_warm_p95_ms=3000`이 존재하며 candidate는 이를
  통과했다. 따라서 "latency threshold가 없었다"는 평가는 사실과 다르지만, 절대 상한만으로
  baseline 대비 회귀 폭을 통제하지 못한다는 지적은 유효하다.
- 이에 따라 `PROMOTE`는 계속 source default 결정으로만 유지한다. 현재 실행 stack의 production
  activation은 `NOT_RUN`이며, 실제 activation 전에는 더 큰 독립 한국어 held-out과 사전 봉인한
  baseline 대비 latency regression budget을 추가해 재평가한다. 결과를 본 뒤 threshold를
  낮추지 않는다.
- caller cancellation test의 0.2초 scheduler 대기를 1초로 완화하되 Event 기반 행위 검증은
  그대로 유지했고, 해당 test를 별도 process에서 20회 반복해 20/20 통과를 확인했다.

## 이전 BLOCKED_ENV와 환경 충돌 기록

변경 전 현재 DataHub Actions 관측:

- status: running
- Docker restart count: 573
- startup log: private-CA HTTPS GMS `/health`를 `curl`이 신뢰하지 못해 timeout 반복
- GMS와 OpenSearch: healthy, restart count 0

원인은 Actions image의 startup script가 `curl`을 사용하지만 Compose에는 Python requests용
`REQUESTS_CA_BUNDLE`만 설정된 점이다. source Compose에는 `CURL_CA_BUNDLE`을 추가했다.

이 수정의 안정성을 분리된 DataHub에서 확인하려 했으나 `infrastructure/database/.env`의
`COMPOSE_PROJECT_NAME=answervice`가 acceptance overlay의 `name`보다 우선했다. 그 결과
2026-08-22 05:33 KST에 현재 `datahub-gms-quickstart`와
`datahub-actions-quickstart`가 의도치 않게 recreate되었고 즉시 명령을 중단했다.

확인된 영향:

- Backend, Frontend, App DB, Trino, MySQL, Kafka, OpenSearch는 recreate되지 않음
- Docker volume 삭제·초기화 없음
- DataHub entity/aspect/index mutation 명령은 실행되지 않음
- GMS는 기존 MySQL/OpenSearch를 사용해 다시 healthy가 됨
- Backend `/readiness`는 이후 HTTP 200과 전체 dependency `ready`를 반환
- GMS host mapping은 의도와 달리 `28081`로 바뀜
- Actions container는 `Created` 상태이며 안정성 Gate를 증명하지 못함
- 잘못 만든 acceptance overlay 파일은 즉시 제거했고 별도 project container/network/volume은
  생성되지 않았음을 확인함

현재 환경의 추가 recreate는 사용자의 금지 범위이므로 원래 port/Actions 상태를 임의로
복구하지 않았다. 당시에는 이 충돌 자체와 Actions 안정성 미증명 때문에 Phase 2B를
`BLOCKED_ENV`, production 결정을 `HOLD`로 기록했다. 이후 현재 stack을 더 변경하지 않고
완전 격리된 project에서 위 재개 조건을 충족했다.

## 재개 조건 충족 확인

1. 현재 DataHub GMS/Actions의 controlled recreate와 host port 복구에 대한 별도 승인, 또는
   `.env`의 project name을 명령행 `-p answervice-phase2b-datahub`로 확실히 덮어쓴 완전 격리
   환경 준비
2. 같은 release metadata를 격리 환경에 candidate namespace로 발행
3. Actions restart 0과 bounded 안정 관측
4. active release Dataset/Glossary search coverage 및 checksum-bound freshness receipt 100%
5. `datahub_lexical` default 전환과 `lexical` rollback rehearsal

다섯 조건을 모두 충족했다. 따라서 `PROMOTE` 판정과 Phase 3 진입을 허용한다. 현재 실행
stack의 실제 cutover는 이 Gate에 포함하지 않으며 별도 배포 작업 전까지 동결 상태를 유지한다.
