# SensePlace — 호텔 VOC·운영 지원 플랫폼

SensePlace는 그랜드 워커힐 서울을 모델링한 합성 운영 데이터와 합성 VOC를 이용해 권한 기반 대화형 분석과 이상 감지·근거 조사·주간 보고를 검증하는 내부 의사결정 지원 플랫폼이다. 결과는 실제 호텔의 현황·문제·성과를 의미하지 않는다.

2026-08-06 중간발표는 두 핵심 경로를 backend·DB·LLM과 연결하지 않은 6화면 frontend fixture로 시연한다. 이후 기능 Baseline의 Django 인증·job 계층, FastAPI 분석 계층, PostgreSQL, LLM 연결은 현재 기획 기준이며 구현 확정 사실이 아니다. 실제 채택·연결 상태는 코드, 테스트와 활성 계약 문서를 확인한다.

VectorDB·sLLM·ML/DL·멀티 에이전트 비교는 Baseline 런타임과 분리된 실험 트랙으로 관리하며, 승인 전 실행 경로의 필수 dependency로 추가하지 않는다.

## Baseline 기준 문서

다른 AI 에이전트 세션은 제품·기능·데이터·일정 판단에 `SensePlace_기획서_초안.md`, `01_요구사항정의서.md`, `03_프로젝트기획서.md`, `02_WBS.md`의 활성 기준을 먼저 확인한다. [AI 에이전트 공용 작업 가이드](./docs/markdown/final_project/codex_공용작업_가이드.md)와 다른 `final_project/` 문서는 작업 역할·과거 계약 참고용 보호 자료이며, 활성 기준과 충돌하면 이를 덮어쓰지 않는다.

1. [AI 에이전트 공용 작업 가이드](./docs/markdown/final_project/codex_공용작업_가이드.md)
2. [프로젝트 통제 문서](./docs/markdown/final_project/00_project_control.md)
3. [공통 개발 명세(보호 문서·과거 제목 유지)](./docs/markdown/final_project/common_project_specification.md)
4. 담당별 공용 문서

구조·화면 지원 문서:

- [최신 저장소 구조 감사](./docs/markdown/final_project/dev_repository_structure_audit.md)
- [프로젝트 디렉터리 구조](./docs/markdown/final_project/project_directory_structure.md)
- [화면설계서 초안](./docs/markdown/05_화면설계서_초안.md)

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
- 저장소 변경 후 WBS 갱신: [`update-project-wbs`](./.agents/skills/update-project-wbs/SKILL.md)
- 개인·팀·주간보고 갱신: [`update-project-reports`](./.agents/skills/update-project-reports/SKILL.md)
- 개인 branch의 `dev` 통합: [`merge-branch-to-dev`](./.agents/skills/merge-branch-to-dev/SKILL.md)
- staged diff 기반 commit message: [`draft-commit-message`](./.agents/skills/draft-commit-message/SKILL.md)
