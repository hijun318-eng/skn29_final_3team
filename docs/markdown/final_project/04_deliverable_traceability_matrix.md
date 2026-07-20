# Hotel Signal AI 산출물 추적 매트릭스

## 1. 결론

공식 산출물 16개는 프로젝트 전체 제출 추적 대상이지 Baseline 구현 선행조건이 아니다. 첫 프로토타입은 아래 5개 evidence gate만 충족하고, 나머지 산출물은 원래 일정과 판단 상태를 유지한다. 파일이 존재하는 것과 구현·검증이 완료된 것은 다르다.

## 2. 사람이 판단해야 할 사항

- [ ] ML/DL 학습결과서·model 파일의 필수 여부
  - 권장안: 교육 담당자 확인 후 `DOC-007`, `DOC-008`의 required와 범위를 함께 확정
  - 선택 시 영향: `MODEL-001`, `TC-ML-*`, model artifact 경로 필요
  - 미선택 시 영향: `NOT_ADOPTED`와 대체 근거 기록

- [ ] VectorDB·GraphDB 구축결과서의 대체 가능 여부
  - 권장안: ontology-lite 대체를 우선하고 실제 구축 의무가 있을 때만 P1 검증
  - 선택 시 영향: 성능·갱신·삭제 evidence 필요
  - 미선택 시 영향: `DOC-009`에 미도입 결정과 평가 대응 기록

- [ ] 멀티 에이전트·sLLM 실제 제출 의무
  - 권장안: 3단계 workflow와 미도입 근거를 먼저 제시
  - 선택 시 영향: `DOC-010`~`DOC-012`의 test·모델 evidence 추가
  - 미선택 시 영향: 상태를 `NOT_ADOPTED` 또는 `대체`로 기록

## 3. 판단 체크리스트

- [ ] 모든 P0 요구사항에 test ID가 있는가
- [ ] 완료 상태에 실제 code·test·evidence path가 있는가
- [ ] 미도입 기술을 완료로 표시하지 않았는가
- [ ] 존재하지 않는 캡처·log·model path를 적지 않았는가
- [ ] owner·due date가 WBS와 일치하는가
- [ ] 변경 시 `version`, `notes`, 관련 ID가 함께 갱신되는가

## 4. 필수 최소 기능 구현 방향

Baseline 구현은 다음 5개 gate로만 판정한다. `DATA-*`와 `API-*`는 논리 연결을 유지하되 모두를 독립 파일·table·endpoint로 만들지 않는다.

| gate | 필수 evidence | 관련 산출물 |
|---|---|---|
| Baseline 계약 | Baseline 범위·제외·결정 기록 | `DOC-001`, `DOC-002`, `DOC-003` |
| V1·V2 데이터 | fixture, manifest, schema 검증 결과 | `DOC-004`, `DOC-006` |
| rule·evidence | `RULE-001` 실행 결과와 evidence ID | `DOC-010`, `DOC-014` |
| 4화면 demo | 역할 선택→report 결정 화면 | `DOC-013`, `DOC-014` |
| E2E 검증 | `TC-BL-001`~`005`, `TC-E2E-001` 결과 | `DOC-016` |

공식 산출물 매핑 표의 16개 행은 삭제하지 않는다. ML/DL·VectorDB·GraphDB·멀티 에이전트·sLLM 관련 행과 운영 수준 시스템 문서는 Baseline을 차단하지 않으며, 교육 평가 의무가 확인된 뒤 P1·P2 또는 별도 산출물 작업으로 수행한다.

## 5. 확장 방향

- P1: `MODEL-001`, 검증 저장소, workflow test 산출물
- P2: 실제 system architecture, 개인정보·보안·운영 evidence
- 미도입 기술: `DECISION_REQUIRED` → `NOT_ADOPTED` 또는 승인된 scope로 전환

## 6. 상태 값

```text
미착수
진행
검토
완료
차단
DECISION_REQUIRED
NOT_ADOPTED
대체
```

`완료`는 파일 존재가 아니라 acceptance test와 evidence까지 충족한 상태다.

## 7. P0 목표 요구사항 연결

아래 표는 최종 P0 추적 계약이다. Baseline에서는 각 행을 조식 대기 시나리오의 얇은 수직 슬라이스로 충족하고 상세 test·API 분리는 P0 강화에서 수행한다.

| requirement_id | 요구사항 | legacy_requirement_ids | data·rule | API·화면 | test |
|---|---|---|---|---|---|
| `REQ-F-001` | V1·V2 합성 데이터 정형화·적재 | `DAT-001`, `DAT-003`, `DAT-005`, `DAT-008`, `FUN-003`, `FUN-004` | `DATA-001`~`DATA-003` | management command, `P0-010` | `TC-DQ-001`~`009`, `TC-E2E-001` |
| `REQ-F-002` | 결정론적 이상 signal 생성 | `AI-005`~`AI-009`, `FUN-013` | `DATA-004`, `DATA-005`, `RULE-001` | `API-001`~`003`, `P0-010` | `TC-UNIT-001`, `TC-E2E-001` |
| `REQ-F-003` | VOC·운영지표 evidence 조회 | `BIZ-001`, `BIZ-003`, `AI-003`, `UI-003` | `DATA-006` | `API-004`, `P0-020` | `TC-CT-003`, `TC-E2E-001` |
| `REQ-F-004` | 원인 후보·반대 근거·missing data 분리 | `BIZ-002`, `AI-009`, `NFR-003` | `DATA-005`, `DATA-006` | `API-AI-002`, `P0-020` | `TC-AI-001`~`003` |
| `REQ-F-005` | 현장 확인 메모 | `FUN-007`, `BIZ-004` | `DATA-007` | `API-005`, `P0-020` | `TC-CT-004`, `TC-AUTH-001` |
| `REQ-F-006` | 긍정 VOC 포함 주간 보고서 초안 | `RPT-001`, `RPT-002` | `DATA-008` | `API-006`, `API-007`, `API-AI-003`, `P0-030` | `TC-E2E-001`, `TC-AI-003` |
| `REQ-F-007` | 관리자 승인·보류·반려 | `BIZ-004`, `FUN-002`, `SEC-003` | `DATA-008` | `API-008`, `P0-030` | `TC-CT-005`, `TC-AUTH-002` |
| `REQ-NF-001` | 개인정보·권한·secret 통제 | `FUN-002`, `FUN-005`, `SEC-001`~`003` | 전체 | 전체 | `TC-SEC-001`~`003` |
| `REQ-NF-002` | version·재현성·fallback | `BIZ-005`, `NFR-002`~`004`, `TST-003` | 전체 | 전체 | `TC-E2E-001`, `TC-AI-002`~`003` |

## 8. 산출물 매핑

| deliverable_id | deliverable_name | required | decision_status | requirement_ids | data_ids | db_ids | api_ids | ui_ids | model_ids | test_case_ids | source_code_paths | evidence_paths | owner | due_date | status | version | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DOC-001` | 요구사항 정의서 | 예 | 확정 | `REQ-*`, legacy 62개 | 전체 | `DB-001`~`005` | `API-*` | `P0-*` | TBD | `TC-*` | 없음, 문서 | `docs/markdown/01_요구사항정의서.md` | 박준희·송민지 | 07/16 | 검토 | 2.1 예정 | P0 상위 ID mapping 추가 필요 |
| `DOC-002` | WBS | 예 | 확정 | 전체 | 전체 | 전체 | 전체 | 전체 | TBD | 전체 | 없음, 문서 | `docs/markdown/02_WBS.md` | 송민지 | 07/16 | 진행 | v2 | 결과·evidence 연결 보강 |
| `DOC-003` | 프로젝트 기획서 | 예 | 확정 | P0 요약 | 전체 | 개념 | 개념 | P0 화면 | TBD | `TC-E2E-001` | 없음, 문서 | `docs/markdown/03_프로젝트기획서.md` | 박준희·송민지 | 07/24 | 진행 | v2 | 넓은 기존 범위는 backlog로 해석 |
| `DOC-004` | 수집 데이터 보고서 | 예 | 확정 | `REQ-F-001`, `REQ-NF-001` | `DATA-001`~`003` | 없음 | 없음 | 없음 | 없음 | `TC-DQ-*` | `data/samples/` 미구현 | 미생성 | 정승 | 07/24 | 미착수 | TBD | source·license·manifest 필요 |
| `DOC-005` | DB·저장소 설계 문서 | 예 | 확정 | `REQ-F-001`~`007` | 전체 | `DB-001`~`005` | `API-*` | 없음 | 없음 | `TC-CT-*`, `TC-DQ-*` | `app/django/`, `src/common/` 미구현 | 미생성 | 정승·김재홍 | 07/31 | 미착수 | TBD | Django migration 단일 주체 |
| `DOC-006` | 데이터 전처리 결과서 | 예 | 확정 | `REQ-F-001`, `REQ-NF-001` | `DATA-001`~`003` | 없음 | 없음 | 없음 | 선택 | `TC-DQ-*` | `src/analysis/` 미구현 | 미생성 | 정승 | 07/31 | 미착수 | TBD | V1·V2 동일 schema |
| `DOC-007` | ML/DL 학습결과서 | 확인 필요 | `DEC-005` | legacy `AI-001`, `AI-002` | `DATA-001` | 없음 | `API-AI-001` | 없음 | `MODEL-001` | `TC-ML-*` | `src/analysis/` 미구현 | 미생성 | 윤대성 | 08/07 | `DECISION_REQUIRED` | TBD | 모델 2개 비교 여부 확인 |
| `DOC-008` | 학습한 ML/DL model | 확인 필요 | `DEC-005` | legacy `AI-001`, `AI-002` | `DATA-001` | 없음 | `API-AI-001` | 없음 | `MODEL-001` | `TC-ML-*` | 미구현 | 미생성 | 윤대성 | 08/07 | `DECISION_REQUIRED` | TBD | model file 생성 금지 상태 |
| `DOC-009` | VectorDB·GraphDB 구축결과서 | 확인 필요 | `DEC-006` | legacy `DAT-006`, `DAT-007` | `DATA-001`, `DATA-006` | `DB-001`~`005` 대체 | 없음 | 없음 | embedding TBD | 저장소 평가 TBD | 미구현 | 미생성 | 김재홍·윤대성 | 08/07 | `DECISION_REQUIRED` | TBD | P0 ontology-lite 대체 |
| `DOC-010` | AI 시스템·멀티 에이전트 architecture | 예 | scope 판단 필요 | `REQ-F-002`~`006` | `DATA-004`~`008` | `DB-001`~`005` | `API-*`, `API-AI-*` | `P0-*` | LLM TBD | `TC-CT-*`, `TC-AI-*` | 구현 경계만 존재 | 미생성 | 김재홍·윤대성 | 08/14 | 진행 | TBD | P0는 3단계 workflow |
| `DOC-011` | 멀티 에이전트 test 계획·결과 | 확인 필요 | `DEC-007` | legacy `TST-002` | `DATA-004`~`008` | 없음 | `API-AI-*` | 없음 | LLM TBD | `TC-AI-*`, `TC-E2E-001` | 미구현 | 미생성 | 김재홍·윤대성 | 08/21 | `DECISION_REQUIRED` | TBD | 물리 분리 의무 확인 |
| `DOC-012` | 자체 sLLM | 확인 필요 | `DEC-008` | legacy `AI-004` | `DATA-001` | 없음 | `API-AI-001` | 없음 | `MODEL-002` 예정 | `TC-ML-*` | 미구현 | 미생성 | 윤대성 | 08/14 | `DECISION_REQUIRED` | TBD | P0 제외 |
| `DOC-013` | 화면설계서 | 예 | 확정 | `REQ-F-003`~`007` | `DATA-005`~`008` | 없음 | `API-001`~`008` | `P0-001`, `010`, `020`, `030` | 없음 | UX·auth TC | `app/react/` 미구현 | `docs/markdown/05_화면설계서_초안.md` | 송민지 | 07/24 | 진행 | 1.2 | P0 4화면 기준 존재 |
| `DOC-014` | LLM 연동 웹 application | 예 | 확정 | `REQ-F-*`, `REQ-NF-*` | 전체 | 전체 | 전체 | 전체 | 선택 | `TC-E2E-001` | `app/`, `src/` 구현 경계만 존재 | 미생성 | 전원 | 08/28 | 미착수 | TBD | framework 초기화 전 |
| `DOC-015` | 시스템 구성도 | 예 | 확정 | `REQ-NF-001`, `002` | 전체 | 전체 | 전체 | 전체 | 선택 | security·availability TC | 미구현 | 미생성 | 김재홍 | 08/21 | 미착수 | TBD | 배포 구조 미확정 |
| `DOC-016` | 서비스 test 계획·결과 | 예 | 확정 | 전체 P0 | 전체 | 전체 | 전체 | 전체 | 선택 | 전체 `TC-*` | `tests/`, `evals/` 미구현 | 미생성 | 전원 | 08/28 | 미착수 | TBD | 실제 결과 조작 금지 |

## 9. 미도입 기술 처리

```text
status = DECISION_REQUIRED
decision_status = DEC-005~DEC-008
evidence_paths = 미생성
notes = 미도입 권장안, 대체 구조, 평가 확인 계획
```

사람이 미도입을 승인하면 `status=NOT_ADOPTED` 또는 `대체`로 변경하고 `DEC-*` 기록을 연결한다. 구현하지 않은 결과·성능·model file을 만들지 않는다.

## 10. evidence 저장 규칙

- 문서 evidence: 실제 Markdown·산출물 경로
- code evidence: 실제 module path와 commit SHA
- test evidence: 실제 test report·log·screenshot path
- model evidence: model card, evaluation result, artifact hash
- 미생성 evidence: `미생성`으로 명시하고 가상 path를 만들지 않음
- 개인 로컬 절대경로를 공용 evidence path로 사용하지 않음

## 11. 변경 이력

| version | 날짜 | 변경 |
|---|---|---|
| `1.0` | 2026-07-20 | P0 요구사항 mapping과 공식 산출물 16개 상태·경로·미확정 기술 gate 정의 |
| `1.1` | 2026-07-20 | 공식 산출물 16개와 Baseline 구현 gate 5개를 분리해 첫 프로토타입의 완료 조건 축소 |
