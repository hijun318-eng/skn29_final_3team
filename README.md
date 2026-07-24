# SensePlace — 호텔 VOC·운영 지원 플랫폼

SensePlace는 그랜드 워커힐 서울을 모델링한 합성 운영 데이터와 합성 VOC를 이용해 권한 기반 대화형 분석과 이상 감지·근거 조사·주간 보고를 검증하는 내부 의사결정 지원 플랫폼이다. 결과는 실제 호텔의 현황·문제·성과를 의미하지 않는다.

2026-08-06 중간발표는 두 핵심 경로를 backend·DB·LLM과 연결하지 않은 6화면 frontend fixture로 시연한다. 이후 기능 Baseline의 Django 인증·job 계층, FastAPI 분석 계층, PostgreSQL, LLM 연결은 현재 기획 기준이며 구현 확정 사실이 아니다. 실제 채택·연결 상태는 코드, 테스트와 활성 계약 문서를 확인한다.

VectorDB·sLLM·ML/DL·멀티 에이전트 비교는 Baseline 런타임과 분리된 실험 트랙으로 관리하며, 승인 전 실행 경로의 필수 dependency로 추가하지 않는다.

## 활성 기준 문서

제품·기능·데이터·일정은 다음 편집 가능한 문서를 먼저 확인한다. 실제 구현 여부는 코드와 테스트를 함께 확인한다.

- [요구사항정의서](./docs/markdown/01_요구사항정의서.md)
- [WBS](./docs/markdown/02_WBS.md)
- [프로젝트기획서](./docs/markdown/03_프로젝트기획서.md)
- [화면설계서](./docs/markdown/05_화면설계서.md)

## AI 참고 자료

`docs/markdown/ai_docs/`는 AI 작성 자료, 외부 조사·분석, 과거 계약과 공식 일정 스냅샷을 모은 참고 폴더다. 공식 산출물이나 현재 구현 사실이 아니며 활성 번호 문서·코드·테스트와 충돌할 때 이를 덮어쓰지 않는다.

- [통합 기획 참고](./docs/markdown/ai_docs/SensePlace_기획서_초안.md)
- [공식 산출물·전체 일정 스냅샷](./docs/markdown/ai_docs/최종_프로젝트_산출물_및_전체_일정.md)
- [AI 에이전트 공용 작업 가이드](./docs/markdown/ai_docs/codex_공용작업_가이드.md)
- [프로젝트 통제 문서](./docs/markdown/ai_docs/00_project_control.md)
- [공통 개발 명세(과거 제목 유지)](./docs/markdown/ai_docs/common_project_specification.md)

## 개인 branch 시작

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git switch <본인 branch>
```

팀원별 branch와 작업 시작, `dev` 반영, commit, push 방법은 [팀원 Git branch 사용 가이드](./docs/markdown/collaboration/README.md)를 확인한다.

## 문서 관리

문서 위치, 보호 폴더, 공식 산출물 번호와 파일명은 [문서 관리 규칙](./docs/문서관리규칙.md)을 확인한다.

## AI 에이전트 반복 작업

- 문서 생성·편집·이동·검증: [`manage-project-documents`](./.agents/skills/manage-project-documents/SKILL.md)
- 실행 일정·상태·담당·산출물 변경 시 WBS 갱신: [`update-project-wbs`](./.agents/skills/update-project-wbs/SKILL.md)
- 개인·팀·주간보고 갱신: [`update-project-reports`](./.agents/skills/update-project-reports/SKILL.md)
- 개인 branch의 `dev` 통합: [`merge-branch-to-dev`](./.agents/skills/merge-branch-to-dev/SKILL.md)
- staged diff 기반 commit message: [`draft-commit-message`](./.agents/skills/draft-commit-message/SKILL.md)

## OpenWiki

[OpenWiki](https://github.com/langchain-ai/openwiki) code mode를 저장소 보조 위키에 적용한다.

- 시작 문서: [OpenWiki Quickstart](./openwiki/quickstart.md)
- 생성 범위 지침: [OpenWiki Instructions](./openwiki/INSTRUCTIONS.md)
- 요구 환경: Node.js 22+, OpenWiki 0.2.2
- 인증 방식: `openai-chatgpt` provider의 ChatGPT/Codex OAuth

최초 설정은 PowerShell에서 다음과 같이 실행한다.

```powershell
$env:OPENWIKI_PROVIDER = "openai-chatgpt"
$env:OPENWIKI_TELEMETRY_DISABLED = "1"
openwiki code --init
```

이후 갱신은 같은 환경 변수에서 `openwiki code --update --print`를 사용한다. OAuth credential은 사용자 경로 `~/.openwiki/.env`에 저장되며 저장소에 복사하거나 CI Secret으로 전용하지 않는다. 실행 시 저장소 내용이 Codex backend로 전송되고 ChatGPT plan의 Codex 사용량이 차감될 수 있다. 생성 결과는 공식 산출물이나 구현 완료 근거가 아니므로 검토 후 반영한다.
