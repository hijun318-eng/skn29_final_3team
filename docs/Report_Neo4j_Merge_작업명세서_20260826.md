# Neo4j Merge 작업명세서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 검증된 Neo4j 패키지를 `jaehong`에서 통합 브랜치로 충돌을 최소화해 반영하는 절차를 정의한다. |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-26 16:24 |
| 작성·수정 | Codex |

## 권장 병합 방식

권장안은 `jaehong` 브랜치 전체 merge가 아니라 이번 Neo4j 커밋 1개만 대상 브랜치에 `cherry-pick`하는 방식이다.

2026-08-26 확인 시점에 `origin/dev`와 기존 `origin/jaehong`은 공통 기준점 이후 각각 19개와 39개 커밋이 있고, `jaehong` 쪽 비교 경로가 405개다. 브랜치 전체를 병합하면 Neo4j와 관계없는 변경까지 들어갈 수 있다.

## 병합 대상

| 항목 | 값 |
|---|---|
| Source | `origin/jaehong` |
| 기본 Target | `origin/dev` |
| Neo4j 적용 전 Source 기준 SHA | `53b870175f7c452884660fd1bb7213da914882eb` |
| 대상 커밋 제목 | `feat(neo4j): 선택형 그래프 투영과 자동 적재 이식` |
| 결과 근거 | [Neo4j 이식 검증 결과보고서](Report_Neo4j_이식_검증_결과_20260826.md) |

## 허용 변경 범위

대상 커밋에는 아래 신규 파일만 있어야 한다.

- `app/backend/app/ports/graph_candidates.py`
- `app/backend/app/adapters/neo4j_*.py`
- `app/backend/app/services/neo4j_projection_loader.py`
- `app/backend/scripts/sync_neo4j_projection.py`
- `app/backend/requirements-neo4j.txt`
- `infrastructure/neo4j/` 아래 4개 구성 파일과 manifest
- `tests/backend/test_neo4j_*.py`
- `tests/integration/test_neo4j_*.py`
- 이 결과보고서와 Merge 작업명세서

root Compose, Backend 기본 requirements, 기존 API, migration, Frontend 파일은 변경 대상이 아니다.

## 사전 확인

1. 대상 저장소 작업 트리가 깨끗한지 확인한다.
2. 원격 Branch를 최신 상태로 받는다.
3. 제목이 일치하는 Neo4j 커밋을 찾는다.
4. 커밋의 파일 목록이 허용 범위와 일치하는지 확인한다.

```powershell
git status --short
git fetch origin --prune
git log origin/jaehong --oneline -n 20
git show --stat --oneline <neo4j-commit-sha>
git show --name-only --format= <neo4j-commit-sha>
```

작업 트리가 더럽거나 허용 범위 밖 파일이 있으면 병합하지 않는다.

## 적용 절차

```powershell
git switch dev
git pull --ff-only origin dev
git switch -c codex/merge-jaehong-neo4j-20260826
git cherry-pick <neo4j-commit-sha>
```

충돌이 없으면 검증 단계로 이동한다. 충돌이 발생하면 다음 원칙을 적용한다.

- 전체 디렉터리에 `ours` 또는 `theirs`를 일괄 적용하지 않는다.
- 같은 경로에 이미 Neo4j 코드가 있으면 파일별 책임과 SHA-256을 비교한다.
- 기존 runtime interface가 달라졌다면 현재 Target 계약에 맞게 adapter 경계만 조정한다.
- root Compose나 Backend 기본 실행 경로에 Neo4j를 강제로 연결하지 않는다.
- 충돌 원인이 Neo4j 범위를 벗어나면 `git cherry-pick --abort` 후 담당자 판단을 받는다.

## 병합 후 필수 검증

### 1. 변경 범위와 공백

```powershell
git diff --check origin/dev...HEAD
git diff --name-only origin/dev...HEAD
```

### 2. 패키지 manifest

`infrastructure/neo4j/package.manifest.sha256`의 15개 파일 해시가 실제 파일과 모두 같아야 한다.

### 3. 단위 및 Compose 계약

```powershell
docker build -f infrastructure/neo4j/Dockerfile.projector `
  -t answervice-neo4j-projector:merge-verify .
docker run --rm --entrypoint python --workdir /workspace `
  -v "${PWD}\tests:/workspace/tests:ro" `
  answervice-neo4j-projector:merge-verify `
  -m unittest tests.backend.test_neo4j_projection_loader `
  tests.backend.test_neo4j_graph_package
python -c "from tests.integration.test_neo4j_projection_compose import test_neo4j_profile_runs_one_shot_projector_after_health as a, test_neo4j_env_example_documents_automatic_projection_inputs as b; a(); b()"
```

기대 결과는 단위 테스트 11개와 Compose 계약 테스트 2개 성공이다.

### 4. 실제 자동 적재

외부 secret과 격리된 Neo4j volume을 사용해 다음 항목을 확인한다.

- projector 종료 코드 `0`
- `NEO4J_PROJECTION_SYNC=PASS`
- 활성 projection의 예상 엔터티·관계 수 일치
- 인덱스 3개 모두 `ONLINE`
- 동일 projector 재실행 뒤 노드·관계 수와 그래프 체크섬 불변
- 검증용 컨테이너·네트워크·볼륨 정리

### 5. Target 전체 회귀

Target 브랜치의 `AGENTS.md`와 CI가 요구하는 Backend 전체 테스트, Frontend 테스트·빌드, OpenAPI, architecture invariant, repository integrity와 모든 Compose config를 실행한다. 하나라도 실패하면 merge하지 않는다.

## 완료 조건

- 대상 커밋 파일이 허용 범위와 일치한다.
- package manifest, 단위 테스트, Compose 계약과 실제 자동 적재가 모두 통과한다.
- 기존 서비스는 Neo4j 설정 없이 정상 동작한다.
- Target 전체 CI가 통과한다.
- 검증 결과와 최종 Target SHA를 PR 또는 merge 기록에 남긴다.

## Rollback

1. 문제가 배포 전에 발견되면 통합 브랜치를 삭제하고 Target을 변경하지 않는다.
2. 병합 후 발견되면 Neo4j 커밋을 `git revert`한다.
3. 실행 중인 선택형 profile만 중지한다.
4. App DB와 DataHub는 되돌리거나 Neo4j 데이터로 덮어쓰지 않는다.
5. Neo4j volume 삭제가 필요하면 정확한 Compose project와 volume 이름을 확인한 뒤 별도 승인으로 처리한다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-08-26 16:24 | 브랜치 전체 merge 위험을 반영해 단일 검증 커밋 cherry-pick 절차와 Gate 작성 |
