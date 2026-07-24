# Hotel Signal AI 프로젝트 디렉터리 구조

## 결론

기존 구현 경계 `app/react`, `app/django`, `app/fastapi`, `src/analysis`, `src/common`은 최종 Baseline 기획서에 적용 가능하다. 다만 `app/fastapi`를 후속 P1 경계로만 본 기존 설명은 수정한다. 기능 Baseline에서 Django와 FastAPI를 실제 연결하며, Django가 유일한 외부 backend·migration 소유자이고 FastAPI는 내부 분석 service다.

## 사람이 판단해야 할 사항

- [ ] 실제 framework 초기화 시점
  - 권장안: API schema v0과 책임 경계 승인 후 담당자가 각 폴더에서 초기화한다.
  - 선택 시 영향: 목업과 backend 골격을 병렬 개발할 수 있다.
  - 미선택 시 영향: 빈 경계만 존재하며 기능 완료로 볼 수 없다.

- [ ] Django worker module 위치
  - 권장안: `app/django` 내부 job app·management process로 시작한다.
  - 선택 시 영향: job·report transaction을 Django가 소유한다.
  - 미선택 시 영향: 별도 queue infrastructure가 불필요하게 추가될 수 있다.

## 판단 체크리스트

- [ ] 새 폴더가 실제 code·test·산출물을 위한 것인가
- [ ] `app`과 `src`의 의존 방향을 지켰는가
- [ ] Django와 FastAPI migration을 중복 생성하지 않았는가
- [ ] 실험 코드가 Baseline runtime import graph와 분리됐는가
- [ ] data raw·processed 생성물을 commit하지 않았는가

## 필수 최소 기능 구현 방향

### 1. 확정 구조

```text
repository/
├─ app/
│  ├─ react/       # 6개 화면·fixture·Django API consumer
│  ├─ django/      # 공개 API·auth·RBAC·job·worker·report·migration
│  └─ fastapi/     # 내부 품질·감지·query·incident·LLM service
├─ src/
│  ├─ analysis/    # framework 독립 품질·집계·rule·evidence
│  └─ common/      # 공통 enum·schema·ID·오류·version 계약
├─ data/
│  ├─ raw/         # 원본·생성물, commit 금지
│  ├─ processed/   # 정제·적재 전 결과, commit 금지
│  └─ samples/     # 작은 합성 fixture·manifest·schema
├─ tests/
├─ evals/
├─ notebooks/
└─ docs/markdown/final_project/
```

현재 다섯 구현 경계는 `.gitkeep`만 있으며 실제 React·Django·FastAPI code·dependency·migration이 존재한다는 뜻이 아니다.

### 2. `app`과 `src`

| 구분 | 포함 | 제외 |
|---|---|---|
| `app` | framework 진입점, HTTP, auth, persistence adapter, UI | framework 독립 domain rule의 중복 구현 |
| `src` | 순수 schema·품질·계산·rule·evidence·공통 계약 | HTTP server, UI, ORM migration |

의존 방향은 `app → src`다. `src`는 React·Django·FastAPI를 import하지 않는다.

### 3. React 책임

- 중간발표: 동일 schema v0의 TypeScript/JSON fixture, `demo_mode=true`
- 기능 Baseline: Django 공개 API만 호출
- `P0-001`, `010`, `020`, `030`, `040`, `050` 6화면
- job polling과 loading·empty·error·partial·forbidden 표시
- 합성·dataset·schema·scenario·기간·단위·근거 표시

React가 role scope, SQL, trigger, KPI, report decision 허용 여부를 최종 판정하지 않는다.

### 4. Django 책임

- 실제 로그인·session/token과 3개 demo role
- 공개 API gateway와 server-side scope 검사
- `scope_snapshot` 생성
- query·analysis job table과 worker orchestration
- report·report decision·field note·audit 저장
- 모든 DB migration의 단일 주체

worker는 FastAPI를 호출하고 analytics view를 직접 읽지 않는다.

### 5. FastAPI 책임

- 데이터 품질 Gate·결정론적 detection
- semantic query plan·SQL Guard·read-only query
- table·chart spec·수치 evidence 구성
- Incident LangGraph와 LLM gateway
- versioned Pydantic response validation

FastAPI는 사용자·role·report approval table을 소유하거나 수정하지 않는다. Browser에 공개하지 않는다.

### 6. `src/analysis`

실제 code가 생기면 다음 책임 단위로 분리한다.

```text
src/analysis/
├─ quality/       # 품질 Gate 순수 검사
├─ detection/     # versioned rule
├─ metrics/       # KPI·비가산 지표
├─ evidence/      # source row→evidence
└─ schemas/       # domain input/output helpers
```

300줄 이상 또는 책임이 독립될 때만 module을 나눈다. 빈 하위 폴더를 미리 만들지 않는다.

### 7. `src/common`

```text
src/common/
├─ enums/         # role·job·report·incident status
├─ contracts/     # API·fixture·AI schema
├─ identifiers/   # 공통 ID·context
└─ errors/        # 오류 code
```

둘 이상의 consumer가 공유할 때만 추가한다. JSON schema·Pydantic·TypeScript가 파생되는 원본과 생성 방법을 명시한다.

### 8. DB migration·schema

- Django migration만 `DB-001`~`027`을 생성한다.
- FastAPI는 Django migration을 import하거나 별도 migration을 만들지 않는다.
- FastAPI용 DB credential은 allowlist analysis view에 대한 read-only다.
- Django worker는 platform table을 쓰고 analysis view를 직접 계산하지 않는다.
- table·field 원본은 `02_data_standard_guide.md`다.

### 9. 파일·모듈 이름

- Python module·data file: `snake_case`
- React component: `PascalCase`
- hook·function·variable: `camelCase` 또는 해당 language convention
- API path: 소문자 복수 명사와 `kebab-case`
- test: `test_<behavior>.py` 또는 project test convention
- migration 이름: 목적이 드러나는 동사·명사, 자동 번호만 사용 금지

### 10. 생성하지 않는 구조

승인 전 다음을 만들지 않는다.

```text
infra/kafka/
infra/redis/
infra/neo4j/
src/retrieval/
src/embeddings/
src/graph/
data/vectorstore/
app/fastapi/mcp/
app/fastapi/agents/swarm/
```

`experiments/`도 평가 범위와 소유자·산출물이 확정된 뒤 생성한다.

### 11. 새 기능 추가 위치

| 변경 | 위치 | 선행조건 |
|---|---|---|
| 화면·상태 | `app/react/` | 화면·API contract 승인 |
| auth·job·report·decision | `app/django/` | Django model·migration review |
| query·incident workflow | `app/fastapi/` | 내부 API schema·scope review |
| pure rule·metric | `src/analysis/` | deterministic test ID |
| shared schema·enum | `src/common/` | 2개 이상 consumer와 version policy |
| fixture·manifest | `data/samples/` | PII·license·size·schema validation |

## 확장 방향

- Celery·Redis는 동시 작업·durability 요구를 측정한 뒤 추가한다.
- pgvector·ML·sLLM·agent 비교는 승인된 `experiments/`에서 런타임과 분리한다.
- 실제 연동 adapter는 기업 승인·비식별·data contract 이후 P2에서 추가한다.

## 변경 이력

| version | date | 변경 |
|---|---|---|
| `2.0` | 2026-07-20 | FastAPI를 Baseline 실제 실행 경계로 수정하고 6화면·worker·read-only view·DB-001~027 책임을 정합화 |
