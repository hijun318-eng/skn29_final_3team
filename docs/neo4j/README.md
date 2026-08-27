# Neo4j 선택형 관계 조회 계층

| 항목 | 내용 |
|---|---|
| 문서 설명 | Neo4j 구현 목적, 현재 범위, 관계 의미, 실행·검증 방법을 한곳에 정리한 기준 문서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-27 09:30 |
| 작성·수정 | OpenAI Codex |
| 대상 브랜치 | `jaehong_neo4j` |
| 기준 base commit | `0791ef9ecda0c24521043354b4517a90dc194999` |
| 현재 상태 | 선택형 package 구현·검증 완료, 제품 요청 경로 미연결 |

> 제품 범위와 도입 결정의 최종 권위는 `docs/product/` 문서다. 이 문서는 현재 로컬
> 구현과 검증 결과를 설명하며, Neo4j의 제품 도입 완료를 선언하지 않는다.

## 1. 한 문장 결론

Neo4j는 기존 데이터베이스를 대체하지 않는다. 승인된 Metric·Dimension·Dataset의 연결을
복제해, 분석 근거와 관련 후보를 탐색하는 선택형 metadata read model이다.

## 2. 왜 필요한가

기존 목록만으로는 Metric이 어느 Dataset을 사용하는지, 같은 Dataset을 사용하는 다른
Metric이 무엇인지 매번 코드·JOIN·문서에서 다시 찾아야 한다. Neo4j는 이 연결을 관계로
저장해 1~2단계 탐색으로 확인하게 한다.

```text
사용자 질문
  → Metric
  → 근거 Dataset
  → 같은 Dataset을 사용하는 관련 Metric
```

현재 제품 API는 이 흐름을 호출하지 않는다. 관계 조회의 가치와 패키지 안정성을 검증한
상태이며, 실제 후보 보강 배선은 별도 승인 대상이다.

## 3. 시스템 경계

| 구분 | 정본 또는 역할 | Neo4j 영향 |
|---|---|---|
| PostgreSQL RuntimeCatalogProjection | 활성 release와 승인 metadata 정본 | projector가 읽기만 한다 |
| DataHub | 카탈로그·의미·권한 정보의 상위 정본 | Neo4j가 역수정하지 않는다 |
| Neo4j | 재생성 가능한 관계 조회 복제본 | 정본 판정과 권한 판정을 하지 않는다 |
| FastAPI 분석 경로 | 기존 DataHub·RuntimeCatalogProjection 경로 유지 | 현재 adapter가 연결되지 않았다 |
| Root Compose | 기본 서비스 실행 | Neo4j fragment를 include하지 않는다 |

Neo4j는 `NEO4J_GRAPH_ENABLED=false`가 기본값이다. 별도 Compose 파일과 `neo4j` profile을
명시하지 않으면 실행되지 않는다. Neo4j 장애도 현재 FastAPI, 권한 검사, SQL 생성·실행,
보고서 흐름으로 전파되지 않는다.

단, Neo4j를 명시적으로 켜면 별도 CPU·메모리·디스크와 projection source 조회 부하는
발생한다. 따라서 물리 자원까지 영향이 0이라는 뜻은 아니다.

## 4. 관계 모델

모든 node는 `CatalogEntity`, 모든 edge는 `RELATED_TO` label을 사용한다. 실제 종류는
`kind` 속성으로 구분한다.

| 시작 node | 관계 `kind` | 도착 node | 의미 |
|---|---|---|---|
| `METRIC` | `SOURCE_ASSET` | `DATASET` | 지표가 사용하는 근거 데이터셋 |
| `DIMENSION` | `DIMENSION_ASSET` | `DATASET` | 분석 구분 기준이 존재하는 데이터셋 |
| `DATASET` | `JOIN` | `DATASET` | 승인된 Dataset 연결. 현재 적재 건수는 0 |

2026-08-26 마지막 격리 검증 결과는 다음과 같다.

| 항목 | 건수 |
|---|---:|
| Dataset | 51 |
| Metric | 14 |
| Dimension | 1 |
| 전체 node | 66 |
| `SOURCE_ASSET` | 14 |
| `DIMENSION_ASSET` | 1 |
| `JOIN` | 0 |
| 전체 relation | 15 |
| 관계가 있는 node / 독립 node | 17 / 49 |

관계가 15개인 것은 오류가 아니다. 현재 active projection에 승인된 의존성만 저장하고
Dataset 사이 관계를 임의로 추정하지 않았기 때문이다.

## 5. 자동 적재 흐름

```text
별도 neo4j profile 실행
→ Neo4j health check
→ projector가 PostgreSQL active projection 조회
→ node·relation을 정렬해 canonical Graph projection 생성
→ schema index 3개 생성 또는 재사용
→ node·relation MERGE
→ release·checksum·건수 exact read-back
→ 성공 receipt 출력 후 projector 종료
```

projector는 계속 감시하는 daemon이 아니라 시작 시점의 one-shot 작업이다. active release가
바뀌면 projector를 다시 실행해야 한다. 같은 projection을 반복 적재해도 중복이 생기지
않도록 release와 Graph checksum을 기준으로 멱등 처리한다.

## 6. 로컬 실행

실제 비밀번호와 App DB URL은 저장소 밖의 환경 파일에 둔다. 저장소의
`infrastructure/neo4j/.env.example`은 변수 이름 예시이며 credential 원본이 아니다.

```powershell
docker compose `
  --env-file <저장소_밖의_neo4j_env> `
  -f infrastructure/neo4j/compose.fragment.yml `
  --profile neo4j up -d --build

docker compose `
  --env-file <저장소_밖의_neo4j_env> `
  -f infrastructure/neo4j/compose.fragment.yml `
  --profile neo4j ps -a
```

기본 로컬 주소는 Browser `http://127.0.0.1:17474/browser/`, Bolt
`bolt://127.0.0.1:17687`이다. 포트는 외부 환경값으로 바꿀 수 있다.

### 관계 그래프

```cypher
MATCH (source:CatalogEntity)-[relation:RELATED_TO]->(target:CatalogEntity)
RETURN source, relation, target
LIMIT 50;
```

### 관계를 표로 확인

```cypher
MATCH (source:CatalogEntity)-[relation:RELATED_TO]->(target:CatalogEntity)
RETURN source.kind AS source_kind,
       source.entity_id AS source,
       relation.kind AS relation,
       target.kind AS target_kind,
       target.entity_id AS target
ORDER BY relation, source;
```

### Schema index

```cypher
SHOW INDEXES
YIELD name, state
WHERE name IN [
  'catalog_entity_identity',
  'catalog_entity_source_receipt',
  'related_to_receipt'
]
RETURN name, state
ORDER BY name;
```

세 index의 상태가 모두 `ONLINE`이어야 한다.

## 7. 검증 결과와 해석

| 검증 | 마지막 결과 | 의미 |
|---|---|---|
| Package manifest | 15개 manifest 항목 PASS | 이식 대상 파일의 checksum 일치 |
| Python compile | PASS | Python syntax·import 기본 검사 통과 |
| Unit test | 11 PASS | 설정, projection, receipt, query 계약 확인 |
| Compose contract | 2 PASS | profile, health, projector, 환경 계약 확인 |
| Live Neo4j | 1 PASS | 실제 driver·schema·적재·조회 확인 |
| Schema | 3/3 `ONLINE` | 필수 index 준비 완료 |
| 멱등 재적재 | PASS | 같은 release 재실행 시 중복 없음 |

이 결과는 Neo4j package의 로컬 동작 증거다. 제품 API가 Neo4j를 사용한다는 증거도 아니고,
새 commit이나 새 active release에 자동 승계되는 증거도 아니다.

## 8. 현재 한계와 다음 단계

1. 제품 분석 후보 검색에 아직 연결하지 않았다.
2. `JOIN`과 column lineage 관계는 현재 active metadata에 없어 적재되지 않았다.
3. projector 재실행 시점을 배포 job 또는 release hook 중 하나로 정해야 한다.
4. 운영 secret, backup·restore, monitoring, read-only 계정을 추가 검증해야 한다.
5. 제품에 연결할 때는 Graph 결과에도 기존 권한과 same-release membership을 다시 적용해야 한다.

Merge와 운영 전환 조건은 [MERGE_GUIDE.md](MERGE_GUIDE.md)를 따른다.

## 9. 발표용 설명

> Neo4j는 고객 원문을 저장하는 핵심 DB가 아닙니다. 승인된 지표와 데이터셋의 연결을
> 복제해, 지표가 어디서 왔고 어떤 지표와 근거를 공유하는지 보여주는 관계 지도입니다.

피해야 할 표현은 “추천 정확도가 이미 향상됐다”, “실시간 자동 동기화가 끝났다”,
“Neo4j가 정본이다”이다. 현재 확인된 사실은 관계 read model의 자동 적재와 독립 실행까지다.

## 변경 내역

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.0 | 2026-08-27 | 과거 결과서·발표자료의 중복을 제거하고 `jaehong_neo4j` package 기준으로 통합 |
