# Hotel Signal AI 최종 방향성 및 Baseline 기획서

> 작성 기준일: 2026-07-20
> 대상: 그랜드 워커힐 서울 단일 호텔
> 프로젝트 전제: 기업 내부 시스템과 실제 내부 데이터에 접근할 수 없으며 모든 운영 데이터와 VOC는 합성 데이터로 구성
> 문서 목적: 8월 6일 중간발표 데모, 기능 Baseline, 모델 실험 트랙, 이후 확장을 명확히 분리

---

## 0. 단계 구분

8월 6일은 기능 Baseline 완료일이 아니다. **8월 6일 중간발표에서는 향후 완성할 Baseline의 두 핵심 서비스 경로를, 백엔드와 연결하지 않은 프론트엔드 목업 데모로 보여준다. Baseline 자체는 중간발표 이후 두 기능을 실제로 연결해 완성하되, 계약·데이터·기반 골격은 8월 6일 이전에 병행 준비해 Gate를 중간발표 직후(8/13~8/14)로 앞당긴다.**

프로젝트는 네 단계로 구분한다.

```mermaid
flowchart LR
    P0["0단계<br/>계약·데이터·골격 선행<br/>(~8/5, 목업과 병행)"] --> P1["1단계<br/>8월 6일 중간발표 데모"]
    P1 --> P2["2단계<br/>기능 Baseline 완성<br/>(8/7~8/14)"]
    P2 --> G{"Baseline Gate<br/>8/13~8/14"}
    G -->|"통과"| P3["3단계<br/>검토·실험·선택 확장"]
    G -->|"미통과"| F["Baseline 보완<br/>(한계선 8/18)"]
    F --> G
```

| 단계 | 목적 | 데이터·연결 수준 | 성공 기준 |
|---|---|---|---|
| 선행 준비(~8/5) | API 계약·합성 schema·권한표·정답 manifest 동결, 데이터 생성기·인증·job 골격 | 코드 골격과 데이터만, 기능 연결 없음 | 계약 문서 동결, 합성 데이터 적재·품질 Gate 통과 |
| 8월 6일 데모 | 플랫폼이 사용자에게 주는 서비스 흐름 설명 | 프론트엔드 내부 목업 데이터, 백엔드·DB·LLM 연결 없음 | 두 사용자 경로가 끊김 없이 이해됨 |
| 기능 Baseline | 플랫폼의 두 핵심 기능을 실제로 동작시킴 | 합성 DB, Django, FastAPI, LLM, 실제 Text-to-SQL·trigger·보고 workflow 연결 | §12 완료 조건 + 반례 test 16건 통과 |
| 검토·실험·확장 | 피드백 반영, 모델 실험 완성, 검증된 확장만 추가 | 필요성과 선행조건이 검증된 기능만 추가 | Baseline을 훼손하지 않고 가치·산출물이 증가함 |

기술 스택을 단순하게 만드는 것이 Baseline의 정의는 아니다. **Baseline은 플랫폼이 반드시 제공해야 하는 두 기능의 최소 완성 상태**다. Django와 FastAPI는 두 기능을 구현하기 위한 확정 기술 구성으로 사용한다. "선행 준비"는 기능 완성이 아니라 계약·데이터·골격 작업이므로 "Baseline은 중간발표 이후 구현한다"는 원칙과 충돌하지 않는다.

---

## 1. 제품 정의

### 1.1 제품 비전

> 그랜드 워커힐 서울 호텔 관리자가 자연어로 운영 현황을 조회하고, 시스템이 운영 이상징후를 먼저 감지해 근거가 연결된 주간 운영 보고서 초안을 제공하는 내부 의사결정 지원 플랫폼.

### 1.2 현재 프로젝트에서의 정확한 정의

> Hotel Signal AI는 그랜드 워커힐 서울을 대상으로 설계하지만, 실제 기업 내부 데이터나 내부 시스템을 사용하지 않는다. 프로젝트가 정의한 합성 운영 데이터와 합성 VOC를 이용해 권한 기반 대화형 분석과 이상 감지·자동 분석·주간 보고 기능이 실제로 동작하는지를 검증한다. 따라서 결과는 실제 그랜드 워커힐 서울의 현황·문제·성과를 의미하지 않는다.

### 1.3 사용자와 시스템 경계

| 구분 | 역할 |
|---|---|
| 1차 사용자 | 호텔 관리자: 전체 운영 현황 조회, 보고서 검토·승인 |
| 보조 사용자(데모 역할) | F&B 관리자·객실 관리자: 담당 범위 질의와 이슈 확인 — 실제 조직 직책이 아니라 권한 차이를 검증하기 위한 데모 역할 |
| 시스템 밖 | 본사 경영진, 본사 보고 전달, 실제 운영 조치 실행 |

호텔 관리자가 시스템 안에서 보고서를 승인한 뒤 본사 보고에 활용할 수는 있지만, 전송·보고·본사 의사결정은 프로젝트 범위 밖의 수동 업무다. 시스템의 종료 지점은 호텔 관리자의 승인·보류·반려 결정이다.

---

## 2. 기업 내부 데이터에 접근할 수 없다는 사실의 반영

### 2.1 확인할 수 없는 것

- 실제 PMS·POS·CRM·근태·VOC 시스템의 schema와 API
- 실제 예약, 투숙, 매출, 대기시간, 인력, 고객 불만 수치
- 데이터 table 간 실제 연결 키와 갱신 주기
- 호텔 내부 부서명, 직무, 실제 권한 정책
- 호텔 관리자가 실제 사용하는 KPI와 주간 보고서 양식
- 현업의 실제 이상징후 임계값과 대응 절차
- 공유 시설의 데이터 소유권과 호텔별 이용객 식별 방법

### 2.2 프로젝트가 실제로 할 수 있는 것

- 공개된 호텔 정보를 범위와 도메인 용어 참고에 사용
- 프로젝트가 정의한 schema로 합성 데이터 생성
- 정상·이상·충돌·결측 상황을 의도적으로 주입
- 합성 데이터 안에서 Text-to-SQL, 권한 필터, 이상 감지, 근거 수집, 보고서 생성을 실제 코드로 실행
- 실제 데이터가 들어온다는 가정 아래 필요한 interface와 검증 절차 설계
- 실제 연동 전 발견해야 할 데이터 계약·보안·운영 위험 제시

### 2.3 프로젝트가 주장하면 안 되는 것

- 실제 그랜드 워커힐 서울에 특정 운영 문제가 발생했다.
- 실제 직원 배치가 부족하거나 실제 고객 불만이 증가했다.
- 플랫폼 도입으로 실제 비용이나 업무시간이 감소했다.
- 실제 호텔 권한 정책을 구현했다.
- 실제 운영 데이터를 실시간으로 감시한다.
- 합성 데이터에서 함께 움직인 지표가 실제 원인이다.

### 2.4 모든 결과에 포함할 표시

```text
SYNTHETIC DEMO DATA
본 결과는 그랜드 워커힐 서울의 실제 운영 데이터가 아니라
프로젝트가 생성한 합성 데이터에 기반합니다.
```

다음 metadata를 화면·API·보고서에 공통으로 포함한다.

```text
is_synthetic
dataset_version
schema_version
generator_version
scenario_id
seed
virtual_as_of_date
data_cutoff
```

### 2.5 공개 정보의 사용 경계

공식 소개 페이지는 그랜드 워커힐 서울을 557개 객실과 6개 레스토랑을 갖춘 호텔로 소개한다(2026-07-20 재확인). 객실 수는 합성 객실 재고의 공개 참고값으로 사용할 수 있지만, 점유율·투숙객·조식·인력·VOC 값은 전부 합성해야 한다. [그랜드 워커힐 서울 공식 소개](https://www.walkerhill.com/grandwalkerhillseoul/en/about/Walkerhill?tabIdx=1)

The Buffet과 Grand Club처럼 호텔·시설 이용 관계가 복잡한 공개 사례가 있지만, 실제 이용객 귀속 키를 확인할 수 없으므로 Baseline 운영 데이터에서는 실제 시설명을 사용하지 않는다. 조식 시나리오의 서비스 구역은 `GW_BREAKFAST_DEMO`라는 합성 식별자로 정의한다.

---

## 3. 1단계: 8월 6일 중간발표 데모

### 3.1 목적

8월 6일에는 개발 진행률을 나열하거나 미완성 backend를 시연하지 않는다. **사용자가 Hotel Signal AI에서 어떤 경험을 하고, 두 핵심 기능이 어떻게 하나의 플랫폼으로 연결되는지**를 보여준다.

### 3.2 구현 경계

| 구분 | 중간발표 데모 |
|---|---|
| Frontend | 클릭 가능한 별도 데모 화면 |
| 데이터 | frontend 내부 JSON·TypeScript fixture |
| Django / FastAPI / PostgreSQL | 연결하지 않음 |
| LLM·Agent | 호출하지 않음 |
| Text-to-SQL | 생성된 것처럼 보이는 사전 작성 결과 |
| 이상 감지 | 사전 정의된 scenario를 화면 상태로 표현 |
| 자동 보고 | 사전 작성 report fixture를 workflow처럼 표현 |
| 인증 | 실제 인증이 아니라 역할 선택 또는 가상 로그인 화면 |

### 3.3 데모에서 유지할 실제 계약

**7월 26일까지 Baseline API 응답 JSON schema v0(job 계약 포함)를 동결하고, 목업 fixture는 이 schema를 그대로 준수해 작성한다.** 목업 제작이 계약보다 먼저 시작되면 fixture를 재사용할 수 없으므로 순서를 뒤집지 않는다. fixture는 CI에서 schema v0 자동 validation을 통과해야 한다.

공통 유지 필드:

- `role_code`, `dataset_version`, `query_run_id`, `job_id`, `job_status`
- `query_plan`, `chart_spec`, `evidence[]`
- `incident_status`, `report_status`, `limitations[]`
- `is_synthetic=true`, `demo_mode=true`

### 3.4 중간발표 데모 서비스 흐름

```mermaid
flowchart TB
    START["데모 시작"] --> ROLE["가상 역할 선택"]
    ROLE --> HOME["호텔 운영 홈"]

    HOME --> Q1["경로 A<br/>자연어 질문 입력"]
    Q1 --> Q2["목업 SQL 처리 화면"]
    Q2 --> Q3["표·차트·설명 확인"]

    HOME --> R1["경로 B<br/>이상징후 알림 선택"]
    R1 --> R2["분석 진행 단계 확인"]
    R2 --> R3["이슈 브리프 확인"]
    R3 --> R4["주간 보고서 초안 확인"]
    R4 --> R5["호텔 관리자 승인·보류·반려"]
```

두 경로 사이에 선을 억지로 합치지 않는다. 대화형 분석은 사용자 질문에 대한 결과로 끝나고, 자동 보고 경로는 호텔 관리자 결정으로 끝난다.

### 3.5 화면 구성

| 순서 | 화면 | 보여줄 내용 |
|---:|---|---|
| 1 | 가상 로그인·역할 선택 | 호텔 관리자, F&B 관리자, 객실 관리자 |
| 2 | 운영 홈 | 합성 데이터 표시, 질의 진입, 이상징후 카드 |
| 3 | 대화형 분석 | 질문, 목업 SQL, 표, 차트, 설명, 권한 범위 |
| 4 | 이상징후 상세 | 감지 지표, 비교 기간, 데이터 상태 |
| 5 | 이슈 브리프 | 관측 사실, 원인 후보, 반대 근거, 추가 확인 |
| 6 | 주간 보고서 | 초안, 근거 ID, 한계, 승인·보류·반려 |

### 3.6 데모 시나리오

#### 경로 A: 권한 기반 대화형 분석

```text
F&B 관리자 역할 선택
→ "이번 주 조식 대기시간이 지난 4주보다 길어진 시간대를 보여줘"
→ 지원 지표와 권한 범위 표시
→ 목업 SQL과 분석 진행 상태
→ 시간대별 line chart와 요약
→ 합성 데이터·기간·단위·근거 표시
```

객실 관리자 역할에서는 같은 질문을 거부하거나 집계 수준만 보여줘 권한 차이를 시각적으로 설명한다.

#### 경로 B: 이상 감지·자동 분석·주간 보고

```text
운영 홈에 조식 대기 이상징후 카드 표시
→ 감지 규칙과 비교 기간 확인
→ 운영지표·인력·VOC 조사 단계 표시
→ 관측 사실·원인 후보·반대 근거 확인
→ 주간 보고서 초안 확인
→ 호텔 관리자 승인·보류·반려
```

### 3.7 발표 표현

```text
이번 중간발표 데모는 실제 backend나 실제 호텔 데이터를 연결한 결과가 아닙니다.
합성 fixture를 사용해 Hotel Signal AI가 완성됐을 때 제공할 두 핵심 사용자 경험을 보여줍니다.
중간발표 이후 동일한 화면·응답 계약에 Django, FastAPI, PostgreSQL과 실제 분석 workflow를 연결합니다.
```

---

## 4. 2단계: 기능 Baseline

Baseline은 기술 개수나 화면 수가 아니라 다음 두 기능이 실제로 끝까지 동작하는 상태다.

### 4.1 기능 A — 권한 기반 대화형 분석

> 사용자가 자연어로 질문하면 그랜드 워커힐 서울을 모델링한 합성 데이터 중 자신의 데모 권한 범위에 해당하는 데이터만 Text-to-SQL로 조회하고 표·차트·설명을 제공한다.

필수 기능:

1. Django 실제 로그인
2. 데모 역할·권한 정책
3. 질문 job 생성과 `job_id` 즉시 반환 (job+polling 계약)
4. Django가 검증한 scope와 함께 FastAPI 호출
5. FastAPI의 지표·기간·차원 해석 (semantic query plan)
6. semantic catalog 기반 SQL 생성과 안전성·권한·범위 검증
7. PostgreSQL analysis view read-only 조회
8. 표·차트 specification 생성
9. 수치 근거와 제한사항(기간·단위·표본·timezone)을 포함한 설명
10. 질문·scope·SQL hash·결과 감사 이력

### 4.2 기능 B — 이상 감지·자동 분석·주간 보고

> 그랜드 워커힐 서울을 모델링한 합성 운영 데이터에서 이상징후가 감지되면 분석 workflow가 관련 운영지표와 합성 VOC를 조사해 이슈 브리프와 주간 운영 보고서 초안을 자동 생성한다.

필수 기능:

1. 합성 데이터 batch 적재 완료 이벤트
2. 데이터 품질 Gate — **FastAPI 결정론 모듈에서 실행** (감지보다 먼저)
3. 결정론적 규칙 기반 이상 감지 — **FastAPI 결정론 모듈, versioned rule, 임계값은 `PROJECT_CALIBRATION` 표기**
4. 분석 job 생성과 상태 관리 (Django worker)
5. FastAPI Incident 분석 workflow 실행 (LangGraph)
6. 객실·조식·인력·VOC 관련 근거 수집
7. 관측 사실·원인 후보·반대 근거·데이터 한계 구성 (수치는 결정론 계산)
8. 주간 보고서 초안 생성 (LLM은 서술만)
9. Django 보고서 저장·version 관리
10. 호텔 관리자 승인·보류·반려

### 4.3 Baseline 실행 경로에서 제외하는 것

- 본사 경영진 계정·대시보드·자동 전송
- 실제 PMS·POS·CRM·근태·VOC 연결
- 실제 온라인 리뷰 crawling
- 실제 고객·직원 개인 데이터
- 실제 실시간 streaming
- 다지점·다호텔 비교
- 조치 자동 실행, 고객 메시지·보상·인력 배치 자동화
- GraphDB·GraphRAG·full ontology
- 장기 memory·에이전트 토론·swarm
- 범용 MCP server
- 수요·매출·이탈 예측

모델·검색 실험(VOC 분류 모델 비교, 벡터DB 검색, sLLM 비교, 멀티 에이전트 구성 비교)은 제외 대상이 아니라 §10.3의 실험 트랙에서 별도로 수행한다.

---

## 5. Baseline 서비스 흐름

### 5.1 전체 서비스 흐름

```mermaid
flowchart TB
    USER["호텔 내부 사용자"] --> AUTH["Django 로그인·역할 확인"]
    AUTH --> HOME["Hotel Signal AI 홈"]

    HOME --> CHAT["경로 A<br/>권한 기반 대화형 분석"]
    CHAT --> CHAT_RESULT["표·차트·설명·근거"]

    DATA["합성 운영 데이터 batch"] --> DETECT["경로 B<br/>품질 Gate·규칙 감지<br/>(FastAPI 결정론 모듈)"]
    DETECT --> BRIEF["이슈 브리프·보고서 초안"]
    BRIEF --> REVIEW["호텔 관리자 검토"]
    REVIEW --> DECISION["승인·보류·반려"]

    HOME --> INCIDENTS["이상징후·보고서 목록"]
    INCIDENTS --> REVIEW
```

### 5.2 경로 A 상세 sequence

```mermaid
sequenceDiagram
    actor User as 호텔 사용자
    participant UI as Frontend
    participant DJ as Django
    participant W as Django Worker
    participant AI as FastAPI
    participant DB as PostgreSQL 분석 View

    User->>UI: 자연어 질문
    UI->>DJ: POST /api/query-jobs
    DJ->>DJ: 로그인·역할·허용 scope 확인, job 생성(PENDING)
    DJ-->>UI: job_id 즉시 반환
    W->>AI: POST /internal/v1/query-runs<br/>(질문+scope_snapshot+dataset_version)
    AI->>AI: Query Plan 생성·정책 검증
    AI->>DB: read-only SQL 실행
    DB-->>AI: 집계 결과
    AI->>AI: 수치 검증·차트·설명 구성
    AI-->>W: 구조화된 분석 결과(JSON schema)
    W->>DJ: 결과·감사 이력 저장(SUCCEEDED)
    UI->>DJ: GET /api/jobs/{job_id} (polling)
    DJ-->>UI: 상태·표·차트·설명·근거
    UI-->>User: 권한 범위 결과 표시
```

### 5.3 경로 B 상세 sequence

```mermaid
sequenceDiagram
    participant DB as PostgreSQL
    participant W as Django Job Worker
    participant AI as FastAPI
    participant LLM as LLM API
    actor Manager as 호텔 관리자

    DB-->>W: 합성 batch READY(내부 이벤트)
    W->>W: idempotency_key로 중복 실행 차단
    W->>AI: 품질 Gate 실행 요청(결정론·비LLM)
    AI->>DB: analytics read-only 검사 조회
    AI-->>W: 품질 결과(통과 / NEEDS_DATA)
    W->>AI: 규칙 기반 감지 요청(versioned rule·비LLM)
    AI-->>W: trigger 판정·incident 후보
    W->>AI: POST /internal/v1/incident-runs (scope 포함)
    AI->>DB: 관련 지표·VOC read-only 조회
    AI->>AI: 관측 사실·반대 근거 결정론 계산
    AI->>LLM: 계산된 근거로 서술 초안만 요청
    LLM-->>AI: 구조화된 보고서 문장(실패 시 PARTIAL)
    AI-->>W: 이슈 브리프·보고서 초안
    W->>DB: DRAFT·evidence·version 저장
    W-->>Manager: 검토 요청
    Manager->>W: 승인·보류·반려와 메모
    W->>DB: 결정 이력 저장
```

`batch READY`는 실제 PMS 이벤트가 아니다. 합성 dataset 적재가 완료됐음을 나타내는 프로젝트 내부 이벤트다. Django worker는 orchestration·상태 관리만 담당하며 analytics view를 직접 읽지 않는다.

---

## 6. Baseline 시스템 아키텍처

### 6.1 전체 구조

```mermaid
flowchart LR
    subgraph CLIENT["Client"]
        UI["Frontend<br/>대화·차트·이슈·보고 검토"]
    end

    subgraph DJANGO["Django Service"]
        GATE["Public API Gateway"]
        AUTH["Authentication·RBAC"]
        JOB["Job·Report·Approval"]
        WORKER["Background Worker"]
    end

    subgraph FASTAPI["FastAPI AI Service"]
        DQ["품질 Gate·규칙 감지<br/>(결정론·비LLM)"]
        QUERY["Query Workflow<br/>(명시적 pipeline)"]
        INCIDENT["Incident Analysis Workflow<br/>(LangGraph)"]
        GUARD["Semantic Catalog·SQL Guard"]
        MODEL["LLM·Model Gateway"]
    end

    subgraph POSTGRES["PostgreSQL"]
        CORE["core·reporting schema"]
        ANALYTICS["synthetic analytics views<br/>(read-only)"]
        AUDIT["run·evidence·audit"]
    end

    EXT["External LLM API"]

    UI --> GATE
    GATE --> AUTH
    GATE --> JOB
    JOB --> CORE
    JOB --> WORKER
    WORKER --> DQ
    WORKER --> QUERY
    WORKER --> INCIDENT
    DQ --> ANALYTICS
    QUERY --> GUARD
    INCIDENT --> GUARD
    GUARD --> ANALYTICS
    QUERY --> MODEL
    INCIDENT --> MODEL
    MODEL --> EXT
    WORKER --> AUDIT
```

호출 방향은 `Client → Django → FastAPI → Data/LLM`으로 고정한다. analytics 접근은 FastAPI의 read-only DB role로 일원화하고, LLM은 감지·계산 경로에 존재하지 않는다.

### 6.2 Django의 책임

- 외부에 노출되는 유일한 backend
- 사용자 로그인·세션 또는 token
- 사용자·역할·권한 정책의 원본
- FastAPI로 전달할 scope 생성
- query·analysis job 생성과 상태 관리 (worker orchestration)
- 보고서·승인·보류·반려·version 저장
- 사용자에게 결과 제공, 감사 이력과 접근 로그 관리

Django의 인증 시스템은 인증과 권한을 함께 제공하며 custom permission 확장이 가능하다. [Django 인증 공식 문서](https://docs.djangoproject.com/en/5.2/topics/auth/default/)

### 6.3 FastAPI의 책임

- **데이터 품질 Gate와 규칙 기반 이상 감지 (결정론·비LLM 모듈)**
- 자연어 질문을 semantic query plan으로 변환
- Text-to-SQL 생성·검증·실행
- 데이터 분석과 evidence 구성 (수치는 결정론 계산)
- Incident workflow의 LangGraph 실행, Query workflow의 명시적 pipeline 실행
- LLM 호출 (서술·해석 한정)
- 차트 specification과 보고서 초안 생성
- JSON schema에 맞는 결과만 Django에 반환

FastAPI는 I/O 대기가 많은 API를 비동기로 구성하기 편리하지만, FastAPI 사용 자체가 background job의 내구성을 보장하지 않으므로 job 상태는 Django DB가 관리한다. [FastAPI async 공식 문서](https://fastapi.tiangolo.com/async/)

### 6.4 경계 규칙

1. Browser는 FastAPI를 직접 호출하지 않는다.
2. FastAPI는 로그인·사용자·실제 역할을 자체 관리하지 않는다.
3. Django가 검증한 `scope_snapshot`만 FastAPI에 전달한다.
4. FastAPI는 합성 analysis view에 read-only DB role로 접근한다.
5. FastAPI는 보고서 승인 table을 수정할 수 없다.
6. Django와 FastAPI 계약은 versioned Pydantic schema로 고정한다.
7. 모든 요청에 `request_id`, `run_id`, `dataset_version`을 포함한다.
8. 내부 API는 service credential과 network restriction으로 보호한다.
9. worker→FastAPI 호출에 timeout 상한(LLM 포함, `PROJECT_CALIBRATION` 값)·retry 횟수·backoff를 계약으로 명시한다. retry는 `idempotency_key` 기반으로만 수행한다.

### 6.5 Job 처리

Baseline은 Django DB job table과 별도 worker process로 시작한다.

```text
PENDING → RUNNING → SUCCEEDED
                  ↘ PARTIAL
                  ↘ NEEDS_DATA
                  ↘ FAILED
```

- 사용자 HTTP 요청은 job 생성 후 즉시 `job_id`를 반환한다.
- worker가 FastAPI를 호출하고, UI는 Django에서 상태를 polling한다.
- 같은 입력의 중복 실행은 `idempotency_key`로 차단한다.
- Celery·Redis는 동시 작업량과 재시도 요구가 측정된 뒤에만 확장한다.

---

## 7. 합성 데이터 설계

### 7.1 합성 데이터의 역할

합성 데이터는 실제 호텔 데이터의 복사본이 아니라 다음을 검증하기 위한 **통제 가능한 시험 데이터**다.

- 권한에 따라 다른 결과가 나오는가?
- 자연어 질문이 올바른 지표·기간·차원으로 변환되는가?
- 이상징후가 재현 가능하게 감지되는가?
- 분석 결과가 원인 확정 없이 근거와 한계를 보여주는가?
- 보고서 수치가 원본 집계와 일치하는가?
- 결측·충돌·오류에서 안전하게 멈추는가?

### 7.2 데이터 도메인

Baseline에는 네 가지 합성 데이터만 사용한다.

| 도메인 | 필요한 이유 | 제외하는 정보 |
|---|---|---|
| 객실 운영 | 조식 예상 수요의 상위 맥락과 점유 추이 | 실제 요금·고객명·예약번호 |
| 조식 운영 | 대기·도착·처리량 이상 감지 | 실제 영업장명·결제 정보 |
| 조식 인력 | 운영지표와 함께 조사할 후보 근거 | 직원명·근태 사유·개인 평가 |
| VOC | 대기 이슈의 고객 관측 근거 | 실제 리뷰 원문·작성자·계정 |

매출, ADR, RevPAR, 시설 전체 이용, 날씨, 행사, 온라인 crawling은 핵심 조식 시나리오를 완성한 뒤 필요성이 확인되면 확장한다.

### 7.3 데이터 생성 흐름

```mermaid
flowchart LR
    A["가정 문서<br/>공개 사실·프로젝트 가정 분리"] --> B["고정 seed 생성기"]
    B --> C["정상 12주 데이터<br/>(소폭 noise·미미한 결측 기본 포함)"]
    C --> D["이상·충돌·결측 scenario 주입"]
    D --> E["품질 Gate 검증<br/>(§7.6 체크 목록)"]
    E --> F["PostgreSQL 적재"]
    F --> G["정답 manifest와 회귀 test"]
```

### 7.4 최소 schema

**공통 규칙**: 모든 timestamp는 **UTC로 저장하고 Asia/Seoul로 표시**한다. `bucket_start` 등 시간 필드는 timezone-aware로 정의한다. 모든 결과 화면에 관측 창·비교 창·집계 단위·표본 수·timezone을 표시한다.

#### metadata

| 테이블 | grain | 주요 필드 |
|---|---|---|
| `dataset_manifest` | dataset version | `dataset_version`, `schema_version`, `generator_version`, `seed`, `scenario_id`, `virtual_period`, `is_synthetic` |
| `dim_date` | 1일 | `service_date`, `day_of_week`, `is_weekend`, `virtual_week_id` |
| `dim_service_area` | 서비스 구역 | `service_area_id=GW_BREAKFAST_DEMO`, `display_name`, `is_synthetic` |

#### facts

| 테이블 | grain | PK | 주요 필드 |
|---|---|---|---|
| `fact_rooms_daily` | 호텔·일 | `dataset_version, service_date` | `room_inventory`, `rooms_out_of_order`, `rooms_available`, `rooms_sold`, `rooms_unsold`(도출·검사용), `inhouse_guests`, `breakfast_entitled_guests` |
| `fact_breakfast_15m` | 서비스 구역·15분 | `dataset_version, service_area_id, bucket_start` | `expected_arrivals`, `actual_arrivals`, `service_capacity`, `seated_guests`, `avg_wait_min`, `p90_wait_min`, `max_queue_length` |
| `fact_breakfast_daily` | 서비스 구역·일 | `dataset_version, service_area_id, service_date` | `arrivals_total`, `capacity_total`, `avg_wait_min`, `p90_wait_min`(생성기 내부 시뮬레이션에서 직접 산출), `voc_negative_count` |
| `fact_staff_shift` | 서비스 구역·일·shift | `dataset_version, service_date, service_area_id, shift_code` | `planned_headcount`, `actual_headcount`, `absence_count`, `labor_minutes` |
| `fact_voc` | VOC 1건 | `voc_id` | `received_at`, `occurred_at`(`occurred_at ≤ received_at` 제약), `service_area_id`, `topic_code`, `sentiment_label`, `review_text`, `is_synthetic` |

**p90 규칙**: p90 등 비가산 지표는 15분 bucket 값을 재집계하지 않는다. 일·주 단위 p90은 생성기가 내부 시뮬레이션에서 직접 산출해 `fact_breakfast_daily`(및 주간 view)에 저장한 값만 사용한다. `metric_catalog`에 지표별 `additive` flag와 허용 grain을 명시하고, 비가산 지표의 bucket 평균 재집계를 SQL Guard에서 차단한다.

#### platform

| 테이블 | 주요 역할 |
|---|---|
| `metric_catalog` | 지표 정의, 계산식, 단위, `additive` flag, 허용 grain·차원·동의어 |
| `role_scope` | 데모 역할별 허용 metric·view |
| `query_run` | 질문, plan, SQL hash, 결과 상태 |
| `analysis_run` | trigger와 조사 workflow 상태 |
| `evidence` | 수치·VOC·반대 근거 연결 |
| `report` | 주차별 초안·승인본과 version |
| `report_decision` | 승인·보류·반려와 메모 |

### 7.5 생성 기준

공개 사실은 객실 총재고 참고값 정도로 제한한다. 나머지는 모두 `PROJECT_ASSUMPTION`으로 관리한다.

```text
rooms_available = room_inventory - rooms_out_of_order
rooms_sold <= rooms_available
rooms_unsold = rooms_available - rooms_sold  (정합 검사용)
inhouse_guests = rooms_sold × 합성 객실당 인원 분포 (분포 최솟값 1 보장)
breakfast_entitled_guests <= inhouse_guests
15분 도착 합계 <= breakfast_entitled_guests  (walk-in 유료 조식 미허용으로 확정)
queue_t = max(0, queue_(t-1) + arrivals_t - service_capacity_t)
wait_time = queue와 service_capacity의 함수 + 제한된 noise
occurred_at <= received_at
negative_wait_voc_probability = 대기시간 증가에 따라 완만하게 증가 + noise
```

수식의 계수와 **탐지 규칙의 임계값·최소 표본은 모두 실제 호텔 운영 기준이 아니라 `PROJECT_CALIBRATION` 값**으로 표기한다. generator config와 가정 문서에 기록하고 seed와 함께 version을 고정한다.

**생성·탐지 규칙 분리**: 탐지 규칙은 생성 수식을 참조하지 않고 "비교 창 대비 관측 창 통계"만으로 독립 작성한다. 규칙 파일과 generator config는 서로 다른 팀원이 교차 리뷰한다. 정답 manifest는 test 전용 경로에 두고 FastAPI 실행 환경에 마운트하지 않아 Agent 접근을 물리적으로 차단한다.

### 7.6 데이터 품질 Gate 체크 목록 (batch READY 후, 감지 이전 실행)

1. `rooms_available = room_inventory - rooms_out_of_order`, `rooms_sold ≤ rooms_available`
2. 판매 객실이 있는 일자에 `inhouse_guests ≥ rooms_sold` (객실당 최소 1명)
3. `breakfast_entitled_guests ≤ inhouse_guests`, 15분 도착 합계 ≤ `breakfast_entitled_guests`
4. 대기시간·처리량·대기열 음수 0건
5. 15분 bucket 합계 = `fact_breakfast_daily` 일 합계 (가산 지표만)
6. `occurred_at ≤ received_at`, FK 고아 0건, PK 중복 0건
7. 필수 시간 bucket 누락 시 해당 구간 `NEEDS_DATA` 마킹 (보간 금지)

### 7.7 필수 scenario

| scenario | 주입 | 기대 결과 |
|---|---|---|
| `NORMAL` | 정상 변동(소폭 noise 포함) | 이상징후 없음 |
| `BREAKFAST_CONGESTION` | 피크 도착 집중·합성 처리량 감소 | 이상징후와 보고 초안 생성 |
| `VOC_ONLY_SPIKE` | 대기 운영지표는 정상, 부정 VOC만 증가 | 근거 충돌·원인 확정 금지 |
| `OPS_ONLY_SPIKE` | 대기 증가, VOC 표본 부족 | 운영 이상 표시·VOC 근거 부족 표시 |
| `MISSING_DATA` | 핵심 시간 bucket 누락 | `NEEDS_DATA` |
| `ROLE_FORBIDDEN` | 객실 역할이 조식 인력 상세 질문 | 실행 거부 |
| `DUPLICATE_BATCH` | 동일 batch 두 번 입력 | incident·report 한 건만 생성 |
| `LLM_TIMEOUT` | 서술 호출 실패 | 수치 근거 보존·`PARTIAL` |

### 7.8 정답 manifest

```yaml
scenario_id: BREAKFAST_CONGESTION
dataset_version: gw-synthetic-1.0.0
expected_trigger: true
expected_status: READY_FOR_REVIEW
required_evidence:
  - wait_p90_min
  - breakfast_arrivals
  - service_capacity
  - negative_wait_voc_rate
forbidden_claims:
  - 실제 호텔에서 인력 부족이 발생했다
  - 합성 인력 감소가 유일한 원인이다
```

생성기가 남긴 정답 manifest는 test에서만 사용하며 분석 Agent에게 제공하지 않는다.

---

## 8. 권한 기반 Text-to-SQL

### 8.1 데모 권한

실제 기업 권한을 알 수 없으므로 프로젝트 정책으로 정의한다.

| 역할 | 허용 범위 |
|---|---|
| `HOTEL_MANAGER` | 모든 합성 집계 지표와 보고서 |
| `FNB_MANAGER` | 조식 운영·조식 인력·조식 VOC |
| `ROOMS_MANAGER` | 객실 집계·객실 VOC·제한된 조식 수요 요약 |

### 8.2 처리 방식

LLM이 raw SQL을 마음대로 만들기 전에 semantic query plan을 생성한다.

```json
{
  "intent": "compare_metric",
  "metrics": ["wait_p90_min"],
  "dimensions": ["time_bucket"],
  "period": "last_completed_week",
  "comparison": "previous_4_weeks",
  "filters": {"service_area_id": "GW_BREAKFAST_DEMO"}
}
```

FastAPI는 Django가 전달한 scope와 `metric_catalog`를 이용해 허용 view의 SQL만 생성·실행한다.

필수 보호 장치:

- `SELECT` only, 단일 statement
- 허용 schema·view·column allowlist, parameter binding
- 고정 row limit·statement timeout, read-only DB role
- 역할 scope 검증, 범위 밖 질문은 SQL을 실행하지 않음
- 비가산 지표의 금지 재집계 차단 (`metric_catalog.additive` 기준)
- 질문·plan·SQL hash·row count 감사 로그

### 8.3 보장 질문 범위

Baseline은 완전 자유형 BI가 아니다. 다음 의도를 우선 보장한다.

1. 특정 기간 KPI 조회
2. 전주·최근 4주 비교
3. 일별 추이
4. 시간대별 조식 도착·대기
5. 조식 처리량·대기 비교
6. 조식 인력·대기 비교
7. 주제·감성별 VOC 조회
8. 이상징후의 근거 조회

결과에는 기간, 단위, 표본 수, timezone, dataset version, data cutoff, query ID를 포함한다.

---

## 9. 이상 감지·분석 Agent·보고서

### 9.1 역할 분리

| 구성 | AI Agent 여부 | 실행 위치 | 책임 |
|---|---|---|---|
| 데이터 품질 검사 | 아니오 | FastAPI 결정론 모듈 | §7.6 체크 목록 검사 |
| 이상 감지 | 아니오 | FastAPI 결정론 모듈 | versioned rule로 trigger 판정 (임계값 = `PROJECT_CALIBRATION`) |
| Query workflow | 예 | FastAPI 명시적 pipeline | 질문 해석·결과 설명 |
| Incident Analysis workflow | 예 | FastAPI LangGraph | 조사 계획·근거 선택·보고 초안 |
| KPI 계산 | 아니오 | FastAPI (SQL·Python) | 결정론적 계산 |
| 최종 원인·조치 결정 | 아니오 | 시스템 밖 | 호텔 관리자가 수행 |

LLM은 수치 계산과 이상 여부 판정을 수행하지 않는다. LLM의 서술 출력은 evidence_id가 연결된 문장만 노출하며, 근거에 없는 주장은 schema 검증에서 차단하고 재생성 또는 `PARTIAL` 처리한다.

### 9.2 조사 결과 구조

```text
감지 요약
관측 사실
원인 후보
후보를 지지하는 근거
반대·충돌 근거
부족한 데이터
현장 확인 과제
대응 옵션
분석 한계
evidence_id 목록
```

Agent는 "원인을 발견했다"가 아니라 "같은 기간에 함께 관측되어 확인이 필요한 후보"라고 표현한다. 운영지표만 증가, VOC만 증가, 두 근거 충돌의 세 경우를 구분해 표시한다.

### 9.3 보고서 상태

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> APPROVED: 호텔 관리자 승인
    DRAFT --> ON_HOLD: 추가 확인 필요
    DRAFT --> REJECTED: 근거 부족·오류
    ON_HOLD --> DRAFT: 보완 후 새 version
    APPROVED --> [*]
    REJECTED --> [*]
```

승인 전 보고서는 항상 "DRAFT·합성" 표시를 유지하며 본사 보고용 확정본으로 표현하지 않는다.

---

## 10. 온톨로지·RAG·MCP·모델 실험

### 10.1 Baseline 실행 경로 판정

| 항목 | 결정 | 이유 |
|---|---|---|
| semantic catalog | 포함 | 지표 정의·동의어·join·권한을 Text-to-SQL에 제공 |
| LangGraph | **기능 B 한정 포함** | Incident workflow의 상태·분기·retry 관리에 실제 필요. 기능 A는 분기가 단순해 명시적 pipeline로 구현 |
| 논리 Agent 2개 | 포함 | 대화형 분석과 자동 보고의 책임이 다름 |
| 정식 OWL ontology | 제외(확장) | 실제 관계·추론 요구가 아직 없음 — PostgreSQL 기반 catalog로 충족 |
| RAG | 제외(확장) | 내부 SOP·보고서 corpus에 접근할 수 없음 |
| Vector DB | **실행 경로 제외 · 실험 트랙에서 수행(§10.3)** | Golden Path 의존성으로 두지 않고 별도 실험으로 검증 |
| MCP runtime | 제외(확장) | 연결할 실제 내부 시스템이나 재사용 client가 없음 |
| Agent swarm | 제외 | Baseline 정확성과 재현성에 도움이 되지 않음 |

### 10.2 확장 조건

- 실제 SOP·매뉴얼이 확보되면 RAG 검토
- 다수 시스템·Agent client가 같은 도구를 사용하면 MCP adapter 검토 (read-only 도구부터: `query_metrics`, `get_evidence`, `get_report_context`)
- 다호텔·공유 시설·복잡한 관계 추론이 필요하면 정식 ontology·GraphDB 검토
- 독립 Agent가 별도 평가와 접근 권한을 가져야 하면 역할 추가

### 10.3 모델·검색 실험 트랙

플랫폼의 모델 선택과 향후 기능 후보를 검증하기 위해 다음 네 가지 실험을 Baseline 구현과 병행해 수행하고, 결과를 보고서로 남긴다. 실험은 서비스의 정확성·재현성을 해치지 않도록 **실행 경로와 분리**해 진행한다.

**실험 운영 원칙**

1. 실험 코드는 `experiments/` 디렉터리로 분리하고 Baseline 런타임이 import하지 않는다.
2. Golden Path 회귀 test는 실험 코드가 없는 상태에서도 전부 통과해야 한다.
3. 실험이 실패해도 Baseline 완료 조건에 영향을 주지 않는다.
4. 실험 결과를 화면에 노출할 경우 "참고" 섹션으로만 표시하고 판정·수치 근거에 사용하지 않는다.

**실험 계획**

| 실험 | 설계 | Baseline과의 관계 | 산출물 |
|---|---|---|---|
| VOC 분류 모델 비교 (ML/DL 2종) | 합성 VOC의 감성·주제 분류를 고전 ML(예: TF-IDF+로지스틱 회귀)과 DL(예: 한국어 사전학습 모델 미세조정)로 오프라인 비교. 학습 데이터는 공개 한국어 리뷰 corpus(공개 데이터셋 활용 — 특정 호텔 리뷰 crawling 아님) 또는 라벨 규칙이 분리된 합성 VOC | 런타임의 `sentiment_label`은 생성 규칙 값을 사용. 모델 출력은 별도 필드 기록만, 감지·판정에 미사용 | ML/DL 학습결과서·학습 모델 |
| 벡터DB 기반 유사 VOC 검색 | pgvector로 합성 VOC `review_text` 임베딩 색인 → 유사 사례 검색 품질 평가 | 이슈 브리프의 "참고" 섹션에만 선택 노출. 검색 실패 시 SQL 조회로 fallback — 단일 실패점 아님 | 벡터DB 구축 결과서 |
| sLLM 비교 | 보고서 서술 생성(또는 VOC 분류)을 sLLM과 API LLM으로 동일 입력 오프라인 비교 — 품질·지연·비용 기록 | 런타임 기본은 API LLM | sLLM 실험 보고서 |
| 멀티 에이전트 구성 비교 | Incident workflow를 단일 Agent 구성과 계획-조사-작성 3역할 구성으로 같은 시나리오에 실행해 정확성·재현성·지연 비교 (LangGraph 기반이므로 Baseline 코드 재사용 가능) | Baseline 런타임은 논리 Agent 2개 유지 | 멀티 에이전트 아키텍처·테스트 보고서 |

각 보고서의 제출 마감일을 확인해 §13 일정에 반영한다.

---

## 11. Django·FastAPI API 계약

### 11.1 외부 공개 API — Django

| method·path | 기능 |
|---|---|
| `POST /api/query-jobs` | 사용자 질문 job 생성 (즉시 `job_id` 반환) |
| `GET /api/jobs/{job_id}` | job 상태와 결과 조회 (polling) |
| `GET /api/incidents` | 권한 범위 이슈 목록 |
| `GET /api/incidents/{run_id}` | 이슈 브리프·근거 조회 |
| `GET /api/reports/{report_id}` | 보고서 version 조회 |
| `POST /api/reports/{report_id}/decision` | 승인·보류·반려 저장 |

### 11.2 내부 API — FastAPI

| method·path | 기능 |
|---|---|
| `POST /internal/v1/quality-gates` | 데이터 품질 Gate 실행 (결정론) |
| `POST /internal/v1/detections` | 규칙 기반 이상 감지 실행 (결정론) |
| `POST /internal/v1/query-runs` | Query workflow 실행 |
| `POST /internal/v1/incident-runs` | 조사·보고 초안 workflow 실행 |
| `GET /internal/v1/health` | 서비스 상태 확인 |

### 11.3 공통 요청 context

```json
{
  "request_id": "uuid",
  "run_id": "uuid",
  "actor_id": "demo-user-id",
  "role_code": "FNB_MANAGER",
  "scope_snapshot": {
    "property_ids": ["GRAND_WALKERHILL_SEOUL"],
    "metric_groups": ["BREAKFAST", "FNB_VOC"]
  },
  "dataset_version": "gw-synthetic-1.0.0",
  "virtual_as_of_date": "2026-08-16"
}
```

FastAPI는 browser가 보낸 역할 값을 신뢰하지 않고 Django가 검증해 전달한 내부 context만 사용한다. worker→FastAPI 호출에는 timeout 상한·retry 횟수·backoff(`PROJECT_CALIBRATION` 값)를 계약으로 명시한다.

---

## 12. Baseline 완료 조건

### 12.1 기능 A

- 실제 Django 로그인 후 역할이 적용된다.
- 보장 질문 8종이 실제 합성 DB SQL로 실행된다.
- 역할별 허용·거부 결과가 서버에서 강제된다.
- 표·차트·설명의 수치가 SQL 결과와 일치한다.
- 기간·단위·표본·timezone·dataset version·query ID가 보인다.
- 잘못된 SQL·권한 우회·범위 밖 질문·금지 재집계는 실행되지 않는다.

### 12.2 기능 B

- 합성 batch 완료 후 품질 Gate와 trigger가 순서대로 실행된다.
- 정상 scenario에서는 경보가 없다.
- 이상 scenario에서는 기대한 이슈 한 건이 생성된다.
- 운영지표와 VOC가 충돌하면 원인을 확정하지 않는다.
- 결측 scenario에서는 `NEEDS_DATA`가 된다.
- 같은 batch 재실행에서 중복 보고서가 생기지 않는다.
- LLM 실패 시 수치 근거는 유지되고 `PARTIAL`이 된다.
- 호텔 관리자가 보고서를 승인·보류·반려할 수 있다.

### 12.3 프로젝트 진실성

- 모든 화면·보고서에 합성 데이터 표시가 있다.
- 실제 호텔 문제·성과로 해석할 문구가 없다.
- 같은 seed에서 결과를 반복 재현할 수 있다 (Golden Path 연속 5회).
- 생성 가정과 탐지 규칙이 분리돼 있다.
- 데모 fixture와 Baseline 실제 분석 결과가 UI에서 구분된다.
- 실험 코드를 제거한 상태에서도 전 test가 통과한다.

### 12.4 반례 검증 시나리오 16건 (Gate 통과 필수)

| # | test | 입력 | 기대 결과 | 금지 결과 |
|---:|---|---|---|---|
| 1 | 권한 없는 인력 상세 질문 | `ROOMS_MANAGER`로 조식 shift별 인원 질문 | SQL 미실행·권한 안내·허용 지표 제안 | 부분 결과, SQL 실행 |
| 2 | raw SQL 실행 요구 | "SELECT * FROM … 실행해줘" | plan 미생성·지원 형식 안내 | 입력 SQL 실행 |
| 3 | 실제 점유율 질문 | "지금 실제 워커힐 점유율은?" | 합성 한계 명시·합성 지표 제안 | 실수치 제시, 합성치의 실제화 |
| 4 | 정상 주차 | `NORMAL` batch | incident 0건 | 억지 이슈 생성 |
| 5 | VOC만 증가 | `VOC_ONLY_SPIKE` | 근거 충돌 표시 | 원인 확정 서술 |
| 6 | 운영만 증가 | `OPS_ONLY_SPIKE` | 운영 이상+VOC 표본 부족 표시 | VOC 근거 날조 |
| 7 | 근거 충돌 | 상충 주입 | "충돌" 명시·후보 보류 | 단일 원인 서술 |
| 8 | 표본 부족 | 최소 표본 미달 | 표본 수 명시·저신뢰 또는 `NEEDS_DATA` | 정상 결과처럼 출력 |
| 9 | bucket 누락 | `MISSING_DATA` | 품질 Gate 차단·`NEEDS_DATA` | 보간 후 무표시 분석 |
| 10 | 잘못된 단위 | 분↔초 불일치 주입 | 품질 Gate 실패 리포트 | 혼합 단위 집계 |
| 11 | 잘못된 p90 집계 | "지난주 전체 p90" 질문 | `fact_breakfast_daily` 기반 응답 | bucket p90의 평균 |
| 12 | 동일 batch 중복 | `DUPLICATE_BATCH` | 2회차 skip·보고서 1건 | 중복 보고서 |
| 13 | FastAPI timeout | 지연 주입 | job `FAILED`/`PARTIAL`·재시도 안내 | 무한 대기, 원인 불명 오류 |
| 14 | LLM 근거 외 원인 | evidence_id 없는 주장 | schema 검증 차단·재생성/`PARTIAL` | 미검증 문장 노출 |
| 15 | 승인 전 확정 노출 | DRAFT 조회 | "DRAFT·합성" 표시 유지 | 확정본 표기 |
| 16 | 목업 오인 | 데모 화면 시연 | `demo_mode=true` 배지+§3.7 고지 | 실연동 시사 표현 |

---

## 13. 권장 일정

목표: **Baseline을 중간발표 직후에 마무리(Gate 8/13~8/14)하고, 이후 약 3주를 검토·모델 실험·확장·안정화에 사용한다.** 아래 일정은 9/3 최종발표 기준 제안이며, 팀 주당 가용 시간 확인 후 확정한다(미확인 상태가 현재 최대 일정 리스크).

| 기간 | 트랙 | 작업 | 산출 |
|---|---|---|---|
| 7/21~7/26 | 계약 | **API 응답 JSON schema v0·합성 schema DDL·권한표·정답 manifest 형식·metric catalog 초안 동결** | 계약 문서 v0 (목업 착수 전) |
| 7/27~8/5 | 데모(2인) | 목업 화면 6종 제작·fixture 작성(schema v0 준수)·리허설 | 중간발표 데모 |
| 7/27~8/5 | 기반(3인) | 합성 데이터 생성기·품질 Gate·PostgreSQL 적재 / Django 인증·job 골격 / FastAPI 골격·semantic catalog. **기능 연결은 하지 않음** | 적재된 dataset v1.0.0, 서비스 골격 |
| 7/27~8/5 | 실험 | VOC 분류 모델 비교·벡터DB 검색 실험 착수 (보고서 제출 마감일에 맞춰 조정) | 실험 중간 기록 |
| **8/6** | — | **중간발표 (비연동 목업 데모)** | 발표·피드백 |
| 8/7~8/11 | 기능 A | 로그인→job→plan→SQL Guard→조회→표·차트 연결 완성 | 보장 질문 8종 end-to-end |
| 8/10~8/13 | 기능 B | 품질 Gate→감지→Incident workflow→DRAFT→승인 연결 완성 | 경로 B end-to-end |
| **8/13~8/14** | **Gate** | **§12 완료 조건 + 반례 test 16건 통합 검증** (미통과 시 보완, 한계선 8/18 — 초과 시 확장 전면 포기·실험 보고서 작업만 유지) | Baseline 통과 판정 |
| 8/17~8/21 | 검토·실험 | 중간발표 피드백 반영, 실험 트랙 마무리(sLLM 비교·멀티 에이전트 구성 비교·보고서 작성), 확장 1순위 착수 | 실험 보고서 4종 |
| 8/24~8/28 | 확장·회귀 | 선택 확장 1~2건 구현+확장별 회귀 test 재통과 | 확장 기능 |
| 8/31~9/2 | 안정화 | 회귀 test·오류 수정·Golden Path 연속 5회 재현·시연 fallback(녹화·정적 캡처) | 발표 준비 완료 |
| **9/3** | — | **최종발표 (실제 연결된 Baseline + 선택 확장)** | 최종 산출물 |

- Baseline Gate를 통과하지 못하면 확장 기능을 시작하지 않는다. 실험 트랙은 실행 경로와 분리돼 있으므로 Gate와 무관하게 계속 진행한다.
- 일정 확정 전 확인 항목: ① 팀 주당 가용 시간·투입률 ② LLM 예산·모델 제약 ③ 실험 보고서별 제출 마감일 ④ 요구사항정의서·화면설계서 등 관련 문서와의 정합화.
- 일정이 밀릴 때의 축소 순서: 보장 질문 8→5종 → 차트 종류 축소 → 기능 B 보고서 서식 단순화. 승인 UI·근거 추적·read-only 안전성·합성 표시는 축소하지 않는다.

---

## 14. 확장 우선순위

| 순위 | 후보 | 시작 조건 |
|---:|---|---|
| 1 | 질문 범위·호텔 운영 도메인 확대 | 기존 8개 의도 회귀 test 통과 |
| 2 | 추가 이상징후·보고 주제 | 조식 scenario precision·fallback 통과 |
| 3 | Celery·Redis | 작업 동시성·durability 요구가 측정됨 |
| 4 | MCP read-only adapter | 별도 Agent client나 외부 도구 재사용 요구 존재 |
| 5 | RAG | 사용할 수 있는 내부·공개 문서 corpus와 인용 요구 존재 |
| 6 | 정식 ontology·GraphDB | 관계 추론이 SQL catalog로 해결되지 않음 |
| 7 | 실제 시스템 연동 | 기업 승인·데이터 계약·비식별·보안 검토 완료 (프로젝트 기간 밖 로드맵) |

기능을 하나씩 추가하고, 추가 전후의 정확성·지연·실패율을 비교한다. 기술 산출물을 위해 추가하더라도 Baseline 실행 경로의 필수 의존성으로 만들지 않는다.

---

## 15. 실제 도입 제안

본 프로젝트는 합성 데이터 기반 PoC이므로 실제 도입 효과를 단정하지 않는다. 대신 **"검증한 사실"과 "다음 단계에서 검증할 가설"을 분리**해 제안한다.

### 15.1 본 프로젝트가 검증한 사실

- 권한 기반 자연어 분석과 이상 감지→근거 수집→보고서 승인의 두 경로가 end-to-end로 실제 동작한다 (합성 데이터 기준).
- 인증·권한, read-only 안전장치, 감사 이력, 승인 workflow 등 아키텍처와 검증 절차는 실제 데이터가 연결돼도 그대로 적용 가능하게 설계됐다.
- 실제 연동 전에 해결해야 할 조건 — 데이터 계약, 시설·시간 연결 키, 비식별 처리, 보안 검토 — 을 식별했다.

### 15.2 본 프로젝트가 주장하지 않는 것

- 실제 그랜드 워커힐 서울에 특정 운영 문제가 존재한다는 사실 (§2.3)
- 도입 시 보고 시간·비용이 감소한다는 효과 (기준선 미측정)
- 합성 데이터에서의 감지 성능이 실제 데이터에서도 유지된다는 보장 (분포·노이즈·품질이 다름)

### 15.3 제안: 실데이터 파일럿 검증

실제 내부 데이터가 연결되면 운영 이슈의 조기 감지와 근거 기반 주간 보고에 기여할 수 있을 것으로 **기대**하며, 이를 확인하기 위한 단계적 파일럿을 제안한다.

| 단계 | 내용 | 판단 기준 |
|---|---|---|
| 1. 데이터 적합성 검증 | 비식별 표본 데이터로 schema 매핑·연결 키·집계 주기 확인 | VOC와 운영지표를 시설·시간 기준으로 연결할 수 있는가 |
| 2. 감지·분석 재보정 | 실데이터 분포로 임계값 재보정, 감지 정밀도·오탐률 측정 | 유효 알림 비율이 운영자 검토 부담을 넘지 않는가 |
| 3. 업무 효과 측정 | 동일 입력으로 수작업 보고와 시스템 보조 보고의 시간·누락 비교 | 기준선 대비 개선이 측정되는가 |

각 단계는 이전 단계를 통과해야 진행하며, 어느 단계에서든 결과가 가설과 다르면 효과 주장 없이 범위를 재조정한다.

### 15.4 발표 표현

```text
본 프로젝트는 합성 데이터로 플랫폼의 기능과 안전장치가 실제로 동작함을 검증했습니다.
실제 내부 데이터가 연결되면 운영 이슈의 조기 감지와 근거 기반 주간 보고에
기여할 수 있을 것으로 기대하며, 이를 확인하기 위한 다음 단계로
비식별 표본 데이터 기반의 파일럿 검증을 제안합니다.
```

"도움이 된다"는 결론이 아니라 파일럿의 검증 대상으로 제시한다. 효과·비용 절감 수치는 3단계 측정 전에는 말하지 않는다.

---

## 16. 핵심 결정 요약

- 8월 6일에는 backend 연결 없이 서비스 경험만 보여주고, API 응답 계약은 목업 착수 전에 동결한다.
- Baseline은 기술을 줄이는 개념이 아니라 핵심 기능의 최소 완성 상태로 정의한다.
- Baseline에서 Django와 FastAPI를 모두 사용하고, 호출 방향과 쓰기 권한을 고정한다. 경로 A는 job+polling, 품질 Gate·이상 감지는 FastAPI 결정론 모듈, LangGraph는 기능 B 한정이다.
- 본사 경영진을 시스템 사용자에서 제외하고, 최종 in-app 승인자는 호텔 관리자다.
- 합성 데이터로 가능한 분석과 실제 호텔에 대한 주장을 분리하고, 공유 시설은 실제 귀속 키가 확인되기 전까지 제외한다.
- 모델·검색 실험은 실행 경로와 분리된 실험 트랙에서 수행하고 보고서로 남긴다.
- Baseline Gate는 8/13~8/14에 두고, 이후 3주를 검토·실험·확장·안정화에 쓴다. Gate를 통과하기 전에는 확장을 시작하지 않는다.

### 최종 방향 한 문장

> 8월 6일에는 두 핵심 사용자 경로를 비연동 프론트엔드 데모로 설명하고, 미리 동결한 계약과 합성 데이터 위에서 중간발표 직후 1주 안에 Django 인증·권한 계층과 FastAPI AI 분석 계층을 실제로 연결해 기능 Baseline을 완성하며, 검증을 통과한 뒤 남은 3주 동안 검토·모델 실험·선택 확장·안정화를 수행한다.

---

## 부록 A. 참고자료

- [그랜드 워커힐 서울 공식 소개](https://www.walkerhill.com/grandwalkerhillseoul/en/about/Walkerhill?tabIdx=1)
- [Grand Club by Walkerhill 공식 안내](https://www.walkerhill.com/grandwalkerhillseoul/m/en/room/GrandClub-by-Walkerhill)
- [The Buffet 공식 안내](https://www.walkerhill.com/vistawalkerhillseoul/en/dining/TheBuffet)
- [Django 인증 공식 문서](https://docs.djangoproject.com/en/5.2/topics/auth/default/)
- [Django 비동기 지원 공식 문서](https://docs.djangoproject.com/en/5.2/topics/async/)
- [FastAPI async 공식 문서](https://fastapi.tiangolo.com/async/)
- [FastAPI Background Tasks 공식 문서](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [PostgreSQL Row Security 공식 문서](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [W3C OWL 2 개요](https://www.w3.org/TR/owl-overview/)
- [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

*본 문서의 모든 기간·임계값·계수 관련 수치는 실제 호텔 운영 기준이 아니라 프로젝트 calibration 가정이다.*
