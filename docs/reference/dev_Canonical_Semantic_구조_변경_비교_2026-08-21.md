# dev Canonical Semantic 구조 변경 비교 보고서

> 상태: 현재 구현을 읽기 전용으로 점검한 참고 보고서다. 제품의 권위 있는 계약이나 live E2E 완료 증거를 대신하지 않는다.

## 1. 서론

### 1.1 검토 목적

작업자 간 조율을 통해 적용한 DataHub 검색·권한·SQL 생성 구조가 기존 구조에서 실제로 어떻게 변경됐는지 현재 `dev` 코드를 기준으로 비교한다.

### 1.2 비교 기준

- 이전 검토 기준 commit: `14fab5d1e7f1b09dbd3d8408fbbd63a3713b36dd`
- 현재 `dev` commit: `1ae1608321c9cd8c51346dd119344c665c6cb8ba`
- 현재 `dev`와 `origin/dev`: 동일 commit
- 비교 규모: 115개 파일, 13,249줄 추가, 516줄 삭제
- 작업 트리의 `infrastructure/database/datahub/semantic_authoring.py`, `tests/data/test_semantic_authoring.py` 미커밋 변경은 다른 작업자의 작업으로 보고 이번 commit 비교에서 제외했다.

결론부터 말하면, 제안했던 구조 중 핵심인 **Contract-first → Canonical Semantic Release → Grain-safe Analysis Plan → SQL Guard** 흐름이 실제 실행 코드에 적용됐다. 다만 DataHub Native 전환과 JOIN SQL의 완전한 결정론적 생성까지 완료된 상태는 아니다.

## 2. 본론

### 2.1 전체 흐름 비교

기존 흐름은 다음과 같았다.

```text
질문
→ DataHub Dataset 전체 Snapshot 조회
→ 질문과 Dataset·Glossary 검색
→ Dataset entitlement 검사
→ Dataset별 join_graph 조립
→ Runtime Context 생성
→ LLM SQL 생성
→ SQL Guard
→ Trino 실행
```

현재 흐름은 다음과 같이 변경됐다.

```text
질문
→ DataHub CatalogSnapshot 조회
→ Legacy metadata를 Canonical Semantic Release로 컴파일
→ Dataset·Glossary 검색
→ 사용자 권한으로 Dataset 필터링
→ 필요한 Semantic subgraph 선택
→ Metric·Dimension·JOIN 권한과 grain 검사
→ 서버 소유 AnalysisPlan 생성
→ SQL 생성
   ├─ 단일 승인 View: Typed SQL Compiler
   └─ 다중 Dataset 또는 JOIN: LLM Node 2 후보
→ AnalysisPlan과 실제 SQL AST 재대조
→ Trino 실행
```

가장 중요한 변화는 LLM이 SQL을 만들기 전에 백엔드가 지표, 차원, 기간, JOIN, fan-out 정책을 포함한 분석 계획을 먼저 확정한다는 점이다.

### 2.2 주요 변경 항목

| 영역 | 기존 구조 | 현재 구조 |
|---|---|---|
| Metadata 사용 | Dataset의 JSON/custom properties를 실행 단계에서 직접 사용 | 전체 릴리스를 `CanonicalSemanticRelease`로 먼저 컴파일 |
| JOIN Graph | Dataset별 `join_graph`를 요청 경로에서 다시 조립 | 컴파일된 `GovernedJoin` 집합을 재사용 |
| Release 검증 | manifest와 checksum 중심 | Asset·Metric·Dimension·JOIN을 포함한 canonical checksum 추가 |
| 분석 계획 | LLM SQL 생성 후 검증 | SQL 생성 전에 서버 소유 `AnalysisPlan` 생성 |
| JOIN 허용 | Dataset entitlement와 연결 가능 여부 중심 | Metric별 `allowed_join_ids`를 계획과 실제 SQL AST에서 모두 검사 |
| Fan-out | cardinality 선언 중심 | `DIRECT_JOIN`, `PREAGGREGATE`, `SEMI_JOIN`, `REJECT`로 명시적 결정 |
| SQL 생성 | 주로 LLM Node 2 | 단일 승인 View는 SQLGlot AST로 결정론적 생성 |
| SQL Guard | 허용 Table·Column·JOIN 검사 | AnalysisPlan의 연산·정렬·LIMIT·fan-out까지 재검사 |
| 장애 처리 | Metadata 검증 실패 시 차단 | Canonical compile 실패도 readiness와 request에서 fail-closed |
| Native 전환 | 미구현 | Legacy/Native 결과 동등성 비교 기반만 준비 |

관련 구현 경계는 다음과 같다.

- Canonical 전체 릴리스 계약: `app/backend/app/services/context/semantic_release.py`
- Legacy DataHub snapshot adapter: `app/backend/app/adapters/legacy_semantic_release.py`
- 검색 경로의 canonical compile/cache: `app/backend/app/adapters/query_governance.py`
- 서버 소유 논리 계획: `app/backend/app/services/analysis/logical_plan.py`
- Fan-out 결정: `app/backend/app/services/context/fanout_policy.py`
- 단일 View SQL 컴파일: `app/backend/app/services/analysis/typed_sql_compiler.py`
- 계획과 SQL AST 재검증: `app/backend/app/services/sql_guard/guard.py`, `join_semantics.py`, `operation_semantics.py`

### 2.3 JOIN 권한과 grain 안전성

현재는 A와 B Dataset에 각각 접근할 수 있더라도 자동으로 두 Dataset의 JOIN을 허용하지 않는다. 최종 JOIN은 다음 조건의 교집합을 통과해야 한다.

```text
A Dataset 권한
∩ B Dataset 권한
∩ 선택 Metric의 allowed_join_ids
∩ 실제 JOIN equality key
∩ grain·unique key 증거
∩ fan-out 정책
```

다음 조건은 차단된다.

- 선택 Metric이 허용하지 않은 JOIN edge
- many-to-many JOIN
- uniqueness 증거가 없는 one-to-one 선언
- one-side Measure를 many-side Dimension으로 분해하는 JOIN
- 필요한 사전 집계 없이 중복 집계가 발생하는 JOIN

Metric의 허용 edge는 논리 계획 단계와 실제 SQL AST 단계에서 이중 검사된다. 다만 JOIN edge 자체에 독립적인 role/domain entitlement를 부여하는 metadata는 아직 없다. 현재 권한 모델은 Dataset·Metric entitlement와 Metric의 `allowed_join_ids`를 결합한 전환 단계다.

### 2.4 결정론적 SQL 생성 범위

새 `Typed SQL Compiler`는 다음 단일 승인 Serving View 분석을 질문 원문 없이 SQLGlot AST로 생성한다.

- 집계와 차원별 분해
- 기간별 추이
- Top-N과 Bottom-N
- 기간 비교
- 동일 범위의 복수 Metric
- Ratio Metric

다음 범위는 아직 결정론적으로 생성하지 않는다.

- 다중 Dataset `VIEW_COMPOSE`
- `RAW_APPROVED_DETAIL`
- JOIN을 포함한 `DIRECT_JOIN`
- `PREAGGREGATE`
- `SEMI_JOIN`

이 범위에서는 기존 LLM Node 2가 SQL 후보를 만들지만, 서버가 만든 AnalysisPlan과 동일한 G2 SQL Guard를 반드시 통과한다. 따라서 무검증 fallback은 아니지만 전체 SQL 생성이 결정론적으로 전환된 것도 아니다.

### 2.5 검색 효율 변화

동일한 cached DataHub snapshot은 canonical release로 한 번만 컴파일되며, 요청마다 Dataset별 `join_graph`를 재조립하지 않는다. 이 점은 일관성과 반복 연산 측면에서 개선됐다.

그러나 다음 한계는 남아 있다.

- 여전히 전체 `CatalogSnapshot`을 읽는다.
- 검색 순위 계산 후 Dataset entitlement를 적용한다.
- 권한별 경량 token/URN 검색 인덱스는 없다.
- canonical release cache는 현재 Backend 프로세스 내부 상태다.
- QPS, latency SLO, multi-process 배포 조건이 확정되지 않아 성능 향상을 수치로 판정할 수 없다.

따라서 현재 상태는 “검증된 전체 릴리스 projection을 재사용하는 구조”이며, “권한별 인덱스에서 필요한 subgraph만 조회하는 최종 구조”까지 도달한 것은 아니다.

### 2.6 아직 적용되지 않은 항목

- DataHub Native Metric/Semantic Model 발행
- Native shadow read-back adapter
- DataHub Dataset custom properties 제거
- JOIN edge별 독립 role/domain/capability 권한
- Trino serving/raw capability principal 분리
- Raw exploration 실행 경로
- Redis 기반 다중 프로세스 release cache
- 권한별 경량 검색 인덱스
- 결정론적 다중 Dataset JOIN SQL 생성
- `latest_snapshot` 실행 경로

현재 단계는 다음과 같다.

```text
Legacy DataHub metadata
→ Canonical Semantic Release
→ 안전한 AnalysisPlan
→ 단일 View 중심 결정론적 SQL
→ 그 밖의 SQL은 LLM 후보 + 동일 Plan/AST Guard
```

아직 도달하지 않은 목표는 다음과 같다.

```text
DataHub Native Semantic Graph
→ Canonical Semantic Release
→ 전체 결정론적 JOIN SQL
→ 분리된 Trino capability principal
```

### 2.7 검증 결과

다음 핵심 회귀 테스트를 실행했다.

```text
tests/backend/test_canonical_semantic_release.py
tests/backend/test_fanout_policy.py
tests/backend/test_analysis_pipeline.py
tests/backend/test_pipeline_query_planner.py
tests/backend/test_pipeline_sql_guard.py
```

결과는 다음과 같다.

```text
104 passed in 3.65s
```

BI candidate와 catalog regression까지 포함한 확장 실행 결과는 `97 passed, 10 failed`였다. 실패 10건은 모두 serving SQL의 3단계 View 이름을 `COMMENT ON VIEW`에서 파싱하는 지점에 모였다. 현재 실행 셸의 SQLGlot은 `28.10.1`이지만 저장소 계약은 `sqlglot>=30.17,<30.18`이므로, 이번 결과는 현 dev의 기능 회귀가 아니라 의존성 불일치에 따른 환경 실패로 분류한다. 요구 버전 환경에서 재검증하기 전에는 확장 검증을 통과했다고 판정하지 않는다.

이번 검증은 핵심 unit/contract 회귀 증거이며, 현재 commit의 실제 DataHub·Trino·Backend·Browser 전체 live E2E를 새로 수행한 결과는 아니다.

## 3. 결론

새 구조는 문서 제안에 머물지 않고 핵심 실행 경로에 실제 반영됐다. 주요 성과는 다음 세 가지다.

1. DataHub metadata를 직접 실행 계약으로 사용하지 않고 검증된 Canonical Semantic Release로 변환한다.
2. LLM SQL 생성 전에 서버가 권한·grain·JOIN·연산 계획을 확정한다.
3. 계획과 실제 SQL AST를 다시 비교해 JOIN 권한, fan-out, 출력 grain과 연산 의미를 이중 통제한다.

객관적인 현재 단계는 **Canonical Graph 전환 기반과 Grain-safe Planner 도입은 완료됐고, DataHub Native 전환과 전체 결정론적 JOIN 컴파일은 미완료인 상태**다.

다음 우선순위는 Native shadow 발행·read-back 동등성 검증, JOIN edge 자체의 entitlement 계약, 다중 Dataset typed SQL compiler, Trino capability principal 분리 순서가 적절하다. 이 과정에서도 권한 거부, checksum 불일치, 승인되지 않은 JOIN과 grain 위반에 Legacy fallback을 허용해서는 안 된다.
