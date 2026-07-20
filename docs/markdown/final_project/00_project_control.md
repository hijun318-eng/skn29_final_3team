# Hotel Signal AI 프로젝트 통제 문서

## 1. 결론

Hotel Signal AI의 P0는 합성 데이터 V1·V2를 이용한 단일 Golden Path로 고정한다. 다만 문서 재검증 결과, 기존 P0 계약 전체를 첫 구현 단위로 적용하면 독립 FastAPI, 운영 수준 인증·감사, 8개 API·데이터 그룹과 전체 시험을 동시에 요구하는 것으로 오해할 수 있어 베이스라인 프로토타입보다 크다. 따라서 첫 실행 단위를 `Baseline`으로 별도 고정하고, 나머지 P0 계약은 Baseline 통과 후 강화 범위로 적용한다.

`Baseline`은 P0를 대체하지 않는다. 조식 대기 시나리오 하나로 Golden Path를 끝까지 실행하기 위한 가장 작은 수직 슬라이스이며, 다른 Codex 세션은 Baseline을 먼저 구현하고 명시적 승인 없이 P0 강화 항목을 선행하지 않는다.

요청안의 문서 수에는 “5개 제한”과 6개 파일 목록이 함께 있어 그대로 적용할 수 없다. 기존 `common_project_specification.md`가 `01_common_development_specification.md`와 같은 역할을 이미 수행하므로 중복 파일을 만들지 않고, 아래 6개만 공용 개발 기준으로 지정한다.

1. `00_project_control.md`
2. `common_project_specification.md` — 요청안의 `01_common_development_specification.md` 역할
3. `02_data_standard_guide.md`
4. `03_api_ai_integration_contract.md`
5. `04_deliverable_traceability_matrix.md`
6. `05_test_acceptance_guide.md`

## 2. 사람이 판단해야 할 사항

- [ ] ML/DL 학습결과서와 모델 파일의 실제 평가 필수 여부
  - 권장안: 필수라면 VOC 감정 또는 카테고리 분류 1개 과제에서 baseline 1개와 후보 모델 1개만 비교한다.
  - 선택 시 영향: `MODEL-001`과 ML 평가 test를 P1에서 구현한다.
  - 미선택 시 영향: P0는 규칙·LLM 보조 분류만 사용하고 ML 결과를 생성하지 않는다.

- [ ] VectorDB·GraphDB 실제 구축 의무
  - 권장안: P0는 PostgreSQL ontology-lite만 사용하고, 평가 의무가 확인될 때만 작은 검증 저장소를 P1로 둔다.
  - 선택 시 영향: 별도 검증 범위·성능 기준·산출물 증거가 필요하다.
  - 미선택 시 영향: 미도입 결정과 대체 구조를 산출물 추적표에 남긴다.

- [ ] 멀티 에이전트의 물리적 분리 의무
  - 권장안: `Detect → Analyze Evidence → Generate Report`의 결정론적 workflow를 사용한다.
  - 선택 시 영향: 분리된 agent 간 상태·timeout·fallback test가 추가된다.
  - 미선택 시 영향: 하나의 orchestration workflow 안에서 논리적 역할만 분리한다.

- [ ] 자체 sLLM 적용 대상 여부
  - 권장안: 평가 필수가 아니면 제외하고, 필수일 때도 별도 실험으로 분리한다.
  - 선택 시 영향: base 모델과 tuning 모델의 데이터·평가·비용 관리가 추가된다.
  - 미선택 시 영향: P0 웹 Golden Path에 sLLM을 연결하지 않는다.

- [ ] STT 적용 여부
  - 권장안: P0 제외, P1에서 파일 업로드·변환·사용자 확인까지만 검토한다.
  - 선택 시 영향: 음성 개인정보·저작권·보관 정책이 추가된다.
  - 미선택 시 영향: 텍스트 VOC만 처리한다.

P0 사용자는 `HOTEL_MANAGER`, `DEPARTMENT_REVIEWER`로 결정됐다. `SYSTEM_ADMIN`, 본사·경영진·고객 계정은 P0에서 제외한다.

## 3. 판단 체크리스트

- [ ] 교육 담당자에게 ML/DL, VectorDB·GraphDB, 멀티 에이전트, sLLM의 실제 제출 의무를 확인했는가
- [ ] 미확정 기술을 WBS나 산출물에서 완료로 표시하지 않았는가
- [ ] 선택한 기술이 단일 Golden Path의 검증 가능성을 높이는가
- [ ] 새 dependency·서비스·저장소의 소유자와 test가 정해졌는가
- [ ] 선택 결과를 `DEC-*`와 `04_deliverable_traceability_matrix.md`에 기록했는가

## 4. 필수 최소 기능 구현 방향

```text
합성 데이터 V1 적재
→ 데이터 정형화
→ 규칙 기반 이상 징후 감지
→ 관련 리뷰·운영지표 근거 조회
→ 원인 후보·반대 근거·데이터 부족 구분
→ 현장 확인 메모
→ 주간 운영 보고서 초안
→ 호텔 관리자 승인·보류·반려
→ 합성 데이터 V2 반영
→ 분석 결과와 보고서 변화 확인
```

P0는 고객 대상 서비스나 실제 워커힐 운영 시스템이 아니다. 공개 참고정보와 합성 데이터만 사용하며, 결과를 실제 호텔 문제·성과로 표현하지 않는다.

Baseline 구현은 아래로 제한한다.

| 구분 | Baseline 확정 범위 |
|---|---|
| 시나리오 | 조식 대기 이상 1개 |
| 데이터 | 같은 schema의 `synthetic-v1`, `synthetic-v2` fixture와 manifest |
| 분석 | `RULE-001` 1개, 대표 VOC·대기시간·방문객 수·근무 인원 evidence |
| 설명 | 결정론적 template 우선, LLM은 선택적 1회 호출과 실패 fallback |
| 화면 | 역할 선택, dashboard, signal 상세·현장 메모, report 검토의 4개 화면 |
| 실행 구조 | React thin UI, Django 단일 업무 API·로컬 persistence, `src/analysis`, `src/common` |
| FastAPI | 폴더 경계만 유지하고 별도 process는 실행하지 않음 |
| 권한 | 두 역할을 선택하는 demo mock과 server-side 역할 검사 |
| 저장 | 교육용 local DB 또는 fixture 저장; 운영 DB·SSO·배포 구성 제외 |
| 검증 | Baseline 필수 test 6개: `TC-BL-001`~`005`, `TC-E2E-001` |

Baseline에서 구현하지 않는 항목은 운영 계정·SSO, 완전한 객체 권한 체계, 독립 FastAPI, 8개 물리 테이블, 전체 8개 공개 endpoint 분리, 운영 수준 감사·관측성, ML·VectorDB·GraphDB·멀티 에이전트·sLLM·STT다.

## 5. 확장 방향

| 우선순위 | 범위 | 진입 조건 |
|---|---|---|
| Baseline | 조식 대기 1개 시나리오, rule 1개, V1·V2, 통합 API 5개, 4개 화면 | 첫 실행 가능한 프로토타입 |
| P0 강화 | 공통 상태·세분 endpoint·권한·감사·품질 계약 강화 | Baseline E2E 통과 후 필요 항목만 승인 |
| P1 | 평가상 필요한 최소 ML, 저장소 검증, 3단계 workflow, STT 파일 변환 | P0 test 통과와 사람의 결정 |
| P2 | 실제 PMS·POS·CRM, 조직 권한, 운영 배포, 실제 데이터 거버넌스 | 호텔·법무·보안·운영 승인 |

자유형 Text-to-SQL, swarm, GraphRAG, 실시간 streaming, 자동 보상·업무 배정은 P0에 추가하지 않는다.

## 6. 공용 문서 적용 범위

상단의 다섯 섹션 순서 규칙은 이 문서를 포함한 6개 공용 개발 기준에 적용한다. 기존 형식을 유지해야 하는 `README.md`, 요구사항 정의서, WBS, 화면설계서, 일일·주간보고와 조사·일정 문서는 해당 고유 형식을 유지하고 공용 문서 링크만 최소 반영한다.

지원 문서는 공용 기준 6개 수에 포함하지 않는다.

- `codex_공용작업_가이드.md`: 다른 Codex 세션의 탐색·인계 진입점
- `dev_repository_structure_audit.md`: 특정 commit의 감사 기록
- `project_directory_structure.md`: 폴더 책임 상세
- `최종_프로젝트_산출물_및_전체_일정.md`: 교육 일정 근거
- `최종_프로젝트_오프닝_자료_요약_3팀.md`: 오프닝 자료 요약

## 7. 다른 Codex 세션의 필수 읽기 순서

```text
1. /AGENTS.md
2. /docs/markdown/final_project/codex_공용작업_가이드.md
3. /docs/markdown/final_project/00_project_control.md
4. /docs/markdown/final_project/common_project_specification.md
5. 담당 작업 관련 공용 문서
6. 개별 작업 지시서
```

담당별 추가 문서:

| 담당 | 추가로 읽을 문서 |
|---|---|
| 데이터·DB | `02_data_standard_guide.md` |
| React·Django·FastAPI | `03_api_ai_integration_contract.md` |
| AI·ML | `02_data_standard_guide.md`, `03_api_ai_integration_contract.md`, `05_test_acceptance_guide.md` |
| QA·산출물 | `04_deliverable_traceability_matrix.md`, `05_test_acceptance_guide.md` |

## 8. 문서 충돌 우선순위

```text
AGENTS.md
→ 00_project_control.md
→ 공용 명세 5개
→ 개별 산출물 명세
→ 개별 Codex 프롬프트
```

기존 `01_요구사항정의서.md`, `02_WBS.md`, `03_프로젝트기획서.md`, `05_화면설계서_초안.md`에 P0보다 넓은 기술이 있으면 삭제하지 않고 P1·P2 backlog 또는 평가 확인 대상으로 해석한다.

## 9. P0 기능과 제외 기능

### 9.1 Baseline 필수

- 조식 대기 시나리오의 versioned 합성 데이터 V1·V2
- `RULE-001` 기반 이상 신호와 연결된 VOC·운영지표 evidence
- 원인 후보·반대 근거·missing data를 구분한 template 또는 선택적 LLM 설명
- 현장 확인 메모와 긍정 VOC가 포함된 주간 보고서 작업본
- demo 역할 검사와 호텔 관리자 승인·보류·반려
- V1→V2 결과 변화의 재현 가능한 E2E

### 9.2 P0 강화

- 8개 논리 데이터 그룹의 독립 persistence
- 8개 공개 endpoint의 물리적 분리
- 전체 상태 전이·오류 code·객체 권한·감사 log
- 추가 topic·aspect·sentiment와 복수 signal rule

위 항목은 Baseline 통과 뒤 실제 필요성이 확인된 경우에만 구현한다. 이 목록 전체를 첫 프로토타입 완료 조건으로 사용하지 않는다.

### 9.3 제외

- 고객 챗봇, 고객 자동 응답, 예약 대행
- 본사·경영진 별도 화면
- 실제 PMS·POS·CRM·실시간 리뷰 연동
- 자동 보상·환불·객실 업그레이드·직원 평가
- 자유형 SQL 실행과 LLM trigger 판단

## 10. 공통 ID 규칙

| ID family | 용도 | 예시 |
|---|---|---|
| `REQ-F-*` | 기능 요구사항 | `REQ-F-001` |
| `REQ-NF-*` | 비기능 요구사항 | `REQ-NF-001` |
| `DATA-*` | 데이터셋·데이터 계약 | `DATA-001` |
| `DB-*` | 테이블·저장소 | `DB-001` |
| `API-*` | 외부 업무 API | `API-001` |
| `API-AI-*` | Django↔AI 내부 API | `API-AI-001` |
| `MODEL-*` | ML·DL·LLM model | `MODEL-001` |
| `RULE-*` | trigger·업무 규칙 | `RULE-001` |
| `ARCH-*` | 아키텍처 구성요소 | `ARCH-001` |
| `TC-{LEVEL}-*` | test case | `TC-E2E-001`, `TC-DQ-001` |
| `BUG-*` | 결함 | `BUG-001` |
| `DEC-*` | 의사결정 | `DEC-001` |
| `DOC-*` | 산출물 | `DOC-001` |

기존 `BIZ-*`, `DAT-*`, `FUN-*`, `AI-*`, `UI-*` 등 62개 요구사항 ID는 이미 의미가 부여됐으므로 재번호화·재사용하지 않는다. 새 `REQ-*`는 P0 공용 추적을 위한 상위 계약이며 `legacy_requirement_ids`로 기존 ID와 연결한다.

기존 `UI-*`는 화면 ID가 아니라 UI 요구사항 ID다. 실제 P0 화면은 화면설계서의 `P0-001`, `P0-010`, `P0-020`, `P0-030`을 유지한다.

## 11. 변경 승인 규칙

1. 변경 대상 ID와 현재 version을 확인한다.
2. P0·P1·P2 중 영향 범위를 표시한다.
3. data·API·UI·test·deliverable 영향 ID를 기록한다.
4. 기존 의미 변경이 필요하면 기존 ID를 폐기 상태로 두고 새 ID를 발급한다.
5. `DEC-*`에 선택·근거·승인자를 기록한다.
6. 공용 문서, 요구사항, WBS, test와 evidence path를 같은 변경에서 갱신한다.
7. 코드·DB migration·외부 연동은 별도 구현 승인을 받는다.

## 12. 현재 결정 상태

| decision_id | 항목 | 상태 | 현재 결정 |
|---|---|---|---|
| `DEC-001` | 공용 문서 수·경로 | 확정 | 기존 공통 명세를 포함한 6개, 신규 `01` 중복 생성 금지 |
| `DEC-002` | 기존 요구사항 ID | 확정 | 유지하고 `REQ-*`와 mapping |
| `DEC-003` | P0 사용자 | 확정 | `HOTEL_MANAGER`, `DEPARTMENT_REVIEWER` |
| `DEC-004` | V1·V2 전환 | 확정 | Django management command 한 가지 |
| `DEC-005` | ML/DL | 판단 필요 | 평가 의무 확인 전 P1 |
| `DEC-006` | VectorDB·GraphDB | 판단 필요 | P0 미도입 |
| `DEC-007` | 멀티 에이전트 | 판단 필요 | P0 3단계 workflow |
| `DEC-008` | sLLM | 판단 필요 | P0 제외 |
| `DEC-009` | STT | 판단 필요 | P0 제외 |
| `DEC-010` | 첫 Baseline 구현 단위 | 확정 | React thin UI + Django 단일 API·local persistence + `src`; FastAPI 별도 process 제외 |

## 13. 변경 이력

| version | 날짜 | 변경 | 상태 |
|---|---|---|---|
| `1.0` | 2026-07-20 | 기존 공통 명세를 보존한 6개 공용 문서 체계, ID 호환, 결정 gate 정의 | 사용자 검토 전 |
| `1.1` | 2026-07-20 | P0 전체 계약과 첫 Baseline 구현 단위를 분리하고 독립 FastAPI·운영 수준 통제를 후속 강화로 축소 | 사용자 검토 전 |
