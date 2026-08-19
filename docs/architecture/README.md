# Answervice 최신 아키텍처 그림

이 폴더에는 과거 버전별 사본을 두지 않고 **현재 기준 JSON 4개와 그 JSON에서 생성한 HTML 4개만** 유지한다. 같은 시스템을 서로 다른 관점으로 나눈 것이므로 네 HTML은 중복 버전이 아니다.

| 순서 | 그림 | 답하는 질문 | 상태 |
|---|---|---|---|
| 1 | [대화형 분석 전체 구성도](./answervice_p0_architecture.html) · [JSON](./answervice_p0_architecture.json) | Conversation 조율, 원자적 분석, 표현·보고서, DataHub·Trino의 책임은 어떻게 나뉘는가? | 현재 요소와 P0 목표를 함께 표시 |
| 2 | [bounded multi-turn 분석 순서](./answervice_analysis_sequence.html) · [JSON](./answervice_analysis_sequence.json) | 후속 Turn이 새 분석, 같은 Artifact의 표현 변경, 확인 요청으로 어떻게 갈리는가? | P0 목표 계약 |
| 3 | [대화 결과 조합·보고서 재실행 순서](./answervice_report_sequence.html) · [JSON](./answervice_report_sequence.json) | 선택한 Artifact·View가 Draft가 되고 승인본이 어떻게 새 Run으로 재실행되는가? | P0 목표 계약 |
| 4 | [승인 데이터 전환 흐름](./answervice_data_release_workflow.html) · [JSON](./answervice_data_release_workflow.json) | 후보 SQL이 DATA-G0~G7, 의미 역검증, 제품 Gold, canary, 복구·승인을 거쳐 어떻게 전환되는가? | P0 목표 계약 |

## 핵심 읽기 원칙

- 현재 제품은 실제 분석 코드 경로가 있지만 UI·API는 사실상 single-turn이다. Conversation DB 필드는 골격이며 Turn 이력·head·상속·표현 routing은 아직 구현되지 않았다.
- 목표는 Analysis Run을 대화 memory처럼 이어 붙이는 구조가 아니다. **각 분석 Run은 원자적 single-turn로 다시 검증하고, Conversation은 승인된 typed 조건과 결과 참조만 이어 주는 bounded multi-turn**이다.
- 발화 이해는 정규식 또는 GPT 하나로 끝내지 않는다. 결정론적 표기 정리 뒤 GPT가 typed 후보를 만들고, 서버가 metadata visibility·DataHub Term·Rule·source Turn·Artifact schema로 하나만 확정한다. 현재 이 Turn-level hybrid resolver는 구현되지 않았다.
- 기간·필터·비교처럼 데이터 의미가 바뀌면 새 Run·권한 snapshot·APP-Gates·query·Artifact가 필요하다. 호환되는 그래프·표 변경은 같은 Artifact와 query를 쓰고 ViewSpec만 새로 만든다.
- Report에는 채팅 문장이나 screenshot이 아니라 선택한 Artifact·ViewSpec·Analysis Definition lineage를 block으로 연결한다.
- 새 데이터 후보와 DataHub-first 의미 discovery는 아직 제품 완료가 아니다. DATA-G0~G7, Golden Dialogue, 실제 E2E, 복구 훈련과 전환 승인 전에는 `NO-GO`다.

논리 그림에는 특정 데이터 버전명이나 물리 namespace를 쓰지 않는다. `승인 데이터`, `승인 Serving`, `호텔 운영 Source`, `후보 SQL`처럼 역할을 표시하고 실제 release ID·namespace·checksum은 정적 감사와 실행 evidence에 기록한다.

## 검증 상태

전체 구성도는 2026-08-16 재생성·재검증했고, 나머지 세 그림은 2026-08-15 최종 산출물 기준이다.

- 네 JSON 모두 Archify `showcase` 구성 검증 `9/9`, error `0`, warning `0`
- 네 HTML 모두 1440×900, 1600×1000, 1920×1080, 2048×1320 containment 통과
- 네 HTML의 1440×900 light·dark 캡처를 수동 확인: 잘림·가로/세로 overflow·겹침 없음
- 데이터 전환도는 기본 화면에서 `후보 → G0~G3 → G4~G5 → G6~G7 → 의미 read-back → 제품 Gold → Canary → 복구·승인·전환`을 순방향으로 읽을 수 있음

최종 시각 산출물 판정은 `GO`다. 다만 이는 **그림 품질 판정**일 뿐 구현 완료나 E2E 통과 판정이 아니다. 현재 작업트리는 아직 commit되지 않았으므로 전체 구성도에는 과거 commit 기반 repository evidence를 넣지 않았다. 구현 경로의 존재와 운영 무결성은 같은 시점에 생성한 `repository-file-inventory.md`와 정적·실행 검증 결과로 별도 판정한다.

검수용 PNG·contact sheet·receipt는 재생성 가능한 중간 산출물이므로 이 폴더에 남기지 않는다. 최종 JSON과 HTML이 변경되면 동일 검증을 다시 실행한다.
