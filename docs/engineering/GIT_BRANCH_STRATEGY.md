# Git Branch 전략

## 1. 최종 구조

5명 팀의 운영 복잡도를 낮추기 위해 원격 branch를 다음 7개로 고정한다.

```text
main        안정·시연 가능한 버전
└─ dev      팀 통합·검증 버전
   ├─ junhee
   ├─ minji
   ├─ seung
   ├─ daesung
   └─ jaehong
```

## 2. 이름 표기

| 팀원 이름 | Branch |
|---|---|
| 준희 | `junhee` |
| 민지 | `minji` |
| 승 | `seung` |
| 대성 | `daesung` |
| 재홍 | `jaehong` |

영문 표기는 branch명에만 적용한다. Git commit 작성자 정보와 GitHub username은 개인 계정의 실제 값을 사용한다.

## 3. Branch 역할

| Branch | 역할 | 허용되는 반영 경로 |
|---|---|---|
| `main` | 발표·시연 가능한 안정본 | `dev -> main` PR만 허용 |
| `dev` | 팀 결과 통합과 회귀 검증 | 개인 branch의 reviewed PR |
| `junhee` | 준희 개인 작업 | `junhee -> dev` |
| `minji` | 민지 개인 작업 | `minji -> dev` |
| `seung` | 승 개인 작업 | `seung -> dev` |
| `daesung` | 대성 개인 작업 | `daesung -> dev` |
| `jaehong` | 재홍 개인 작업 | `jaehong -> dev` |

`feature`, `fix`, `data`, `eval`, `docs`, `release`, `hotfix` branch는 만들지 않는다. 업무 유형은 GitHub Issue label, PR title, commit type으로 구분한다.

## 4. 개인 작업 시작

개인 branch에서는 한 번에 하나의 Issue만 진행한다. 다음 예시는 준희 기준이며 다른 팀원은 자신의 branch명으로 바꾼다.

```powershell
git status --short
git switch junhee
git fetch origin
git merge origin/dev
git push origin junhee
```

`git merge origin/dev`는 이전 PR이 squash merge된 뒤 개인 branch를 최신 `dev`와 다시 연결하기 위한 절차다. 충돌이 발생하면 해결하고 test한 뒤 push한다. 미완성 변경이 남아 있으면 먼저 정리하고 merge한다.

## 5. 개인 작업과 commit

Issue 하나의 범위만 변경한다. 의도한 경로만 stage하고 staged diff를 확인한다.

```powershell
git status --short
git add <path-1> <path-2>
git diff --cached --stat
git diff --cached
```

Codex에는 다음과 같이 요청한다.

```text
$draft-commit-message를 사용해 현재 staged diff만 근거로 commit message를 작성해줘.
실행하지 않은 검증은 포함하지 마.
```

commit message는 `<type>(<scope>): <summary>` 형식과 72자 제한을 따른다. 기능 구분은 branch명이 아니라 commit type과 Issue/PR에서 표현한다.

## 6. 개인 branch에서 `dev`로 반영

```text
junhee ─┐
minji  ─┤
seung  ─┼─ PR + review + CI + squash merge ─> dev
daesung─┤
jaehong─┘
```

PR에는 다음 근거를 남긴다.

- 연결 Issue와 작업 목적
- 실제 변경 diff
- 실행한 test와 결과
- 기능별 test set과 baseline 비교가 필요한지 여부
- synthetic/public/internal data 구분
- 문서, schema, migration 영향
- 알려진 제한과 후속 작업

파일을 수동으로 복사해 반영하지 않는다. 불필요한 변경이 섞였다면 PR 전에 개인 branch에서 제거하고 다시 검증한다. 확인된 결과는 squash merge해 `dev`에 하나의 정리된 commit으로 반영한다.

## 7. `dev`에서 `main`으로 반영

개인 branch는 `main`을 직접 대상으로 하지 않는다. `dev -> main` PR에 다음 근거가 있을 때만 반영한다.

- release 범위와 포함 Issue
- 통합 test 결과
- 기능별 eval baseline 비교 보고서
- schema 또는 migration 영향
- synthetic data version 또는 실제 데이터 사용 여부
- 알려진 제한과 rollback 방법

기능 동작, prompt, model, data pipeline이 바뀌었다면 `evals/reports/`의 비교 보고서를 함께 갱신한다.

## 8. GitHub Ruleset 권장값

| 항목 | `dev` | `main` |
|---|---|---|
| Direct push | 금지 | 금지 |
| Pull Request | 필수 | 필수 |
| 승인 | 1명 이상 | 1명 이상, 가능하면 2명 |
| Required status check | `collaboration-guard`와 stack test | 동일 + 최종 eval gate |
| Force push / delete | 금지 | 금지 |
| Merge 방식 | squash | squash |
| 허용 source | 5개 개인 branch | `dev`만 |

개인 branch에는 팀원이 직접 push할 수 있어야 한다. 개인 branch는 고정해서 재사용하므로 GitHub의 `Automatically delete head branches`는 비활성화한다.

## 9. 금지 사항

- `main` 또는 `dev`에서 직접 개발
- 개인 branch에서 `main`으로 직접 PR
- 한 개인 branch에서 여러 Issue를 동시에 진행
- 다른 팀원의 개인 branch에 무단 push
- 수동 파일 복사로 Git history와 review 근거 제거
- `git push --force`로 공유 history 변경
- test set 또는 metric을 바꾸고 기존 성능과 직접 비교
- 생성 데이터, model cache, secret, 개인 경로 commit
