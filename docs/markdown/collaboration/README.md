# 팀원 Git branch 사용 가이드

| 항목 | 내용 |
|---|---|
| 문서 설명 | 팀원 개인 branch와 dev·main 통합 정책 및 사람이 수행하는 Git 절차 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.3 |
| 문서 기준일 | 2026-07-22 16:16 |
| 작성·수정 | 박준희 |

각 팀원은 본인 개인 branch에서만 작업하고 완료한 변경을 개인 branch에 push한 뒤 관리자에게 알린다. 관리자는 확인한 개인 branch만 `dev`에 merge하고, 최종 검증 후 `dev`를 `main`에 merge한다.

## Branch 역할

| 용도 | Branch |
|---|---|
| 최종 안정본 | `main` |
| 팀 통합본 | `dev` |
| 준희 | `junhee` |
| 민지 | `minji` |
| 승 | `seung` |
| 대성 | `daesung` |
| 재홍 | `jaehong` |

## 처음 clone하는 팀원

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git fetch origin
git switch <본인 branch>
git status
```

예를 들어 대성은 `git switch daesung`을 실행한다.

## Git Hook 활성화

clone한 뒤 또는 `.githooks`를 처음 받은 뒤 repository root에서 최초 한 번 실행한다. 이 설정은 branch가 아니라 해당 local repository 전체에 적용된다.

```powershell
git config --local core.hooksPath .githooks
git config --local --get core.hooksPath
```

출력이 `.githooks`이면 활성화된 상태다.

- `pre-commit`: secret, 실제·생성 데이터, 10MB 초과 파일과 staged Markdown의 문서관리규칙 준수 여부를 검사한다.
- `commit-msg`: `<type>(<scope>): <한국어 summary>` 형식과 72자 제한을 검사한다.
- 검사가 실패하면 표시된 항목을 수정한 뒤 다시 commit한다. `--no-verify`로 우회하지 않는다.

## 이미 clone한 팀원

먼저 미완료 변경이 없는지 확인한다.

```powershell
git status --short
```

출력이 없다면 본인 branch를 최신 상태로 갱신한다.

```powershell
git fetch origin
git switch <본인 branch>
git pull --ff-only origin <본인 branch>
```

미완료 변경이 표시되면 pull이나 branch 전환 전에 본인 작업을 확인한다. 다른 사람의 변경을 지우거나 `reset --hard`로 정리하지 않는다.

## 새 작업 시작

현재 branch가 본인 개인 branch이고 미완료 변경이 없을 때 최신 `dev`를 반영한다.

```powershell
git branch --show-current
git status --short
git pull --no-rebase origin dev
git push origin <본인 branch>
```

첫 번째 출력이 본인 branch가 아니거나 `git status --short`에 내용이 표시되면 pull하지 않는다. merge conflict가 발생하면 push하지 말고 관리자에게 알린다.

## 변경 확인과 commit

```powershell
git status --short
git add <변경한 파일>
git diff --cached
```

AI 에이전트에 다음처럼 요청할 수 있다.

```text
현재 staged diff를 확인해서 한국어 commit message 초안을 작성해줘.
```

AI 에이전트가 Skill을 표시하는 환경에서는 `$draft-commit-message`를 직접 선택해도 된다. Skill이 보이지 않으면 repository root에서 AI 에이전트를 다시 시작한다.

제안된 메시지가 실제 변경과 일치하는지 확인한 뒤 commit한다.

```powershell
git commit -m "<확인한 commit message>"
git push origin <본인 branch>
```

commit 형식은 `<type>(<scope>): <한국어 summary>`이며 subject는 72자 이하로 작성한다. 하나의 commit에는 하나의 주된 의도만 담는다.

## dev 병합 요청 시 보고 통합

AI 에이전트가 개인 branch의 `dev` 병합을 수행할 때는 `.agents/skills/merge-branch-to-dev/SKILL.md`를 적용한다. Skill은 이 문서의 Git 정책과 `docs/markdown/daily_reports/README.md`의 보고 정책을 읽고 source push, local/remote 일치, 최신 `dev`, merge, 보고 통합·검증, 최종 push를 순서대로 수행한다.

`dev` 병합 요청은 위 통합에 필요한 개인 branch push, `dev` fetch·pull·merge·push와 `team_summaries/` 파일의 stage·commit을 승인한 것으로 본다. 기존 미커밋 변경과 다른 파일은 포함하지 않으며, 작업 트리가 깨끗하지 않거나 로컬·원격 commit이 일치하지 않거나 병합·보고 검증이 실패하면 stash·reset·임의 commit 없이 중단하고 사용자에게 알린다.

## 관리자 통합

팀원은 개인 branch push가 끝나면 관리자에게 branch 이름과 변경 내용을 알린다. 관리자는 다음 순서로 검증된 개인 branch를 `dev`에 반영하며, 병합 후 보고 통합·검증을 마친 뒤 마지막에 push한다.

```powershell
git switch dev
git status --short
git fetch origin
git pull --ff-only origin dev
git rev-parse dev
git rev-parse origin/dev
git merge origin/<팀원 branch>
```

두 `git rev-parse` 출력은 병합 전에 같아야 하며 첫 번째 값을 병합 직전 commit으로 기록한다. 이후 작업은 위 `dev 병합 요청 시 보고 통합` 절차를 그대로 따른다.

최종 검증이 끝나면 관리자가 `dev`를 `main`에 반영한다.

```powershell
git switch main
git status --short
git pull --ff-only origin main
git merge dev
git push origin main
```

## 금지 사항

- `main`과 `dev`에서 기능·기획 작업을 직접 하지 않는다. 관리자의 branch 병합과 병합 직후 규칙에 따른 `team_summaries/` 보고 통합 commit·push만 허용한다.
- `dev`에서 개인 일일보고를 수정하지 않는다.
- 다른 팀원의 개인 branch에서 작업하지 않는다.
- force push, 임의 rebase, history rewrite를 하지 않는다.
- `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일을 commit하지 않는다.
- 미완료 변경이 있는 상태에서 무리하게 pull하거나 branch를 전환하지 않는다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.3 | 2026-07-22 16:16 | pre-commit의 staged Markdown 문서관리규칙 자동 검증 추가 |
| v1.2 | 2026-07-22 09:19 | AI 에이전트 범용 표현 반영과 문서 버전·변경 이력 동기화 |
| v1.1 | 2026-07-21 17:32 | AI 에이전트의 개인 branch→dev 반복 절차를 `merge-branch-to-dev` Skill로 분리 |
