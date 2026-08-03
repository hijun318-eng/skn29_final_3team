---
name: merge-branch-to-dev
description: >-
  Safely merge one recognized personal branch into dev with guarded push, merge, and report integration. Use only for "merge or apply my branch to dev" or "개인 branch를 dev에 merge·병합·반영해줘" requests. Do not use for a dev update, dev-to-personal sync, dev-to-main integration, generic Git help, or commit-message drafting.
---

# 개인 Branch를 dev에 병합

`docs/markdown/collaboration/README.md`를 Git 정책의 단일 기준으로 적용한다. 보고서 통합에는 `.agents/skills/update-project-reports/SKILL.md`를 읽고 따른다. 보고서 규칙을 이 Skill에 복사하지 않는다.

## 권한 경계

개인 branch를 `dev`에 병합하라는 명시적 요청은 대상 branch push, `dev` fetch/pull/merge/push, 보고서 절차가 반환한 `team_summaries/` 파일만 담은 보고 전용 commit만 승인한다. 무관한 파일, force push, rebase, reset, stash 또는 history rewriting은 승인하지 않는다.

## 절차

1. 단일 Git 정책에 매핑된 개인 branch 중 정확히 하나를 source로 정한다. 사용자가 이름을 지정하지 않았다면 현재 branch가 매핑된 경우에만 사용하고, 아니면 중단한다.
2. source 작업이 commit되었고 working tree가 clean인지 확인한다. source를 push하고 origin을 fetch한 다음 실행한다.
   `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase source`
3. `dev`로 전환하고 clean tree를 확인한 뒤 origin을 fetch하고 `git pull --ff-only origin dev`를 실행한다.
4. local/remote `dev`가 정확히 같은지 확인하고 `base=$(git rev-parse dev)`를 기록한다. preflight script를 `--phase dev`로 실행한다.
5. `origin/<branch>`를 merge하고 `head=$(git rev-parse HEAD)`를 기록한다. conflict가 생기면 보고서 생성이나 push 전에 중단하고 충돌 path를 보고한다. 새 명시적 지시 없이 해결하지 않는다.
6. 보고서 Skill의 post-merge mode를 `source=<branch>`, `base=<base>`, `head=<head>`로 적용한다. 영향받은 날짜 요약과 누적 주간보고를 검증한다.
7. 반환된 `docs/markdown/daily_reports/team_summaries/` path만 stage한다. staged diff를 검토하고 비어 있지 않으면 팀 형식의 보고 전용 commit 하나를 만든다. 비어 있으면 생략한다.
8. `git diff --check`와 보고서 제한을 다시 확인한다. origin을 fetch한 다음 `<python> .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py --source <branch> --phase final --base <base>`를 실행한다.
9. `dev`를 push한 뒤 `dev`와 `origin/dev`가 같은 commit인지 확인한다.

## 중단 조건

작업 tree가 dirty이거나, source 또는 `dev`가 origin과 예상 밖으로 다르거나, 통합 전에 local `dev`가 ahead/diverged 상태이거나, merge conflict가 생기거나, 보고서 검증이 실패하거나, 보고서 변경만 분리할 수 없으면 cleanup 없이 중단한다. 근거를 보존하고 지시를 요청한다.
