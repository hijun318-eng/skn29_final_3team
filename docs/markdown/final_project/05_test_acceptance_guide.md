# Hotel Signal AI 테스트·인수 가이드

## 1. 결론

Baseline 완료는 `TC-BL-001`~`TC-BL-005`와 `TC-E2E-001`의 6개 test가 실제로 통과한 상태다. 기존의 세부 unit·contract·data quality·AI·security inventory는 P0 강화 대상이며 첫 프로토타입을 차단하지 않는다. 문서·폴더·코드 존재만으로 완료 처리하지 않는다.

## 2. 사람이 판단해야 할 사항

- [ ] P0 합격 threshold
  - 권장안: Baseline 필수 6개 test 100% 통과, 미해결 severity 1·2 defect 0건
  - 선택 시 영향: release gate가 명확해짐
  - 미선택 시 영향: 발표 직전 완료 판단이 주관적이 됨

- [ ] ML/DL 평가 대상
  - 권장안: 실제 구현 승인 시에만 `TC-ML-*`와 모델 2개 비교 수행
  - 선택 시 영향: split·metric·model artifact evidence 필요
  - 미선택 시 영향: ML 결과 section을 `NOT_ADOPTED`로 유지

- [ ] 관리자 수용성 평가 참여자·일정
  - 권장안: 역할별 시나리오 검토자 최소 1명과 중간발표 전 dry-run
  - 선택 시 영향: UAT evidence와 개선 feedback 확보
  - 미선택 시 영향: 내부 개발자 검증만 수행했다는 한계 표시

## 3. 판단 체크리스트

- [ ] 모든 P0 `REQ-*`에 최소 1개 test가 있는가
- [ ] 정상·empty·error·permission 경로가 있는가
- [ ] V1과 V2 기대 결과가 manifest와 test fixture에 분리돼 있는가
- [ ] LLM 실패 시 signal·metric·evidence가 유지되는가
- [ ] 실제 실행하지 않은 test를 통과로 표시하지 않았는가
- [ ] evidence path와 실행 commit·version이 기록되는가

## 4. 필수 최소 기능 구현 방향

- `TC-BL-001`: V1·V2 fixture·manifest·PII 최소 검증
- `TC-BL-002`: V1과 V2의 `RULE-001` 결과 변화
- `TC-BL-003`: signal과 VOC·운영지표 evidence ID 연결
- `TC-BL-004`: AI 미사용·실패 시 rule·evidence·template report 유지
- `TC-BL-005`: 현장 메모 반영과 관리자 decision 역할 검사
- `TC-E2E-001`: V1→V2→signal→note→report→approval 전체 흐름

## 5. 확장 방향

- P1: ML 비교, 독립 FastAPI 부하·failure test, 검증 저장소 test
- P2: 실제 개인정보·SSO·연동·DR·운영 monitoring test
- P0 제외: 실시간 streaming·대규모 load·다중 property test

## 6. test 수준

| 수준 | ID prefix | 목적 | 기본 위치 |
|---|---|---|---|
| Unit | `TC-UNIT-*` | 순수 function·rule·상태 전이 | `tests/` |
| Integration | `TC-INT-*` | DB·service 조합 | `tests/` |
| Contract | `TC-CT-*` | API·AI schema·consumer contract | `tests/` |
| Data Quality | `TC-DQ-*` | schema·version·PII·분포 | `tests/`, `evals/` |
| AI Evaluation | `TC-AI-*` | evidence·환각·fallback | `evals/` |
| ML Evaluation | `TC-ML-*` | model 비교 | `evals/` |
| Security | `TC-SEC-*`, `TC-AUTH-*` | secret·권한·개인정보 | `tests/` |
| End-to-End | `TC-E2E-*` | Golden Path | 승인 후 `tests/e2e/` |
| User Acceptance | `TC-UAT-*` | 역할별 수용성 | `evals/reports/` |

`tests/e2e/`와 `evals/reports/`는 실제 test·결과 파일을 만들 때만 생성한다.

## 7. test case field

```text
test_case_id
requirement_ids
title
precondition
input
steps
expected_result
actual_result
status
evidence_path
executed_at
executor
bug_ids
data_version
schema_version
rule_version
model_version
analysis_version
commit_sha
```

status:

```text
NOT_RUN
PASS
FAIL
BLOCKED
SKIPPED_WITH_REASON
```

## 8. P0 E2E 시나리오

### `TC-E2E-001` V1→V2 분석·보고 변화

| field | 내용 |
|---|---|
| requirement_ids | `REQ-F-001`~`REQ-F-007`, `REQ-NF-001`, `REQ-NF-002` |
| precondition | versioned V1·V2 fixture, `RULE-001`, 두 역할, report template 준비 |
| input | `synthetic-v1`, `synthetic-v2` |
| expected | V1 낮은 또는 정상 signal, V2 조식 대기 signal·evidence·report 변화 |
| current status | `NOT_RUN` |
| evidence_path | 미생성 |

단계:

```text
V1 데이터 적재
→ 정상 상태 또는 낮은 이상 신호 확인
→ V2 데이터 적재
→ RULE-001 trigger 발생
→ VOC·운영지표 evidence 표시
→ 부서 관리자 현장 메모 제출
→ 주간 보고서 재생성
→ 호텔 관리자 승인
```

필수 assertion:

1. 화면·API·보고서에 `data_version`이 표시된다.
2. 동일 input·rule version은 동일 signal을 생성한다.
3. signal에 대표 VOC와 운영 metric evidence ID가 연결된다.
4. AI는 원인을 확정하지 않고 counter evidence와 missing data를 분리한다.
5. field note가 report에 반영된다.
6. 승인 전 report는 최종 확정되지 않는다.
7. `DEPARTMENT_REVIEWER`가 승인할 수 없다.
8. LLM failure 후에도 signal·metric·evidence가 유지된다.
9. V2 report는 V1과 달라진 section과 version을 표시한다.
10. repository에 secret과 실제 고객 data가 없다.

## 9. Baseline 필수 test

| test_case_id | 검증 | 완료 조건 |
|---|---|---|
| `TC-BL-001` | fixture·manifest·필수 schema·PII | 두 version 모두 검증 통과 |
| `TC-BL-002` | `RULE-001` 재현 | V1 정상·낮음, V2 trigger |
| `TC-BL-003` | evidence 연결 | VOC와 metric evidence ID 존재 |
| `TC-BL-004` | AI fallback | AI 없이도 signal·evidence·report 작업본 유지 |
| `TC-BL-005` | note·decision | note 반영, reviewer 승인 거부, manager 승인 허용 |
| `TC-E2E-001` | 전체 Golden Path | 화면 또는 API 시연과 실행 evidence 존재 |

## 10. P0 강화 test inventory

아래 세부 test는 Baseline 통과 뒤 해당 기능을 실제로 강화할 때 활성화한다. Baseline 단계에서는 `NOT_RUN`이 정상이며 완료 실패로 계산하지 않는다.

| test_case_id | requirement_ids | 검증 | 상태 | evidence |
|---|---|---|---|---|
| `TC-UNIT-001` | `REQ-F-002` | `RULE-001` boundary·minimum sample·version | `NOT_RUN` | 미생성 |
| `TC-UNIT-002` | `REQ-F-007` | report status 허용·금지 전이 | `NOT_RUN` | 미생성 |
| `TC-DQ-001` | `REQ-F-001` | primary key uniqueness | `NOT_RUN` | 미생성 |
| `TC-DQ-002` | `REQ-F-001` | property ID exact match | `NOT_RUN` | 미생성 |
| `TC-DQ-003` | `REQ-F-001` | code catalog membership | `NOT_RUN` | 미생성 |
| `TC-DQ-004` | `REQ-F-001` | required date·timestamp | `NOT_RUN` | 미생성 |
| `TC-DQ-005` | `REQ-F-001`, `REQ-NF-002` | optional experience date 추정 금지 | `NOT_RUN` | 미생성 |
| `TC-DQ-006` | `REQ-F-001` | count non-negative | `NOT_RUN` | 미생성 |
| `TC-DQ-007` | `REQ-F-001` | rate·ratio range | `NOT_RUN` | 미생성 |
| `TC-DQ-008` | `REQ-NF-001` | VOC PII scan·mask | `NOT_RUN` | 미생성 |
| `TC-DQ-009` | `REQ-F-001` | duplicate reject | `NOT_RUN` | 미생성 |
| `TC-CT-001` | `REQ-NF-002` | 성공 envelope | `NOT_RUN` | 미생성 |
| `TC-CT-002` | `REQ-NF-002` | 실패 envelope | `NOT_RUN` | 미생성 |
| `TC-CT-003` | `REQ-F-003`, `REQ-NF-001` | role별 signal·evidence 범위 | `NOT_RUN` | 미생성 |
| `TC-CT-004` | `REQ-F-005` | field note 중복 방지·입력 보존 | `NOT_RUN` | 미생성 |
| `TC-CT-005` | `REQ-F-007` | report version·상태 충돌 | `NOT_RUN` | 미생성 |
| `TC-AI-001` | `REQ-F-004` | evidence 없는 주장 거부 | `NOT_RUN` | 미생성 |
| `TC-AI-002` | `REQ-NF-002` | invalid JSON fallback | `NOT_RUN` | 미생성 |
| `TC-AI-003` | `REQ-F-004`, `REQ-F-006` | timeout 후 signal·evidence 유지 | `NOT_RUN` | 미생성 |
| `TC-AUTH-001` | `REQ-F-005`, `REQ-NF-001` | 담당 외 field note 거부 | `NOT_RUN` | 미생성 |
| `TC-AUTH-002` | `REQ-F-007`, `REQ-NF-001` | reviewer 승인 거부 | `NOT_RUN` | 미생성 |
| `TC-SEC-001` | `REQ-NF-001` | Git secret pattern 0건 | `NOT_RUN` | 미생성 |
| `TC-SEC-002` | `REQ-NF-001` | log PII·token 미포함 | `NOT_RUN` | 미생성 |
| `TC-SEC-003` | `REQ-NF-001` | prompt injection data 격리 | `NOT_RUN` | 미생성 |
| `TC-E2E-001` | 전체 P0 | V1→V2 Golden Path | `NOT_RUN` | 미생성 |

## 11. 정상·empty·error·권한

각 P0 화면과 API는 다음을 검증한다.

- 정상: expected data·version·근거 표시
- empty: 정상적인 0건과 `NEEDS_DATA` 구분
- error: 부분 성공 data 유지와 request ID 표시
- permission: 목록·상세·수정·decision object 권한
- conflict: stale report version·중복 note 처리
- recovery: 사용자가 입력한 field note 보존

## 12. AI 평가

| 평가 | 지표·assertion |
|---|---|
| evidence grounding | 모든 수치 주장에 존재하는 evidence ID |
| factual boundary | observed fact와 cause candidate 분리 |
| uncertainty | missing data·counter evidence 누락률 |
| prohibited action | 자동 보상·인력 배치·원인 확정 0건 |
| contract | JSON schema validation rate |
| fallback | timeout·invalid output에서 deterministic result 유지 |
| reproducibility | 같은 version·input의 구조·source ID 일치 |

정답률 기준은 eval dataset과 reviewer 합의 후 version으로 고정한다. 기준이 없으면 임의 합격 수치를 만들지 않는다.

## 13. ML/DL 평가

실제 ML/DL 구현이 승인된 경우에만 작성한다.

- baseline model 1개
- candidate model 1개
- 동일 split·seed
- accuracy, precision, recall, F1
- confusion matrix
- inference time
- train·validation gap과 과적합 점검
- 최종 선정 또는 미선정 근거
- dataset·model·code version

구현하지 않으면 `MODEL-001=NOT_ADOPTED` 또는 `DECISION_REQUIRED`로 두고 결과를 작성하지 않는다.

## 14. evidence 저장

test 결과가 생길 때 다음 기준을 사용한다.

```text
evals/reports/<test_run_id>/summary.md
evals/reports/<test_run_id>/results.json
evals/reports/<test_run_id>/screenshots/
```

실행 전에는 위 폴더를 만들지 않는다. evidence에는 commit SHA, 환경, data·schema·rule·model·analysis version과 실행 시각을 포함한다. 실제 개인정보와 secret은 저장하지 않는다.

## 15. 결함 관리

| field | 설명 |
|---|---|
| `bug_id` | `BUG-001` 형식 |
| `severity` | 1 critical, 2 major, 3 normal, 4 minor |
| `related_test_case_ids` | 재현 test |
| `affected_versions` | data·schema·rule·model·analysis |
| `reproduction_steps` | 최소 재현 절차 |
| `expected`·`actual` | 기대·실제 결과 |
| `status` | OPEN·FIXED·VERIFIED·DEFERRED |
| `evidence_path` | log·capture·result |

## 16. Baseline 인수 기준

- `TC-BL-001`~`005`, `TC-E2E-001` 100% `PASS`
- severity 1·2 미해결 defect 0건
- `TC-E2E-001` 실제 실행 evidence 존재
- Baseline Golden Path의 requirement와 test mapping 존재
- 합성 데이터·version·근거·한계가 화면과 report에 표시
- manager 승인 전 report 미확정
- LLM failure fallback 통과
- Git secret·실제 고객 data 0건
- 미구현 ML·VectorDB·GraphDB·sLLM·멀티 에이전트 결과 조작 0건

P0 강화 인수는 실제로 구현한 세부 계약에 해당하는 기존 `TC-UNIT-*`, `TC-DQ-*`, `TC-CT-*`, `TC-AI-*`, `TC-AUTH-*`, `TC-SEC-*`만 추가 적용한다.

## 17. 변경 이력

| version | 날짜 | 변경 |
|---|---|---|
| `1.0` | 2026-07-20 | P0 test ID, V1→V2 E2E, data·API·AI·security test와 인수 gate 정의 |
| `1.1` | 2026-07-20 | Baseline 필수 test를 6개로 제한하고 기존 상세 inventory를 P0 강화 단계로 이동 |
