# SKN29-FINAL-3Team AI 작업 지침

## 프로젝트 원칙

- 주제는 **호텔 VOC/운영 이슈 분석 Agent**로 고정한다.
- 기술 스택과 frontend/backend 구조는 실제 결정·구현 전까지 임의로 만들지 않는다.
- 호텔 실데이터 확보 전 합성 데이터는 `synthetic`으로 표시하고 seed와 schema version을 기록한다.

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
- 실제 code가 생길 때만 하위 module을 만들고 RAG 채택 전 `src/embeddings`, `src/retrieval`을 만들지 않는다.

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
