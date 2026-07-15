# Claude shared assets

`.claude/`는 팀에서 공유하는 AI 작업 지침과 Skill 연결 파일을 보관하며 Git으로 버전 관리한다.

- Codex용 Skill 원본: `.agents/skills/`
- Claude용 진입점: `.claude/skills/`
- 프로젝트 공통 규칙: root `AGENTS.md`
- 개발환경 문서: `docs/engineering/`

같은 workflow를 두 곳에서 독립적으로 수정하지 않는다. Claude용 Skill은 `.agents/skills/`의 원본을 읽도록 연결하고, 공통 script는 repository root의 `scripts/`를 사용한다.
