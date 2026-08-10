# SKN29-FINAL-3Team AI 작업 지침

## 프로젝트 계약

- 프로젝트는 **DataHub Core 기반 대화형 데이터 분석·자동 리포팅 서비스 Answervice**로 구현한다.
- 기능 범위·아키텍처의 기준은 `docs/Answervice_기획서.md`, 실행 일정·담당·상태의 기준은 `docs/markdown/02_WBS.md`다. `docs/markdown/05_화면설계서.md`는 검토 중 참고자료이며, R1·R5가 작업 카드에서 승인한 화면 ID만 구현하고 route·API·권한·design token을 추정하지 않는다.
- 각 역할은 `docs/markdown/ai_docs/5인_병렬구현_*_매뉴얼_최종안.md` 중 본인 역할 매뉴얼을 읽고, R1이 통합 Wave별로 승인한 `EXECUTION_BUNDLE_ID`의 `TASK_CARD_RANGE`를 수행한다. 승인 범위 안에서는 카드 번호 순서대로 재승인 없이 자율 진행하며, 목표 통합 Gate·범위 밖 변경·계약 충돌 시 멈추고 R1에게 반환한다. 매뉴얼과 통합 일정은 AI 실행 참고서이며 기획서나 공식 WBS를 덮어쓰지 않는다.
- 역할별 Gate 실행 묶음의 번호·범위·상태·발행 값은 `docs/markdown/collaboration/Gate_실행_카드_원장.md`에서 관리한다. `PLANNED`는 실행 승인이 아니며 R1이 기준 SHA와 버전을 채워 `READY`로 바꾼 묶음만 시작한다.
- DataHub는 메타데이터 기준 시스템, Trino는 읽기 전용 연합 조회 엔진, FastAPI Controller는 고정 상태 전이와 G1·G2·G3를 통제하는 Control Plane으로 둔다.
- backend 기준은 FastAPI다. Django나 자유 ReAct loop를 별도 승인 없이 추가하지 않는다.
- 실제 고객 데이터 대신 합성 데이터만 사용하고 `synthetic`, deterministic seed, schema·seed·scenario version을 기록한다.
- P0/P1 구현을 우선하며 P2 MCP·문서 RAG·ML-as-a-Tool·외부 Report 배포와 선택 고객 360은 R1의 별도 편입 결정 전까지 구현 범위에서 제외한다.

## 5인 역할과 단일 작성자

| 역할 | 담당자 | 개인 branch | 책임 영역 | 직접 수정하지 않는 영역 |
|---|---|---|---|---|
| R1 기술 PM·통합 플랫폼·품질·릴리스 | 박준희 | `junhee` | 공통 계약·결정 원장, root Compose·`.env.example`·CI, 통합 test, 보안·복구·release | R2~R5 서비스 내부 구현 |
| R2 데이터 플랫폼·메타데이터·연합조회 | 정승 | `seung` | 5 source·4 engine, 합성 DDL·seed, DataHub, Trino, 데이터 adapter·gold fixture | 공통 FastAPI, AI model·prompt, frontend·Report |
| R3 AI·모델·프롬프트·ModelOps | 윤대성 | `daesung` | Node 1·2·2′·3, prompt registry, 평가 runner, model serving·조건부 LoRA | DB 원천, G1·G2·G3, 공통 FastAPI, frontend |
| R4 백엔드 Control Plane | 김재홍 | `jaehong` | FastAPI·OpenAPI, Controller, Context, G1·G2·G3, cache·artifact·audit, worker·migration | 데이터 원천, AI model·prompt, frontend, root Compose |
| R5 프론트엔드·자동 리포팅 | 송민지 | `minji` | 활성 frontend, Chat·Evidence·Chart·Report·Catalog·Audit UI, Report domain/router/migration proposal | root Compose, 공통 FastAPI entrypoint·Alembic chain, DB·AI 파일 |

- 한 AI에는 한 번에 하나의 통합 Wave 실행 묶음만 준다. 실행 묶음에는 `EXECUTION_BUNDLE_ID`, `TARGET_INTEGRATION_GATE`, `CHECKPOINT_GATES`, `TASK_CARD_RANGE`, `BASE_SHA`, `ALLOWED_PATHS`, `ACCEPTANCE_CRITERIA`, `TEST_COMMANDS`, `STOP_CONDITIONS`를 기록한다.
- 담당자는 승인된 `TASK_CARD_RANGE`를 번호 순서대로 수행하며 카드 사이에 별도 승인을 기다리지 않는다. 현재 카드의 완료 조건과 검증을 충족하지 못하면 다음 카드로 넘어가지 않는다.
- 실행 묶음의 `ALLOWED_PATHS`만 수정한다. 다른 역할 소유 파일 변경은 재현 절차·기대 계약·필요 변경을 적은 change request로 소유자에게 넘긴다.
- R1은 root Compose·공통 env·CI·통합 harness의 단일 작성자이며, 각 서비스의 내부 Dockerfile은 해당 서비스 소유자가 작성한다.
- R4는 공통 FastAPI/OpenAPI/Alembic chain의 단일 작성자다. R5의 Report router·migration은 독립 proposal로 받고 contract test 후 R4가 공통 chain에 등록한다.
- R5는 `app/react`와 `app/enterprise-react`를 동시에 개발하지 않는다. I0에서 활성 frontend 하나를 결정하고 다른 후보는 보존·제거 결정을 기록한다.
- PM·통합 책임은 다른 역할의 구현을 대신하는 권한이 아니다. 통합 결함은 원 소유자에게 반환한다.

## 병렬 개발과 통합 Gate

- R1은 각 통합 Wave 시작 전에 역할별 실행 묶음을 승인한다. 아직 동결되지 않은 계약 버전은 공란으로 두지 않고 `DRAFT` 또는 `N/A — 사유`로 기록하며, checkpoint에서 갱신하고 목표 통합 Gate에서 승인 버전으로 교체한다.
- 각 역할은 자기 소유 경로와 승인된 카드 범위 안에서 독립 구현한다. fake adapter와 versioned fixture를 사용해 다른 역할의 미완료 구현을 기다리지 않는다.
- `CHECKPOINT_GATES`는 계약·증거만 확인하는 지점이며 그 자체만으로 개인 branch의 전체 구현을 병합하지 않는다. 현재 일정에서는 I0를 Wave 1의 checkpoint로 사용한다.
- 역할별 중단 조건은 `TARGET_INTEGRATION_GATE` 도달, `TASK_CARD_RANGE` 완료, `ALLOWED_PATHS` 밖 변경 필요, 계약·보안 충돌, 필수 검증 실패다. 중단 시 변경·검증·handoff를 보고하고 통합 판정을 기다린다.
- `BLOCKED`는 기존 카드의 무단 재개가 아니라 R1의 owner-scoped `REWORK` 묶음으로 해제한다. 차단 해소에 둘 이상의 역할이 필요하면 파일 소유권을 섞은 공동 카드 대신 같은 checkpoint를 공유하는 역할별 묶음을 병렬 발행하고 생산자 contract를 소비자보다 먼저 통합한다.
- 카드 발행 뒤 `dev`가 앞서가도 `BASE_SHA`부터 최신 `dev`까지의 변경과 역할 변경 경로가 겹치지 않으면 기존 token으로 계속할 수 있다. 경로가 겹치거나 기준 이력이 갈라진 경우에만 최신 SHA로 묶음을 재발행한다.
- I0 전에 역할·branch·P0/P1/P2·backend·frontend·파일 소유권을 확정하고 `I0_DECISION_VERSION`을 기록한다.
- I1에서 metric·time·schema·API·model·Report·health 계약과 versioned fixture를 동결한다. 실제 연동 전에는 fake adapter와 fixture로 병렬 개발한다.
- Gate는 `I0 기준 정렬 → I1 Contract Freeze → I2 Deterministic Slice → I3 General LLM → I4 Reporting → I5 Release` 순서로 통과한다.
- 작업 상태는 `READY`, `IN_PROGRESS`, `REVIEW`, `BLOCKED`, `MERGED_DEV`, `VERIFIED_GATE`를 구분한다. fixture 통과나 `dev` 병합만으로 통합 Gate 통과라고 쓰지 않는다.
- 통합은 `Wave 1 I1 기반 계약 → Wave 2 I2 deterministic slice → Wave 3 I3 핵심 기능 → Wave 4 I4~I5 Reporting·Release` 네 번을 기본으로 한다. 달력상 checkpoint 도달이나 부분 구현만으로 병합하지 않는다. 의존성이 있는 변경은 생산자→소비자→R1 follow-up 순서로, 의존성이 없는 역할 묶음은 병렬 검증·독립 통합한다.
- R1이 목표 통합 Gate 결과와 다음 Wave 실행 묶음을 승인하기 전에는 다음 Wave의 카드 범위로 넘어가지 않는다.
- 개인 branch에서는 역할 대상 test와 선언된 소비자 contract test를 실행하고, `dev`에서는 전체 test를 실행한다. Release Gate에서는 전체 test와 승인된 E2E를 다시 실행한다. 실행하지 않은 검증은 `Not Run`, 외부 환경 부족은 `Blocked`로 기록한다.
- 2026-08-28 기능 동결, 2026-09-02 code·data·model·prompt·policy 동결, 2026-09-03 최종 발표를 기준으로 한다.

## 응답과 작업 원칙

- 자연어와 Skill 본문은 한국어로 작성하고 code, command, path, API, library, error string은 원문을 유지한다.
- 확인된 사실·결정·가정·제안을 구분하고, 불확실한 내용은 한계와 검증 방법을 함께 제시한다.
- 사용자의 범위와 권한을 임의로 넓히지 않는다. 위험한 모호성만 질문하고 대안이 있으면 같은 기준으로 비교해 권장안을 제시한다.
- 시작할 때 repository root를 확인해 working directory로 삼고, current branch와 `git status --short`를 확인해 기존 변경을 사용자 작업으로 보존한다.
- 현재 파일·실제 동작·관련 contract를 확인한 뒤 가장 작은 일관된 변경을 적용하고, 위험에 맞는 결정론적 검증을 실행한다.
- 외부 시스템 변경, 비용 발생, 데이터 전송, 저장소 밖 쓰기는 사용자 승인을 받은 뒤 수행한다.

## AI 구현 도구와 코드 품질

- 팀 공통 환경 설정은 `docs/markdown/collaboration/AI_개발_환경_설정.md`를 따른다.
- Codex로 code 작성·수정·refactoring·bug fix·dependency 선택·code review를 수행할 때 Ponytail plugin `v4.8.4`의 `full` mode를 사용하며, 구현 선택·과설계 방지·필수 안전 경계의 단일 기준으로 삼는다.
- 팀원은 Ponytail을 임의로 `off`, `normal`, `lite`, `ultra`로 바꾸지 않는다. plugin 충돌로 일시 해제가 필요하면 작업을 중단하고 R1에게 사유와 재현 절차를 전달한다.
- MCP server는 현재 도입하지 않으며, 추후 필요성과 권한을 검토해 R1 결정으로 확장한다. MCP 부재를 현재 작업 또는 검증 실패 사유로 삼지 않는다.
- 작업 카드의 `TEST_COMMANDS`에 formatter·lint·type check·관련 test·build 중 적용 가능한 명령을 적고 실행한다. 해당 도구가 아직 없으면 임의로 새 dependency를 추가하지 말고 `Not Run` 또는 `Blocked`와 이유를 기록한다.
- 완료 전 변경 기능을 직접 확인하고 Ponytail 관점의 과설계 검토와 정확성·보안·회귀 검토를 구분해 수행한다. 검증하지 않은 항목을 `Pass`로 기록하지 않는다.

## 권한과 Git

- branch·commit message 형식·PR·CI 정책의 단일 기준은 `docs/markdown/collaboration/README.md`다.
- 명시적 요청 전에는 stage, commit, push, dependency 설치를 하지 않는다.
- 개인 branch의 `dev` 병합과 commit message 초안은 각 Skill의 `description`에 따라 라우팅하며, 초안 요청은 stage·commit·push 승인으로 해석하지 않는다.
- commit message에는 staged diff와 확인된 검증만 기록하고, 미실행 검증의 성공이나 diff에서 확인되지 않은 의도·효과를 쓰지 않는다.
- 제목은 구현 수단보다 사용자가 체감하는 결과를 먼저 적고, `수정`, `개선`, `반영`처럼 대상이 불명확한 표현만 단독으로 쓰지 않는다. 예: `Report 오류 수정`보다 `Report 재생성 시 중복 Artifact가 생기지 않도록 수정`처럼 대상·상황·결과가 드러나게 쓴다.
- PowerShell에서 다중행 commit message를 만들 때 작은따옴표 안의 `` `n `` 같은 escape 문자열을 사용하지 않는다. 본문은 실제 개행이 있는 UTF-8 message file과 `git commit -F <file>`을 사용해 `변경:`·목록·`검증:`·목록 구조를 보존한다. push 전 `git log -1 --format=%B`로 실제 개행과 각 헤더가 한 번만 있는지 확인한다.

## 데이터와 구조

- `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일은 commit하지 않는다.
- `src`에는 핵심 로직을, `app`에는 사용자 노출 서비스의 실행 진입점만 둔다.
- Template·cache·생성 SQL 모두 G1·G2를 우회하지 않고 실행 결과는 G3 통과 후에만 설명·Artifact 성공으로 저장한다.
- Node는 권한·SQL 실행 허용·Gate 통과·결과 정답을 판정하지 않는다. frontend는 수치·권한·Gate를 재계산하지 않고 API 결과를 표시한다.
- 실제 code가 생길 때만 하위 module을 만들고 P2 편입 전 `src/embeddings`, `src/retrieval`을 만들지 않는다.

## 문서와 스킬

- 문서 위치·번호·파일명·헤더·템플릿 매핑의 단일 기준은 `docs/문서관리규칙.md`다.
- `.agents/skills/**/scripts`를 실행할 때 Python 3.10+ launcher인 `python` 또는 `python3`를 사용한다.
- Skill `description`에는 실제 한글·영어 호출 표현만 넣고 본문 절차를 반복하지 않으며, `name`은 원문을 유지한다.
- 작업 완료 전 WBS·보고 갱신 여부를 `update-project-wbs`와 `update-project-reports`의 `description`으로 판정한다.
- `docs/markdown/ai_docs/`는 AI 작성·외부 조사·과거 스냅샷을 모은 참고 폴더이며 공식 산출물이나 현재 구현 사실로 간주하지 않는다.
- `docs/templates/`는 읽기 전용이다. 생성·수정·삭제·이동·이름 변경·덮어쓰기를 하지 않는다.
- 정책 데이터는 전용 문서, 조건부 절차는 `.agents/skills`, 항상 적용할 원칙과 권한 경계는 이 파일에서 관리한다.

## 완료 보고

- 결과 요약
- 변경 파일
- 실행한 검증과 결과
- 실행하지 못한 검증
- 갱신한 WBS ID 또는 `WBS 갱신 제외(영향 없음/보고 전용/읽기 전용)`
- 남은 위험 또는 결정 필요 항목
