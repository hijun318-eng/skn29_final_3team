# 협업 개발환경 문서 인덱스

이 디렉터리는 실제 호텔 VOC 프로젝트를 새 폴더에서 시작할 때 복사해서 사용하는 협업환경 원본이다. 애플리케이션 기술 스택은 아직 고정하지 않는다.

## 팀원이 먼저 읽을 문서

1. [팀원 개발환경 세팅 가이드](./TEAM_DEVELOPMENT_SETUP_GUIDE.md)
2. [Git branch 전략](./GIT_BRANCH_STRATEGY.md)
3. [최소 프로젝트 폴더 구조](./PROJECT_STRUCTURE.md)
4. [Commit convention](./COMMIT_CONVENTION.md)
5. [기능별 품질 평가 가이드](./QUALITY_EVALUATION_GUIDE.md)
6. [Codex 개발환경·하네스](./CODEX_HARNESS.md)

## 프로젝트 관리자 문서

1. [프로젝트 관리자 초기 세팅 가이드](./PROJECT_OWNER_SETUP_GUIDE.md)
2. [팀 공통 전역 AGENTS 원본](./CODEX_GLOBAL_AGENTS.md)
3. [GitHub Pull Request template](../../.github/PULL_REQUEST_TEMPLATE.md)
4. [GitHub CODEOWNERS 설정 파일](../../.github/CODEOWNERS)

## 실행 script

| Script | 용도 |
|---|---|
| `scripts/bootstrap-new-project.ps1` | 이 협업환경을 별도의 새 프로젝트 폴더로 복사하고 `main` 저장소 초기화 |
| `scripts/setup-repo.ps1` | local Git hook 설치와 공통 validator 검사 |
| `scripts/install-global-codex-agents.ps1` | 팀 공통 개인 Codex `AGENTS.md` 설치 |
| `scripts/create-branch-structure.ps1` | 최초 commit 후 `dev`와 5개 개인 branch 생성 |
| `scripts/check-team-environment.ps1` | 팀원 PC 설정 최종 점검 |

## 작업 기록 template

- [Task Brief](./templates/TASK_BRIEF.md)
- [Decision Record](./templates/DECISION_RECORD.md)
- [Work Log](./templates/WORK_LOG.md)
- [Project README](./templates/PROJECT_README.md)

빈 디렉터리는 실제 산출물이 필요할 때 생성한다. 사용하지 않는 구조를 미리 확장하지 않는다.
