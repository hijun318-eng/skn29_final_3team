# Answervice — 대화형 데이터 분석·자동 리포팅 플랫폼

Answervice는 여러 업무 데이터 소스를 자연어로 조회하고 근거가 있는 분석 결과를 반복 실행 가능한 보고서로 전환하는 서비스다. 상세 범위·아키텍처·현재 상태는 아래 활성 기준 문서와 실제 코드·테스트에서 확인한다.

## 활성 기준 문서

- 프로젝트 범위·아키텍처: [최종 기획서](./docs/Answervice_기획서.md)
- 실행 일정·담당·상태: [공식 WBS](./docs/markdown/02_WBS.md)
- 화면·상태·사용자 흐름: [화면설계서](./docs/markdown/05_화면설계서.md)
- AI 작업·권한·병합 원칙: [AGENTS.md](./AGENTS.md)
- 문서 위치·번호·보호 규칙: [문서 관리 규칙](./docs/문서관리규칙.md)

## AI 참고 자료

`docs/markdown/ai_docs/`는 AI 작성 자료, 외부 조사·분석, 과거 계약과 공식 일정 스냅샷을 모은 참고 폴더다. 공식 산출물이나 현재 구현 사실이 아니며 활성 번호 문서·코드·테스트와 충돌할 때 이를 덮어쓰지 않는다. 현재 파일과 사용 경계는 [AI 참고 문서 안내](./docs/markdown/ai_docs/README.md)를 확인한다.

- [5인 병렬 구현 통합 일정](./docs/markdown/ai_docs/5인_병렬구현_통합일정_20260729-20260903.md)
- [공식 산출물·전체 일정 스냅샷](./docs/markdown/ai_docs/최종_프로젝트_산출물_및_전체_일정.md)

## 개인 branch 시작

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git switch <본인 branch>
```

팀원별 branch와 작업 시작, `dev` 반영, commit, push 방법은 [팀원 Git branch 사용 가이드](./docs/markdown/collaboration/README.md)를 확인한다.

## AI 에이전트 반복 작업

- 문서 생성·편집·이동·검증: [`manage-project-documents`](./.agents/skills/manage-project-documents/SKILL.md)
- 실행 일정·상태·담당·산출물 변경 시 WBS 갱신: [`update-project-wbs`](./.agents/skills/update-project-wbs/SKILL.md)
- 개인·팀·주간보고 갱신: [`update-project-reports`](./.agents/skills/update-project-reports/SKILL.md)
- 개인 branch의 `dev` 통합: [`merge-branch-to-dev`](./.agents/skills/merge-branch-to-dev/SKILL.md)
- staged diff 기반 commit message: [`draft-commit-message`](./.agents/skills/draft-commit-message/SKILL.md)
