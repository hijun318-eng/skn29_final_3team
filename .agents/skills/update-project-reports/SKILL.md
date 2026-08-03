---
name: update-project-reports
description: >-
  Update and validate personal daily reports, team daily summaries, and weekday-based weekly reports. Use after a qualifying non-report change on a recognized personal branch, for date- or period-based "write or update the daily or weekly report", "일일보고 작성", or "팀 요약·주간보고 갱신" requests, or when merge-branch-to-dev invokes post-merge report integration. Do not infer an author on dev/main, perform Git integration, update WBS, or create recursive entries for report-only changes.
---

# 프로젝트 보고서 갱신

`docs/markdown/daily_reports/README.md`를 branch 매핑, 보고 근거, 형식, 기간, 제한의 단일 기준으로 사용한다.

## 모드 선택

- **개인 완료:** 매핑된 개인 branch에서 보고서 이외의 저장소 변경을 마치면 해당 branch의 `일일보고.md`만 갱신한다.
- **요청 기간:** 사용자가 날짜나 기간을 지정하면 5개 개인 보고서를 근거로 해당 날짜 요약과 주간보고를 갱신한다.
- **Post-merge 통합:** `merge-branch-to-dev`에서 source branch, merge 전 `base` SHA, merge 후 `head` SHA를 받아 영향받은 `team_summaries/` 파일만 갱신하고 path와 검증 결과를 반환한다.

## 개인 보고서 절차

1. 단일 기준 README에서 현재 branch와 매핑된 보고서 파일을 확인한다. `main`, `dev` 또는 매핑되지 않은 branch에서는 작성자를 추정하지 않는다.
2. 사용자가 다른 날짜를 명시하지 않으면 현재 KST 날짜를 사용한다.
3. 조건을 충족한 저장소 결과만 기록하고 단일 기준 README의 형식, 문구, 제한에 따라 날짜 block을 작성한다.
4. repository root에서 `<python> .agents/skills/update-project-reports/scripts/validate_reports.py --date <YYYYMMDD> <changed report path>`와 `git diff --check`로 변경 파일을 검증한다.

## 팀·주간보고 절차

1. post-merge mode에서는 `source`, `base`, `head`를 필수로 받고 `base`가 `head`의 ancestor이며 `head`가 현재 commit인지 확인한다. 두 SHA에서 source 팀원의 개인 보고서를 비교해 전체 block이 바뀐 날짜를 고르고, 팀 요약이 없는 날짜를 추가한다. 사용자가 지정한 범위가 있으면 먼저 따른다.
2. 5개 개인 `일일보고.md`를 직접 읽는다. 날짜 요약을 source of truth로 사용하지 않는다.
3. 단일 기준 README에서 공식 주차를 정한다.
4. 단일 기준 README의 source, 형식, 문구, 제한 규칙에 따라 대상 날짜 요약을 만들고 영향받은 주간보고를 다시 작성한다.
5. 보고서 통합 자체를 보고 항목으로 쓰지 않고 보고 전용 변경으로 WBS를 갱신하지 않는다.
6. repository root에서 `<python> .agents/skills/update-project-reports/scripts/validate_reports.py <changed report paths>`와 `git diff --check`를 실행한다.
7. post-merge mode에서는 `source`, `base`, `head`, 변경된 `team_summaries/` path, 대상 날짜, 검증 결과를 `merge-branch-to-dev`에 반환한다. 여기서는 stage하거나 commit하지 않는다.
