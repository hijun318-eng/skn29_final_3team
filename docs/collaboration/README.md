# 팀원 Git branch 사용 가이드

각 팀원은 본인 개인 branch에서만 작업하고, 완료한 변경을 PR로 `dev`에 요청한다. PR(Pull Request)은 한 branch의 변경을 다른 branch에 합치기 전에 GitHub에서 검토를 요청하는 기능이다.

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

- `pre-commit`: secret, 실제·생성 데이터, 10MB 초과 파일을 검사한다.
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

본인 branch에 최신 `dev`를 반영한 뒤 작업한다.

```powershell
git switch <본인 branch>
git status --short
git fetch origin
git pull --ff-only origin <본인 branch>
git merge origin/dev
```

merge conflict가 발생하면 파일을 임의로 삭제하지 말고 충돌 내용을 확인한 뒤 해결한다.

## 변경 확인과 commit

```powershell
git status --short
git add <변경한 파일>
git diff --cached
```

Codex에 다음처럼 요청할 수 있다.

```text
현재 staged diff를 확인해서 한국어 commit message 초안을 작성해줘.
```

Codex가 Skill을 표시하는 환경에서는 `$draft-commit-message`를 직접 선택해도 된다. Skill이 보이지 않으면 repository root에서 Codex를 다시 시작한다.

제안된 메시지가 실제 변경과 일치하는지 확인한 뒤 commit한다.

```powershell
git commit -m "<확인한 commit message>"
git push origin <본인 branch>
```

commit 형식은 `<type>(<scope>): <한국어 summary>`이며 subject는 72자 이하로 작성한다. 하나의 commit에는 하나의 주된 의도만 담는다.

## GitHub에서 PR 만들기

1. GitHub repository에서 `Pull requests`를 연다.
2. `New pull request`를 선택한다.
3. `base`는 `dev`, `compare`는 본인 개인 branch로 선택한다.
4. 변경 목적, 주요 변경, 실행한 검증, 남은 위험을 작성한다.
5. 팀원 검토 후 `dev`에 merge한다.

최종 반영은 프로젝트 관리자가 `dev -> main` PR로 진행한다. 개인 branch에서 `main`으로 직접 PR을 만들지 않는다.

## PR merge 후 개인 branch 갱신

```powershell
git fetch origin
git switch <본인 branch>
git merge origin/dev
git push origin <본인 branch>
```

## 금지 사항

- `main`과 `dev`에서 직접 작업하거나 push하지 않는다.
- 다른 팀원의 개인 branch에서 작업하지 않는다.
- force push, 임의 rebase, history rewrite를 하지 않는다.
- `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일을 commit하지 않는다.
- 미완료 변경이 있는 상태에서 무리하게 pull하거나 branch를 전환하지 않는다.
