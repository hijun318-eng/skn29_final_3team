# Neo4j 이식 검증 결과보고서

| 항목 | 내용 |
|---|---|
| 문서 설명 | `jaehong` 브랜치에 이식한 선택형 Neo4j 그래프 투영 기능과 검증 결과를 간단히 설명한다. |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-26 16:24 |
| 작성·수정 | Codex |

## 한 줄 결론

Neo4j 기능은 기존 서비스에서 분리된 선택형 구성으로 이식됐고, 실제 Neo4j에서 엔터티 66개와 관계 15개의 자동 적재 및 중복 없는 재적재까지 확인했다.

## 적용 범위

- 승인된 `RuntimeCatalogProjection`을 읽어 Neo4j 노드와 관계로 변환한다.
- 노드와 관계를 항상 같은 순서로 정렬해 같은 입력에서 같은 체크섬을 만든다.
- Neo4j 스키마를 준비하고 활성 projection을 한 번 적재하는 projector를 제공한다.
- 브라우저와 Bolt 포트는 기본적으로 `127.0.0.1`에만 공개한다.
- 단위 테스트, Compose 계약 테스트와 실제 Neo4j 연동 테스트를 포함한다.
- 패키지 파일 15개의 SHA-256 manifest를 포함한다.

## 검증 결과

| 검증 항목 | 결과 | 확인 내용 |
|---|---|---|
| 원격 기준선 | PASS | 로컬 `jaehong` 시작점과 `origin/jaehong`이 `53b870175f7c452884660fd1bb7213da914882eb`로 일치 |
| 패키지 manifest | PASS | 15개 항목의 SHA-256 일치 |
| Python 구문 검사 | PASS | 신규 production 및 test 파일 compile 성공 |
| 단위 테스트 | PASS | 11개 성공 |
| Compose 계약 테스트 | PASS | 2개 성공 |
| 실제 Bolt 연동 테스트 | PASS | disposable Neo4j에서 1개 성공 |
| 자동 projection | PASS | 엔터티 66개, 관계 15개 적재 |
| 스키마 상태 | PASS | 제약·인덱스 3개 중 3개 `ONLINE` |
| 동일 데이터 재적재 | PASS | 엔터티·관계 수 불변, 중복 없음 |
| 그래프 체크섬 | PASS | `529e106b507f3b99437a17e813805da175cd05e419175d1f763c6a1048e90459` 유지 |
| 격리 자원 정리 | PASS | 검증용 컨테이너·네트워크·볼륨 잔여 0개 |

## 기존 서비스 영향

기본 서비스 흐름에는 연결하지 않았다. 다음 조건 때문에 Neo4j를 실행하지 않는 환경의 동작은 바뀌지 않는다.

- root Compose 파일에 Neo4j를 포함하지 않았다.
- Backend 기본 requirements를 수정하지 않았다.
- FastAPI와 기존 후보 검색 경로에 Neo4j adapter를 연결하지 않았다.
- 별도 `compose.fragment.yml`과 `neo4j` profile을 명시할 때만 Neo4j와 projector가 실행된다.
- Neo4j는 metadata read model이며 App DB나 DataHub의 정본을 역으로 수정하지 않는다.

## 실행 방법

비밀번호와 App DB 주소는 저장소에 넣지 않고 외부 환경 파일로 제공한다.

```powershell
Copy-Item infrastructure/neo4j/.env.example .env.neo4j.local
# .env.neo4j.local에 실제 NEO4J_PASSWORD와 NEO4J_PROJECTION_DATABASE_URL을 입력한다.
docker compose --env-file .env.neo4j.local `
  -f infrastructure/neo4j/compose.fragment.yml `
  --profile neo4j up -d --build
docker compose --env-file .env.neo4j.local `
  -f infrastructure/neo4j/compose.fragment.yml `
  --profile neo4j logs neo4j-projector
```

projector 로그에서 `NEO4J_PROJECTION_SYNC=PASS`와 엔터티·관계 수를 확인한다.

## 아직 포함하지 않은 작업

- 실제 서비스 후보 검색에 Neo4j 결과를 연결하는 runtime wiring
- 운영용 read-only Neo4j 계정과 secret manager 연동
- release 변경을 감지하는 scheduler 또는 event 기반 재적재
- Backend·Frontend·DataHub·Trino까지 포함한 전체 제품 E2E

위 작업은 서비스 범위를 바꾸므로 별도 승인과 검증이 필요하다. 현재 package 검증 결과만으로 전체 제품 E2E 완료를 의미하지 않는다.

## Merge 안내

`jaehong`에서 다른 브랜치로 반영할 때는 [Neo4j Merge 작업명세서](Report_Neo4j_Merge_작업명세서_20260826.md)를 따른다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-08-26 16:24 | 선택형 Neo4j 이식 범위와 실제 자동 적재·재적재 검증 결과 작성 |
