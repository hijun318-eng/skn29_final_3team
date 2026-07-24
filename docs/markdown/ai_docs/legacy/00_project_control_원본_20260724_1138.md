# Hotel Signal AI 프로젝트 통제 문서

## 결론

Hotel Signal AI의 Baseline은 다음 두 핵심 기능이 합성 데이터에서 실제로 끝까지 동작하는 상태다.

1. 권한 기반 대화형 분석: 자연어 질문 → semantic query plan → 안전한 Text-to-SQL → 표·차트·설명
2. 이상 감지·자동 분석·주간 보고: 품질 Gate → 결정론적 감지 → 근거 조사 → 보고서 초안 → 관리자 결정

2026-08-06 중간발표는 위 두 경로를 동일한 응답 계약을 사용하는 비연동 프론트엔드 fixture로 시연한다. 실제 Django·FastAPI·PostgreSQL·LLM 연결은 2026-08-07~14 Baseline에서 완성한다. 기존 문서의 `조식 대기 단일 경로·4화면·통합 API 5개·FastAPI 미실행` 축소안은 최종 Baseline 기획서와 충돌하므로 폐기한다.

## 사람이 판단해야 할 사항

- [ ] API 응답 JSON schema v0 동결 승인
  - 권장안: 2026-07-26까지 job·query·incident·report 계약을 동결한다.
  - 선택 시 영향: 목업 fixture를 실제 Baseline에서도 재사용할 수 있다.
  - 미선택 시 영향: 화면과 backend 계약 재작업 위험이 크다.

- [ ] 프로젝트별 보정값 승인
  - 권장안: 탐지 임계값·timeout·retry·minimum sample을 `PROJECT_CALIBRATION`으로 별도 version 관리한다.
  - 선택 시 영향: 실제 호텔 기준으로 오인하지 않고 재현 가능하다.
  - 미선택 시 영향: 합성 결과를 실제 운영 기준처럼 해석할 위험이 있다.

- [ ] 모델·검색 실험 제출 범위 확인
  - 권장안: VOC ML/DL 비교, pgvector, sLLM, 멀티 에이전트 비교는 Baseline 런타임과 분리된 실험 트랙으로 수행한다.
  - 선택 시 영향: 평가 산출물을 만들면서 Golden Path 안정성을 보존한다.
  - 미선택 시 영향: 불필요한 런타임 의존성이 늘어날 수 있다.

## 판단 체크리스트

- [ ] 요청이 8월 6일 비연동 목업, 기능 Baseline, 실험 트랙, 확장 중 어디에 속하는가
- [ ] 두 Baseline 경로 중 영향을 받는 경로와 계약 ID를 확인했는가
- [ ] 실제 호텔 데이터·권한·KPI를 사용한 것처럼 표현하지 않았는가
- [ ] `is_synthetic`, dataset·schema·generator version, scenario·seed를 보존했는가
- [ ] 수치 계산·품질 Gate·trigger가 결정론적으로 실행되는가
- [ ] LLM 문장에 `evidence_id`가 있고 원인을 확정하지 않는가
- [ ] Browser가 FastAPI를 직접 호출하지 않는가
- [ ] Django만 인증·권한·job·보고서·결정 상태와 migration을 소유하는가
- [ ] Baseline Gate 통과 전 확장을 실행 경로에 추가하지 않았는가

## 필수 최소 기능 구현 방향

### 단계와 완료 시점

| 단계 | 기간 | 구현 수준 | 완료 기준 |
|---|---|---|---|
| 계약·데이터·골격 선행 | ~2026-08-05 | schema v0, 합성 데이터, 권한표, manifest, 서비스 골격 | fixture schema 검증과 데이터 품질 Gate 통과 |
| 중간발표 목업 | 2026-08-06 | React fixture, 가상 역할 선택, backend·DB·LLM 미연결 | 두 사용자 경로를 6개 화면으로 시연 |
| 기능 Baseline | 2026-08-07~14 | Django·worker·FastAPI·PostgreSQL·LLM 실제 연결 | §테스트 Gate와 반례 16건 통과 |

### P0 Baseline 경로

```text
경로 A: 로그인·역할 확인 → 자연어 질문 → job/polling → query plan → SQL Guard
       → read-only 조회 → 표·차트·설명·근거

경로 B: 합성 batch READY → 품질 Gate → versioned rule 감지 → Incident workflow
       → 이슈 브리프·보고서 초안 → 호텔 관리자 승인·보류·반려
```

두 경로는 운영 홈을 공유하지만 서로 억지로 합치지 않는다. 경로 A는 질의 결과에서 끝나고 경로 B는 호텔 관리자 결정에서 끝난다.

### 사용자·권한

| 역할 | Baseline 범위 |
|---|---|
| `HOTEL_MANAGER` | 모든 합성 집계 지표, 이슈, 보고서 검토·결정 |
| `FNB_MANAGER` | 조식 운영·인력·VOC 질의와 이슈 확인 |
| `ROOMS_MANAGER` | 객실 집계·객실 VOC·제한된 조식 수요 요약 |

`FNB_MANAGER`, `ROOMS_MANAGER`는 실제 조직 직책을 복제한 것이 아니라 권한 차이를 검증하는 데모 역할이다. 본사·경영진·고객 사용자는 시스템 밖이다.

### 중간발표 화면 6개

| ID | 화면 | 핵심 목적 |
|---|---|---|
| `P0-001` | 가상 로그인·역할 선택 | 세 역할과 합성·목업 표시 |
| `P0-010` | 운영 홈 | 질의 진입, 이상징후 카드, dataset 상태 |
| `P0-020` | 대화형 분석 | 질문, 처리 상태, SQL·표·차트·설명·권한 범위 |
| `P0-030` | 이상징후 상세 | trigger, 비교 기간, 지표, 데이터 상태 |
| `P0-040` | 이슈 브리프 | 관측 사실, 원인 후보, 반대 근거, 부족 데이터, 확인 과제 |
| `P0-050` | 주간 보고서 | 초안, evidence, 한계, 승인·보류·반려 |

현장 확인 메모는 `P0-040` 안의 form 또는 drawer로 둔다.

### 공통 실행 계약

- Client 호출 방향: `React → Django → Django worker → FastAPI → PostgreSQL/LLM`
- 외부 공개 backend: Django 하나
- 분석 DB 접근: FastAPI read-only role 하나
- job 상태: `PENDING`, `RUNNING`, `SUCCEEDED`, `PARTIAL`, `NEEDS_DATA`, `FAILED`
- report 상태: `DRAFT`, `APPROVED`, `ON_HOLD`, `REJECTED`
- 공통 context: `request_id`, `run_id`, `actor_id`, `role_code`, `scope_snapshot`, `dataset_version`, `virtual_as_of_date`

### Baseline 데이터 범위

- 객실 운영
- 조식 운영
- 조식 인력
- VOC
- platform metadata·catalog·run·evidence·report·decision

실제 서비스 구역명 대신 `GW_BREAKFAST_DEMO`를 사용한다. timestamp는 UTC 저장, `Asia/Seoul` 표시다.

## 확장 방향

Baseline 실행 경로에서 제외한다.

- 실제 PMS·POS·CRM·근태·VOC 연동과 실시간 수집
- 본사·경영진 계정·대시보드·자동 전송
- 고객 메시지·보상·인력 배치 등 자동 조치
- GraphDB·GraphRAG·OWL, 범용 MCP, agent swarm
- 수요·매출·이탈 예측과 다호텔 비교

실험 트랙은 런타임과 분리한다.

- VOC 분류 ML/DL 2종 비교
- pgvector 기반 유사 VOC 검색
- API LLM과 sLLM 비교
- 단일 Incident Agent와 계획·조사·작성 3역할 구성 비교

## 기준 문서와 읽기 순서

1. `/AGENTS.md`
2. `/docs/markdown/final_project/00_project_control.md`
3. `/docs/markdown/final_project/common_project_specification.md`
4. 담당 영역의 데이터·API·테스트 계약
5. `/docs/markdown/05_화면설계서_초안.md`
6. 개별 작업 지시서

제품 방향의 원본은 2026-07-20 `Hotel Signal AI 최종 방향성 및 Baseline 기획서`다. 화면설계서는 이를 UI 계약으로 구체화하고, 공용 명세는 코드·데이터·API·시험 계약으로 전개한다. 충돌 시 `AGENTS.md → 00_project_control.md → 공용 계약 → 화면 상세 → 개별 프롬프트` 순서로 적용한다.

## 공통 ID 규칙

| 접두사 | 의미 | 예시 |
|---|---|---|
| `REQ-F-*`, `REQ-NF-*` | 기능·비기능 요구사항 | `REQ-F-001` |
| `DATA-*` | 데이터 계약 | `DATA-001` |
| `DB-*` | table·view | `DB-001` |
| `API-*` | Django 외부 API | `API-001` |
| `API-AI-*` | FastAPI 내부 API | `API-AI-001` |
| `UI-*` | 화면 요구사항 | `UI-001` |
| `P0-*` | Baseline 화면 | `P0-020` |
| `MODEL-*` | 모델·프롬프트 | `MODEL-001` |
| `RULE-*` | 결정론 규칙 | `RULE-001` |
| `TC-*` | 테스트 | `TC-E2E-001` |
| `DEC-*`, `DOC-*` | 결정·산출물 | `DEC-001`, `DOC-001` |

ID는 재사용하거나 의미를 바꾸지 않는다.

## 현재 결정 상태

| ID | 결정 | 상태 |
|---|---|---|
| `DEC-001` | Baseline은 기능 A·B 두 경로 | 확정 |
| `DEC-002` | 중간발표는 비연동 6화면 fixture | 확정 |
| `DEC-003` | Django 외부 경계·FastAPI 분석 경계 | 확정 |
| `DEC-004` | 실제 서비스 구역명 대신 `GW_BREAKFAST_DEMO` | 확정 |
| `DEC-005` | VectorDB·sLLM·멀티 에이전트 비교는 분리 실험 | 평가 의무 확인 필요 |
| `DEC-006` | schema v0 동결일과 PROJECT_CALIBRATION 값 | 사람 승인 필요 |

## 변경 승인 규칙

1. 변경할 요구사항·data·API·화면·test ID를 명시한다.
2. React·Django·FastAPI·데이터·시험 소비자 영향을 확인한다.
3. schema·role·status·endpoint 변경은 공용 계약과 fixture를 함께 갱신한다.
4. 승인 전 기존 ID 의미를 바꾸거나 확장 기술을 런타임 의존성으로 추가하지 않는다.
5. 실제 구현·시험 evidence가 없으면 완료로 표시하지 않는다.

## 변경 이력

| version | date | 변경 |
|---|---|---|
| `2.0` | 2026-07-20 | 최종 Baseline 기획서 기준으로 단일 축소 경로를 폐기하고 두 기능·6화면·Django/FastAPI 실제 연결 계약으로 재정렬 |
