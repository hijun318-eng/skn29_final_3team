---
type: Repository guide
title: SensePlace Repository Wiki Instructions
description: SensePlace 저장소 위키의 범위, 우선 근거, 제외 항목과 문서 생성 원칙
tags: [senseplace, documentation, repository, code-wiki]
---

SensePlace는 호텔 VOC와 합성 운영 데이터를 연결해 운영 이슈의 관측 사실, 원인 후보, 반대 근거와 관리자 검토용 보고서를 제공하는 프로젝트다.

위키를 생성하거나 갱신할 때 다음 원칙을 적용한다.

- 자연어는 한국어로 작성하고 code, command, path, API, library, error string은 원문을 유지한다.
- 현재 요구사항과 수용 기준은 `docs/markdown/01_요구사항정의서.md`, 일정·담당·상태는 `docs/markdown/02_WBS.md`, 화면 상세는 `docs/markdown/05_화면설계서.md`를 우선한다.
- 실제 구현 여부와 기술 스택은 코드·테스트·설정 파일로 확인하며 문서의 계획을 구현 완료로 표현하지 않는다.
- `docs/markdown/ai_docs/`는 AI 작성·외부 조사·과거 스냅샷 참고 자료이며 활성 번호 문서나 실제 코드를 덮어쓰지 않는다.
- 호텔 실데이터가 확인되기 전 데이터는 `synthetic`으로 표시하고 seed와 schema version을 함께 설명한다.
- `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일의 내용은 읽거나 위키에 복사하지 않는다.
- 요구사항→화면→구현→테스트의 추적 관계, 주요 업무 흐름, 실행 방법, 테스트·운영 경계와 알려진 미결정을 우선 문서화한다.
- 구현되지 않은 frontend/backend 구조, API, 모델, RAG·VectorDB 구성은 추정해 생성하지 않는다.
- 공식 산출물의 문서명·경로·링크나 참고 작성 과정은 공식 제출 내용으로 전용하지 않는다.
- 간결한 quickstart, 저장소 구조, 도메인 개념, 아키텍처, 핵심 흐름, 테스트, 운영·보안 주의사항과 source map을 제공한다.

`openwiki/`의 생성 문서는 개발자와 AI 에이전트를 위한 보조 위키이며 공식 산출물이나 WBS의 대체물이 아니다.
