# Answervice v3.4 아키텍처 안내

이 폴더는 과거 버전별 사본을 쌓아 두지 않고, **현재 v3.4 그림 4개**만 유지한다. 네 그림은 같은 시스템을 서로 다른 질문으로 나눈 것이며 중복 버전이 아니다.

각 그림마다 파일이 2개인 이유는 다음과 같다.

- `.html`: 브라우저에서 바로 열고 탐색·확대·내보내기 할 수 있는 최종 그림
- `.json`: 내용이나 배치를 다시 고칠 때 쓰는 편집 원본

따라서 사람이 관리하는 그림 문서는 안내 문서를 포함해 총 9개만 남긴다: `HTML 4개 + JSON 4개 + README 1개`. 검수용 PNG·contact sheet·receipt는 최종 확인 뒤 보관하지 않는다.

이 폴더에는 손으로 고치지 않는 생성물 1개가 함께 있다. [`repository-file-inventory.md`](./repository-file-inventory.md)는 `python scripts/audit_repository_integrity.py --write-report`가 매번 덮어쓰는 전수 감사 산출물이므로 직접 편집하거나 삭제하지 않는다.

## 그림 읽는 순서

| 순서 | 그림 | 쉽게 말하면 |
|---|---|---|
| 1 | [전체 역할과 흐름](./answervice_v3_4_agent_architecture.html) · [편집 원본](./answervice_v3_4_agent_architecture.json) | Agent 3개, MCP Tool 7개, Core Stage, 의미 정본, 선택형 Neo4j, 결과·보고서가 각각 무엇을 맡는가? |
| 2 | [후속 질문·Graph 보강·분석 흐름](./answervice_v3_4_analysis_sequence.html) · [편집 원본](./answervice_v3_4_analysis_sequence.json) | “그 전 달은?” 같은 질문을 어떻게 이해하고, 복잡한 관계일 때만 Graph 후보를 더한 뒤 안전하게 분석하는가? |
| 3 | [분석 결과 조합·보고서 재실행](./answervice_v3_4_report_sequence.html) · [편집 원본](./answervice_v3_4_report_sequence.json) | 검증된 결과를 보고서에 담고, 승인한 보고서를 현재 권한으로 어떻게 다시 실행하는가? |
| 4 | [데이터·의미·Graph 승인 릴리스](./answervice_v3_4_data_release_workflow.html) · [편집 원본](./answervice_v3_4_data_release_workflow.json) | Walkerhill V4.3, 의미 정본, 선택형 Graph 투영을 어떤 시험과 복구 확인 뒤 전환하는가? |

## 한눈에 보는 책임과 순서

1. **전체 조율**이 질문을 이해하고 Analysis·RAG·ML Agent 중 필요한 담당만 고른다.
2. **Agent 3개**는 수치 분석, 문서 근거, 예측처럼 서로 다른 문제를 맡고 DB를 직접 실행하지 않는다.
3. **MCP Tool 7개**가 안전한 기능 호출 형식을 제공하며 Core의 권한과 Gate를 우회하지 못한다.
4. 기본 수치 분석은 `조건 확정 → Semantic Contract → Query Planner → G1 → SQL 후보 → G2 → Trino → G3 → Artifact` 순서로 진행한다.
5. **DataHub Snapshot과 Semantic Registry가 정본**이다. Neo4j는 승인 관계를 읽기 전용으로 복사한 선택형 후보 탐색 계층이다.
6. `graph.resolve`는 복잡한 Cross-domain 질문이나 관계·경로 재계획 때만 사용한다. 결과는 Semantic Contract와 G1이 다시 확인한다.
7. Neo4j가 멈추면 Registry-only 경로로 돌아가지만, 권한·PII·쓰기·미승인 Join 실패는 돌아가지 않고 즉시 차단한다.
8. 검증을 마친 Artifact만 다시 사용한다. Report는 Agent가 아니라 승인·부분 실패·HTML/PDF 생성을 맡는 Service다.

## 구현 상태를 읽을 때 주의할 점

- 그림은 v3.4의 책임 경계와 목표 흐름을 설명한다. 그림이 있다고 해서 모든 P0/P1 기능과 실제 E2E가 구현 완료됐다는 뜻은 아니다.
- 현재 구현과 목표 구조의 차이는 [제품 아키텍처 문서](../product/03_아키텍처.md)와 감사 기록에서 구분한다.
- 기준 데이터는 Walkerhill V4.3이지만 실제 적재·행 수·조회 성공은 실행·감사 증거로 별도 확인한다.
- Neo4j는 P1 선택형 확장이다. Graph가 없거나 실패해도 P0 Core가 동작해야 한다.

## 검증 상태

2026-08-19 기준 네 JSON과 HTML을 모두 다시 생성·검증했다.

- Archify `showcase` 구성 검사: 각 문서 `9/9`, error `0`, warning `0`
- 화면 크기 검사: 1440×900, 1600×1000, 1920×1080, 2048×1320 모두 overflow 없음
- 라이트·다크 테마: 네 그림의 1440×900과 2048×1320 캡처를 직접 확인
- 수동 연결 검토: Agent→MCP→Core, 정본→Graph 단방향 투영, 후보 재검증·fallback, 보고서 재실행, 데이터 전환 순서가 서로 일치
- 폰트: 설치된 환경에서는 Pretendard를 우선 사용하고, 없으면 한국어 시스템 산세리프 폰트로 대체
- 시각 보정: 최대 허용 범위인 2회 안에서 타임라인과 결론 카드의 중복 여백만 줄였으며 글자 크기와 핵심 단계는 유지

최종 시각 품질 판정은 `GO`다. 이는 그림 품질 판정이며 제품 구현 완료 판정은 아니다.
