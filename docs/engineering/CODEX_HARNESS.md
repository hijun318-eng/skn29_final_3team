# Codex 개발환경·하네스 운영 가이드

## 1. 이번 설정의 범위

이 문서는 frontend/backend 기술을 결정하지 않는다. GitHub, Codex, Claude를 함께 사용할 때 AI 작업 방식과 검증 장치를 통일한다. 팀원이 실제로 따라 할 설치 절차는 `TEAM_DEVELOPMENT_SETUP_GUIDE.md`, 관리자가 새 저장소를 만드는 절차는 `PROJECT_OWNER_SETUP_GUIDE.md`를 원본으로 사용한다.

- 저장소 지침 로딩
- diff 기반 commit message
- skill 사용·추가 기준
- AI 작업 제어 방식
- Markdown 기반 Task/결정/작업 기록
- 반복 가능한 검증 장치
- branch·PR 품질 gate
- 기능별 test set과 baseline 비교

## 2. 저장소 구성

| 경로 | 역할 |
|---|---|
| `AGENTS.md` | 모든 Codex 작업에 적용되는 지속 규칙 |
| `.agents/skills/` | 저장소 전용 반복 workflow |
| `.claude/skills/` | Claude에서 공통 workflow를 찾는 연결 지침 |
| `.github/` | Issue/PR template, CODEOWNERS, stack-neutral CI |
| `.editorconfig` | editor 기본 문자셋·개행·들여쓰기 |
| `.gitattributes` | Git line ending과 binary 처리 |
| `.gitignore` | secret, cache, build, 생성 데이터 제외 |
| `.env.example` | secret 없는 환경변수 이름과 안전한 예시 |
| `requirements.txt` | 확정·검증된 Python runtime dependency |
| `.githooks/commit-msg` | commit subject 형식 검사 |
| `scripts/bootstrap-new-project.ps1` | 별도의 새 프로젝트 폴더에 협업환경 복사·Git 초기화 |
| `scripts/setup-repo.ps1` | 팀원별 local Git hook 연결·환경 점검 |
| `scripts/create-branch-structure.ps1` | 최초 commit 후 `dev`와 5개 개인 branch 생성 |
| `scripts/validate_commit_message.py` | commit message 결정론적 validator |
| `docs/engineering/` | 하네스·commit 규칙·Markdown 템플릿 |
| `evals/` | 기능별 test set, baseline, 품질 비교 report |

사용자 기능 폴더의 최소 구조는 `PROJECT_STRUCTURE.md`를 원본으로 사용한다.

## 3. 팀원 최초 설정

전체 순서는 `TEAM_DEVELOPMENT_SETUP_GUIDE.md`를 따른다. Windows PowerShell에서 repository root로 이동한 뒤 최소 다음을 실행한다.

```powershell
git status --short
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1
```

설정을 바꾸지 않고 공유 파일만 점검하려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1 -CheckOnly
```

`setup-repo.ps1`은 local `.git/config`의 `core.hooksPath`만 `.githooks`로 설정한다. 전역 Git config는 바꾸지 않는다.

### 팀 공통 전역 AGENTS 설치

전역 답변 품질 기준의 원본은 `docs/engineering/CODEX_GLOBAL_AGENTS.md`다. 각 팀원이 자신의 Codex home에 설치한다.

먼저 비교만 하려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-global-codex-agents.ps1 -CheckOnly
```

현재 전역 파일이 없을 때 설치한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-global-codex-agents.ps1
```

기존 전역 파일이 있으면 자동 덮어쓰지 않는다. 내용을 검토하고 명시적으로 `-Force`를 사용할 때만 기존 파일을 timestamp backup한 뒤 교체한다. `AGENTS.override.md`가 있으면 그 파일이 우선하므로 별도로 검토해야 한다.

Git, hook, 개인 AGENTS, 공유 자산을 한 번에 점검한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-team-environment.ps1
```

새 Codex task/session에서 다음으로 지침 로딩을 확인한다.

```text
현재 repository에서 활성화된 프로젝트 범위, AI 제어 규칙, commit message 규칙을 요약해줘.
```

## 4. AI 제어 계층

| 계층 | 무엇을 넣는가 | 예 |
|---|---|---|
| 현재 Prompt | 이번 요청의 목표·범위·승인 | `문서만 수정, commit 금지` |
| `AGENTS.md` | 모든 작업의 불변 규칙 | dirty worktree 보존, 검증 보고 |
| Skill | 반복되는 한 가지 workflow | staged diff로 commit message 작성 |
| Script/Hook | 반드시 같은 결과가 필요한 검사 | subject regex, schema check |
| Markdown evidence | 결정과 실행 결과 | Task Brief, Decision Record, Work Log |

규칙은 가장 작은 적합한 계층에 둔다. 일회성 요구를 `AGENTS.md`에 넣지 않고, 해석이 필요 없는 형식 검사는 AI 지침만 믿지 말고 script로 검증한다.

## 5. 표준 작업 loop

```text
Issue -> 개인 branch에 최신 dev 반영 -> Task Brief -> Scope 확정 -> 작은 변경 -> 검증/eval -> Work Log -> staged diff -> Commit -> PR(dev)
```

### 요청 전

- 여러 파일, contract 변경, 위험한 가정이 있으면 `templates/TASK_BRIEF.md`를 작성한다.
- In/Out scope, 수정 권한, acceptance criteria, 검증, 중단 조건을 적는다.

### 작업 중

- 실제 repo와 현재 diff를 우선한다.
- 한 번에 한 의도만 변경한다.
- AI 판단을 줄일 수 있는 formatter, validator, test가 있으면 먼저 사용한다.
- 사용자 소유 변경과 이번 변경을 분리한다.

### 작업 후

- 실행한 검사와 미실행 검사를 구분한다.
- 결정이 생겼으면 `DECISION_RECORD.md` 형식으로 남긴다.
- 작업 증거는 `WORK_LOG.md` 형식으로 짧게 남긴다.
- commit message는 staged diff가 생긴 뒤 `$draft-commit-message`로 작성한다.

## 6. Commit history로 context 절약

`docs/engineering/COMMIT_CONVENTION.md`를 기준으로 다음을 지킨다.

- type/scope로 변경 종류와 영역을 압축한다.
- subject는 72자 이하 한 의도만 쓴다.
- body는 이유·위험·검증이 subject로 부족할 때만 쓴다.
- staged diff와 최근 subject 최대 5개만 commit message context로 사용한다.
- 테스트를 실행하지 않았다면 commit body에 통과했다고 쓰지 않는다.

Git hook은 형식만 검사한다. 변경의 의미와 commit 분할은 사람과 `$draft-commit-message`가 검토한다.

## 7. Skill·Tool 탐구 결과와 적용 기준

현재 설치 목록은 바뀔 수 있으므로 task 시작 시 실제 가용성을 확인한다.

| 구분 | 현재 적용/향후 용도 | 사용 기준 |
|---|---|---|
| `skill-creator` | `$draft-commit-message` 생성·검증에 적용 | 반복 workflow를 새 skill로 만들 때 |
| `openai-docs` | `AGENTS.md`, repo skill, config/hook 범위 확인에 적용 | Codex/OpenAI 동작의 최신 공식 근거가 필요할 때 |
| `$draft-commit-message` | 현재 적용 | staged commit message 요청 |
| Spreadsheet | 합성 Raw/Clean 파일 품질 확인 | CSV/XLSX artifact 작업이 시작된 뒤 |
| Browser/Chrome | dashboard live verification | 실행 가능한 UI가 생긴 뒤 |
| PDF/Documents/Presentations | 리포트·발표 artifact 생성/검증 | 해당 파일 형식이 확정된 뒤 |
| GitHub workflow skills | PR, review, CI | remote와 CI가 있고 사용자가 요청한 경우만 |
| Plugin creator | 여러 skill/tool의 팀 배포 | repo skill 하나로 부족하다는 증거가 있을 때 |
| MCP/Connector | live/private 외부 시스템 연결 | 실제 데이터·행동 요구와 권한 모델이 있을 때 |
| Multi-agent | 독립 병렬 작업 | 명확한 분리·handoff·통합 검증이 있을 때 |

Skill은 많이 만드는 것이 목표가 아니다. 같은 절차가 반복되고, 일반 지침보다 skill이 context와 오류를 줄일 때만 추가한다.

## 8. 현재 보류한 설정

- project `.codex/config.toml`: 모델, approval, sandbox는 팀원의 계정·관리 정책에 따라 달라질 수 있어 지금 강제하지 않는다.
- Codex lifecycle hooks: trust review와 운영 책임이 필요하므로 현재는 Git `commit-msg` hook만 둔다.
- custom plugin/MCP: 반복 요구가 확인되기 전에는 만들지 않는다.
- frontend/backend 개발 명령: stack과 실제 project structure가 생긴 뒤 검증된 명령만 추가한다.

## 9. Token 절약 규칙

- `AGENTS.md`는 불변식만 유지하고 상세 절차는 이 문서에 링크한다.
- 매 task에서 관련 파일만 읽고 `docs/` 전체를 기본 context로 넣지 않는다.
- skill은 description으로 선택된 뒤에만 전체 `SKILL.md`를 읽는다.
- Work Log는 결정, 변경, 검증, 남은 문제만 적는다.
- 긴 로그·대형 diff는 필요한 구간과 요약만 제공한다.
- commit history에는 실제로 완료된 변경만 기록한다.

## 10. 개발환경 변경 절차

1. 반복되는 문제와 현재 workaround를 Work Log에 기록한다.
2. 해결 계층을 선택한다: prompt / `AGENTS.md` / skill / script / hook.
3. 작은 변경으로 적용한다.
4. 새 session 또는 독립 실행으로 동작을 확인한다.
5. 팀원이 따라 할 명령과 rollback을 문서화한다.
6. 사용자 승인 없이 전역 config, production dependency, 외부 서비스는 변경하지 않는다.
