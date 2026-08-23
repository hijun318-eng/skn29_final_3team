# DataHub Core Phase 0B compatibility·evidence Gate

## 1. 결론과 범위

| 항목 | 판정 |
|---|---|
| 기준 시각 | 2026-08-22 KST |
| 활성 범위 | `Phase 0B` 공통 compatibility·evidence 계약 |
| Phase 0B Gate | `PASS` |
| 제품 기능 판정 | `READY_TO_VERIFY`가 아님 — 내부 계약과 migration 호환성만 검증 |
| 다음 Phase | 사용자 일괄 승인에 따라 `Phase 1` 자동 진입 |

Phase 0B는 공개 HTTP/MCP 결과를 변경하지 않고 내부 capability 봉투, evidence authority,
제품 release manifest와 7종 domain object binding을 추가했다. 현재 실행 중인 Backend,
Frontend, App DB, DataHub, Trino에는 mutation을 수행하지 않았다.

## 2. 구현 계약

### Versioned capability schema

`app/backend/app/capability_contracts.py`에 다음 불변 내부 계약을 추가했다.

- `CapabilityInvocation.v1`: request/conversation/turn, capability+version, typed payload,
  effective subject, permission snapshot, product/capability release vector, source Turn/Artifact 참조,
  deadline, token/tool/query/time budget, idempotency key와 서버 canonical input hash
- `CapabilityResult.v1`: `SUCCEEDED | PARTIAL | BLOCKED | FAILED | CANCELLED`, typed reason,
  clarification, coverage, warning, Artifact/Evidence 참조, release·permission receipt
- `EvidenceRef.v1`: `OBSERVED_DATA | DOCUMENTED_CONTEXT | MODEL_PREDICTION |
  DERIVED_INFERENCE` authority와 checksum이 있는 객체 참조만 전달
- `ProductReleaseEvidenceManifest.v1`: source commit, dirty patch digest, image digest, Alembic
  chain, model manifest, catalog/projection과 data/semantic/prompt/policy/runtime release vector를
  canonical SHA-256으로 봉인

Capability 모델은 공개 API DTO에 연결하지 않았다. 따라서 이 Phase에서 기존 OpenAPI 응답에
새 필드를 강제하거나 기존 client schema를 변경하지 않는다.

### 영속화 계약

Alembic `20260822_29`는 기존 도메인 테이블을 수정하지 않는 additive migration이다.

| Table | 책임 |
|---|---|
| `governance.product_release_manifests` | typed manifest와 각 receipt 축을 함께 저장하고 JSON/column 일치를 검사 |
| `governance.product_release_bindings` | `CONVERSATION`, `TURN`, `CONTEXT`, `RUN`, `ARTIFACT`, `VIEW`, `REPORT`를 하나의 product/permission/semantic/capability receipt에 고정 |

두 table은 `UPDATE`와 `DELETE`를 trigger로 거부한다. `(object_kind, object_id)`는 unique이므로
한 객체를 나중 release로 조용히 재해석할 수 없다. runtime role은 `SELECT, INSERT`만 가진다.

Conversation·Turn·View가 현재 수기 DDL에 포함된 상태에서 이번 migration이 해당 table을 직접
변경하면 빈 DB upgrade와 과거 설치 호환성이 깨진다. 따라서 Phase 0B는 정규화된 binding을
권위 계약으로 추가했고, Phase 1이 수기 DDL을 Alembic 소유로 전환하면서 Conversation·Turn·Run·
Artifact 직접 전파와 FK/transaction 경계를 닫는다.

## 3. 공개 identifier non-regression

다음 기존 호환 identifier와 wire schema를 literal contract test로 고정했다.

- MCP protocol `2026-07-28`
- Tool code `analysis.get_run`, registry version `1.0.0`과 결합한 공개 식별자
  `analysis.get_run@1.0.0`
- `request_id`만 허용하는 input schema
- `request_id`, `status`, `trace_id`, `query_id`, `artifact_id`를 요구하는 기존 output schema

기존 OpenAPI fixture/schema test를 포함한 전체 Backend suite를 같이 실행해 공개 API 결과가
회귀하지 않았음을 확인했다. 이는 현재 host source의 contract 증거이며 배포된 live image의
same-release 인증은 아니다.

## 4. 격리 인수환경과 검증

`infrastructure/acceptance/phase-gates.compose.yml`은 현재 Compose와 이름·network·volume·port가
분리된 `answervice-phase-gates` PostgreSQL만 실행한다. host bind는
`127.0.0.1:55439`이고 synthetic trust DB이며 외부 credential을 저장하지 않는다.

| 구분 | 검증 | 결과 |
|---|---|---|
| Static | `docker compose ... config --quiet` | `PASS` |
| Unit/contract | capability/evidence, runtime release, MCP, OpenAPI, migration graph | `23 passed`, OpenAPI subtest `9 passed` |
| Backend regression | `pytest tests/backend -q` | `512 passed`, `30 skipped`, subtest `109 passed` |
| Isolated DB | 전체 migration compatibility suite | exit `0`, 8개 test 수집·실행 |
| Isolated DB | 빈 DB `upgrade head` | head `20260822_29` |
| Isolated DB | 7종 binding insert와 immutable update negative | 7건 저장, mutation 거부 |
| Isolated DB | `downgrade 20260820_28` 후 `upgrade head` replay | `PASS` |
| Isolation | Compose health/port/label | 전용 container healthy, current stack resource와 이름 충돌 없음 |
| Whitespace | `git diff --check` | `PASS` |

`30 skipped`는 외부/live 환경 변수가 없는 test다. 이를 성공 evidence에 합산하지 않았다.
Migration Gate는 승인된 격리 DB에서 별도로 실행했다.

## 5. Gate 체크

| Gate 조건 | 결과 | 근거 |
|---|---|---|
| `CapabilityInvocation/Result/EvidenceRef` versioned schema | `PASS` | typed/frozen Pydantic contract와 negative test |
| release receipt 7종 객체 영속 계약 | `PASS` | additive binding table, unique pin, immutable trigger |
| source/dirty/image/migration/model/catalog manifest | `PASS` | typed manifest, canonical hash, tamper negative test |
| 기존 API 결과 non-regression | `PASS` | OpenAPI fixture + 전체 Backend regression |
| `analysis.get_run@1.0.0` non-regression | `PASS` | literal protocol/name/input/output contract test |
| schema upgrade/rollback/replay | `PASS` | 격리 PostgreSQL 실 migration |
| 기존 dirty 변경 보존 | `PASS` | 관련 파일만 additive/minimal patch, reset/cleanup 없음 |
| 현재 실행환경 무변경 | `PASS` | 전용 project만 생성, current stack은 read-only 상태 확인만 수행 |

## 6. 남은 경계와 rollback

- 이 Phase는 영속 계약을 만든 것이며 실제 Conversation 요청이 receipt를 전파한다고 인증하지
  않는다. 그 실행 경로와 stale state는 Phase 1 Gate 대상이다.
- manifest는 release 후보를 봉인할 형식이다. 현재 dirty host와 기존 deployed image가 같은
  product release라는 뜻이 아니다. 실제 same-release manifest는 Phase 10에서 생성한다.
- rollback은 격리 DB에서 `20260820_28`까지 검증했다. 현재 App DB에는 migration을 적용하지 않았다.
- 전용 Compose resource는 후속 Phase Gate에 재사용하고 Phase 10 종료 또는 안전 중단 시
  이번 작업이 만든 project/network/volume만 식별해 정리한다.
