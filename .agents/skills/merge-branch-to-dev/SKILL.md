---
name: merge-branch-to-dev
description: >-
  Safely merge one or more recognized personal branches into dev and integrate reports. Use only for "merge/apply my branch to dev" or "개인 branch를 dev에 병합·반영". Exclude dev updates, dev-to-personal sync, dev-to-main, generic Git help, and commit-message drafting.
---

# 개인 Branch를 dev에 병합

작업 전 `docs/markdown/collaboration/README.md`를 Git 정책의 단일 기준으로 읽고, 보고서 통합에는 `.agents/skills/update-project-reports/SKILL.md`를 적용한다.

## 권한 경계

개인 branch를 `dev`에 병합하라는 명시적 요청은 대상 branch push, `dev` fetch/pull/merge/push, 보고서 절차가 반환한 `team_summaries/` 파일만 담은 보고 전용 commit과 병합 완료 후 source branch의 안전한 fast-forward·push까지 승인한다. 여러 branch가 한 요청에 포함되면 보고 전용 commit은 마지막 source 병합 뒤 하나만 만든다. 무관한 파일, force push, rebase, reset, stash 또는 history rewriting은 승인하지 않는다.

## 절차

1. 단일 Git 정책에 매핑된 개인 branch 중 사용자가 요청한 source 목록을 기록한다. 사용자가 이름을 지정하지 않았다면 현재 branch가 매핑된 경우에만 source 하나로 사용하고, 아니면 중단한다. 여러 source는 `dev`에서 `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --phase batch --sources <branch...> --session` 한 번으로 worktree root·clean 상태·remote SHA·source CI를 먼저 점검한다. `--session`은 Git 공용 디렉터리의 untracked JSON에 최초 dev SHA·source SHA·CI 결과만 저장하며 secret이나 변경 파일 내용은 저장하지 않는다.
2. 각 source의 작업이 commit되었고 clean인지 확인한다. origin을 fetch하고 `<python> .github/scripts/gate_scope.py --branch <branch> --base origin/dev --head HEAD --mode merge-base`로 handoff·범위를 local에서 먼저 검증한 뒤 push한다. push된 source SHA의 CI가 완료될 때까지 기다리고 다음 검사를 통과해야 한다.
   `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase source --session`
   CI가 `missing`·`queued`·`in_progress`면 payload의 run ID 또는 `gh run list`로 찾은 ID를 `gh run watch <id> --exit-status`로 기다린 뒤 사전검사를 다시 실행한다. `failure`·`cancelled`·조회 불가는 병합하지 않는다.
3. `dev`로 전환해 origin을 fetch하고 `git pull --ff-only origin dev`를 실행한 뒤 preflight script를 `--phase dev --session`으로 실행한다. 이 단계가 병합 직전 dev SHA를 같은 session에 기록한다.
4. source 순서대로 `origin/<branch>`를 merge하고 각 merge 직전 SHA와 직후 SHA를 기록한다. conflict가 생기면 보고서 생성이나 push 전에 중단하고 충돌 path를 보고하며, 새 지시 없이 해결하지 않는다.
5. 모든 source 병합 후 각 source의 활성 실행 카드를 `MERGED_DEV`로 바꾸고 session을 사용한 source 사전검사 payload의 `result_fields`를 그대로 `RESULT_SHA`·`RESULT_CI`에 기록한다. 보고서 Skill의 post-merge mode를 각 source의 merge 직전·직후 SHA로 순서대로 적용하고, Gate 원장과 반환된 `docs/markdown/daily_reports/team_summaries/` path만 한 번 stage해 통합 기록 commit 하나를 만든다. `final` 사전검사는 source 카드가 `MERGED_DEV`·`VERIFIED_GATE`가 아니면 실패한다.
6. origin을 fetch한 다음 각 source에 `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase final --session`을 실행한다. final 검사는 session의 최초 base·source SHA·CI 성공을 현재 Git 상태와 대조한다.
7. `dev`를 push한 뒤 `dev`와 `origin/dev`가 같은 commit인지 확인한다.
8. 각 source worktree가 해당 branch에 있고 clean하며 `origin/<branch>`가 `origin/dev`의 조상인지 확인한다. 모두 맞으면 source worktree에서 `git merge --ff-only origin/dev`, `git push origin <branch>`를 실행하고 local source·`origin/<branch>`·`origin/dev`가 같은 commit인지 확인한다. 하나라도 맞지 않으면 해당 source를 변경하지 않고 동기화가 생략된 이유를 보고한다.

## 중단 조건

preflight, merge 또는 보고서 검증이 실패하면 cleanup이나 임의 해결 없이 근거를 보존하고 중단한다.
