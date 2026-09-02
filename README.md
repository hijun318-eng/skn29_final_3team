<div align="center">

# Answervice

### 기업 데이터에 질문하고, 근거 있는 답을 보고서로

객실·고객·식음료·시설·연회에 흩어진 호텔 데이터를<br />
자연어로 분석하고 검증 가능한 업무 보고서로 연결하는 Enterprise Intelligence Platform

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)
![Alembic](https://img.shields.io/badge/Alembic-Migration-6BA81E)
<br />
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111111)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Recharts](https://img.shields.io/badge/Recharts-3.10-22B5BF)
![Nginx](https://img.shields.io/badge/Nginx-1.28-009639?logo=nginx&logoColor=white)
<br />
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-4479A1?logo=mysql&logoColor=white)
![SQL Server](https://img.shields.io/badge/SQL_Server-2022-CC2927?logo=microsoftsqlserver&logoColor=white)
![ClickHouse](https://img.shields.io/badge/ClickHouse-FFCC01?logo=clickhouse&logoColor=111111)
![Trino](https://img.shields.io/badge/Trino-483-DD00A1?logo=trino&logoColor=white)
![DataHub](https://img.shields.io/badge/DataHub-1.7-5A67D8)
<br />
![SQLGlot](https://img.shields.io/badge/SQLGlot-30.17-4B5563)
![pgvector](https://img.shields.io/badge/pgvector-Vector_DB-336791?logo=postgresql&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-1.9-F7931E?logo=scikitlearn&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

[제품 문서](docs/README.md) · [PRD](docs/product/01_PRD.md) · [사용자 흐름](docs/product/02_유저플로우.md) · [아키텍처](docs/product/03_아키텍처.md)

</div>

---

## Answervice란?

호텔의 운영 데이터는 PMS, POS, CRM, 시설, 연회 시스템에 나뉘어 있습니다. 현업 담당자가 하나의 질문에 답하려면 여러 부서에서 자료를 모으고, 서로 다른 기준을 맞추고, 결과를 다시 표와 보고서로 옮겨야 합니다.

**Answervice**는 사용자가 업무 언어로 질문하면 승인된 용어·데이터 자산·권한·계산 규칙 안에서 여러 원천을 읽기 전용으로 분석하고, 결과와 근거를 재사용 가능한 분석·보고서 자산으로 만드는 서비스입니다.

> **예시 질문**<br />
> 2025년 5월과 6월 GOLD 고객의 객실·식음료 매출을 비교하고, 차이가 큰 항목을 보고서로 만들어 줘.

| 기존 업무의 문제 | Answervice가 제공하는 방식 |
|---|---|
| 데이터가 시스템별로 분산됨 | Trino를 통한 5개 업무 원천의 연합 조회 |
| 같은 지표도 계산 기준이 달라짐 | DataHub 용어·자산과 Runtime Catalog 기반의 승인된 의미 사용 |
| SQL 작성과 검증에 전문 인력이 필요함 | 다단계 AI 분석과 결정론적 SQL Guard 결합 |
| 결과의 출처와 조건을 다시 확인하기 어려움 | 기간·필터·Metric·데이터셋·query ID를 Artifact에 함께 보존 |
| 분석 결과를 보고서로 다시 옮겨야 함 | 분석 Artifact를 보고서 초안·승인본·HTML/PDF로 연결 |

## 핵심 사용자 경험

```text
로그인 → 자연어 질문 → 기준 확인 → 읽기 전용 분석 → KPI·차트·표·근거 확인
       → 분석 저장·재실행 → 보고서 편집 → 승인·HTML/PDF 출력
```

- **대화형 데이터 분석**: 한국어 질문과 제한된 멀티턴 문맥을 구조화해 새로운 분석 또는 기존 결과의 표현 변경으로 구분합니다.
- **Governed Text-to-SQL**: 모델이 만든 후보를 그대로 실행하지 않고 승인 Context, SQL AST, 자산·컬럼·JOIN·함수·조회량 정책으로 다시 검증합니다.
- **다중 원천 통합**: PostgreSQL, MySQL, Microsoft SQL Server, ClickHouse에 분산된 호텔 데이터를 Trino에서 읽기 전용으로 조회합니다.
- **설명 가능한 결과**: 요약뿐 아니라 KPI, 차트, 표, 기간, 필터, Metric, 데이터 출처와 query 추적 정보를 하나의 Artifact로 제공합니다.
- **분석 재사용**: 분석 정의를 저장하고 현재 권한·데이터·정책으로 다시 실행해 과거 SQL이나 결과를 새 실행처럼 재사용하지 않습니다.
- **보고서 워크플로**: 드래그 앤 드롭 편집, 버전 관리, 승인, 수동·예약 실행, Assistant 제안 승인, HTML·PDF 문서화를 지원합니다.
- **역할 기반 접근 제어**: 분석 사용자와 보고서 관리자의 화면·API·객체 소유권을 서버의 Capability 정책으로 분리합니다.

## 현재 구현 범위

아래 표는 **현재 코드에 연결된 기능 범위**를 나타냅니다. 운영 승인 상태는 같은 릴리스의 실제 Backend·DataHub·Trino·DB·모델 증거를 요구하는 [제품 요구사항 정의서](docs/product/01_PRD.md)에서 별도로 관리합니다.

| 영역 | 현재 코드 경로 |
|---|---|
| 분석 Core | Frontend → FastAPI → Context/권한 → Node 1·2·3 → G1·G2·G3 → Trino → Artifact 경로 통합 |
| 대화·재실행 | Conversation/Turn 영속화, 동시성·멱등성 경계, 분석 저장·조회·재실행 경로 통합 |
| 보고서 | Artifact 기반 초안, 블록 편집, Assistant, 버전·승인, 수동·예약 실행, HTML·PDF 렌더링 통합 |
| 내부 매뉴얼 RAG | pgvector 검색, 근거 제한 답변, 후속 질문, 문서 목록·원문 PDF 경로 통합. 기본값은 `RAG_FEATURE_ENABLED=0` |
| 객실 수요 ML | 합성 데이터로 검증한 HGBR v2.2 후보와 최대 7일 예측 API 통합. 기본값은 `ML_FEATURE_ENABLED=0` |
| Node 2 sLLM | OpenAI-compatible 전용 endpoint, SQL-only 계약, Compiler 보완, 1회 제한 Repair, 학습·평가·승격 Gate 구현 |
| 운영 안전성 | 외부 secret, PBKDF2 세션 principal, TLS Trino/DataHub, read-only source, fail-closed readiness 적용 |

> 고정 demo 응답이나 질문별 정답 SQL은 운영 경로에 없습니다. 승인된 데이터·metadata·권한·모델 구성이 불완전하면 `/readiness`는 의도적으로 `NOT_READY`를 반환합니다.

## 시스템 아키텍처

```mermaid
flowchart LR
    USER["Analyst / Report Admin"] --> WEB["React Web<br/>분석 · 보고서"]
    WEB --> API["FastAPI Control Plane"]
    API --> AUTH["Session · RBAC · Object Ownership"]
    API --> ORCH["Conversation Orchestrator"]

    subgraph PIPE["Governed Analysis Pipeline"]
        N1["Node 1<br/>질문 해석"] --> G1["APP-G1<br/>Context · 권한"]
        G1 --> N2["Node 2 / Compiler<br/>SQL 후보"]
        N2 --> G2["APP-G2<br/>SQL AST · Policy"]
        G2 --> TRINO["Trino<br/>Read-only Query"]
        TRINO --> G3["APP-G3<br/>결과 · 노출 검증"]
        G3 --> N3["Node 3<br/>근거 기반 설명"]
    end

    ORCH --> N1
    DATAHUB["DataHub<br/>Glossary · Dataset · Lineage"] --> G1
    DATAHUB --> N2
    TRINO --> PMS["PMS<br/>PostgreSQL"]
    TRINO --> POS["POS<br/>MySQL"]
    TRINO --> CRM["CRM<br/>SQL Server"]
    TRINO --> FACILITY["Facility<br/>ClickHouse"]
    TRINO --> BANQUET["Banquet<br/>PostgreSQL"]

    N3 --> APPDB["App PostgreSQL<br/>Turn · Run · Artifact · Audit"]
    APPDB --> REPORT["Report Workflow<br/>Draft · Approval · HTML/PDF"]
    REPORT --> WEB

    ORCH -. "선택 기능" .-> RAG["Manual RAG<br/>pgvector · Evidence"]
    ORCH -. "선택 기능" .-> ML["Room Demand ML<br/>HGBR"]
```

### 분석 파이프라인의 안전 경계

| 단계 | 책임 |
|---|---|
| Node 1 | 자연어 질문을 승인된 Metric·기간·필터·차원 후보로 구조화 |
| APP-G1 | Context 버전, 사용자 권한, metadata 관계, 기간과 데이터 범위 검증 |
| Node 2 / Compiler | 승인된 Context 안에서만 parameterized Trino SQL 후보 생성 |
| APP-G2 | SQLGlot AST로 단일 `SELECT`, allowlist, JOIN, 함수, 조회 예산과 read-only 정책 검사 |
| Trino | 5개 원천을 연합 조회하고 query ID·통계·실행 시간을 기록 |
| APP-G3 | 결과 schema, 행 수, 값 범위, 노출 정책과 근거 완전성 검사 |
| Node 3 | G3를 통과한 결과만 사용해 요약·비교·주의사항 생성 |

모델 출력은 언제나 **비신뢰 입력**입니다. 권한, 실행 여부, 최종 상태와 공개 가능한 결과는 서버의 결정론적 Gate가 결정합니다.

## 기술 스택

| 구분 | 기술 |
|---|---|
| Frontend | React 19, Vite 8, Recharts, dnd-kit, React Markdown, Nginx |
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, HTTPX |
| AI / LLM | OpenAI-compatible API, typed JSON Schema, SQLGlot, Node 1·2·Repair·3 pipeline |
| Data Platform | DataHub 1.7, Trino, Apache Polaris, S3-compatible object storage |
| Source DB | PostgreSQL, MySQL, Microsoft SQL Server, ClickHouse |
| RAG | pgvector, Qwen3 Embedding 후보, reranker, evidence-bound answer pipeline |
| ML | scikit-learn HistGradientBoostingRegressor, rolling validation, immutable model artifact |
| Report | Artifact lineage, versioned workflow, WeasyPrint HTML/PDF rendering |
| Infra / QA | Docker Compose, GitHub Actions, pytest, Node contract tests |

## 저장소 구조

```text
.
├─ app/
│  ├─ frontend/                 # React 분석·보고서 UI
│  └─ backend/                  # FastAPI API, orchestration, persistence
├─ src/
│  ├─ ai/                       # 모델 계약, prompt, SQL policy, Node 2 학습·평가
│  ├─ data/                     # DataHub·Trino·governance 도메인 계약
│  ├─ rag/                      # 내부 매뉴얼 검색·답변·평가
│  ├─ ml/                       # 객실 수요 예측 학습·serving artifact
│  └─ report/                   # 보고서 도메인·repository 계약
├─ infrastructure/
│  ├─ database/                 # Source DB, App DB, Trino, DataHub, Polaris
│  ├─ rag/                      # pgvector·RAG API Compose
│  └─ ml/                       # ML runtime Compose
├─ evals/                       # Gold set, RAG·ML·모델 평가 계약
├─ tests/                       # Backend, AI, Data, RAG, ML, Report, Frontend, E2E
├─ docs/product/                # 기획서, PRD, 사용자 흐름, 아키텍처 기준
└─ compose.yml                  # 전체 서비스 Compose 진입점
```

## 보안과 데이터 원칙

- 프로젝트 저장소에는 실제 고객 데이터 대신 합성 데이터를 사용합니다.
- Source DB는 애플리케이션에서 직접 쓰지 않으며 Trino의 최소 권한 read-only principal로 조회합니다.
- 모델 출력과 DataHub 자유 텍스트는 비신뢰 입력으로 처리하고 서버 정책으로 재검증합니다.
- 다중 statement, DDL/DML, 승인 밖 자산·컬럼·JOIN, 과도한 조회는 실행 전에 차단합니다.
- 로그인, API, 객체 소유권과 보고서 승인 권한을 서버의 Role→Capability 정책으로 검사합니다.
- 비밀번호, API key, TLS private key와 principal 파일은 Git에 포함하지 않습니다.
- dependency 실패를 fixture, 이전 Artifact, 빈 성공값 또는 숨은 fallback으로 대체하지 않습니다.

## 팀 구성

| 팀원 | GitHub | 담당 영역 |
|---|---|---|
| 박준희 | [hijun318-eng](https://github.com/hijun318-eng) | 프로젝트 통합, 실행 환경, 품질 관리 |
| 정승 | [jseung89](https://github.com/jseung89) | 데이터 플랫폼, DataHub·Trino, 합성 데이터 |
| 윤대성 | [YoonDaeSung-01](https://github.com/YoonDaeSung-01) | AI 분석 파이프라인, Text-to-SQL, 모델 학습·평가 |
| 김재홍 | [kkix1025](https://github.com/kkix1025) | Backend, 인증·권한, 데이터 영속화 |
| 송민지 | [nowis1350](https://github.com/nowis1350) | Frontend, 분석 결과 UX, 보고서 편집기 |

## 문서 안내

| 문서 | 내용 |
|---|---|
| [문서 지도](docs/README.md) | 제품 문서의 우선순위와 증거 원칙 |
| [프로젝트 기획서](docs/product/00_기획서.md) | 문제, 사용자, 가치와 제품 범위 |
| [제품 요구사항](docs/product/01_PRD.md) | Requirement, 인수 조건과 현재 판정 |
| [사용자 흐름](docs/product/02_유저플로우.md) | 로그인, 분석, 멀티턴, 실패와 보고서 흐름 |
| [기술 아키텍처](docs/product/03_아키텍처.md) | 컴포넌트 책임, 신뢰 경계와 전환 계약 |
| [아키텍처 시각화](docs/architecture/README.md) | Agent·분석·보고서·데이터 릴리스 다이어그램 |
| [Backend 가이드](app/backend/README.md) | API, 인증, runtime과 컨테이너 검증 |
| [RAG 가이드](src/rag/README.md) | 내부 매뉴얼 RAG 구성과 검증 |
| [Node 2 학습 가이드](src/ai/training/README.md) | 데이터셋, LoRA 학습, 평가와 승격 Gate |
| [보고서 도메인](src/report/README.md) | 보고서 버전·승인·실행 무결성 계약 |

---

<div align="center">

**Answervice — 데이터에 질문하고, 근거로 답하다.**

</div>