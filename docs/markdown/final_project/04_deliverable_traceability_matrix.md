# Hotel Signal AI 산출물 추적 매트릭스

## 결론

Baseline 산출물은 권한 기반 대화형 분석과 이상 감지·주간 보고의 두 경로를 기준으로 추적한다. 목업, 기능 Baseline, 분리 실험을 같은 완료 상태로 표시하지 않는다. 기존 단일 경로·4화면·FastAPI 미실행 매핑은 최종 기획서와 맞지 않아 아래 계약으로 교체한다.

## 사람이 판단해야 할 사항

- [ ] ML/DL·VectorDB·sLLM·멀티 에이전트 산출물의 평가 필수 여부
  - 권장안: 필수 여부와 제출일을 확인하고 `EXPERIMENT_REQUIRED` 또는 `NOT_REQUIRED`로 확정한다.
  - 선택 시 영향: Baseline 런타임과 별도 일정·evidence로 관리된다.
  - 미선택 시 영향: 미구현 항목을 완료로 오인하거나 Baseline을 불필요하게 차단한다.

- [ ] 기준 Baseline 기획서의 저장소 편입 위치
  - 권장안: 프로젝트 기획서 갱신 시 핵심 결정과 계약을 병합하고 출처·변경 이력을 남긴다.
  - 선택 시 영향: 팀원이 저장소 안에서 기준을 재현할 수 있다.
  - 미선택 시 영향: 외부 로컬 파일에 의존하게 된다.

## 판단 체크리스트

- [ ] 모든 P0 요구사항에 data·API·UI·test가 연결됐는가
- [ ] 목업 evidence를 기능 구현 evidence로 사용하지 않았는가
- [ ] 실제 code·model·test가 없으면 `완료`가 아닌가
- [ ] 실험 산출물이 Baseline 실행 경로의 필수 dependency가 아닌가
- [ ] 경로와 소유자가 현재 저장소 구조와 일치하는가

## 필수 최소 기능 구현 방향

### 1. 요구사항 추적

| requirement_id | Baseline 요구사항 | data·rule | API | 화면 | test |
|---|---|---|---|---|---|
| `REQ-F-001` | 합성 dataset 생성·품질 Gate·적재 | `DB-001`~`014` | `API-AI-001` | `P0-010`, `030` | `TC-DQ-*`, `TC-GATE-009`, `010` |
| `REQ-F-002` | 실제 로그인·역할·scope 강제 | `DB-021` | `API-001`~`007` | `P0-001`~`050` | `TC-AUTH-*`, `TC-GATE-001`~`003` |
| `REQ-F-003` | 권한 기반 Text-to-SQL 분석 | `DB-020`~`022` | `API-001`, `002`, `API-AI-003` | `P0-020` | `TC-E2E-001`, `TC-GATE-001`, `002`, `011` |
| `REQ-F-004` | 결정론적 이상 감지 | `DB-023`, `RULE-001` | `API-AI-001`, `002` | `P0-010`, `030` | `TC-GATE-004`~`012` |
| `REQ-F-005` | evidence 기반 이슈 브리프·현장 확인 | `DB-024`, `DB-027` | `API-004`, `005`, `API-AI-004` | `P0-030`, `040` | `TC-AI-*`, `TC-GATE-005`~`009`, `014` |
| `REQ-F-006` | 주간 보고서 DRAFT·version | `DB-025` | `API-006`, `API-AI-004` | `P0-050` | `TC-E2E-002`, `TC-GATE-012`~`015` |
| `REQ-F-007` | 관리자 승인·보류·반려 | `DB-026` | `API-007` | `P0-050` | `TC-AUTH-002`, `TC-CT-004`, `TC-GATE-015` |
| `REQ-NF-001` | 합성·개인정보·권한·SQL 보안 | 전체 | 전체 | 전체 | `TC-SEC-*`, `TC-GATE-001`~`003`, `016` |
| `REQ-NF-002` | version·감사·idempotency·fallback | `DB-001`, `022`~`026` | 전체 | 전체 | `TC-CT-*`, `TC-GATE-012`~`014` |

기존 요구사항 정의서의 `BIZ-*`, `DAT-*`, `FUN-*`, `AI-*`, `UI-*`, `SEC-*`, `NFR-*` ID는 의미를 바꾸지 않고 위 상위 계약의 `legacy_requirement_ids`로 연결한다.

### 2. 화면·API 매핑

| 화면 | 소비 API | 주요 출력 |
|---|---|---|
| `P0-001` 역할 선택·로그인 | Django auth | role·scope·합성·demo 표시 |
| `P0-010` 운영 홈 | `API-003`, 최근 job/report 조회 | 질의 진입·incident card·dataset 상태 |
| `P0-020` 대화형 분석 | `API-001`, `API-002` | plan·SQL·table·chart·설명·evidence |
| `P0-030` 이상징후 상세 | `API-004` | rule·window·metric·data status |
| `P0-040` 이슈 브리프 | `API-004`, `API-005` | fact·candidate·counter·missing·field note |
| `P0-050` 주간 보고서 | `API-006`, `API-007` | DRAFT·evidence·limitations·decision |

### 3. 산출물 매핑

| ID | 산출물 | required | decision/status | requirement | source·evidence path | owner·due | 비고 |
|---|---|---:|---|---|---|---|---|
| `DOC-001` | 요구사항 정의서 | 예 | 진행 | 전체 | `docs/markdown/01_요구사항정의서.md` | 기획 담당·07/24 | 상위 `REQ-*` 연결 필요 |
| `DOC-002` | WBS | 예 | 진행 | 전체 | `docs/markdown/02_WBS.md` | 전원·상시 | 두 경로·Gate 일정 반영 |
| `DOC-003` | 프로젝트 기획서 | 예 | 진행 | 전체 | `docs/markdown/03_프로젝트기획서.md` | 기획 담당·07/24 | 최종 Baseline 방향 병합 필요 |
| `DOC-004` | 수집 데이터 보고서 | 예 | 미착수 | `REQ-F-001` | 미생성 | 데이터 담당·07/24 | 합성 source·license·manifest |
| `DOC-005` | DB·저장소 설계 | 예 | 미착수 | `REQ-F-001`~`007` | 미생성 | 데이터·backend·07/31 | `DB-001`~`027`, view, migration |
| `DOC-006` | 데이터 전처리 결과서 | 예 | 미착수 | `REQ-F-001` | 미생성 | 데이터 담당·07/31 | Gate 결과·scenario |
| `DOC-007` | ML/DL 학습결과서 | 확인 필요 | `EXPERIMENT_REQUIRED?` | 실험 | 미생성 | 모델 담당·일정 확인 | Baseline 분리 |
| `DOC-008` | 학습한 ML/DL 모델 | 확인 필요 | `EXPERIMENT_REQUIRED?` | 실험 | 미생성 | 모델 담당·일정 확인 | 2종 비교 시만 생성 |
| `DOC-009` | VectorDB·GraphDB 구축 결과서 | 확인 필요 | `EXPERIMENT_REQUIRED?` | 실험 | 미생성 | AI 담당·일정 확인 | pgvector 실험, GraphDB 제외 권장 |
| `DOC-010` | AI 시스템 아키텍처 | 예 | 진행 | `REQ-F-003`~`006` | 공용 명세·구조 문서 | AI·backend·08/14 | Query pipeline+Incident LangGraph |
| `DOC-011` | 멀티 에이전트 테스트 | 확인 필요 | `EXPERIMENT_REQUIRED?` | 실험 | 미생성 | AI 담당·08/21 확인 | 단일 vs 3역할 비교 |
| `DOC-012` | 자체 sLLM | 확인 필요 | `EXPERIMENT_REQUIRED?` | 실험 | 미생성 | 모델 담당·일정 확인 | API LLM 비교, 런타임 기본 아님 |
| `DOC-013` | 화면설계서 | 예 | 진행 | 전체 UI | `docs/markdown/05_화면설계서_초안.md` | UI 담당·07/24 | Baseline 6화면 |
| `DOC-014` | LLM 연동 웹 애플리케이션 | 예 | 미착수 | 전체 기능 | `app/`, `src/` 경계만 존재 | 전원·08/28 | 목업과 실제 연결 구분 |
| `DOC-015` | 시스템 구성도 | 예 | 진행 | `REQ-NF-*` | 공용 명세 | backend·08/21 | Django·worker·FastAPI·PostgreSQL |
| `DOC-016` | 서비스 테스트 결과 | 예 | 미착수 | 전체 | 미생성 | 전원·08/28 | 반례 16건과 E2E evidence |

### 4. Evidence 상태 규칙

```text
NOT_STARTED      실제 작업·evidence 없음
IN_PROGRESS      일부 산출물 존재, Gate 미통과
REVIEW           산출물과 evidence가 검토 가능
COMPLETE         필수 test·승인 완료
DECISION_REQUIRED 평가 의무·범위 미확정
NOT_ADOPTED      미도입 결정과 대체 근거 존재
```

문서만 있으면 code·model·DB·test를 완료로 표시하지 않는다. screenshot은 UI evidence이며 수치·권한·SQL·장애 시험을 대체하지 않는다.

### 5. 저장소 경로 계약

| 산출물 종류 | 경로 |
|---|---|
| UI | `app/react/` |
| 인증·job·report·migration | `app/django/` |
| 품질 Gate·Text-to-SQL·Incident workflow | `app/fastapi/` |
| framework 독립 분석·공통 schema | `src/analysis/`, `src/common/` |
| 작은 합성 fixture | `data/samples/` |
| test·evaluation | `tests/`, `evals/` |
| 공용 계약 | `docs/markdown/final_project/` |

## 확장 방향

- 실험 산출물은 `experiments/` 도입 승인을 받은 뒤 런타임과 분리한다.
- 실제 도입 산출물은 비식별 표본 mapping, 보안 검토, calibration, 운영 효과 측정을 별도 Gate로 둔다.
- 실제 호텔 성과·비용 절감 evidence가 없으면 효과 산출물을 완료로 표시하지 않는다.

## 변경 이력

| version | date | 변경 |
|---|---|---|
| `2.0` | 2026-07-20 | 두 Baseline 경로, 6화면, Django 7·FastAPI 5 API, DB-001~027, E2E·반례 16건으로 추적 매핑 갱신 |
