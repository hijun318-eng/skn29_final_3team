---
name: merge-branch-to-dev
description: >-
  Safely merge a recognized personal branch into dev and integrate reports. Use only for "merge/apply my branch to dev" or "개인 branch를 dev에 병합·반영". Exclude dev updates, dev-to-personal sync, dev-to-main, generic Git help, and commit-message drafting.
---

# 개인 Branch를 dev에 병합

작업 전 `docs/markdown/collaboration/README.md`를 Git 정책의 단일 기준으로 읽고, 보고서 통합에는 `.agents/skills/update-project-reports/SKILL.md`를 적용한다.

## 권한 경계

개인 branch를 `dev`에 병합하라는 명시적 요청은 대상 branch push, `dev` fetch/pull/merge/push, 보고서 절차가 반환한 `team_summaries/` 파일만 담은 보고 전용 commit과 병합 완료 후 source branch의 안전한 fast-forward·push까지 승인한다. 무관한 파일, force push, rebase, reset, stash 또는 history rewriting은 승인하지 않는다.

## 절차

1. 단일 Git 정책에 매핑된 개인 branch 중 정확히 하나를 source로 정하고 source worktree root를 기록한다. 사용자가 이름을 지정하지 않았다면 현재 branch가 매핑된 경우에만 사용하고, 아니면 중단한다.
2. source 작업이 commit되었고 working tree가 clean인지 확인한 뒤 source를 push하고 origin을 fetch해 실행한다.
   `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase source`
3. `dev`로 전환해 origin을 fetch하고 `git pull --ff-only origin dev`를 실행한다. `base=$(git rev-parse dev)`를 기록하고 preflight script를 `--phase dev`로 실행한다.
4. `origin/<branch>`를 merge하고 `head=$(git rev-parse HEAD)`를 기록한다. conflict가 생기면 보고서 생성이나 push 전에 중단하고 충돌 path를 보고하며, 새 지시 없이 해결하지 않는다.
5. 보고서 Skill의 post-merge mode를 `source=<branch>`, `base=<base>`, `head=<head>`로 적용한다. 반환된 `docs/markdown/daily_reports/team_summaries/` path만 stage하고 staged diff를 검토해, 비어 있지 않으면 보고 전용 commit 하나를 만든다.
6. origin을 fetch한 다음 `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase final --base <base>`를 실행한다.
7. `dev`를 push한 뒤 `dev`와 `origin/dev`가 같은 commit인지 확인한다.
8. source worktree가 source branch에 있고 clean하며 `origin/<branch>`가 `origin/dev`의 조상인지 확인한다. 모두 맞으면 source worktree에서 `git merge --ff-only origin/dev`, `git push origin <branch>`를 실행하고 local source·`origin/<branch>`·`origin/dev`가 같은 commit인지 확인한다. 하나라도 맞지 않으면 source를 변경하지 않고 동기화가 생략된 이유를 보고한다.

## 중단 조건

preflight, merge 또는 보고서 검증이 실패하면 cleanup이나 임의 해결 없이 근거를 보존하고 중단한다.
