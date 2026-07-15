# 프로젝트 관리자 초기 세팅 가이드

이 문서는 현재 협업환경 원본을 이용해 **별도의 새 프로젝트 폴더와 GitHub 저장소를 처음부터 구성하는 관리자용 절차**다. 실제 애플리케이션 코드는 새 폴더에서 시작한다.

## 1. 먼저 결정하고 수집할 정보

- 새 프로젝트 local 경로
- GitHub repository 이름과 공개 범위
- GitHub remote URL
- 팀원 GitHub username 목록
- 고정 branch 담당자: 준희=`junhee`, 민지=`minji`, 승=`seung`, 대성=`daesung`, 재홍=`jaehong`
- repository 관리자와 최종 merge 담당자
- 팀원이 사용할 Git email
- `main` release 승인 인원

frontend/backend/database/model은 이번 단계에서 정하지 않아도 된다.

## 2. 새 프로젝트 폴더 생성

현재 협업환경 원본 저장소 root에서 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap-new-project.ps1 `
  -TargetPath "C:\path\to\hotel-voc-agent" `
  -GitUserName "<관리자 이름>" `
  -GitUserEmail "<GitHub email>"
```

script는 다음 작업만 수행한다.

- 대상이 새 폴더 또는 빈 폴더인지 검사
- 협업환경 파일만 선택적으로 복사
- `git init -b main`
- local Git 사용자 정보와 `.githooks` 연결
- 정책 validator 실행
- 최소 `data`, `docs`, `notebooks`, `src`, `app`, `tests`, `evals`, `submission`, `scripts` 구조 복사
- `.env.example`과 빈 기준 `requirements.txt` 복사

실제 `.env`는 만들지 않는다. stage, commit, remote 등록, push도 자동으로 하지 않는다.

## 3. 최초 commit과 remote 연결

새 폴더로 이동하고 복사 결과를 직접 검토한다.

```powershell
Set-Location "C:\path\to\hotel-voc-agent"
git status --short
Get-Content -LiteralPath README.md -Encoding UTF8
```

새 빈 저장소에 협업환경 파일만 존재하는지 확인한 뒤 최초 commit을 만든다.

```powershell
git add .
git diff --cached --stat
git commit -m "chore(repo): initialize collaboration environment"
git remote add origin <REPOSITORY_URL>
git push -u origin main
```

`git add .`은 bootstrap script가 생성한 새 빈 저장소의 최초 검토가 끝난 경우에만 사용한다.

폴더 역할은 `docs/engineering/PROJECT_STRUCTURE.md`를 원본으로 사용하며 기술 스택 확정 전에는 추가 top-level 구조를 만들지 않는다.

## 4. `dev`와 개인 branch 생성

최초 commit 후 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/create-branch-structure.ps1 -Push
```

결과:

- `main`: 최초 협업환경 기준점
- `dev`: 팀 통합 branch
- `junhee`: 준희 개인 branch
- `minji`: 민지 개인 branch
- `seung`: 승 개인 branch
- `daesung`: 대성 개인 branch
- `jaehong`: 재홍 개인 branch

script는 branch가 이미 있으면 덮어쓰지 않고, force push를 사용하지 않는다.

## 5. GitHub repository 설정

### General

- Default branch: `dev` 권장
- Allow squash merging: 활성화
- Allow merge commits: 비활성화 권장
- Allow rebase merging: 팀 합의가 없으면 비활성화
- Automatically delete head branches: 비활성화

`dev`를 default로 두면 일반 PR의 기본 target이 `dev`가 되어 실수로 `main`에 PR을 여는 경우를 줄일 수 있다. `main`은 안정 release branch로 유지한다.

### Ruleset: `dev`

- Require a pull request before merging
- Require at least 1 approval
- Dismiss stale approvals 또는 Require approval of most recent push
- Require conversation resolution
- Require status checks: `collaboration-guard / repository-policy`
- Block force pushes
- Restrict deletions
- PR source는 `junhee`, `minji`, `seung`, `daesung`, `jaehong`만 허용

### Ruleset: `main`

- Require a pull request before merging
- Require at least 1 approval, 가능하면 2명
- Require approval of most recent push
- Require conversation resolution
- Require status checks
- Block force pushes
- Restrict deletions
- PR source는 `dev`만 허용

stack이 정해지면 build, lint, unit/integration test, security scan을 required check에 추가한다.

공식 참고:

- [GitHub - Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub - About issue and pull request templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates)
- [GitHub - About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)

## 6. CODEOWNERS 입력

`.github/CODEOWNERS`는 username을 알 수 없어 comment template만 포함한다. 팀원 초대 후 실제 username으로 규칙을 작성한다.

```text
* @project-owner
/AGENTS.md @project-owner
/.agents/ @ai-owner
/.claude/ @ai-owner
/docs/engineering/ @project-owner
/evals/ @eval-owner
```

실제 owner가 write permission을 갖는지 확인한 뒤 `Require review from Code Owners`를 활성화한다.

## 7. 팀원 초대와 온보딩

1. GitHub collaborator 또는 team으로 초대한다.
2. [팀원 개발환경 세팅 가이드](./TEAM_DEVELOPMENT_SETUP_GUIDE.md)를 공유한다.
3. 각 팀원이 `scripts/check-team-environment.ps1` 결과를 확인한다.
4. 각 개인 branch 접근과 `dev` PR 생성이 되는지 작은 docs PR로 시험한다.
5. `main`과 `dev` direct push가 실제로 차단되는지 확인한다.

## 8. 기능별 평가 체계 활성화

기능 구현을 시작할 때 `evals/registry.json`에 feature를 등록한다.

- test set owner
- test set version
- metric과 threshold
- current baseline version
- 마지막 비교 보고서

동작 변경 PR에는 동일 test set을 사용한 비교 보고서를 요구한다. metric 또는 test set이 바뀌면 기존 성능과 분리해서 평가한다.

## 9. 관리자 완료 조건

- [ ] 새 프로젝트가 별도 폴더와 GitHub repository에 생성됨
- [ ] `main`, `dev`, `junhee`, `minji`, `seung`, `daesung`, `jaehong`이 remote에 존재함
- [ ] GitHub default branch가 `dev`로 설정됨
- [ ] `main`과 `dev` Ruleset이 활성화됨
- [ ] 실제 username으로 CODEOWNERS가 작성됨
- [ ] squash merge 정책이 설정됨
- [ ] Issue/PR template이 표시됨
- [ ] `collaboration-guard`가 PR에서 통과함
- [ ] 모든 팀원이 환경 검사 완료
- [ ] docs test PR로 전체 flow 검증 완료

## 10. 아직 만들지 않는 항목

- 확정되지 않은 frontend/backend/database 구조
- 근거 없는 Docker 또는 cloud 배포 구성
- 실제 secret 값이 포함된 `.env`
- 실데이터로 오해될 수 있는 생성 데이터
- 측정 기준이 없는 model/prompt 성능 주장
