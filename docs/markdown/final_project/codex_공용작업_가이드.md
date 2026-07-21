# 다른 Codex 세션 공용 작업 가이드

## 결론

다른 Codex는 먼저 프로젝트가 `중간발표 비연동 목업`과 `기능 Baseline`을 구분하고, Baseline에 `권한 기반 대화형 분석`과 `이상 감지·자동 분석·주간 보고` 두 경로가 있다는 사실을 확인해야 한다. 기존의 조식 대기 단일 경로·4화면·FastAPI 미실행 안내는 사용하지 않는다.

## 사람이 판단해야 할 사항

- [ ] 현재 요청의 단계
  - 권장안: 목업, 기능 Baseline, 실험, 확장 중 하나를 작업 시작 전에 표시한다.
  - 선택 시 영향: fixture와 실제 구현을 혼동하지 않는다.
  - 미선택 시 영향: 미연동 화면을 완료 기능으로 잘못 보고할 수 있다.

- [ ] 공통 계약 변경 필요 여부
  - 권장안: schema·role·status·endpoint를 바꾸기 전 소비자와 test 영향 ID를 보고하고 승인받는다.
  - 선택 시 영향: 병렬 작업의 계약이 유지된다.
  - 미선택 시 영향: React·Django·FastAPI fixture가 불일치한다.

## 판단 체크리스트

- [ ] 현재 branch·status와 사용자 변경을 확인했는가
- [ ] 아래 필수 문서를 순서대로 읽었는가
- [ ] 기능 A·B 중 작업 경로와 완료 조건을 적었는가
- [ ] data·API·UI·test ID를 연결했는가
- [ ] 실제 구현·시험 없이 완료로 표시하지 않았는가
- [ ] 합성·demo·version 표시를 보존했는가
- [ ] 범위를 넘는 실험·인프라를 추가하지 않았는가

## 필수 최소 기능 구현 방향

### 1. 필수 읽기 순서

| 순서 | 문서 | 확인 내용 |
|---:|---|---|
| 1 | `/AGENTS.md` | 저장소·Git·문서·보고 규칙 |
| 2 | `00_project_control.md` | 최종 Baseline 범위·단계·금지 기능 |
| 3 | `common_project_specification.md` | 서비스 책임·역할·상태·공통 계약 |
| 4 | `02_data_standard_guide.md` | 물리 schema·scenario·품질 Gate |
| 5 | `03_api_ai_integration_contract.md` | Django·FastAPI·AI 요청·응답 |
| 6 | `05_화면설계서_초안.md` | 6화면·상태·권한·문구 |
| 7 | `05_test_acceptance_guide.md` | E2E·반례 16건·인수 Gate |
| 8 | `04_deliverable_traceability_matrix.md` | 요구사항·산출물·evidence 상태 |
| 9 | 담당 작업 지시서 | 이번 변경의 구체 범위 |

문서는 모두 저장소 root 기준 `docs/markdown/` 아래에 있다. 상대 링크는 이 문서가 있는 `docs/markdown/final_project/`를 기준으로 해석한다.

### 2. 작업 단계 구분

| 단계 | 구현 |
|---|---|
| 8월 6일 목업 | React fixture, 가상 역할, 6화면, `demo_mode=true`; backend·DB·LLM 호출 없음 |
| 기능 Baseline | Django 로그인·RBAC·job, worker, FastAPI, PostgreSQL, LLM 실제 연결 |
| 실험 | ML/DL·pgvector·sLLM·agent 구성 비교; 런타임 import 금지 |
| 확장 | Baseline Gate 후 승인된 질문·시나리오·인프라만 추가 |

### 3. 두 Baseline 경로

```text
기능 A
로그인 → 질문 job → semantic query plan → SQL Guard → read-only query
→ table·chart·설명·evidence

기능 B
batch READY → 품질 Gate → 결정론적 trigger → Incident LangGraph
→ evidence·brief·report DRAFT → HOTEL_MANAGER decision
```

### 4. 담당별 문서와 경계

| 담당 | 먼저 볼 문서 | 작업 경계 |
|---|---|---|
| React | 화면설계서, API 계약 | 6화면·polling·상태·합성·근거 표시; 권한·수치 판정 금지 |
| Django | 공통 명세, API·data 계약 | 공개 API·인증·RBAC·scope·job·report·decision·audit·migration |
| FastAPI | API·data·test 계약 | 품질 Gate·trigger·query·Incident·LLM gateway; 사용자 DB·승인 쓰기 금지 |
| Data | 데이터 표준, test 가이드 | metadata 3·fact 5·platform 8 table, fixture·manifest·Gate |
| AI/ML | API·test·추적표 | LLM evidence 경계; ML·검색 실험은 Baseline 분리 |
| QA | test 가이드, 추적표 | 목업 Gate, E2E 2개, 반례 16건, 실제 evidence |

### 5. 구현 경계 폴더

| 경로 | 책임 |
|---|---|
| `app/react/` | UI 실행 진입점 |
| `app/django/` | 외부 backend·worker·migration |
| `app/fastapi/` | 분석 service·내부 API |
| `src/analysis/` | framework 독립 품질·집계·rule·evidence |
| `src/common/` | versioned enum·schema·ID·오류 계약 |

의존 방향은 `app → src`다. FastAPI는 Baseline 실제 실행 경계이며 Browser가 직접 호출하지 않는다.

### 6. 작업 시작 템플릿

```text
목표:
단계: MOCK | BASELINE | EXPERIMENT | EXTENSION
경로: QUERY | INCIDENT | SHARED
in-scope:
out-of-scope:
관련 ID: REQ / DATA·DB / API / P0 화면 / TC
변경 파일:
완료 조건:
검증 명령:
실행하지 못할 검증:
```

### 7. 구현 중 금지

- 다른 framework가 소유한 상태·migration·권한을 중복 구현
- Browser→FastAPI 직접 호출
- user input raw SQL 실행
- LLM trigger·KPI·최종 원인·조치 결정
- 실제 호텔 시설·운영 수치·권한을 확인된 사실로 표현
- 실험 dependency를 Baseline import graph에 추가
- 목업 fixture를 실제 backend evidence로 보고
- `.env`, secret, 실제 고객·직원 데이터 commit

### 8. 완료·인계 형식

```text
결과:
변경 파일:
관련 계약 ID:
실행한 검증과 결과:
미실행 검증:
dataset/schema/rule/analysis version:
남은 위험·결정:
다음 담당자가 먼저 볼 파일:
```

코드·DB·모델·시험이 실제로 없으면 `경계 생성`, `문서화`, `미구현` 중 정확한 상태로 적는다.

## 확장 방향

- 공용 계약을 코드로 생성할 필요가 확인되면 `src/common`에서 schema 원본을 관리한다.
- 실험 폴더는 별도 승인 후 만들며 Baseline에서 import하지 않는다.
- 실제 연동은 비식별 표본·data mapping·보안 검토 이후 P2로 수행한다.

## 변경 이력

| version | date | 변경 |
|---|---|---|
| `2.0` | 2026-07-20 | 다른 Codex 읽기 순서와 담당별 경계를 두 Baseline 경로·6화면·FastAPI 실제 실행 기준으로 갱신 |
