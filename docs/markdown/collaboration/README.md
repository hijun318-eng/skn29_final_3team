# 팀원 Git branch 사용 가이드

| 항목 | 내용 |
|---|---|
| 문서 설명 | 팀원 개인 branch와 dev·main 통합 정책 및 사람이 수행하는 Git 절차 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.12 |
| 문서 기준일 | 2026-08-06 10:56 |
| 작성·수정 | 박준희 |

각 팀원은 본인 개인 branch에서만 작업하고 완료한 변경을 개인 branch에 push한 뒤 관리자에게 알린다. 관리자는 확인한 개인 branch만 `dev`에 merge하고, 최종 검증 후 `dev`를 `main`에 merge한다. PR은 필수 절차가 아니며 GitHub Actions는 개인 branch와 `dev` push를 기준으로 실행한다. CI를 실행할 수 없으면 같은 검증을 local에서 수행하고, 필수 검증이 실패한 branch는 병합하지 않는다.

개인 branch CI는 변경 경로에 필요한 검사만 실행한다. Python·문서·frontend·Compose 변경을 구분하고 문서는 실제 변경된 Markdown만 검사하며, workflow 자체가 바뀌면 모든 검사를 실행한다. 같은 branch에 새 push가 생기면 이전 CI는 자동으로 취소한다. 역할 카드에 선언된 소비자 contract test를 포함해 `TEST_COMMANDS`가 CI보다 넓으면 해당 명령을 추가로 실행하며, 개인 branch CI 통과를 전체 저장소 검증으로 표현하지 않는다.

## 에이전트 작업 시작

역할 작업은 파일을 수정하기 전에 본인 branch에서 다음 한 명령으로 시작한다.

```powershell
python .github/scripts/gate_scope.py --branch <본인 branch> --bootstrap
```

이 명령은 현재 branch·dirty worktree·마지막 non-`PLANNED` 실행 카드 상태를 검사하고, 처음부터 끝까지 읽을 문서와 현재 카드 관련 절을 읽을 문서를 구분해 출력한다. worktree의 절대 경로는 달라도 되지만 branch가 카드의 `PERSONAL_BRANCH`와 다르거나 카드가 `READY`·`IN_PROGRESS`가 아니거나 기존 변경이 있으면 구현하지 않는다.

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
- `commit-msg`: `<type>: <한국어 summary>` 또는 `<type>(<scope>): <한국어 summary>` 형식과 72자 제한을 검사한다.
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

Commit message 초안은 `.agents/skills/draft-commit-message/SKILL.md`로 staged diff만 검토해 작성한다. 제안된 메시지가 실제 변경과 일치하는지 확인한 뒤 commit한다.

```powershell
git commit -m "<확인한 제목>" -m "<확인한 상세 본문>"
git push origin <본인 branch>
```

commit 제목은 `<type>: <한국어 summary>` 또는 `<type>(<scope>): <한국어 summary>`이며 72자 이하로 작성한다. `type`은 `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`, `perf`, `style`, `data`, `eval` 중 하나를 사용한다. `summary`에는 한국어를 포함하고 끝에 마침표를 붙이지 않는다. 변경이 한 component에 명확히 모이면 영문 소문자·숫자·`.`·`_`·`/`·`-`로 된 짧은 scope를 사용하고, 저장소 전반·여러 component·자연스러운 scope가 없는 변경은 scope를 생략한다. 하나의 commit에는 하나의 주된 의도만 담는다.

제목 아래 상세 본문을 기본으로 작성한다.

- `변경:`에는 staged diff의 서로 다른 실제 작업을 1~5개 bullet로 묶어 contract·동작·경로 그룹·판정이 어떻게 바뀌었는지 적고, 한 변경을 반복 bullet로 부풀리지 않는다.
- `검증:`에는 실제 실행해 확인한 command 또는 결과만 적고, 확인 근거가 없으면 `미실행`으로 기록한다.
- 호환성·migration·Gate/status·배포·보안·남은 위험이 소비자에게 영향을 줄 때만 `영향:`을 추가한다.
- 제목 반복, 파일명만 나열, 실행하지 않은 검증의 성공 표시는 금지한다.

## dev 병합 요청 시 보고 통합

AI 에이전트가 개인 branch의 `dev` 병합을 수행할 때는 이 문서의 정책과 `docs/markdown/daily_reports/README.md`를 기준으로 `.agents/skills/merge-branch-to-dev/SKILL.md`를 적용한다.

`dev` 병합 요청은 위 통합에 필요한 개인 branch push, `dev` fetch·pull·merge·push, Gate 원장의 source 카드 종료 기록과 `team_summaries/` 파일의 단일 통합 기록 commit, 병합 완료 후 개인 branch의 안전한 fast-forward·push를 승인한 것으로 본다. source SHA의 개인 branch CI가 성공해야 병합할 수 있다. 여러 branch를 한 요청에서 통합하면 카드 종료와 팀 요약·주간보고는 마지막 source 뒤 한 번만 commit한다. 개인 branch 작업 트리가 깨끗하고 기존 원격 개인 branch가 `origin/dev`의 조상일 때만 동기화하며, 조건이 맞지 않으면 개인 branch를 변경하지 않고 이유를 알린다. 기존 미커밋 변경과 다른 파일은 포함하지 않으며, 작업 트리가 깨끗하지 않거나 로컬·원격 commit이 일치하지 않거나 CI·병합·보고 검증이 실패하면 stash·reset·임의 commit 없이 중단한다.

병합 사전검사의 `--session`은 worktree들이 공유하는 Git 공용 디렉터리에 `answervice-merge-session.json`을 두고 최초 dev SHA, source SHA와 CI 결과를 단계 사이에서 재사용한다. 이 파일은 Git 추적 대상이 아니며 secret이나 변경 파일 내용을 저장하지 않는다. 실제 merge·원장 수정·commit·push는 계속 승인된 절차에서만 수행한다.

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

두 `git rev-parse` 출력은 병합 전에 같아야 하며 첫 번째 값을 병합 직전 `base` SHA로 기록한다. 병합 직후 `head` SHA도 기록해 source branch와 함께 보고 통합 절차에 전달한다. 이후 작업은 위 `dev 병합 요청 시 보고 통합` 절차를 그대로 따른다.

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
| v1.12 | 2026-08-06 10:56 | 병합 단계가 공용 JSON session에서 dev·source SHA와 CI 결과를 재사용하도록 사전검사 절차 보완 |
| v1.11 | 2026-08-06 10:09 | 역할 작업 bootstrap, 다중 branch 사전점검과 병합 카드 종료 기록 추가 |
| v1.10 | 2026-08-06 09:30 | source CI 성공을 병합 조건으로 추가하고 실제 변경 문서 검사·여러 branch 보고 일괄 commit 적용 |
| v1.9 | 2026-08-06 09:10 | 변경 경로별 CI 실행·중복 실행 취소와 dev 병합 후 개인 branch 안전 동기화 추가 |
| v1.8 | 2026-08-05 22:30 | 개인 branch 역할 검증과 dev 전체 검증을 분리해 중복 CI 실행 축소 |
| v1.7 | 2026-08-03 12:14 | commit 형식은 Git 정책, staged 검토·병합 실행은 Skill로 단일화하고 중복 예시 제거 |
| v1.6 | 2026-07-30 14:25 | commit 제목 아래 변경·검증·선택적 영향 본문을 기본 작성하고 staged diff와 확인된 검증만 구체적으로 기록하도록 Skill·Git 절차를 동기화 |
| v1.5 | 2026-07-30 10:56 | commit 제목의 선택적 scope 규칙과 staged 변경 범위에 따른 사용 기준을 추가하고 hook·Skill 형식을 동기화 |
| v1.4 | 2026-07-27 17:07 | 개인 branch 병합 전후 SHA 기반 보고 통합 계약과 최종 사전검사 기준 추가 |
| v1.3 | 2026-07-22 16:16 | pre-commit의 staged Markdown 문서관리규칙 자동 검증 추가 |
