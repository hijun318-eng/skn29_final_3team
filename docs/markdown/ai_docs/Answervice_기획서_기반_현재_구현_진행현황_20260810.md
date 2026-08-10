# Answervice 기획서 기반 현재 구현 진행현황

| 항목 | 내용 |
|---|---|
| 문서 설명 | 첨부 기획서의 목표와 MVP를 현재 저장소의 코드·테스트·WBS·Gate 상태에 대조한 구현 진행현황 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-10 10:33 |
| 작성·수정 | 박준희 / Codex 분석 |
| 평가 기준 | `C:\Users\Playdata\Downloads\00_Answervice_프로젝트_기획서.md` |
| 구현 기준 | `junhee` branch `77c2508` 및 `dev` branch `ccbb94c` |

## 서론

첨부 기획서가 정의한 Answervice의 목표는 여러 업무 시스템의 데이터를 자연어로 분석하고, 승인된 Context와 세 단계 Gate를 거쳐 Trino로 조회한 뒤, 검증된 결과를 Analysis와 Report 자산으로 저장·재사용하는 것이다. 따라서 파일 수나 화면 수만으로 진행률을 판단하면 실제 서비스 완성도를 과대평가할 수 있다.

이 문서는 다음 두 수치를 구분해 사용한다.

| 구분 | 현재 값 | 의미 |
|---|---:|---|
| 공식 WBS 완료율 | **61.6%** | 99개 작업 중 `완료` 61개를 반영한 엄격한 하한선 |
| 기획서 P0 구현 완성도 | **약 65%** | 기획서의 P0 10개 항목을 실제 코드·계약·테스트와 대조한 기능 관점 평가 |

WBS에는 `진행` 18개, `차단` 1개, `대기` 19개가 남아 있다. 진행 작업을 임의로 절반 완료로 계산하지 않았으며, 65%는 아래 평가표의 항목별 근거를 합산한 값이다. 또한 WBS 기준일은 2026-08-04이므로 2026-08-10 현재의 세부 branch 작업이 일부 늦게 반영될 수 있다. 이 차이는 [Gate 실행 카드 원장](../collaboration/Gate_실행_카드_원장.md)의 최신 상태로 보완했다.

## 본론

### 1. 기획서 P0 기준 구현 완성도

각 P0 항목을 10점으로 두고, 계약·단위 테스트만 있는 상태와 실제 사용자 왕복까지 연결된 상태를 구분했다.

| P0 항목 | 점수 | 확인된 구현 | 남은 핵심 작업 |
|---|---:|---|---|
| 자연어 질문과 구조화 요청 | 7/10 | FastAPI `/analysis`, typed request·response, Node 1 질문 정규화와 모호성 처리가 구현됨 | 실제 GPT Interpreter와 대표 질문의 운영형 연결 검증 |
| Permission-filtered Metadata와 Approved Context | 7/10 | DataHub·Trino adapter, entitlement, Context Builder와 versioned Context 계약이 존재함 | live DataHub 기준 5개 Source 조회·lineage·권한 제외 trace 완결 |
| Asset Binding과 Business Rule | 8/10 | URN↔FQN, Metric·JOIN·time·required filter 계약과 승인 View registry가 구현됨 | 2·3-source 대표 질문의 전체 규칙 coverage와 result hash 확정 |
| G1→재사용/신규→sLLM→G2 | 6/10 | G1·G2, Node 2 SQL 생성, 1회 repair, model adapter와 호출 제한이 구현됨 | 실제 sLLM endpoint 연결·평가, 기존 Analysis 재사용 판정의 영속 경로 검증 |
| Trino 교차 조회와 G3 | 8/10 | 5개 논리 Source·4종 DBMS DDL/seed, Trino catalog, read-only 정책, query lifecycle와 G3가 구현됨 | 기획서 대표 3-source 질문을 실제 통합 환경에서 고정 결과와 비교 |
| 표·차트·설명·근거 | 7/10 | 분석 응답의 table·chart·evidence·artifact contract와 Frontend 표시 구조가 존재함 | 실제 모델 설명의 grounded 평가와 서버 결과만 사용하는 최종 UI 회귀 |
| Analysis 저장·재실행·이력 | 4/10 | Artifact·cache key·query ID·trace와 application DB 골격이 존재함 | Analysis Definition/Run/Result의 사용자 API, Parameter 재실행과 과거 이력 보존 E2E |
| Report Block·수동 실행·부분 실패 | 5/10 | Report Definition/version/block, manual command, run 조회 Backend API와 migration이 구현됨 | 실제 Frontend API integration, worker 처리, block별 partial/retry와 이력 E2E |
| request_id 중심 Audit Trace | 7/10 | user·role·context·policy·model·query·Gate·artifact를 연결하는 trace contract와 테스트가 존재함 | 운영 Audit 검색 UI, 영속 조회와 보존 정책 검증 |
| Golden E2E·보안 negative test | 6/10 | deterministic fixture, Gold SQL/result hash, DDL/DML 차단·권한·timeout·cancel 테스트가 존재함 | 대표 질문 전체 왕복, 공격 corpus, 재기동·복구·성능을 승인 환경에서 최종 실행 |
| **합계** | **65/100** | 기반 데이터·계약·Control Plane은 상당 부분 구현됨 | 실제 모델·영속 재실행·Report 실행·통합 E2E가 완성도를 결정함 |

### 2. 영역별 현재 구현 상태

#### 2.1 데이터 플랫폼과 연합 조회 — 약 75%

확인된 구현은 다음과 같다.

- PostgreSQL·MySQL·SQL Server·ClickHouse 기반 5개 논리 Source의 DDL과 deterministic synthetic seed가 있다.
- Trino catalog와 read-only access control, 분석 View, 2-source Gold SQL과 result hash 계약이 있다.
- DataHub source ingestion recipe와 serving analytics recipe, URN↔FQN·column·lineage 계약이 있다.
- query·status·cancel·health adapter와 watermark fingerprint가 코드와 테스트로 정의돼 있다.

남은 작업은 WBS `R2-09~17`에 집중되어 있다. 특히 기획서의 대표 질문에 해당하는 3-source 정답 조회, live DataHub trace, 전체 JOIN registry와 watermark 기반 cache invalidation을 실제 통합 환경에서 확정해야 한다.

주요 근거:

- [database compose](../../../infrastructure/database/compose.yml)
- [Trino 2-source Gold SQL](../../../infrastructure/database/sql/queries/i3_gold_total_guest_revenue.sql)
- [DataHub·Trino adapter](../../../src/data/i2_adapters.py)
- [Analytics Context 계약](../../../src/data/analytics_context_contract.i4.v2.json)

#### 2.2 AI·Text-to-SQL·ModelOps — 약 60%

Node 1·2·2′·3, prompt registry, schema validator, deterministic fake model, model serving manifest와 학습·평가 도구는 구현돼 있다. Model이 권한·Gate·실행 여부를 결정하지 않는 경계도 코드 계약에 반영돼 있다.

그러나 현재 model decision은 외부 model download, GPU/RunPod, 비용 발생과 deployment를 허가되지 않은 상태로 기록한다. 즉, sLLM 학습·serving 코드가 존재하는 것과 실제 제품 요청이 학습된 sLLM endpoint로 처리되는 것은 다르다. `Qwen3-4B-Instruct-2507` 또는 승인된 최종 모델의 endpoint health, Validation 정확도·p50·p95, trace·비용과 최종 release manifest가 아직 남아 있다.

주요 근거:

- [Node 2 SQL 생성](../../../src/ai/node2.py)
- [Model 결정 원장](../../../src/modelops/model_decision.v0.1.json)
- [Model runtime](../../../src/modelops/runtime.py)
- [학습·평가 도구](../../../src/ai/training/README.md)

#### 2.3 Backend Control Plane — 약 80%

FastAPI Controller, 인증·role·as_of·trace context, 고정 상태 전이, G1·G2·G3, query lifecycle, plan/result cache, Artifact, model call budget, OpenAPI와 Report API가 구현돼 있다. `DATA_PLATFORM_MODE`는 `fake`, `versioned-trino`, `real`을 구분하고 `MODEL_MODE`는 fake·contract-fake·OpenAI-compatible endpoint를 구분한다.

Backend는 현재 가장 완성도가 높은 영역이다. 다만 기획서의 최종 성공 기준을 충족하려면 다음이 더 필요하다.

- Analysis Definition/Run/Result 영속 저장과 Parameter 재실행 API 완결
- 기존 local DB migration head 호환성 확인
- Report manual command를 소비하는 worker와 schedule runtime
- retention·backup·restore hook과 release migration 검증

주요 근거:

- [FastAPI 분석 API](../../../app/backend/app/api/router.py)
- [분석 pipeline](../../../app/backend/app/services/analysis_service.py)
- [Context Builder](../../../app/backend/app/services/context_builder.py)
- [Report API](../../../app/backend/app/api/report_router.py)
- [분석 pipeline 테스트](../../../tests/backend/test_analysis_pipeline.py)

#### 2.4 Frontend와 Report — 약 55%

활성 Frontend는 `app/enterprise-react`이며 분석 질문·상태·표·차트·근거·Catalog·Connections·Report 화면과 production build 구성이 존재한다. Analysis client는 Backend 응답 계약을 소비할 수 있다.

반면 현재 `junhee/dev` 기준에는 Report 전용 HTTP client가 없고 WBS의 `R5-17 실제 API integration`은 `차단` 상태다. Backend Report API는 존재하지만, Frontend에서 definition 생성·block 교체·승인·next draft·manual command·run history를 실제 서버 응답으로 끝까지 소비하는 변경은 아직 `dev` 통합 완료로 볼 수 없다. worker와 schedule이 없으므로 manual command 이후의 실제 Report Run 진행도 완결되지 않았다.

주요 근거:

- [활성 Frontend](../../../app/enterprise-react/src/App.jsx)
- [Analysis client](../../../app/enterprise-react/src/api/analysisClient.ts)
- [Report 화면](../../../app/enterprise-react/src/pages/ReportsPage.jsx)
- [Frontend contract 테스트](../../../tests/frontend/contracts.test.mjs)

### 3. 기획서의 대표 성공 경로별 판정

| 성공 경로 단계 | 현재 판정 | 설명 |
|---|---|---|
| 질문 입력 | 구현 | Frontend와 `/analysis` API가 존재함 |
| 질문 구조화 | 부분 구현 | Node 1과 contract는 있으나 실제 GPT Interpreter 운영 검증이 남음 |
| 승인 Context | 부분 구현 | versioned binding 경로는 구현, live DataHub 전체 trace는 진행 중 |
| 신규 SQL 생성 | 부분 구현 | Node 2·repair는 구현, 실제 sLLM serving·평가는 대기 |
| G2 정책 검증 | 구현 | fail-closed 정책과 negative contract가 존재함 |
| Trino 3-source 조회 | 부분 구현 | 2-source Gold 경로는 존재, 대표 3-source 고정 검증이 진행 중 |
| G3·설명·Artifact | 구현에 가까움 | pipeline과 테스트 계약이 존재하나 실제 최종 모델 E2E가 남음 |
| Analysis 저장·기간 변경 재실행 | 미완결 | Artifact·cache는 있으나 사용자 관점 영속 Definition/Run 재실행이 부족함 |
| Report 수동 실행 | 부분 구현 | Backend command API는 있으나 worker와 Frontend 실제 연결이 미완결 |
| Trace 확인 | 부분 구현 | 응답 trace는 있으나 전체 영속 Audit 검색 UI가 대기 |

현재는 “핵심 부품과 보호 장치는 대부분 구현됐고, 일부 대표 분석은 실행 가능한 단계”다. 그러나 기획서의 성공 기준인 질문→3-source 조회→Analysis 재실행→Report 수동 실행→Trace 확인을 하나의 실제 사용자 흐름으로 끝까지 통과했다고 판단할 근거는 아직 부족하다.

### 4. 현재 바로 실행·확인할 수 있는 범위

| 실행 범위 | 가능 여부 | 확인할 수 있는 내용 | 한계 |
|---|---|---|---|
| Frontend 단독 | 가능 | 화면·fixture·반응형·분석 상태 표시 | 실제 데이터 결과를 보장하지 않음 |
| Backend fake mode | 가능 | 인증·상태 전이·G1/G2/G3·오류·Artifact·trace | 실제 DataHub·Trino·sLLM이 아님 |
| Backend versioned-trino mode | 조건부 가능 | 승인된 versioned Context와 Trino read-only 조회 | live DataHub 대신 승인 binding 사용 |
| Backend real mode | 환경 의존 | live DataHub metadata와 Trino 조회 | container health·token·DB migration 정합성 필요 |
| Report Backend API | DB 준비 시 가능 | definition/version/block/approve/manual command/history API | worker가 없어 command 이후 자동 실행은 안 됨 |
| 기획서 전체 대표 흐름 | 아직 불가 | 구성요소별 검증은 가능 | 실제 sLLM, 3-source Gold, Analysis 재실행, Report worker·Frontend 통합 필요 |

### 5. 남은 작업 우선순위

1. **3-source 대표 질문 고정:** PMS·CRM·POS를 사용하는 Gold SQL·result hash와 live/versioned Context를 일치시킨다.
2. **실제 모델 경로 검증:** 승인된 sLLM endpoint로 Node 2 Validation, latency와 실패 처리를 측정한다.
3. **Analysis 재사용 완결:** Definition·Run·Result 저장, Parameter 변경 재실행과 이력 API/UI를 연결한다.
4. **Report 실제 왕복 완결:** Frontend API integration을 `dev`에 통합하고 manual command worker, partial/retry와 history를 연결한다.
5. **최종 통합 Gate:** 대표 성공·차단·부분 실패·timeout·cancel·재시작을 동일 release SHA에서 검증한다.

## 결론

첨부 기획서 기준 현재 구현은 **약 65%**로 평가한다. 공식 WBS의 확정 완료율은 **61.6%**이며, 두 수치의 차이는 일부 진행 작업이 코드와 계약으로 존재하지만 아직 WBS `완료` 또는 통합 Gate 통과로 확정되지 않았기 때문이다.

강점은 5개 합성 Source 기반 데이터 골격, Trino read-only 경계, DataHub·Context 계약, FastAPI Control Plane, G1·G2·G3와 trace·Artifact가 이미 구체적인 코드와 테스트 구조로 구현되어 있다는 점이다. 가장 큰 미완료 구간은 실제 sLLM serving, 대표 3-source Gold E2E, Analysis 영속 재실행, Report worker와 실제 Frontend API 통합이다.

따라서 현재 프로젝트는 단순 목업 단계는 벗어났지만 완성 서비스 단계는 아니다. 다음 목표는 기능을 더 넓히는 것이 아니라, 기획서의 대표 질문 하나를 실제 DataHub/승인 binding→Trino→G3→Analysis 재실행→Report 수동 실행→Trace까지 단일 release 환경에서 끊김 없이 통과시키는 것이다. 이 경로가 통과하면 P0 구현 완성도는 약 80% 이상으로 올라갈 수 있으며, 이후 worker·schedule·복구·보안·성능과 최종 release 검증을 마쳐야 기획서의 MVP 완료로 판정할 수 있다.

## 평가 한계

- 이 문서는 2026-08-10의 저장소 코드·WBS·Gate 상태를 정적 대조한 결과다.
- 이번 문서 작성 과정에서는 전체 Docker stack, 실제 DataHub·Trino·DB, sLLM endpoint와 브라우저 E2E를 새로 기동하지 않았다.
- 테스트 파일의 존재는 확인했지만 이 문서 작성 시점에 전체 테스트를 재실행하지 않았으므로, 현재 branch의 전체 검증 상태는 `Not Run`이다.
- 개인 branch의 미통합 변경은 `dev` 구현 완료로 계산하지 않았다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-08-10 10:33 | 첨부 기획서의 P0·성공 경로를 코드·WBS·Gate와 대조해 현재 구현률과 남은 병목을 최초 평가 |
