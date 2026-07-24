# 프로젝트 디렉터리 원칙 요약

> 2026-07-24 압축본. 과거 목표 구조는 `legacy/project_directory_structure_원본_20260724_1138.md`에 보관한다.

## 원칙

- 실제 구현이 생길 때 필요한 최소 폴더만 만든다.
- `src`에는 핵심 로직, `app`에는 사용자 노출 서비스의 실행 진입점을 둔다.
- RAG 채택 전 `src/embeddings`, `src/retrieval`을 만들지 않는다.
- 문서는 `docs/문서관리규칙.md`, 보고서는 `docs/markdown/daily_reports/README.md`를 따른다.
- `.env`, 비밀정보, 실제 고객 데이터와 생성 데이터는 commit하지 않는다.
- 현재 구조와 실행 방법은 파일 시스템, 설정과 테스트에서 확인한다.

과거 제안 구조를 현재 구현 사실로 해석하지 않는다.
