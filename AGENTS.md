# SKN29-FINAL-3Team AI 작업 지침

## 프로젝트 범위

- 세부 주제는 **호텔 VOC/운영 이슈 분석 Agent**로 고정한다.
- 기술 스택과 frontend/backend 구조는 실제 결정 전까지 임의로 만들지 않는다.
- 호텔 실데이터 확보 전 합성 데이터는 `synthetic`으로 표시하고 seed와 schema version을 기록한다.

## 작업 규칙

1. `git rev-parse --show-toplevel`, `git status --short`, 현재 branch를 먼저 확인한다.
2. 기존 변경은 사용자 작업으로 취급하고 관련 없는 파일을 수정하거나 정리하지 않는다.
3. 코드와 문서 변경은 담당 개인 branch에서 수행하고 PR은 개인 branch에서 `dev`로 연다.
4. 사용자가 명시적으로 요청하기 전에는 stage, commit, push, PR 생성, dependency 설치를 하지 않는다.
5. `.env`, API key, 실제 고객 데이터와 `data/raw`, `data/processed` 생성 파일은 commit하지 않는다.
6. 실제 code가 생길 때만 하위 module을 만들고 RAG 채택 전 `src/embeddings`, `src/retrieval`을 만들지 않는다.
7. 확인한 사실과 가정·제안을 구분하고, 실행하지 않은 검증을 통과했다고 쓰지 않는다.

## 협업 원본

- 사람이 읽는 협업 절차와 commit 규칙은 `docs/collaboration/README.md` 한 곳에서 관리한다.
- root `AGENTS.md`는 Codex 자동 인식을 위해 이 위치에 둔다. 별도 `.agents` 또는 `.claude` 공유 지침은 만들지 않는다.

## 완료 보고

- 변경 파일
- 실행한 검증과 결과
- 실행하지 못한 검증
- 남은 위험 또는 결정 필요 항목
