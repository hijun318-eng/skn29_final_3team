# Answervice 구현·운영·검증

| 항목 | 내용 |
|---|---|
| 문서 역할 | 구현 구조, 통합·보안·AI 평가, CI와 재현 가능한 Demo 기준 정의 |
| 완료 판단 | 설치 화면이 아니라 Golden E2E의 실제 동작과 근거가 있는 검증 결과 |
| 배포 표현 | 실제 Production이 아닌 `Production-like Demo Environment` |

> 이 문서는 구현·검증 계약이다. 아래 항목은 테스트를 실행하기 전까지 `Pass`가 아니며, 결과는 `Pass / Fail / Not Run / Blocked`로 구분해 기록한다.

## 1. 구현 원칙

1. 대표 E2E 하나의 완성도를 기능 수보다 우선한다.
2. AI와 결정론적 프로그램의 책임을 분리한다.
3. 보안은 G2 하나가 아니라 Context·G2·Trino·read-only·G3의 다층 방어로 만든다.
4. Critical security regression은 merge gate다.
5. 전체 AI benchmark는 모든 PR에서 실행하지 않고 변경 영향이 있을 때 실행한다.
6. Application release와 model/prompt/rule/data configuration을 각각 Version으로 기록한다.
7. 실측하지 않은 정확도·latency·throughput을 확정값으로 쓰지 않는다.
8. Golden Result와 test data snapshot을 변경하면 기존 점수와 분리한다.

## 2. 기본 기술 구조

| 영역 | 기본 방향 |
|---|---|
| Frontend | React + Vite + TypeScript |
| Backend | FastAPI + Pydantic |
| Workflow | Deterministic Orchestrator |
| App DB | PostgreSQL + SQLAlchemy + Alembic |
| Metadata | DataHub OSS |
| Metadata ↔ Query | Answervice Asset Binding |
| Business Rule | Answervice Rule Layer |
| Integrated Query | Trino |
| SQL AST | SQLGlot |
| GPT | Interpreter / Narrator |
| sLLM | 신규 Trino Text-to-SQL |
| Container | Docker / Docker Compose |
| CI/CD | GitHub Actions + manual demo approval |
| Observability | structured log + request/trace/query ID |

LangGraph, Kubernetes, Jenkins는 MVP Core의 선행 조건이 아니다.

## 3. 권장 Repository 경계

```text
answervice/
├─ frontend/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ workflow/
│  │  ├─ interpreter/
│  │  ├─ metadata/
│  │  ├─ binding/
│  │  ├─ rules/
│  │  ├─ context/
│  │  ├─ resolver/
│  │  ├─ validation/
│  │  ├─ query/
│  │  ├─ result/
│  │  ├─ analysis/
│  │  ├─ report/
│  │  └─ audit/
│  └─ tests/
├─ sllm/
│  ├─ datasets/
│  ├─ eval/
│  ├─ training/
│  └─ serving/
├─ data/
├─ infrastructure/
├─ docs/
└─ .github/workflows/
```

이 구조는 책임 경계의 예시다. 실제 Repository에 이미 있는 구조와 중복 폴더를 새로 만들지 않는다.

## 4. Backend 모듈 계약

| 모듈 | 입력 | 출력·책임 |
|---|---|---|
| API | user request | 인증, input Schema, `request_id` |
| Interpreter | 자연어 질문 | Business Analysis Request |
| Metadata / Binding | 분석 요청·권한 | DataHub URN과 Trino FQN 후보 |
| Rules / Context | 후보 자산·Rule·Role | Approved Context |
| Resolver | 요청·Context | Reuse / New 결정 |
| Validation | Context / SQL / Result | G1 / G2 / G3 정형 상태 |
| Query | G2 통과 SQL | Trino result / query ID / source error |
| Result | Raw Result | Safe Result / chart spec |
| Analysis | 검증된 실행 | Definition / Run / Result |
| Report | Block와 `report_as_of` | Report Run / Block Run |
| Audit | 모든 stage event | Version·근거·상태 Trace |

## 5. Frontend 최소 사용자 흐름

### Chat / Analysis

- 자연어 질문과 clarification
- 현재 stage와 실패 이유
- 결과 요약·표·차트
- 기간·filter와 기준 시각
- 데이터 출처·Metric·검증 상태
- Analysis 저장과 Report 추가

### Saved Analysis

- Definition 목록과 Version
- 최신 Run / 과거 Run 구분
- Parameter 변경과 재실행
- 현재 Rule과 호환되지 않을 때 재검토 상태

### Report

- Analysis Block 추가·배치
- visualization 변경
- 공통 `report_as_of`로 수동 실행
- Block별 최신 상태와 마지막 성공 시각
- 과거 Report Run 조회

Data Catalog 전용 UI와 고급 Audit Dashboard는 후순위다.

## 6. Application DB 핵심 Entity

```text
User / Role

AssetBinding
BusinessRule / MetricRule / JoinRule / TimeRule / IdentityRule
PolicyVersion

AnalysisDefinition / AnalysisRun / AnalysisResult
ReportDefinition / ReportBlock / ReportRun / BlockRun

RequestTrace / AuditEvent
```

DataHub Metadata 전체를 App DB에 복제하지 않는다. Answervice가 소유하는 Binding·Rule과 DataHub URN reference를 저장한다. Run 이력은 append-only로 관리하고, 민감 result의 보존 기간과 접근 권한을 별도로 둔다.

## 7. Typed API와 AI Contract

API 예:

```text
POST /analysis/query
GET  /analysis/{analysis_id}
POST /analysis/{analysis_id}/runs
POST /reports
POST /reports/{report_id}/runs
GET  /runs/{run_id}/trace
```

Pydantic/JSON Schema로 고정할 계약:

- Business Analysis Request
- Approved Context Package
- Asset Binding
- G1 / G2 / G3 Result
- sLLM SQL Draft
- Safe Result / Chart Spec
- GPT Narrator Input/Output

Error는 HTTP 상태만 반환하지 않고 `error_code`, `stage`, 사용자 메시지와 내부 trace reference를 분리한다.

## 8. Logging과 Observability

최소 필드:

- `request_id`, `trace_id`, `analysis_run_id`, `report_run_id`
- stage / duration / status / error code
- model / prompt / context / rule / binding / policy Version
- Trino query ID / source / scanned data / row count

로그 제외:

- password / API key / secret
- 전체 민감 Raw Result
- 불필요한 개인정보와 SQL literal의 민감 값
- LLM private chain-of-thought

사용자에게는 안전한 오류 메시지를 제공하고 상세 stack trace와 내부 경로를 노출하지 않는다.

## 9. Version Compatibility와 Lock

다음 표는 2026-08-10 공식 문서 기준의 **검증 후보**다. 최종 lock은 실제 Compose 통합 테스트를 통과한 image tag/digest와 lockfile로 기록한다.

| Component | 문서 기준 후보 | 호환 조건 | 프로젝트에서 확인할 것 |
|---|---|---|---|
| DataHub OSS | v1.7.0 | CLI/Python SDK 1.7.0 | 5 Source ingestion, search API, immutable image tag |
| Trino | 483 | 현재 공식 문서 Version | 5 catalog, type mapping, G2 dialect regression |
| PostgreSQL | 16.x 후보 | connector는 12.x 이상 | 두 database/catalog, DataHub와 Trino 동시 연결 |
| MySQL | 8.0.x 후보 | connector는 5.7·8.0 이상 | timestamp/decimal/null, read-only |
| SQL Server | 2022 후보 | connector는 2019 이상 | temporal history, `procedure` 차단, read-only |
| ClickHouse | 25.3.x 이상 | connector는 ClickHouse 25.3 이상 | event data, type mapping, passthrough 차단 |
| SQLGlot | 구현 시 exact pin | Trino dialect regression 필요 | 허용/차단 AST corpus |
| Python / Node | Repository exact pin | Backend·Frontend 도구와 통합 | lockfile·CI·container 일치 |

Version 변경 시 다시 실행한다.

1. Metadata ingestion과 search
2. Asset Binding health test
3. Source별 조회와 2/3 Source JOIN
4. G2 parser/policy regression
5. Golden E2E와 security negative

공식 확인 링크:

- [DataHub releases](https://docs.datahub.com/docs/releases)
- [Trino 483 documentation](https://trino.io/docs/current/)
- [PostgreSQL connector](https://trino.io/docs/current/connector/postgresql.html)
- [MySQL connector](https://trino.io/docs/current/connector/mysql.html)
- [SQL Server connector](https://trino.io/docs/current/connector/sqlserver.html)
- [ClickHouse connector](https://trino.io/docs/current/connector/clickhouse.html)

## 10. DataHub 통합 검증

### Metadata ingestion

- 5개 논리 Source에서 Dataset 생성
- 두 PostgreSQL Source가 다른 logical source로 구분
- table/column/description/domain/tag/sensitivity 확인
- ingestion 재실행과 stale asset 처리 확인

### 실제 분석 사용

Golden Scenario에서 다음 chain을 증명한다.

```text
질문 + permission scope → 범위가 제한된 DataHub search → Dataset URN 재검증
→ Asset Binding → Trino FQN → Approved Context
→ 실제 SQL asset → 사용자 Evidence
```

UI screenshot만으로 통합 완료 처리하지 않는다.

## 11. Trino 통합 검증

### 연결과 타입

- PostgreSQL 2 catalog, MySQL, SQL Server, ClickHouse
- source별 `SELECT`
- date/timezone/decimal/null/string/identifier type
- 대표 2 Source와 3 Source JOIN

### 보안과 운영

- Source DB 전용 read-only 계정
- Trino catalog/column access control
- DDL/DML/CALL 차단
- `system.execute`, connector `query`, SQL Server `procedure` 차단
- timeout, cancellation, resource group, result cap
- query ID와 source 장애 식별

### 성능

`LIMIT` 유무만 보지 않고 single/2-source/3-source query의 elapsed time, queued time, scanned rows/bytes, output rows와 connector 병목을 측정한다.

## 12. 테스트 계층

| Layer | 범위 | 외부 AI |
|---|---|---|
| Unit | Time Rule, Binding, Permission, Resolver, G1/G2/G3, Result Shaper | mock |
| Contract | Pydantic/JSON Schema, API error, model response parser | fixture |
| Integration | App DB, DataHub API, Trino, 5 Source, migration | 선택적 mock |
| E2E | 질문 → UI → Analysis → Report → Trace | 지정 model endpoint |
| AI Evaluation | GPT Interpreter/Narrator, Context, sLLM, Gold Result | 실제 후보 |

한 테스트가 여러 목적을 대신하지 않게 한다. Unit pass가 connector read-only를 증명하지 않고, E2E 1건이 전체 AI 정확도를 증명하지 않는다.

## 13. Gate별 핵심 테스트

### G1

| Case | 기대 상태 |
|---|---|
| 정상 질문 | `PASS` |
| Metric·Dataset·Binding·JOIN Rule 없음 | 해당 `MISSING_*` |
| 권한 없음 | `BLOCKED_PERMISSION` |
| 모호한 기간 | `NEED_CLARIFICATION` |
| 비활성 Rule/Binding | 차단 |

G1 실패 뒤 sLLM이 호출되면 테스트 실패다.

### G2 security corpus

- DML: `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- DDL: `CREATE`, `ALTER`, `DROP`
- `CALL`, `system.execute`, passthrough `query`, SQL Server `procedure`
- 복수 statement와 comment/whitespace 우회
- 권한 밖 catalog/table/column
- 승인되지 않은 JOIN과 금지 function
- 과도한 scan·complexity 후보

Dangerous case 차단뿐 아니라 정상 Gold SQL의 과대 차단도 측정한다.

### G3

- schema mismatch / empty / null
- row·payload limit
- distinct business key와 JOIN amplification
- metric invariant / expected range
- sensitive column/pattern과 redaction

## 14. Security 0-tolerance 검증

0-tolerance 기준:

- 원본 Source DB write 성공 0건
- 권한 없는 민감정보가 Safe Result·UI·GPT·Report에 노출된 건수 0건

실제 write probe는 합성 데이터가 있는 폐기 가능한 test environment에서만 실행한다. 테스트 전후 table checksum/row count와 DB audit log를 비교한다. Production 또는 보존해야 할 환경에 공격 SQL을 실행하지 않는다.

테스트 corpus를 모두 차단한 결과는 “정의한 corpus 통과”로 기록하며 모든 공격을 절대적으로 차단한다고 일반화하지 않는다.

## 15. AI 평가

### GPT Interpreter

- Metric / Dimension / Filter / Period intent
- analysis type
- ambiguity detection
- Output Schema compliance

실제 날짜 계산은 Time Rule unit test가 담당한다.

### Context Builder

- context recall / precision
- permission filtering
- DataHub asset grounding / binding accuracy
- metric/join rule accuracy
- Context token size

### sLLM

- contract parse / SQL parse / G2 / query success
- Result Accuracy
- table/column/JOIN/Metric/Time
- Context violation
- latency / VRAM / serving error

### GPT Narrator

숫자와 기간 충실도는 코드로 비교한다. groundedness·가독성·불필요한 인과 추론만 별도 rubric 또는 LLM judge를 보조로 사용한다.

## 16. Golden E2E

대표 질문:

> 지난달 골드 회원의 객실 매출과 F&B 매출을 지점별로 비교해줘.

필수 경로:

1. Interpreter → Business Analysis Request
2. Permission-filtered DataHub Asset 3 Source
3. Asset Binding → Trino FQN
4. Metric/JOIN/Time/Identity Rule
5. G1 → Resolver → sLLM → G2
6. Trino 3 Source query → G3 → Safe Result
7. GPT 설명과 chart
8. Analysis 저장 → 기간 변경 재실행
9. Report Block → 공통 `report_as_of` 실행
10. 과거 Run 보존과 request ID Trace

Result 비교는 row order·type·decimal tolerance 정책을 고정하고 Gold Result와 자동 비교한다.

## 17. Analysis·Report 재현성

### Analysis

- Definition과 Parameter Schema 저장
- Run마다 실제 기간·권한·Rule/Binding/Policy/Model Version 저장
- 재실행마다 현재 G1/G2 재통과
- SQL / query ID / source freshness 보존
- 과거 Result 미덮어쓰기

### Report

- Block이 Analysis Definition을 참조
- 공통 `report_as_of`
- Block Run이 새 Analysis Run을 참조
- `PARTIAL_SUCCESS`와 실패 사유 표시
- 과거 결과를 이번 최신 결과로 오표시하지 않음

## 18. CI와 Release

### PR fast CI

- Frontend lint / type / unit / build
- Backend format/lint/type/schema/unit
- Binding·G1·G2·G3 regression
- critical security corpus
- GPT/sLLM은 mock 또는 작은 deterministic fixture

### Integration

- App DB migration
- DataHub API와 ingestion smoke
- 5 Source + Trino
- source별 조회와 2/3 Source JOIN
- read-only·timeout·cancellation

### Release candidate

```text
Build
→ Unit / Contract
→ Integration
→ Security Negative
→ Golden E2E
→ 영향받은 AI Evaluation
→ Image digest 기록
→ Manual Approval
→ Demo Deploy
→ Health / Smoke
```

## 19. AI Evaluation Trigger

| 변경 | 다시 실행할 평가 |
|---|---|
| GPT model/prompt/output Schema | Interpreter 또는 Narrator eval |
| sLLM base/adapter/decoding | 전체 sLLM Gold eval |
| Context Schema/search/rule serialization | Context eval + sLLM regression |
| Binding/Rule/Policy | 관련 unit/integration + Golden E2E |
| Trino/DataHub/DB Version | ingestion + query + G2 + Golden E2E |

## 20. Release Manifest

최소 기록:

- frontend/backend image digest와 commit SHA
- App DB migration revision
- GPT model·prompt·Schema Version
- sLLM model ID·revision·adapter·runtime
- DataHub·Trino·Source DB image Version
- data snapshot·Binding·Rule·Policy Version
- 실행한 test suite와 결과 artifact

`latest`만 기록하지 않는다.

## 21. 주요 리스크와 완화

| 리스크 | 완화 |
|---|---|
| Metadata와 실행 경로 불일치 | versioned Asset Binding + health test |
| Connector type·성능 문제 | type matrix + query stats 실측 |
| 잘못된 JOIN·Metric | Rule + G2 + G3 signal + Gold Result |
| 권한 누락 | Context filter + G1/G2 + Trino ACL + read-only |
| Raw Result 외부 전송 | Backend 내부 G3 + shaping/redaction 후 전달 |
| 모델 오류를 시스템 오류로 오진 | 단계별 error attribution |
| 범위 과다 | Golden E2E와 P0를 먼저 완료 |

## 22. 최종 완료 기준

- 5 Source / 4 DBMS와 DataHub·Trino가 고정 Version으로 기동
- Metadata → Binding → Context → SQL → Result Evidence가 연결
- 대표 2/3 Source JOIN과 type·timeout·read-only 검증
- GPT Interpreter, Context Builder, sLLM, Narrator 평가 결과 존재
- G1/G2/G3와 security corpus 통과
- Golden E2E Result Accuracy 측정
- Analysis·Report 재실행과 과거 Run 보존
- Release Manifest와 Docker 기반 Demo 재현

다음 문서: [04. 단계별 구현 가이드](04_Answervice_단계별_구현_가이드.md)
