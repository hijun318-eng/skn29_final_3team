# 팀 AI 개발 환경 설정 가이드

| 항목 | 내용 |
|---|---|
| 문서 설명 | 5명 팀원이 동일한 AI 개발 환경을 준비하기 위한 최초 설정 체크리스트 |
| 문서 분류 | 일반 문서 |
| 버전 | v2.3 |
| 문서 기준일 | 2026-08-10 10:52 |
| 작성·수정 | 윤대성 / 박준희 |
| 권장 저장 위치 | `docs/markdown/collaboration/AI_개발_환경_설정.md` |

## 1. 공통 준비

- Git
- Python 3.10 이상
- Node.js와 `node` PATH
- Codex
- MCP server는 현재 설치하지 않음

## 2. Repository 설정

repository root에서 실행한다.

```powershell
git fetch origin
git switch <본인 branch>
git config --local core.hooksPath .githooks
git config --local --get core.hooksPath
```

마지막 명령의 결과가 `.githooks`인지 확인한다.

| 역할 | 본인 branch | 먼저 읽을 매뉴얼 |
|---|---|---|
| R1 기술 PM·통합 | `junhee` | `../ai_docs/5인_병렬구현_01_기술PM_통합플랫폼_품질릴리스_매뉴얼_최종안.md` |
| R2 데이터 플랫폼 | `seung` | `../ai_docs/5인_병렬구현_02_데이터플랫폼_메타데이터_연합조회_매뉴얼_최종안.md` |
| R3 AI·ModelOps | `daesung` | `../ai_docs/5인_병렬구현_03_AI_모델_프롬프트_ModelOps_매뉴얼_최종안.md` |
| R4 백엔드 | `jaehong` | `../ai_docs/5인_병렬구현_04_백엔드_ControlPlane_매뉴얼_최종안.md` |
| R5 프론트엔드·리포팅 | `minji` | `../ai_docs/5인_병렬구현_05_프론트엔드_자동리포팅_매뉴얼_최종안.md` |

## 3. Ponytail 설치

전원 `v4.9.0`, `full` mode를 사용한다.

```powershell
codex plugin marketplace add DietrichGebert/ponytail --ref v4.9.0
codex plugin add ponytail@ponytail
codex plugin list --json
python .github/scripts/gate_scope.py --branch <본인 branch> --bootstrap
```

PowerShell에서 `codex.ps1`이 차단되면 `codex.cmd`를 사용한다. 설치 후 `/hooks`에서 Ponytail hook을 검토·신뢰하고 Codex를 재시작해 새 작업을 연다.

## 4. 최종 확인

```powershell
git branch --show-current
git status --short
git config --local --get core.hooksPath
python --version
node --version
codex plugin list --json
```

- 본인 branch가 맞다.
- `core.hooksPath`가 `.githooks`다.
- Ponytail `v4.9.0`, `full` mode가 활성화됐다.
- Codex가 root `AGENTS.md`를 읽는다.
- bootstrap이 `PASS`이고, 출력된 전체 읽기 문서와 현재 카드 관련 절을 확인했다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v2.3 | 2026-08-10 10:52 | 실제 사용 가능한 Ponytail Skill과 팀 기준을 v4.9.0 full mode로 통일 |
| v2.2 | 2026-08-06 10:09 | branch·dirty 상태·실행 카드와 읽기 문서를 한 번에 확인하는 bootstrap 추가 |
| v2.1 | 2026-07-29 12:16 | 팀 공통 AI 도구를 Codex로 한정하고 Claude Code 절차 제거 |
| v2.0 | 2026-07-29 12:14 | 팀원별 공통 개발 환경 구축에 필요한 설정만 남기도록 문서 축약 |
| v1.3 | 2026-07-29 12:12 | 개인 branch 확인과 dev 병합 주체를 R1이 아닌 관리자로 정정 |
| v1.2 | 2026-07-29 12:10 | 역할별 매뉴얼·branch 연결과 본인 매뉴얼·승인 작업 카드 선행 규칙 추가 |
