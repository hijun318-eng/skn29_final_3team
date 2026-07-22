# SKN29-FINAL-3Team AI 작업 지침

## 프로젝트 범위

- 세부 주제는 **호텔 VOC/운영 이슈 분석 Agent**로 고정한다.
- 기술 스택과 frontend/backend 구조는 실제 결정 전까지 임의로 만들지 않는다.
- 호텔 실데이터 확보 전 합성 데이터는 `synthetic`으로 표시하고 seed와 schema version을 기록한다.

## 응답과 판단 원칙

- 판단이 필요한 작업은 `결론과 현재 상태 -> 확인된 사실 -> 제약과 위험 -> 대안과 trade-off -> 결정 -> 검증 방법 -> 다음 행동` 순서로 정리한다.
- 자연어 설명은 한국어로 작성하고 code, command, path, API, library, error string은 원문을 유지한다.
- 사용자가 요청한 범위를 임의로 넓히지 않고, 범위 변경이 필요하면 추가되는 작업을 먼저 알린다.
- `확인된 사실`, `결정`, `가정`, `제안`, `추가 확인 필요`를 구분하고, 불확실하면 확인 방법과 한계를 함께 제시한다.
- 여러 대안이 있으면 같은 기준으로 장점, 단점, 위험, 검증 방법을 비교하고 권장안을 하나 제시한다.
- 단순한 질문에는 단순하게 답하고, 결과를 크게 바꾸는 위험한 모호성만 질문한다.
- 제목과 목록은 이해에 필요한 만큼만 사용하며, 최종 답변은 앞선 진행 메시지 없이도 이해되도록 작성한다.

## 작업 규칙

1. `git rev-parse --show-toplevel`, `git status --short`, 현재 branch를 먼저 확인한다.
2. 기존 변경은 사용자 작업으로 취급하고 관련 없는 파일을 수정하거나 정리하지 않는다.
3. 작업 전에 목표, in-scope, out-of-scope, 권한, 완료 조건, 검증 방법을 확인한다.

## Git 협업 규칙

- branch와 commit 정책은 `docs/markdown/collaboration/README.md`를 따른다.
- 사용자가 명시적으로 요청하기 전에는 stage, commit, push, dependency 설치를 하지 않는다.
- 개인 branch의 `dev` 병합을 명시적으로 요청하면 `.agents/skills/merge-branch-to-dev/SKILL.md`를 적용한다. 이 요청의 권한은 해당 Skill에 명시된 Git 통합과 보고 전용 변경으로만 제한한다.
- commit message 작성 요청에는 `.agents/skills/draft-commit-message/SKILL.md`를 적용한다.
- commit message 초안 요청은 stage, commit, push 승인으로 간주하지 않는다.

## 데이터와 프로젝트 구조

- `.env`, API key, 실제 고객 데이터와 `data/raw`, `data/processed` 생성 파일은 commit하지 않는다.
- `src`에는 핵심 로직(데이터 처리, agent, 공용 module)을 두고, `app`에는 사용자에게 노출되는 서비스 실행 code(web app, API 진입점)만 둔다.
- 실제 code가 생길 때만 하위 module을 만들고 RAG 채택 전 `src/embeddings`, `src/retrieval`을 만들지 않는다.

## 작업 품질 기준

- 문서나 결과를 만들기 전에 현재 파일, 실제 동작, 관련 contract를 먼저 확인한다.
- 파일을 만들거나 유지할 때 실제 목적에 필요한지 확인하고, 가장 작은 일관된 변경을 적용한다.
- 계산, 집계, formatting, 정책 검사는 가능한 한 결정론적 script와 test로 확인한다.
- 변경 위험에 맞는 검증을 실행하고, 실행하지 않은 검증은 통과했다고 쓰지 않는다.
- 외부 시스템 변경, 비용 발생, 데이터 전송, 저장소 밖 쓰기는 사용자 승인을 받은 뒤 수행한다.

## 지침 관리

- 이 파일은 AI 작업·응답 품질 규칙의 원본으로 사용하고, 사람이 참고하는 Git 절차는 `docs/markdown/collaboration/README.md`에서 관리한다.
- root `AGENTS.md`는 항상 적용할 원칙과 권한 경계를 관리하고, 정책 데이터는 전용 문서, 조건부 실행 절차는 `.agents/skills`에서 관리한다.

## 문서 저장 규칙

- 문서 위치·번호·파일명·헤더·템플릿 매핑의 단일 기준은 `docs/문서관리규칙.md`다. 문서를 생성·편집·이동·검토할 때 `.agents/skills/manage-project-documents/SKILL.md`를 적용한다.
- Markdown 작업본은 `docs/markdown/`, 공식 제출물은 `docs/deliverables/`, 제공받은 원본 양식은 `docs/templates/`에서 관리한다.
- `docs/markdown/final_project/`와 `docs/templates/`는 읽기 전용 기준 자료 폴더다. 이 두 폴더의 파일은 생성·수정·삭제·이동·이름 변경·덮어쓰기를 하지 않는다.
- 보호 자료의 보완은 원본 밖의 편집 가능한 작업 문서나 제출물에 반영하며, `작성·수정`에 실제 편집자가 아닌 이름을 만들거나 추정하지 않는다.

## 완료 보고

- 결과 요약
- 변경 파일
- 실행한 검증과 결과
- 실행하지 못한 검증
- 남은 위험 또는 결정 필요 항목

## WBS 갱신

- 저장소 파일을 변경한 작업을 마칠 때 일정 관리의 단일 기준인 `docs/markdown/02_WBS.md`의 관련 실행 WBS 행과 작업 로그를 갱신한다.
- WBS 편집에도 `.agents/skills/manage-project-documents/SKILL.md`의 번호 문서·템플릿·헤더 검증을 적용한다.
- 기존 작업이 없으면 `02_WBS.md`의 실행 단계와 ID 체계에 따라 새 행을 추가하고 전체 태스크 수·단계별 요약을 함께 수정한다.
- 일정·상태가 바뀌면 실행 WBS, 8주 핵심 개발 일정, Mermaid Gantt와 산출물 제출 일정의 관련 항목을 동기화한다.
- 단순 조사·설명처럼 저장소 파일을 변경하지 않은 작업은 갱신하지 않는다.
- 개인 일일보고·날짜별 팀 요약·주간보고만 보완한 보고 전용 변경은 순환 기록을 막기 위해 WBS 갱신 대상에서 제외한다.
- 완료 보고에 갱신한 WBS 작업 ID를 포함하고, 위 보고 전용 변경이면 `WBS 갱신 제외(보고 전용)`로 표기한다.

## 일일보고 갱신

- 저장소 파일을 변경한 작업을 마치면 개인 branch에서 `.agents/skills/update-project-reports/SKILL.md`를 적용한다.
- `dev`에서는 작성자를 추정하지 않으며, 조사·설명 또는 보고 전용 변경은 다시 기록하지 않는다. 보고 정책과 형식의 단일 기준은 `docs/markdown/daily_reports/README.md`다.

## 주간보고 작성

- 날짜·기간이 지정된 요청이나 개인 branch의 `dev` 병합 후에는 `.agents/skills/update-project-reports/SKILL.md`를 적용한다.
