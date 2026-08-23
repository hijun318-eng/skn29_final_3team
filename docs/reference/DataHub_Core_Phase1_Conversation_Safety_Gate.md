# DataHub Core Phase 1 — Conversation Safety Foundation Gate

- 판정일: 2026-08-22 KST
- 판정: **PASS — isolated candidate**
- 대상: 현재 host source의 Phase 1 변경과 전용 `answervice-phase-gates` PostgreSQL
- 비대상: 현재 실행 중 Backend·Frontend·DB·DataHub·Trino, 기존 volume/index/active pointer
- 선행 Gate: Phase 0B `PASS`

이 판정은 현재 실행 stack에 배포됐다는 뜻이 아니다. 기존 stack은 read-only 상태 확인만 했고,
migration·fault injection·reconcile은 `127.0.0.1:55439`의 작업 전용 PostgreSQL에서만 수행했다.

## 1. 구현 계약

### Admission과 불변성

- `idempotency_key`와 명시적 `expected_head_turn_id`를 command API의 필수 입력으로 만들었다.
- server canonical hash는 path Conversation, effective subject, permission snapshot, product/semantic
  release, CAS head, payload, 시간·계약 version을 포함한다.
- 저장 hash를 먼저 비교한 뒤에만 replay하며 같은 key의 다른 payload는 실행 전에 거부한다.
- Turn, command admission, ViewSpec은 DB trigger로 불변이며 command terminal 전이는 단방향이다.

### 원자적 terminal commit과 release receipt

- Conversation ANALYSIS 성공은 Run terminal/evidence, Artifact, Turn, release binding, head,
  command terminal, lease 해제를 하나의 PostgreSQL transaction으로 commit한다.
- 실패도 Run terminal, 실패 Turn, head, command terminal, lease 해제를 같은 transaction으로 닫는다.
- Conversation 생성 시 product/semantic release와 permission snapshot을 pin하고, 신규
  Conversation 경로의 Turn·Run·Artifact로 동일 receipt를 전파한다.
- path `conversation_id`와 server `RequestContext.conversation_id`가 다르면 admission 전에 거부한다.

### Durable query recovery

- Trino 첫 응답의 same-origin, same-query `nextUri`를 SQL 원문 없이 `RUNNING` query evidence로
  먼저 저장한다. 저장 실패 시 query를 취소하고 다음 page를 읽지 않는다.
- pagination heartbeat가 최신 cancel URI를 갱신하고 terminal event가 URI를 제거한다.
- process-local query map이 없는 재시작 뒤에도 DB의 query ID와 URI가 일치할 때만 coordinator
  `DELETE`를 호출한다. 취소가 terminal로 확인되지 않으면 DB command/run을 성공처럼 닫지 않는다.
- stale worker는 bounded batch·poll·timeout 설정을 사용하며 orphan query 취소 뒤
  query→Run→recovery Turn→command→lease를 멱등 terminalize한다.

## 2. Gate 결과

| Gate 조건 | 결과 | 증거 |
|---|---:|---|
| stale command/run/lease/query nonterminal 0 | PASS | 격리 reconcile 후 합계 0, 두 번째 실행 변경 0 |
| crash-point fault injection | PASS | Run terminal write 직후 예외를 주입해 Run·Turn·head·command·lease 전체 rollback 확인 |
| duplicate query/Turn 0 | PASS | 같은 command의 다른 Trino query 제출 거부, 같은 key replay는 기존 Turn 반환 |
| path와 `RequestContext.conversation_id` 일치 | PASS | 불일치 입력은 query/Turn 생성 전 거부 |
| Turn↔Run↔Artifact lineage 100% | PASS | 성공 acceptance row의 request/artifact FK와 head를 exact read-back |
| permission/release receipt 전파 | PASS | Conversation·Turn·Run·Artifact 및 4종 release binding exact read-back |
| release 없는 신규 Artifact 0 | PASS | Phase 1 대상인 신규 Conversation ANALYSIS acceptance에서 null 0; legacy/direct API 전역 수렴은 Phase 4 Gate 대상 |
| Alembic upgrade/rollback/replay | PASS | fresh rollback은 Phase 1 객체·column 제거, pre-existing 수기 객체·column 보존, 재-upgrade 성공 |

마지막 항목의 범위는 Phase 1 `Conversation Safety Foundation`이다. direct Analysis, View, Report를
포함한 제품 전 객체 receipt 수렴과 RuntimeCatalogProjection checksum 전파는 전략상 Phase 4·7에서
완료한다. 이를 Phase 1에서 완료했다고 확대 해석하지 않는다.

## 3. 실행 검증

| 검증 | 결과 |
|---|---:|
| Backend 전체, 격리 PostgreSQL 포함 | `530 passed, 21 skipped, 109 subtests passed` |
| Conversation orchestrator + async DataPlatform | `41 passed, 4 subtests passed` |
| Conversation safety 격리 integration | `3 passed` |
| Alembic compatibility 격리 suite | `9 passed` |
| Frontend unit | `21 passed` |
| Frontend production build | PASS |
| OpenAPI export/check | PASS |

skip 21건은 환경 의존 live/native probe이며 성공으로 계산하지 않았다. 이번 Gate의 DB acceptance는
skip 없이 별도 실행했다. `.pytest_cache` 쓰기 권한 warning은 test 결과와 무관하며 저장소 파일을
우회 삭제하지 않았다.

## 4. 주요 변경

- Alembic: `20260822_30_conversation_safety_foundation.py`
- 계약/권한: `conversation_contracts.py`, `contract_core.py`, `authorization.py`
- 영속화: `conversation_repository.py`, `analysis_run_start_repository.py`,
  `analysis_evidence_repository.py`
- query lifecycle: `query_execution.py`, `trino_async.py`, `governed_data_platform.py`
- 실행/복구: `conversation/orchestrator.py`, `conversation/reconciler.py`, app lifespan/readiness
- API/UI: typed command OpenAPI, Frontend per-action idempotency key와 CAS retry
- 검증: migration compatibility, orchestrator, async client, 격리 transaction/fault-injection tests

## 5. 남은 경계

- 현재 실행 stack에는 migration 30이나 새 worker를 적용하지 않았다.
- 현재 live DB의 과거 stale row를 변경하지 않았다. candidate 배포 전에는 별도 backup·deployment
  승인과 live migration rehearsal이 필요하다.
- Presentation focus와 Report revision까지 포함한 전체 terminal transaction, Golden Dialogue,
  browser same-release 증거는 Phase 7·10 대상이다.
- Phase 2는 이 PASS를 선행조건으로 삼아 격리/shadow Search에서만 시작한다.
