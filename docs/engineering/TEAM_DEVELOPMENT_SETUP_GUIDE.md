# 팀원 개발환경 세팅 가이드

이 문서는 새 호텔 VOC 프로젝트 저장소를 clone한 팀원이 개인 PC에서 Git, Codex, 공통 Skill, commit hook을 동일하게 설정하는 절차다. Windows PowerShell 기준이며 애플리케이션 기술 스택 설치는 별도 문서가 생긴 뒤 진행한다.

## 1. 준비물

- Git
- Python 3: commit hook과 공통 validator 실행에 사용
- Windows PowerShell
- GitHub 계정과 프로젝트 저장소 권한
- Codex: 팀 공통 응답 지침을 사용할 경우
- Claude Code: `.claude/skills/`를 사용할 경우 선택 사항

설치 확인:

```powershell
git --version
python --version
powershell -NoProfile -Command '$PSVersionTable.PSVersion'
```

## 2. 저장소 clone

```powershell
git clone <REPOSITORY_URL>
Set-Location <PROJECT_DIR>
git rev-parse --show-toplevel
git status --short
```

`<REPOSITORY_URL>`과 `<PROJECT_DIR>`은 프로젝트 관리자가 전달한 실제 값으로 바꾼다.

기본 디렉터리의 역할은 `docs/engineering/PROJECT_STRUCTURE.md`에서 확인한다. 기술 스택이 정해지기 전에는 임의로 `frontend`, `backend`, `api`, `web` 구조를 추가하지 않는다.

## 3. 개인 Git 정보 설정

전역 설정을 덮어쓰지 않도록 프로젝트 저장소에만 설정한다.

```powershell
git config --local user.name "<표시 이름>"
git config --local user.email "<GitHub email>"
git config --local --get user.name
git config --local --get user.email
```

GitHub private email을 사용한다면 GitHub 계정에 표시된 `noreply` 주소를 사용한다.

## 4. 로컬 Python·환경변수와 공통 장치 설치

Python 가상환경과 개인 `.env`를 만든다. 실제 secret이 들어간 `.env`는 Git에 올리지 않는다.

```powershell
python -m venv .venv
Copy-Item -LiteralPath .env.example -Destination .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

현재 `requirements.txt`는 기술 스택이 미정이라 package를 임의로 포함하지 않는다. dependency가 확정되면 개인 branch에서 추가하고 설치·test 결과를 PR에 남긴다.

저장소 공통 장치를 설치한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1
```

이 script는 local `.git/config`의 `core.hooksPath`를 `.githooks`로 설정하고 공통 정책 validator를 검사한다. 전역 Git 설정은 변경하지 않는다.

## 5. 개인 Codex 지침 설치

먼저 현재 개인 지침과 팀 원본의 차이를 확인한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-global-codex-agents.ps1 -CheckOnly
```

개인 `%USERPROFILE%\.codex\AGENTS.md`가 없으면 설치한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-global-codex-agents.ps1
```

기존 개인 지침이 있다면 내용을 검토한 뒤에만 `-Force`를 사용한다. 기존 파일은 timestamp가 붙은 backup으로 보존된다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-global-codex-agents.ps1 -Force
```

`%USERPROFILE%\.codex\AGENTS.override.md`가 있으면 `AGENTS.md`보다 우선하므로 팀 지침을 가릴 수 있다. 설치 또는 변경 후에는 새 Codex task/session을 시작한다. Codex는 실행을 시작할 때 global 지침과 repository 지침을 조합한다.

공식 참고:

- [OpenAI - Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenAI - Build skills](https://learn.chatgpt.com/docs/build-skills)

## 6. 전체 환경 확인

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-team-environment.ps1
```

다음 항목이 확인되어야 한다.

- Git/Python 실행 가능
- local `user.name`, `user.email` 설정
- `core.hooksPath=.githooks`
- 개인 Codex `AGENTS.md`와 팀 원본의 SHA256 일치
- `.agents`, `.claude`, `docs/engineering`, `evals`가 ignore되지 않음

## 7. 개인 branch

팀원별 branch는 다음 5개로 고정한다.

| 이름 | Branch |
|---|---|
| 준희 | `junhee` |
| 민지 | `minji` |
| 승 | `seung` |
| 대성 | `daesung` |
| 재홍 | `jaehong` |

한 개인 branch에서는 한 번에 하나의 Issue만 작업한다. 작업을 시작하기 전에 자신의 branch에 최신 `dev`를 반영한다.

코드뿐 아니라 test, data schema, 설정, Markdown 개발 문서도 자신의 개인 branch에서만 수정한다. Codex를 열기 전에 현재 branch를 확인하고 `main` 또는 `dev`라면 수정 요청을 시작하지 않는다.

```powershell
git status --short
git switch <MY_BRANCH>
git fetch origin
git merge origin/dev
```

예를 들어 대성은 `<MY_BRANCH>`를 `daesung`으로 바꾼다. merge conflict가 발생하면 해결하고 관련 test를 실행한 뒤 개인 branch에 push한다.

```powershell
git push origin <MY_BRANCH>
```

업무 유형은 별도 branch명으로 나누지 않는다. GitHub Issue label, PR title, commit type으로 `feat`, `fix`, `data`, `eval`, `docs` 등을 구분한다.

## 8. Codex 작업 시작

Codex는 반드시 실제 repository root에서 새 task를 시작한다. 첫 요청에 다음 정보를 제공한다.

```text
AGENTS.md와 관련 문서를 먼저 읽어줘.
담당 개인 branch: <MY_BRANCH>
현재 branch가 담당 개인 branch가 아니면 파일을 수정하지 말고 먼저 알려줘.
Issue: #<번호>
목표: <완료할 결과>
In scope: <수정 허용 범위>
Out of scope: <수정 금지 범위>
완료 조건: <검증 가능한 기준>
검증: <실행할 test 또는 확인 방법>
commit/push/PR은 요청 전까지 하지 마.
```

여러 파일 또는 contract를 변경하면 `docs/engineering/templates/TASK_BRIEF.md`를 먼저 작성한다.

## 9. Commit과 PR

```powershell
git status --short
git add <의도한 경로>
git diff --cached --stat
git diff --cached
```

Codex에 staged diff 기반 메시지를 요청한다. `$draft-commit-message` Skill은 staged diff와 최근 subject 최대 5개만 읽으며 unstaged 변경을 포함하지 않는다.

```text
$draft-commit-message를 사용해 staged diff 기반 commit message를 작성해줘.
```

메시지를 검토한 뒤 직접 commit하고 push한다.

```powershell
git commit
git push -u origin HEAD
```

GitHub에서 개인 branch의 PR target이 `dev`인지 확인한다. 개인 branch에서 `main`으로 직접 PR을 열지 않는다. PR title도 `<type>(<scope>): <summary>` 형식과 72자 제한을 따른다. PR template의 scope, test, eval, data, documentation 항목을 작성하고 실제로 실행한 검증만 체크한다.

## 10. 기능별 품질 보고

기능 동작이 달라지면 다음을 함께 관리한다.

- `evals/testsets/<feature-id>/`: 고정 입력과 기대값
- `evals/baselines/<feature-id>/`: 승인된 기준 결과
- `evals/reports/<feature-id>/`: version 간 비교 보고서
- `evals/runs/`: 일회성 raw run, Git ignore

자세한 절차는 `docs/engineering/QUALITY_EVALUATION_GUIDE.md`를 따른다.

## 11. 매일 작업 시작과 종료

시작:

```powershell
git status --short
git switch <MY_BRANCH>
git fetch origin
git merge origin/dev
```

종료:

```powershell
git status --short
git log -5 --oneline
git push origin <MY_BRANCH>
```

미완성 작업은 개인 작업 branch에 commit하거나 명시적으로 기록한다. 다른 팀원의 변경을 숨기기 위해 임의로 stash, reset, clean하지 않는다.

## 12. 문제 해결

| 증상 | 확인 |
|---|---|
| commit message가 거부됨 | `docs/engineering/COMMIT_CONVENTION.md`와 72자 제한 확인 |
| 팀원마다 Codex 답변 기준이 다름 | global AGENTS hash, `AGENTS.override.md`, 새 session 여부 확인 |
| `.claude` 또는 `.agents`가 안 보임 | `git check-ignore -v <path>` 실행 |
| 개인 branch PR target이 `main`임 | `dev`로 변경, `main`은 `dev -> main` PR만 허용 |
| 개인 branch 변경이 너무 많음 | 한 번에 하나의 Issue만 남기고 관련 없는 변경을 제거한 뒤 다시 검증 |
| 이전 PR 변경이 다시 보임 | 개인 branch에 최신 `origin/dev`를 merge했는지 확인 |
| test 결과 비교가 불가능함 | test set, metric, threshold version이 동일한지 확인 |
