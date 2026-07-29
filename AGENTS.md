# SKN29-FINAL-3Team AI 작업 지침

## 프로젝트 계약

- 프로젝트는 **DataHub Core 기반 대화형 데이터 분석·자동 리포팅 서비스 Answervice**로 구현한다.
- 기능 범위·아키텍처의 기준은 `docs/Answervice_기획서.md`, 실행 일정·담당·상태의 기준은 `docs/markdown/02_WBS.md`, 화면 상세 기준은 `docs/markdown/05_화면설계서.md`다.
- `docs/markdown/ai_docs/5인_병렬구현_*_매뉴얼_최종안.md`와 통합 일정은 AI 실행 참고서다. 기획서나 공식 WBS를 임의로 덮어쓰지 않으며 충돌은 R1의 I0 결정 원장으로 해결한다.
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

- 한 AI에는 한 번에 `TASK_CARD_ID` 하나만 주고 카드 번호 순서대로 수행한다.
- 작업 카드의 `ALLOWED_PATHS`만 수정한다. 다른 역할 소유 파일 변경은 재현 절차·기대 계약·필요 변경을 적은 change request로 소유자에게 넘긴다.
- R1은 root Compose·공통 env·CI·통합 harness의 단일 작성자이며, 각 서비스의 내부 Dockerfile은 해당 서비스 소유자가 작성한다.
- R4는 공통 FastAPI/OpenAPI/Alembic chain의 단일 작성자다. R5의 Report router·migration은 독립 proposal로 받고 contract test 후 R4가 공통 chain에 등록한다.
- R5는 `app/react`와 `app/enterprise-react`를 동시에 개발하지 않는다. I0에서 활성 frontend 하나를 결정하고 다른 후보는 보존·제거 결정을 기록한다.
- PM·통합 책임은 다른 역할의 구현을 대신하는 권한이 아니다. 통합 결함은 원 소유자에게 반환한다.

## 병렬 개발과 통합 Gate

- I0 전에 역할·branch·P0/P1/P2·backend·frontend·파일 소유권을 확정하고 `I0_DECISION_VERSION`을 기록한다.
- I1에서 metric·time·schema·API·model·Report·health 계약과 versioned fixture를 동결한다. 실제 연동 전에는 fake adapter와 fixture로 병렬 개발한다.
- Gate는 `I0 기준 정렬 → I1 Contract Freeze → I2 Deterministic Slice → I3 General LLM → I4 Reporting → I5 Release` 순서로 통과한다.
- 작업 상태는 `READY`, `IN_PROGRESS`, `REVIEW`, `BLOCKED`, `MERGED_DEV`, `VERIFIED_GATE`를 구분한다. fixture 통과나 `dev` 병합만으로 통합 Gate 통과라고 쓰지 않는다.
- 개인 branch 병합은 `R1 공통 계약 → R2 데이터 계약 → R3 model 계약 → R4 backend 계약 → R5 frontend 계약 → R1 통합 follow-up` 순서를 기본으로 하며, 단계별 상세 순서는 `docs/markdown/ai_docs/5인_병렬구현_통합일정_20260729-20260903.md`를 따른다.
- 병합마다 생산자 test와 소비자 contract test를 실행한다. 실행하지 않은 검증은 `Not Run`, 외부 환경 부족은 `Blocked`로 기록한다.
- 2026-08-28 기능 동결, 2026-09-02 code·data·model·prompt·policy 동결, 2026-09-03 최종 발표를 기준으로 한다.

## 응답과 작업 원칙

- 자연어는 한국어로 작성하고 code, command, path, API, library, error string은 원문을 유지한다.
- 확인된 사실·결정·가정·제안을 구분하고, 불확실한 내용은 한계와 검증 방법을 함께 제시한다.
- 사용자의 범위와 권한을 임의로 넓히지 않는다. 위험한 모호성만 질문하고 대안이 있으면 같은 기준으로 비교해 권장안을 제시한다.
- 시작할 때 repository root, current branch, `git status --short`를 확인하고 기존 변경을 사용자 작업으로 보존한다.
- 현재 파일·실제 동작·관련 contract를 확인한 뒤 가장 작은 일관된 변경을 적용하고, 위험에 맞는 결정론적 검증을 실행한다.
- 외부 시스템 변경, 비용 발생, 데이터 전송, 저장소 밖 쓰기는 사용자 승인을 받은 뒤 수행한다.

## 권한과 Git

- branch·commit 정책의 단일 기준은 `docs/markdown/collaboration/README.md`다.
- 명시적 요청 전에는 stage, commit, push, dependency 설치를 하지 않는다.
- 개인 branch를 `dev`에 병합하라는 요청에는 `.agents/skills/merge-branch-to-dev/SKILL.md`를 적용한다.
- commit message 요청에는 `.agents/skills/draft-commit-message/SKILL.md`를 적용하며, 초안 요청을 stage·commit·push 승인으로 해석하지 않는다.

## 데이터와 구조

- `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일은 commit하지 않는다.
- `src`에는 핵심 로직을, `app`에는 사용자 노출 서비스의 실행 진입점만 둔다.
- Template·cache·생성 SQL 모두 G1·G2를 우회하지 않고 실행 결과는 G3 통과 후에만 설명·Artifact 성공으로 저장한다.
- Node는 권한·SQL 실행 허용·Gate 통과·결과 정답을 판정하지 않는다. frontend는 수치·권한·Gate를 재계산하지 않고 API 결과를 표시한다.
- 실제 code가 생길 때만 하위 module을 만들고 P2 편입 전 `src/embeddings`, `src/retrieval`을 만들지 않는다.

## 문서와 스킬 라우팅

- 문서 위치·번호·파일명·헤더·템플릿 매핑의 단일 기준은 `docs/문서관리규칙.md`다.
- `docs/`의 문서를 생성·편집·이동·검토할 때 `.agents/skills/manage-project-documents/SKILL.md`를 적용한다.
- `docs/markdown/ai_docs/`는 AI 작성·외부 조사·과거 스냅샷을 모은 참고 폴더이며 공식 산출물이나 현재 구현 사실로 간주하지 않는다.
- `docs/templates/`는 읽기 전용이다. 생성·수정·삭제·이동·이름 변경·덮어쓰기를 하지 않는다.
- 실행 WBS 행과 연결된 일정·상태·담당·산출물·근거가 바뀌거나 사용자가 WBS 갱신을 요청하면 `.agents/skills/update-project-wbs/SKILL.md`를 적용한다. 단순 조사·설명, 보고 전용 변경, 실행 일정에 영향 없는 문서·코드·설정 정리는 제외한다.
- 개인 branch에서 파일 변경을 마치거나 날짜·기간이 지정된 보고 요청을 받으면 `.agents/skills/update-project-reports/SKILL.md`를 적용한다. `dev`에서는 작성자를 추정하지 않는다.
- 정책 데이터는 전용 문서, 조건부 절차는 `.agents/skills`, 항상 적용할 원칙과 권한 경계는 이 파일에서 관리한다.

## 완료 보고

- 결과 요약
- 변경 파일
- 실행한 검증과 결과
- 실행하지 못한 검증
- 갱신한 WBS ID 또는 `WBS 갱신 제외(영향 없음/보고 전용/읽기 전용)`
- 남은 위험 또는 결정 필요 항목
