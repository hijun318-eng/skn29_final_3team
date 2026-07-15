# SKN29-FINAL-3Team AI 협업 지침

## 프로젝트 맥락

- 대주제는 **대화형 데이터 기반 분석 에이전트 및 자동 리포팅 플랫폼**이다.
- 세부 주제는 **호텔 VOC/운영 이슈 분석 Agent**로 고정하며 주제 선정을 다시 열지 않는다.
- 실제 애플리케이션은 별도의 새 저장소에서 시작한다. 이 저장소의 협업환경 파일을 새 저장소에 복사해 사용한다.
- 실제 호텔 데이터가 확보되기 전에는 합성 Raw data를 생성하되 `synthetic`임을 명시하고 생성 기준, seed, schema version을 기록한다.
- 이 지침은 frontend, backend, database, model, deployment stack을 미리 결정하지 않는다.

## 작업 시작 규칙

1. `git rev-parse --show-toplevel`로 실제 Git root를 확인한다.
2. `git status --short`로 기존 변경을 확인하고 사용자 작업으로 취급한다.
3. 현재 branch와 작업 대상 Issue/Task Brief를 확인한다. 실제 프로젝트에서 현재 branch가 담당 개인 branch가 아니면 수정 작업을 시작하지 않는다.
4. 목표, in-scope, out-of-scope, 완료 조건, 검증 방법을 먼저 정한다.
5. 관련 없는 파일을 정리하거나 덮어쓰지 않는다.

## 지침과 문서의 원본

- 개인 공통 응답 기준의 원본은 `docs/engineering/CODEX_GLOBAL_AGENTS.md`이다.
- 프로젝트 지침의 원본은 root `AGENTS.md`이다.
- Codex Skill의 원본은 `.agents/skills/`이며 `.claude/skills/`에는 다른 AI 도구용 연결 지침을 둔다.
- `.agents/`, `.claude/`, `.github/`, `docs/engineering/`, `evals/`는 팀 공유 자산이므로 Git으로 버전 관리한다.
- 같은 규칙을 여러 문서에 복사하지 않고 원본 문서에 링크한다.

## 프로젝트 기본 구조

- 최소 구조는 `data/`, `docs/`, `notebooks/`, `src/`, `app/`, `tests/`, `evals/`, `submission/`, `scripts/`만 사용한다.
- 구조의 원본 설명은 `docs/engineering/PROJECT_STRUCTURE.md`이다.
- 기술 스택과 실제 module이 정해지기 전에는 추가 top-level directory나 세부 module directory를 미리 만들지 않는다.
- `data/raw/`, `data/processed/`의 생성 data는 commit하지 않는다.
- `data/samples/`, `evals/`, 개발 문서, submission 최종 산출물은 검토 가능한 파일만 버전 관리한다.
- `notebooks/`에는 재현 가능한 EDA·실험 notebook만 두고 commit 전 불필요한 output과 secret을 제거한다.
- `app/`은 demo/service entrypoint 용도이며 framework별 구조는 기술 선택 후 만든다.
- `src/config`, `src/data`, `src/llm`, `src/agent` 등은 실제 code가 생길 때만 추가하고 `src/embeddings`, `src/retrieval`은 RAG 채택 후에만 추가한다.
- 실제 secret이 들어가는 `.env`는 commit하지 않고 `.env.example`에는 안전한 기본값과 변수명만 둔다.
- `requirements.txt`에는 실제로 선택하고 검증한 Python dependency만 추가한다.

## Branch 규칙

- `main`: 시연·배포 가능한 안정본만 유지한다.
- `dev`: 다음 버전을 통합하고 검증하는 branch다.
- 개인 branch는 준희=`junhee`, 민지=`minji`, 승=`seung`, 대성=`daesung`, 재홍=`jaehong`만 사용한다.
- 실제 프로젝트의 코드, test, 데이터 schema, 설정, 개발 문서 변경은 모두 담당자의 개인 branch에서 수행한다.
- Codex는 현재 branch가 `main` 또는 `dev`이면 파일을 수정하지 않고 담당 개인 branch로 전환해야 한다고 먼저 알린다.
- 협업환경 원본 자체의 유지보수와 프로젝트 관리자가 명시적으로 승인한 최초 repository bootstrap만 위 규칙의 예외다.
- 각 개인 branch에서는 한 번에 하나의 Issue만 작업하고 완료 후 `dev`로 PR을 연다.
- 개인 branch의 결과는 PR diff, test, eval report를 검토한 뒤 squash merge로 `dev`에 반영한다. 파일을 수동 복사해 history를 잃지 않는다.
- PR 반영 후 다음 작업을 시작하기 전에 개인 branch에 최신 `origin/dev`를 merge한다.
- `main` 반영은 `dev -> main` PR로만 수행한다. 개인 branch에서 `main`으로 직접 PR을 열지 않는다.
- 직접 push, force push, 임의 history rewrite를 금지하고 GitHub Ruleset과 PR review를 통과한다.
- 상세 절차는 `docs/engineering/GIT_BRANCH_STRATEGY.md`를 따른다.

## Git과 commit

- 사용자가 명시적으로 요청하기 전에는 stage, commit, push, PR 생성, history rewrite를 하지 않는다.
- stage할 경로를 먼저 검토하며 관련 없는 변경을 함께 stage하지 않는다.
- 하나의 commit은 하나의 의도를 표현한다.
- commit message는 staged diff만 근거로 작성하고 최근 subject 최대 5개만 문체 참고용으로 사용한다.
- `docs/engineering/COMMIT_CONVENTION.md`의 `<type>(<scope>): <summary>` 형식과 72자 제한을 따른다.
- 실행하지 않은 검증을 commit body나 PR에 기록하지 않는다.

## AI 제어 규칙

- `확인된 사실`, `결정`, `가정`, `제안`, `추가 확인 필요`를 구분한다.
- 계산, schema, formatting, 정책 검사는 가능한 한 script와 test로 수행한다.
- AI는 해석, 초안, 분류, 요약, 근거 범위 내 설명에 사용한다.
- 존재하지 않는 파일, 명령, 데이터, 출처, 테스트 결과, 비즈니스 사실을 만들지 않는다.
- 가장 작은 일관된 변경을 적용하고 위험에 비례해 검증한다.
- 외부 서비스 변경, 비용 발생, dependency 설치, 저장소 밖 쓰기, 데이터 전송은 사전 승인을 받는다.
- subagent는 사용자가 요청하거나 문서화된 독립 병렬 workflow가 있을 때만 사용한다.

## Markdown 작업 방식

- 자연어 문서는 한국어로 작성하고 code, command, path, schema, library, API, error string은 원문을 유지한다.
- 여러 파일이나 contract를 변경하면 `docs/engineering/templates/TASK_BRIEF.md`를 사용한다.
- 지속되는 결정은 `DECISION_RECORD.md`, 실행 근거는 `WORK_LOG.md` 형식으로 기록한다.
- 동작이나 규칙을 바꾸면 같은 변경에서 관련 문서도 갱신한다.

## 기능별 품질 평가

- 기능별 고정 test set은 `evals/testsets/`, 기준 결과는 `evals/baselines/`, 비교 보고서는 `evals/reports/`에 버전 관리한다.
- 일회성 대용량 run artifact는 `evals/runs/`에 두고 commit하지 않는다.
- 기능 또는 model/prompt/data version이 바뀌면 동일 test set으로 재평가하고 기존 baseline과 비교한다.
- 지표, threshold, test set 변경은 성능 향상과 구분해 기록한다.
- 합성 데이터 기반 결과를 실제 호텔 운영 성과로 표현하지 않는다.

## 완료 보고

- 결과 요약
- 변경 파일
- 실행한 검증과 결과
- 실행하지 못한 검증
- 남은 위험과 결정 필요 항목
