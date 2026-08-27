# Neo4j 패키지 Merge 작업명세서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 선택형 Neo4j package를 충돌 없이 검증·commit·Merge하기 위한 실행 명세 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-27 09:30 |
| 작성·수정 | OpenAI Codex |
| Source branch | `jaehong_neo4j` |
| 기준 base commit | `0791ef9ecda0c24521043354b4517a90dc194999` |
| 원격 대상 | `origin/jaehong_neo4j` |
| 현재 판정 | 선택형 package Merge 범위이며 제품 runtime 배선은 제외 |

## 1. Merge 결론

권장안은 Neo4j optional package만 하나의 독립 commit으로 올리는 것이다. Root Compose와
기존 FastAPI dependency injection은 건드리지 않는다. 제품 후보 탐색 연결은 별도 요구사항,
권한 Gate와 E2E 검증이 준비된 뒤 두 번째 작업으로 진행한다.

| 안 | 범위 | 판정 |
|---|---|---|
| 1안 | 선택형 package·자동 적재·테스트·문서만 Merge | 권장 |
| 2안 | 로컬에만 보존하고 원격 반영 보류 | 시연만 필요할 때 가능 |
| 3안 | package와 제품 API 배선을 한 번에 Merge | 회귀 범위가 커서 비권장 |

## 2. 현재 기준선

| 항목 | 상태 |
|---|---|
| Base `jaehong` | `0791ef9ecda0c24521043354b4517a90dc194999` |
| Target branch | `jaehong_neo4j` |
| Neo4j package | 16개 파일 allowlist |
| 제품 runtime wiring | 없음 |
| Root Compose include | 없음 |
| 기본 설정 | `NEO4J_GRAPH_ENABLED=false` |
| 최근 격리 검증 | node 66, relation 15, index 3/3 `ONLINE`, 멱등 재적재 PASS |

새 commit이나 active release로 기준이 바뀌면 이 표의 수치를 그대로 승계하지 않고 다시
검증한다.

## 3. Package allowlist

다음 경로만 Neo4j package commit에 포함한다.

```text
app/backend/app/ports/graph_candidates.py
app/backend/app/adapters/neo4j_graph.py
app/backend/app/adapters/neo4j_graph_queries.py
app/backend/app/adapters/neo4j_graph_settings.py
app/backend/app/adapters/neo4j_projection.py
app/backend/app/services/neo4j_projection_loader.py
app/backend/scripts/sync_neo4j_projection.py
app/backend/requirements-neo4j.txt
infrastructure/neo4j/.env.example
infrastructure/neo4j/compose.fragment.yml
infrastructure/neo4j/Dockerfile.projector
infrastructure/neo4j/package.manifest.sha256
tests/backend/test_neo4j_graph_package.py
tests/backend/test_neo4j_projection_loader.py
tests/integration/test_neo4j_graph_live.py
tests/integration/test_neo4j_projection_compose.py
docs/neo4j/README.md
docs/neo4j/MERGE_GUIDE.md
docs/README.md
```

`package.manifest.sha256`는 자신을 제외한 15개 package 파일을 고정한다. 문서 파일은
manifest 대상이 아니다.

## 4. 이번 Merge에서 제외할 경로

- Root `compose.yml`
- `app/backend/app/api/analysis_router_runtime.py`
- 기존 DataHub·PostgreSQL·Trino adapter
- Frontend와 사용자용 Graph 화면
- `docs/product/` 상태 변경
- 실제 `.env`, 비밀번호, DB URL, 인증서와 raw 실행 로그
- Neo4j와 관계없는 사용자 변경

제품 기준 문서에는 Neo4j가 여전히 조건부 기능으로 기록돼 있다. 이 package Merge만으로
제품 도입 상태를 `VERIFIED`로 변경하지 않는다.

## 5. 충돌 최소화 절차

### 5.1 사전 확인

```powershell
git status --short --branch
git fetch origin
git rev-parse jaehong_neo4j
git rev-parse origin/jaehong
git diff --name-only origin/jaehong...jaehong_neo4j
```

1. Local·remote SHA 차이가 있으면 먼저 원인을 확인한다.
2. 다른 사용자 변경이 있으면 stash·reset·임의 commit하지 않는다.
3. `git add .` 대신 3절 allowlist만 명시적으로 stage한다.
4. Merge 직전 manifest를 현재 파일로 다시 검증한다.

### 5.2 기본 검증

```powershell
python -m compileall -q `
  app/backend/app/ports/graph_candidates.py `
  app/backend/app/adapters/neo4j_graph.py `
  app/backend/app/adapters/neo4j_graph_queries.py `
  app/backend/app/adapters/neo4j_graph_settings.py `
  app/backend/app/adapters/neo4j_projection.py `
  app/backend/app/services/neo4j_projection_loader.py `
  app/backend/scripts/sync_neo4j_projection.py

python -m pytest -p no:cacheprovider `
  tests/backend/test_neo4j_graph_package.py `
  tests/backend/test_neo4j_projection_loader.py `
  tests/integration/test_neo4j_projection_compose.py -q

docker compose `
  --env-file <저장소_밖의_neo4j_env> `
  -f infrastructure/neo4j/compose.fragment.yml `
  --profile neo4j config --quiet

git diff --check
```

### 5.3 Live 검증

실제 Neo4j와 유효한 read 전용 App DB 연결을 사용해 다음을 확인한다.

1. Neo4j health check가 통과한다.
2. projector 종료 코드가 0이다.
3. 로그에 product release, source checksum, Graph checksum과 건수가 출력된다.
4. index 3개가 모두 `ONLINE`이다.
5. read-back node·relation 건수가 projector 결과와 같다.
6. 같은 projection을 다시 실행해도 중복이 생기지 않는다.
7. 실제 secret과 DB URL이 Git diff와 문서에 포함되지 않는다.

Live dependency가 없어 test가 skip되면 PASS 건수에 포함하지 않는다.

### 5.4 Stage와 검토

```powershell
git add -- <3절_allowlist의_각_경로>
git diff --cached --name-status
git diff --cached --check
```

staged 목록이 allowlist와 다르면 commit하지 않는다. commit·push·`dev` Merge는 사용자의
명시적 요청이 있을 때만 실행한다.

## 6. Merge Gate

| ID | 수용 기준 |
|---|---|
| N4J-M01 | staged 경로가 3절 allowlist와 정확히 일치 |
| N4J-M02 | manifest 15개 항목 checksum 일치 |
| N4J-M03 | Python compile과 대상 unit·Compose test 통과 |
| N4J-M04 | 기본 OFF에서 기존 Backend 시작·분석 경로 불변 |
| N4J-M05 | 별도 profile에서 live 적재·read-back·멱등성 통과 |
| N4J-M06 | node·relation이 같은 release와 checksum으로 결속 |
| N4J-M07 | index 3개 `ONLINE` |
| N4J-M08 | secret·개인정보·raw row가 diff와 Graph에 없음 |
| N4J-M09 | 제품 API 미연결 상태를 문서와 코드가 동일하게 표현 |
| N4J-M10 | 전체 저장소 Gate에서 신규 회귀 없음 |

## 7. Rollback

### 7.1 운영 profile

Neo4j를 중지할 때는 별도 Compose project만 내리고 volume은 보존한다.

```powershell
docker compose `
  --env-file <저장소_밖의_neo4j_env> `
  -f infrastructure/neo4j/compose.fragment.yml `
  --profile neo4j down
```

`down -v`는 사용하지 않는다. volume 삭제는 정확한 대상과 복구 가능성을 확인한 뒤 별도
승인을 받아야 한다. 현재 제품 요청 경로가 Neo4j를 사용하지 않으므로 profile 중지는 기존
서비스 기능 rollback을 요구하지 않는다.

### 7.2 Git

- commit 전: staged allowlist만 `git restore --staged -- <경로>`로 해제한다.
- 공유되지 않은 commit도 사용자 파일을 보존해야 하면 reset보다 새 보존 branch를 우선한다.
- 원격에 공유된 commit은 이력을 다시 쓰지 않고 `git revert <commit>`을 사용한다.
- `git reset --hard`, force push와 다른 사용자 변경 삭제는 금지한다.

## 8. 제품 연결을 별도 작업으로 두는 이유

Graph 후보를 FastAPI 분석 흐름에 연결하면 서비스 결과가 달라질 수 있다. 그 작업에는 다음
조건이 추가로 필요하다.

- Graph 결과에 기존 entitlement와 active release membership 재적용
- 최대 hop, 결과 수, timeout을 제한한 고정 query
- stale checksum 거부
- 장애·timeout 시 명시적 fallback 또는 실패 정책
- request별 driver 생성 금지와 process lifecycle 관리
- fallback 사유, latency, release·receipt 관측성
- OFF·ON·장애·권한 거부·stale release 서비스 E2E

이 조건이 승인되기 전까지 Neo4j는 독립적인 검증·탐색 package로 유지한다.

## 9. 완료 정의

1. 3절 allowlist만 commit됐다.
2. 6절 Gate가 모두 통과했다.
3. 기본 서비스 흐름과 Root Compose가 변경되지 않았다.
4. 문서가 실제 commit과 live receipt를 정확히 가리킨다.
5. 팀 관리자가 `dev` 통합과 원격 push를 승인했다.

## 변경 내역

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.0 | 2026-08-27 | 과거 패키징·향후 작업 명세를 `jaehong_neo4j` 독립 package 기준으로 통합 |
