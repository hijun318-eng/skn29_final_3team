# DataHub Core Phase 4 RuntimeCatalogProjection Gate

## 판정

- 상태: `PASS`
- 판정일: 2026-08-22
- 마지막 완료 Phase: Phase 4 `PASS`
- 다음 Phase: Phase 5 진입 허용
- 격리 project: `answervice-phase2b-datahub`
- 기존 `answervice` stack: mutation 명령 미실행

승인받은 stale 임시 service account 1개를 exact target에서 삭제한 뒤 service account와 token이
각각 0개임을 확인했다. 새 빈 격리 DB에 migration head를 적용하고 Phase 4 전체 runner를 한 번의
same-release 실행으로 완료했다. membership/canonical equality, activation CAS, canary, rollback,
cold/warm readiness와 Report receipt 검증이 모두 통과했으므로 Gate를 `PASS`로 판정한다.

## 구현 완료 범위

- DataHub full scroll/read-back을 질문 runtime과 분리한 out-of-band compiler
- native-priority/legacy-shadow source-selection manifest
- immutable `RuntimeCatalogProjection.v1`, Trino fingerprint, projection checksum 검증
- PostgreSQL candidate repository, active pointer, activation receipt, CAS와 rollback
- production runtime의 active projection 전용 read 경로와 full-read 금지 경계
- full read 실패 시 sibling task cancel/await로 token cleanup race 차단
- Conversation·Turn·Context·Analysis Run·Artifact·View receipt 경로
- Report definition/run receipt columns, immutable trigger, product binding과 replay Context 전파
- product manifest의 `semantic_release_id`를 runtime `catalog_version`과 동일하게 결속
- Alembic head `20260822_32`

## 격리·충돌 증거

Phase 4 DB 생성 직전 exact typed identity 비교 결과는 다음과 같았다.

- 기존 `answervice`: container 23, network 2, volume 13
- 계획한 Phase 4 추가 resource: container 1, volume 1, 기존 격리 network 1 사용
- 기존/계획 identity 교집합: 0
- host port `55440`: 생성 전 미사용
- 실제 생성 대상:
  - container `answervice-phase2b-datahub-phase4-app-db`
  - volume `answervice-phase2b-datahub_phase4-app-postgres-data`
  - network `answervice-phase2b-datahub_datahub-network`
- 명령은 항상 `docker compose -p answervice-phase2b-datahub`로 실행
- `--remove-orphans` 미사용

격리 DB는 최초 생성 뒤 `20260822_31` upgrade → `20260822_30` downgrade → head replay와
전체 migration compatibility 9건을 통과했다. Docker 복구 후 같은 격리 DB에서
`20260822_31 → 20260822_32 → 20260822_31 → head` replay를 통과했고, Report receipt column
6개의 생성·제거·재생성을 각 revision에서 read-back했다.

## Docker 복구·용량 재검사

- 기존 `answervice`: container 23, network 2, volume 13, typed identity 총 38
- 격리 target: container 7, network 1, volume 4, typed identity 총 12
- 기존/격리 exact typed intersection: 0
- Windows `C:`: 475.91GB 중 58.98GB 여유(12.4%)
- Docker 내부 filesystem: 1007GB 중 약 900GB 여유(사용률 6%)
- Docker VHDX 실제 크기: 81.88GB
- 격리 고유 volume: 약 1.58GB
- 격리 GMS writable layer 1.35GB의 대부분은 `/tmp/datahub/logs/gms`의 bounded debug log
- Docker log의 `ENOSPC`, `no space left on device`, OOM 기록: 0
- 실행 container memory: Docker 한도 15.44GiB 중 약 12.4GiB
- Windows 물리 memory: 31.64GB 중 약 5.05GB 여유

확인된 직접 장애는 Docker API proxy와 Linux VM 사이의 `no route to host`였고, disk-full은
원인으로 확인되지 않았다. 두 DataHub stack 동시 실행에 따른 memory·I/O 압박은 가능한
기여 요인이지만 OOM 증거가 없어 확정 원인으로 기록하지 않는다.

## Host 검증 증거

서로 겹치는 test 집합은 합산하지 않는다.

- Report domain/API/repository/conversation/migration:
  `48 passed, 10 skipped, 11 subtests passed`
- Report 전체 Python 회귀:
  `62 passed, 4 skipped, 47 subtests passed`
- Analysis persistence/runtime/report receipt 회귀:
  `49 passed, 2 skipped`
- Phase 4 관련 Python `compileall`: 통과
- Alembic `20260822_31 → 20260822_32` offline upgrade/downgrade SQL 생성: 통과
- 격리 PostgreSQL migration compatibility·Context receipt·Report execution: `20 passed`
- Phase 4 Windows event-loop entrypoint·Report migration/registration: `22 passed, 2 skipped,
  11 subtests passed`
- `git diff --check`: 통과

Skip은 disposable PostgreSQL 환경 변수가 필요한 integration test다. 통과로 간주하지 않는다.

## 과거 환경 차단 증거

동일 시점의 bounded read-only probe 결과:

- Docker Engine `/_ping`, containers, networks API: timeout 또는 HTTP 500
- Docker API proxy → Linux VM `192.168.65.7:2376`: `no route to host`
- containerd: 모든 종류의 container health check 시작 timeout
- 격리 PostgreSQL `127.0.0.1:55440`: TCP accept 후 3초 connection timeout
- 격리 DataHub `127.0.0.1:38081/health`: TCP accept 후 3초 HTTP timeout

Docker Desktop process 자체는 Windows에서 `Responding=True`지만 Linux VM의 containerd/API와
컨테이너 workload가 응답하지 않는다. Docker Desktop 또는 VM restart는 기존 `answervice`
stack까지 재시작할 수 있으므로 당시에는 실행하지 않았다. 사용자가 직접 Docker Desktop을
재시작한 뒤 이 환경 차단은 해소됐다.

## Phase 4 live Gate 증거

- 상태: `PHASE4_RUNTIME_CATALOG_PROJECTION_PASSED`
- catalog/canonical checksum: 승인값과 일치
- native/legacy membership equality: `100%`
- canonical equality: `100%`
- asset/Metric membership: 51/14
- native Metric: 10
- candidate canary: readiness 3단계 `ready`, active pointer 불변
- activation receipt: `ACTIVATE 0→1`, `ACTIVATE 1→2`, `ROLLBACK 2→3`, `ACTIVATE 3→4`
- final active: generation 4, `NATIVE_PRIORITY` candidate
- stale CAS rejection: 1
- release pair mismatch rejection: 1
- mixed-release block/execution/pointer: 1/0/0
- runtime full-scroll attempt: 0, bounded Search request: 3
- immutable projection/activation/binding mutation rejection: 3
- 7종 product binding: 7
- Report definition/run binding: 1/1
- Report receipt mutation rejection: 2, run status `success`
- cold/warm/rollback readiness: 모두 3단계 `ready`
- temporary read token revoked/service account deleted: true/true

독립 read-back은 다음을 확인했다.

- `Phase 2B Acceptance` 임시 service account: 0
- target bootstrap Catalog Reader/Publisher service account: 2(정리 대상 아님)
- current access-token entity/aspect: 0, runner가 만든 exact token revoke: true
- 기존/격리 exact typed resource: 38/12, intersection 0
- Alembic revision: `20260822_32`
- projection/active pointer/activation receipt: 2/1/4
- manifest/binding: 2/9
- Report definition version/run: 1/1

원문 token과 system credential은 출력하거나 파일에 기록하지 않았다.

## Phase 5 인계 조건

Phase 5는 generation 4의 active `NATIVE_PRIORITY` projection과 같은 product release receipt를
고정 입력으로 사용한다. current DataHub·DB·Trino는 계속 read-only로 유지하고, 다음 Gate가
요구하는 변경과 검증도 격리 project 안에서만 수행한다.
