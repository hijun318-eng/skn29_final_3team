# Hotel Signal AI Codex 공용 작업 가이드

## 1. 결론

다른 Codex 세션은 저장소에 들어오면 이 문서를 탐색용 진입점으로 사용한다. 정책과 구현 범위의 원본은 이 문서가 아니라 루트 `AGENTS.md`, `00_project_control.md`, `common_project_specification.md`다.

첫 구현 목표는 조식 대기 시나리오 하나를 끝까지 실행하는 Baseline 프로토타입이다. 담당 문서에 더 넓은 `Core`, P0, AI 또는 인프라 기능이 있더라도 Baseline 통과 전에는 임의로 구현하지 않는다.

## 2. 사람이 판단해야 할 사항

- [ ] 요청이 Baseline 구현인지 P0 강화·P1·P2 작업인지 구분한다.
  - 권장안: 명시가 없으면 Baseline만 작업한다.
  - P0 강화 이상이면 영향 범위와 추가 작업을 먼저 사용자에게 알린다.

- [ ] ML/DL, 독립 FastAPI, VectorDB·GraphDB, 멀티 에이전트, sLLM, STT가 실제 평가 필수인지 확인한다.
  - 권장안: 확인 전에는 구현하거나 완료로 표시하지 않는다.

- [ ] 기존 파일을 수정할지 새 파일을 만들지 판단한다.
  - 권장안: 같은 목적의 문서·module·schema가 있으면 기존 파일을 최소 수정한다.

- [ ] 작업 지침·WBS 원본을 변경해도 되는지 확인한다.
  - 권장안: 루트 `AGENTS.md`와 경로와 관계없이 `AI_AGENT_WBS.md`라는 파일은 사용자의 현재 명시 요청 없이는 변경하지 않는다. 프로젝트 일정·작업 결과는 `docs/markdown/02_WBS.md`에서 관리한다.

## 3. 작업 전 판단 체크리스트

- [ ] 저장소 root, 현재 branch, 기존 변경을 확인했는가
- [ ] 아래 필수 문서를 순서대로 읽었는가
- [ ] 담당 작업에 필요한 추가 문서를 읽었는가
- [ ] Baseline의 in-scope와 out-of-scope를 구분했는가
- [ ] 실제 구현 상태를 파일·code·test로 확인했는가
- [ ] 변경할 요구사항·data·API·화면·test ID를 확인했는가
- [ ] 완료 조건과 실행할 검증을 먼저 정했는가

## 4. 필수 최소 기능 구현 방향

Baseline은 다음 한 경로만 구현한다.

```text
synthetic-v1·v2 fixture
→ schema·PII 최소 검증
→ RULE-001 조식 대기 signal
→ VOC·운영지표 evidence
→ 원인 후보·반대 근거·missing data
→ 현장 확인 메모
→ 긍정 VOC 포함 주간 report 작업본
→ HOTEL_MANAGER 승인·보류·반려
→ V1과 V2 결과 변화 확인
```

| 항목 | Baseline 제한 |
|---|---|
| 시나리오 | `BREAKFAST_WAITING` 1개 |
| rule | `RULE-001` 1개 |
| 화면 | `P0-001`, `P0-010`, `P0-020`, `P0-030` 4개 |
| API | Django 통합 demo endpoint 5개 |
| 실행 service | React, Django, `src/analysis`, `src/common` |
| FastAPI | 폴더 경계만 유지, 실행하지 않음 |
| AI | 결정론적 template 우선, 선택적 LLM 1회와 fallback |
| persistence | local DB 또는 fixture |
| test | `TC-BL-001`~`TC-BL-005`, `TC-E2E-001` |

## 5. 확장 방향

구현 순서는 `Baseline → P0 강화 → P1 → P2`다.

- P0 강화: 세분 API·data persistence·객체 권한·감사·추가 rule
- P1: 평가 필수 최소 ML, 필요성이 검증된 독립 FastAPI와 저장소 실험
- P2: 실제 PMS·POS·CRM, 실제 조직 권한, 운영 배포와 데이터 거버넌스
- 승인 전 제외: 자유형 Text-to-SQL, RAG·GraphRAG, swarm, MCP, streaming, 자동 보상·환불·배정·직원 평가

## 6. 반드시 읽을 문서 순서

| 순서 | 문서 | 읽는 목적 |
|---:|---|---|
| 1 | [루트 AGENTS.md](../../../AGENTS.md) | AI 작업·Git·문서·보고의 최상위 규칙 |
| 2 | [프로젝트 통제 문서](./00_project_control.md) | Baseline·P0·P1·P2와 금지 범위 |
| 3 | [공통 명세서](./common_project_specification.md) | Golden Path, 역할, 상태, 공통 계약 |
| 4 | 아래 담당별 문서 | 실제 변경 대상의 세부 계약 |
| 5 | 사용자의 현재 작업 지시 | 위 기준 안에서 수행할 구체 작업 |

이 문서는 읽을 문서를 찾아주는 안내서다. 내용이 충돌하면 다음 순서로 판단한다.

```text
사용자의 현재 명시 지시
→ AGENTS.md
→ 00_project_control.md
→ common_project_specification.md
→ 담당별 공용 계약
→ 개별 산출물 문서
→ 기존의 넓은 기획·참고 문서
```

사용자 지시가 상위 규칙·보안·데이터 통제와 충돌하거나 범위를 크게 확대하면 임의 실행하지 말고 차이와 영향을 보고한다.

## 7. 담당 작업별 추가 문서

| 작업 | 먼저 읽을 문서 | 확인할 핵심 |
|---|---|---|
| 공통 범위·아키텍처 | [공통 명세서](./common_project_specification.md), [디렉터리 구조](./project_directory_structure.md) | Baseline 경계, dependency 방향, FastAPI 미실행 |
| React 화면 | [화면설계서](../05_화면설계서_초안.md), [API·AI 계약](./03_api_ai_integration_contract.md) | Baseline 4화면, loading·empty·error, 합성 version |
| Django API·DB | [API·AI 계약](./03_api_ai_integration_contract.md), [데이터 표준](./02_data_standard_guide.md) | 통합 endpoint 5개, 역할 검사, local persistence |
| 분석 rule·evidence | [데이터 표준](./02_data_standard_guide.md), [API·AI 계약](./03_api_ai_integration_contract.md), [테스트 가이드](./05_test_acceptance_guide.md) | `RULE-001`, evidence ID, 재현성, fallback |
| 데이터·fixture | [데이터 표준](./02_data_standard_guide.md), [요구사항 정의서](../01_요구사항정의서.md) | V1·V2, manifest, seed, PII, schema version |
| AI·LLM·ML | [프로젝트 통제 문서](./00_project_control.md), [API·AI 계약](./03_api_ai_integration_contract.md), [테스트 가이드](./05_test_acceptance_guide.md) | LLM 판단 경계, 근거 연결, ML 승인 여부 |
| QA·인수 | [테스트 가이드](./05_test_acceptance_guide.md), [산출물 추적표](./04_deliverable_traceability_matrix.md) | Baseline test 6개, 실제 evidence, 미구현 결과 금지 |
| 요구사항·일정 | [요구사항 정의서](../01_요구사항정의서.md), [WBS](../02_WBS.md) | ID·수용 기준과 담당·기한을 혼동하지 않음 |
| Git 협업 | [Git branch 가이드](../collaboration/README.md) | 개인 branch, hook, commit·push 승인 |
| 일일·주간보고 | [보고 작성 규칙](../daily_reports/README.md) | 현재 branch 보고, 실제 수행 내용만 기록 |
| 공식 산출물 | [전체 일정](./최종_프로젝트_산출물_및_전체_일정.md), [문서 관리 규칙](../../문서관리규칙.md) | 번호·마감·template·deliverable 경로 |

## 8. 구현 경계

| 경로 | Baseline 책임 | 하지 않는 일 |
|---|---|---|
| `app/react/` | 4개 화면과 UI 상태 | 분석 임계값·권한 최종 판단 |
| `app/django/` | demo 역할 검사, API, local persistence, 메모·결정 | 모델 중복 구현, 원시 SQL 생성 API |
| `app/fastapi/` | 향후 분석 service 경계 | Baseline 초기화·실행, DB migration |
| `src/analysis/` | schema·집계·rule·evidence | HTTP·UI dependency |
| `src/common/` | 최소 enum·schema·식별자 | framework별 계약 중복 |
| `data/samples/` | 작은 비식별 fixture·manifest·schema | 실제 고객 데이터 |
| `tests/`, `evals/` | 실제 작성한 test와 평가 | 실행하지 않은 결과·가상 evidence |

`app/fastapi/` 등 폴더가 존재하는 것은 구현 완료를 뜻하지 않는다. `data/raw/`, `data/processed/`의 생성 파일, `.env`, secret, 실제 고객 데이터는 commit하지 않는다.

## 9. 작업 시작 절차

1. 다음 명령으로 현재 상태를 확인한다.

   ```powershell
   git rev-parse --show-toplevel
   git branch --show-current
   git status --short
   ```

2. 기존 변경을 사용자 작업으로 보고 임의 정리하지 않는다.
3. 필수 문서와 담당별 문서를 읽는다.
4. 목표, in-scope, out-of-scope, 권한, 완료 조건, 검증 명령을 정한다.
5. 기존 구현·schema·test·문서를 검색하고 가장 작은 변경을 적용한다.
6. 사용자 요청이 설명·검토라면 code를 만들지 않는다.
7. dependency 설치, commit, push, 외부 전송은 명시적 승인 후 수행한다.
8. 루트 `AGENTS.md`와 `AI_AGENT_WBS.md`를 일반 작업의 보고·추적 파일로 수정하지 않는다.

## 10. 완료 및 인계 기준

- Baseline 범위를 넘긴 기능이 없는지 확인한다.
- 관련 contract와 실제 구현이 일치하는지 확인한다.
- 정상·empty·error와 필요한 역할 검사를 수행한다.
- 실행하지 않은 test를 통과로 표시하지 않는다.
- 실제 데이터·secret·가상 evidence가 없는지 확인한다.
- `git diff --check`와 변경 범위에 맞는 test를 실행한다.
- 저장소 파일을 변경했으면 WBS와 현재 branch 일일보고·주간보고를 규칙에 맞게 갱신한다.
- 최종 보고에는 변경 파일, 검증 결과, 미실행 검증, 남은 결정 사항을 적는다.

다른 Codex 세션에 작업을 넘길 때 다음 형식을 사용한다.

```text
목표:
현재 branch와 commit:
읽은 기준 문서:
관련 ID:
in-scope:
out-of-scope:
변경 파일:
실행한 검증:
미실행 검증:
남은 결정·위험:
commit·push 상태:
```

## 11. 변경 이력

| version | 날짜 | 변경 |
|---|---|---|
| `1.1` | 2026-07-20 | `AGENTS.md`·`AI_AGENT_WBS.md` 보호와 프로젝트 WBS 원본 경로 명시 |
| `1.0` | 2026-07-20 | 다른 Codex 세션을 위한 문서 읽기 순서, Baseline 범위, 담당별 라우팅과 작업 절차 정의 |
