# Answervice 프로젝트 기획서

| 항목 | 내용 |
|---|---|
| 한 줄 정의 | 여러 업무 시스템의 데이터를 자연어로 분석하고, 검증된 분석을 저장·재실행해 반복 보고에 활용하는 서비스 |
| 서비스 성격 | 범용 기업 내부 데이터 분석·리포팅 서비스 |
| 검증 도메인 | 호텔·리조트 운영 |
| 검증 데이터 | 실제 기업 데이터가 아닌 합성 데이터 |
| 이 문서의 범위 | 프로젝트가 해결할 문제, 사용자 가치, 전체 흐름, MVP와 성공 기준 |
| 읽는 순서 | 이 문서 → [시각 요약](00_Answervice_프로젝트_기획서_Visual.html) → [Core 설계](01_Answervice_데이터_분석_Core_설계.md) |

> 이 문서는 목표 설계를 설명한다. 실제 구현 완료 여부와 성능은 테스트 결과가 생긴 뒤 별도로 기록한다.

## 1. 3분 요약

### 해결할 문제

기업의 객실, 주문, 회원, 시설, 행사 데이터는 서로 다른 시스템에 흩어져 있다. 기존 대시보드에 없는 질문에 답하려면 데이터 위치, 연결 키, 지표 계산법과 권한을 다시 확인해야 한다. 한 번 만든 분석이 채팅 답변으로만 남으면 다음 보고 때 같은 작업을 반복한다.

### 해결 방식

```text
질문
→ 질문을 분석 조건으로 구조화
→ 권한 안에서 관련 데이터·업무 규칙 확인
→ G1에서 Context 완전성 확인
→ 기존 검증 분석 재사용 또는 sLLM으로 신규 SQL 생성
→ SQL 정책 검증
→ Trino 통합 조회
→ 결과 제공 전 검증
→ 표·차트·설명
→ Analysis 저장·재실행
→ Report에서 재사용
```

### 핵심 가치

1. 여러 시스템의 데이터를 연결해 기존 BI에 없는 질문에 답한다.
2. AI가 만든 SQL을 바로 실행하지 않고 생성 전·실행 전·결과 제공 전에 통제한다.
3. 검증된 분석을 일회성 답변이 아닌 재사용 가능한 업무 자산으로 남긴다.

### 대표 질문

> 지난달 골드 회원의 객실 매출과 F&B 매출을 지점별로 비교해줘.

이 질문은 멤버십·객실·F&B 세 Source, 고객 식별자 연결, 회원 등급 이력, 기간 계산, 두 매출 지표와 교차 조회를 함께 검증한다.

## 2. 누구를 위한 서비스인가

| 사용자 | 필요한 일 | Answervice가 제공하는 것 |
|---|---|---|
| 현업 분석 담당자 | 새로운 질문 분석, 반복 보고 | 자연어 질의, 근거가 있는 결과, 저장·재실행 |
| 데이터·시스템 담당자 | 데이터 경로, 규칙, 권한 관리 | Metadata, Asset Binding, Rule, Trace |
| 관리자·의사결정자 | 분석 결과 확인 | 기준 시각과 근거가 명확한 Report |

정해진 KPI를 반복 조회하는 일은 기존 BI가 더 적합할 수 있다. Answervice는 교차 데이터가 필요하거나 기존 화면에 없는 질문, 그리고 그 분석을 이후 보고에 재사용해야 하는 상황에 집중한다.

## 3. 프로젝트에서 사용할 데이터

프로젝트는 5개의 논리적 업무 Source를 4종 DBMS에 구성한다.

| 논리 Source | DBMS | 대표 데이터 | 대표 질문에서 사용 |
|---|---|---|---|
| 객실 운영 | PostgreSQL | 예약, 투숙, 객실 매출, 취소 | 사용 |
| F&B | MySQL | 주문, 결제, 환불 | 사용 |
| 멤버십 | SQL Server | 회원, 등급 이력, 고객 ID 연결 | 사용 |
| 시설 운영 | ClickHouse | 시설 이용, 점검·장애 | 별도 시나리오 |
| 연회·행사 | PostgreSQL | 행사 예약, 고객, 행사 매출 | 별도 시나리오 |

두 PostgreSQL Source는 논리적·물리적 연결을 구분하기 위해 별도 Trino catalog로 구성한다. 모든 질문에서 5개 Source를 JOIN하지 않는다. 질문에 필요한 1~3개 Source만 조회하고, 5개 Source는 연결 상태를 확인하는 smoke test에 사용한다.

## 4. 핵심 구성요소와 책임

| 구성요소 | 하는 일 | 하지 않는 일 |
|---|---|---|
| GPT Interpreter | 질문을 Metric·기간·필터·그룹으로 구조화 | 물리 테이블·JOIN·권한 결정 |
| DataHub | 테이블·컬럼·설명·도메인 등 구조적 Metadata 검색 | 프로젝트의 최종 Metric·JOIN 정책 결정 |
| Asset Binding | DataHub Dataset URN과 Trino FQN 연결 | SQL 생성·실행 |
| Business Rule | Metric·JOIN·Time·Identity 기준 관리 | 사용자 질문 해석 |
| Context Builder | 권한 범위에서 질문별 최소 Context 구성 | 자유로운 Agent 탐색 |
| sLLM | 승인 Context로 신규 Trino SQL 초안 생성 | Schema 탐색·권한 판단·실행 |
| G1 | SQL 생성 전 Context 완전성 확인 | SQL 문법 검사 |
| G2 | SQL AST·자산·정책을 확인하고 실행 허용 여부 결정 | 단독으로 전체 보안을 보장 |
| Trino | 여러 DB를 하나의 SQL로 조회 | 업무 지표와 JOIN 의미 결정 |
| G3 | 결과 구조·크기·민감정보·이상 신호 확인 | 업무 정답성 보증 |
| GPT Narrator | 안전하게 정리된 결과 설명 | 결과에 없는 숫자·인과관계 생성 |
| Analysis / Report | 분석 정의·실행·결과와 보고서 이력 보존 | 과거 결과 덮어쓰기 |

`Asset Binding`, `Business Rule`, `G1/G2/G3`는 Answervice가 정의하는 프로젝트 구성요소다. DataHub나 Trino가 자동으로 제공하는 기능명으로 오해하지 않는다.

> 제품 관점에서는 대화형 분석 에이전트라고 표현할 수 있지만, MVP 내부 구현은 멀티 에이전트가 아니라 결정론적 Orchestrator와 역할별 LLM Node로 구성한다.

## 5. 전체 서비스 흐름

### 5.1 질문 해석

GPT는 자연어 질문을 구조화된 `Business Analysis Request`로 바꾼다. 모호한 Metric, 기간, 범위가 있으면 SQL을 만들지 않고 사용자 확인 상태로 전환한다.

### 5.2 승인 Context 구성

Backend는 다음 정보를 결합한다.

```text
질문별 분석 조건
+ 권한이 허용한 Metadata
+ 활성 Asset Binding
+ Metric / JOIN / Time / Identity Rule
= Approved Context Package
```

권한 필터는 Context 단계에서 적용하고 G1·G2에서 다시 확인한다. 권한 확인을 한 지점에만 의존하지 않는다.

### 5.3 재사용 또는 신규 생성

기존 `Analysis Definition`이 같은 Metric, Dimension, Filter Schema, Join Graph와 호환되는 Rule Version을 사용하면 재사용 후보가 된다. 단, 재실행할 때 현재 사용자 권한과 현재 활성 Rule을 다시 확인하고 G1·G2를 다시 통과해야 한다.

재사용할 수 없는 질문만 sLLM이 신규 SQL 초안을 만든다.

### 5.4 SQL 검증과 조회

G2는 SQLGlot AST와 프로젝트 allowlist 정책으로 단일 조회문, 허용된 자산·컬럼·JOIN·함수만 통과시킨다. 파싱 실패나 알 수 없는 구조는 허용하지 않는 fail-closed가 기본이다.

`LIMIT`은 결과 행 수를 줄일 뿐 전체 스캔 비용을 보장하지 않는다. 따라서 다음 통제를 함께 사용한다.

- Trino access control과 허용 catalog 제한
- Source DB 전용 read-only 계정
- query timeout·resource group·scan 제한
- 결과 행·열·payload 제한
- connector passthrough, `system.execute`, procedure 경로 차단

Trino는 원본을 중앙 DB에 미리 모두 복사하지 않고 조회 시 각 Source에서 데이터를 읽는다. 다만 실행 중 데이터가 Trino worker로 이동할 수 있고, pushdown 여부에 따라 성능이 달라질 수 있다.

### 5.5 결과 검증과 설명

G3는 결과를 UI·GPT·Report에 전달하기 전에 Schema, 크기, 민감정보, JOIN 증폭 신호와 Metric invariant를 확인한다. G3는 잘못된 업무 계산을 모두 찾아내는 정답 판정기가 아니다. 최종 정답성은 별도의 Gold Result와 비교하는 E2E 평가로 측정한다.

통과한 결과만 필요한 행·열로 축소하고 masking/redaction한 뒤 GPT Narrator와 UI에 전달한다.

## 6. Analysis와 Report의 재사용 구조

### Analysis

```text
Analysis Definition   무엇을 분석하는가
        ↓
Analysis Run          누가, 언제, 어떤 기간·버전으로 실행했는가
        ↓
Analysis Result       표·차트·설명·검증 상태·근거
```

- 기간·지점·회원 등급처럼 정의된 Parameter만 바뀌면 같은 Definition으로 새 Run을 만든다.
- Metric, 그룹 기준, JOIN 의미나 분석 목적이 바뀌면 새 Definition 또는 새 Version을 만든다.
- 실제 SQL과 Parameter는 접근 통제하며, 로그와 저장본에는 Secret·불필요한 개인정보가 남지 않게 한다.
- 과거 Run과 Result는 덮어쓰지 않는다.

### Report

Report는 별도 SQL 엔진이 아니라 여러 Analysis를 묶는 실행 단위다.

```text
Report Definition
├─ Block A → Analysis Definition A
├─ Block B → Analysis Definition B
└─ Block C → Analysis Definition C
        ↓ 공통 report_as_of
Report Run
├─ Block Run A → Analysis Run A
├─ Block Run B → Analysis Run B
└─ Block Run C → Analysis Run C
```

일부 Block이 실패하면 `PARTIAL_SUCCESS`로 기록하고, 과거 성공 결과를 이번 실행의 최신 결과처럼 보여주지 않는다.

## 7. 세 Gate를 한눈에 보기

| Gate | 시점 | 통과 질문 | 실패 시 |
|---|---|---|---|
| G1 — Context Gate | SQL 생성 전 | 필요한 Metric·Dataset·Binding·JOIN·Time·Permission이 준비됐는가? | 확인 요청 또는 종료; sLLM 미호출 |
| G2 — SQL Policy Gate | SQL 실행 전 | 이 SQL이 허용된 자산과 읽기 경로만 사용하는가? | 실행 차단; 정형 오류로 최대 1회 수정 |
| G3 — Result Validation Gate | 결과 제공 전 | 결과 구조·크기·민감정보·이상 신호가 허용 범위인가? | 결과 차단 또는 명시적 실패 상태 |

## 8. MVP 범위

### P0 — 반드시 끝까지 연결

1. 자연어 질문과 구조화된 분석 요청
2. Permission-filtered Metadata와 Approved Context
3. Asset Binding과 Business Rule
4. G1 → 기존 Analysis 재사용 또는 신규 sLLM 생성 → G2
5. Trino read-only 교차 조회 → G3
6. 표·차트·설명·근거
7. Analysis 저장·Parameter 재실행·이력 보존
8. Report Block·수동 실행·부분 실패 처리
9. request_id 중심 Audit Trace
10. Golden E2E와 보안 negative test

### P1 — Core 안정화 후 판단

- 일정 기반 Report 실행
- Report Assistant 고도화
- RAG, MCP, ML-as-a-Tool

### 후순위

- Data Catalog 전용 UI
- 고급 Audit Dashboard
- Investigation Agent와 LangGraph
- Kubernetes 등 production infrastructure

## 9. 성공 기준

### 기능 성공

대표 질문이 다음 경로를 실제로 통과한다.

```text
질문 → 승인 Context → 검증 SQL → Trino 3 Source 조회
→ 결과 검증 → 설명 → Analysis 저장 → 기간 변경 재실행
→ Report 수동 실행 → Trace 확인
```

### 품질 성공

| 품질 | 측정 방식 |
|---|---|
| E2E Result Accuracy | 정렬·타입·허용 오차를 정규화한 뒤 Gold Result와 비교 |
| 보안 | 준비한 공격 corpus 차단, Source DB write 0건, 민감정보 노출 0건 |
| 재현성 | 입력·as_of·Rule/Binding/Policy/Model Version과 Query ID로 Run 추적 |
| 운영성 | 단계별 latency, 실패 코드, cancellation·timeout 확인 |

보안 테스트가 준비한 사례를 모두 통과해도 “모든 공격을 100% 막는다”고 표현하지 않는다. MVP가 정의한 위협 모델과 테스트 corpus를 통과했다고 기록한다.

## 10. 프로젝트 한계

- 합성 데이터 검증 결과를 실제 기업 환경의 성능이나 안전성으로 일반화하지 않는다.
- 실제 기업 IAM/SSO 전체를 구현하지 않는다.
- 모든 DB·SQL·질문을 지원한다고 주장하지 않는다.
- Metadata와 Rule이 잘못되면 분석 결과도 잘못될 수 있다.
- Federated query의 지연은 데이터 크기, 네트워크, connector pushdown에 영향을 받는다.
- G3 통과는 업무 정답 보증이 아니다.

## 11. 용어 지도

| 용어 | 뜻 |
|---|---|
| Source | 객실·F&B처럼 논리적으로 구분한 업무 데이터 원천 |
| Asset | DataHub에서 식별하는 Dataset |
| FQN | Trino의 `catalog.schema.table` 전체 경로 |
| Approved Context | 질문별로 허용된 Metadata·Binding·Rule·Permission 묶음 |
| Golden Scenario | 프로젝트 전체 흐름을 검증하는 대표 업무 질문 |
| Gold SQL / Result | 사람이 검토한 기준 SQL과 기대 결과 |
| sLLM | 이 프로젝트에서 Text-to-SQL 전용으로 사용하는 소형 언어 모델 후보군 |
| Trace | 요청부터 결과까지 사용한 단계·버전·상태·근거 기록 |

다음 문서: [01. 데이터·분석 Core 설계](01_Answervice_데이터_분석_Core_설계.md)
