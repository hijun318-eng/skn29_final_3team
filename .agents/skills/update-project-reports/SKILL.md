---
name: update-project-reports
description: >-
  Update personal daily, team summary, and weekly reports. Use after qualifying work on a mapped personal branch; for "update the daily/weekly report", "일일보고 작성", or "팀 요약·주간보고 갱신"; or for merge-branch-to-dev report integration. Exclude dev/main author inference, Git integration, WBS updates, and report-only recursion.
---

# 프로젝트 보고서 갱신

branch 매핑, 근거, 형식, 기간, 제한은 `docs/markdown/daily_reports/README.md`를 따른다.

## 모드 선택

- **개인 완료:** 매핑된 branch의 `일일보고.md`만 갱신한다.
- **요청 기간:** 지정 날짜의 팀 요약과 주간보고를 갱신한다.
- **Post-merge 통합:** `source`, `base`, `head`를 받아 영향받은 `team_summaries/`만 갱신한다.

## 개인 보고서 절차

1. 단일 기준 README에서 현재 branch의 보고서 매핑을 찾고, 없으면 중단한다.
2. 사용자가 다른 날짜를 명시하지 않으면 현재 KST 날짜를 사용한다.
3. 조건을 충족한 저장소 결과만 기록하고 단일 기준 README의 형식, 문구, 제한에 따라 날짜 block을 작성한다.

## 팀·주간보고 절차

1. post-merge mode에서는 `source`, `base`, `head`를 필수로 받고 `base`가 `head`의 ancestor이며 `head`가 현재 commit인지 확인한다. 두 SHA에서 source 팀원의 개인 보고서를 비교해 전체 block이 바뀐 날짜를 고르고, 팀 요약이 없는 날짜를 추가한다. 사용자가 지정한 범위가 있으면 먼저 따른다.
2. 5개 개인 `일일보고.md`를 직접 읽는다. 날짜 요약을 source of truth로 사용하지 않는다.
3. 단일 기준 README에서 공식 주차를 정하고 해당 형식·문구·제한에 따라 날짜 요약과 주간보고를 작성한다.
4. 한 요청에서 여러 source를 병합하면 각 source의 `base`·`head`를 순서대로 적용하되 모든 보고 변경을 마지막 source 뒤 한 번만 반환한다. `source`, `base`, `head`, 변경된 `team_summaries/` path, 대상 날짜, 검증 결과를 `merge-branch-to-dev`에 반환하며 여기서는 stage하거나 commit하지 않는다.

## 검증

repository root에서 `<python> .agents/skills/update-project-reports/scripts/validate_reports.py <changed report paths>`와 `git diff --check`를 실행한다. 개인 완료 mode에서는 changed path 앞에 `--date <YYYYMMDD>`를 추가한다.
