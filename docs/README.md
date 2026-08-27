# Answervice 문서 지도

이 폴더의 제품 기준 문서는 `product/` 아래 네 파일이다. 현재 무엇이 실제 구현됐는지는 문서 순위가 아니라 코드·설정·마이그레이션·런타임 증거로 판정하고 그 결과를 PRD 상태에 반영한다. 문서가 충돌하면 단순히 위 파일이 아래 파일을 모두 덮지 않고, 아래의 필드별 권위를 먼저 적용한다.

1. 사용자의 현재 명시적 결정
2. 제품 목적·사용자·P0/P1/P2 범위는 `docs/product/00_기획서.md`
3. Requirement ID·상태·인수 조건·Release Gate는 `docs/product/01_PRD.md`
4. actor·정상/거부/실패 순서·상태 전이는 `docs/product/02_유저플로우.md`
5. 컴포넌트 책임·신뢰 경계·배포/전환 방식은 `docs/product/03_아키텍처.md`
6. 실제 구현 여부는 현재 코드·설정·마이그레이션·실행 증거
7. `docs/e2e_mvp/source/` 원문과 그 밖의 과거 기획·파생·제출 문서는 참고 근거

문서와 코드가 다르면 어느 한쪽을 자동으로 정답 처리하지 않는다. 차이를 결함 또는 미검증 상태로 기록하고, 같은 릴리스 후보에서 다시 검증한다.

## 기준 문서

| 문서 | 책임 | 넣지 않는 내용 |
|---|---|---|
| [`product/00_기획서.md`](product/00_기획서.md) | 왜 만들고 누구에게 어떤 가치를 주는지, P0/P1/P2 범위 | API·테이블·클래스 세부 |
| [`product/01_PRD.md`](product/01_PRD.md) | 구현해야 할 사용자 결과, 인수 조건, 현재 판정 | 구현 방법과 과거 작업 일지 |
| [`product/02_유저플로우.md`](product/02_유저플로우.md) | 필수 정상·확인·거부·실패·재사용 흐름 | 컴포넌트 내부 호출 상세 |
| [`product/03_아키텍처.md`](product/03_아키텍처.md) | 현재 구조, P0 목표 구조, 확장 경계와 전환 순서 | 기능 완료 선언 |

## 보조 자료

- `e2e_mvp/source/`: 사용자가 지정한 원문. 이번 재정의의 근거이지만 최신 제품 계약은 아니다.
- `e2e_mvp/derived/`: 과거 시점의 작업 문서와 실행 기록. 현재 성공을 자동 증명하지 않는다.
- `reference/Walkerhill_V4.1_SQL_검토.md`: 실행 금지 판정을 포함한 과거 SQL 후보의 읽기 전용 감사 기록이다.
- `reference/P0_실행목표_프롬프트.md`: 이전 기준선에서 파생된 실행 금지 archive다. 새 작업은 저장소 루트 `AGENTS.md`와 제품 기준 문서를 직접 따른다.
- `reference/멀티턴_발화이해_BP_벤치마크.md`: Dialogflow CX, KLUE-DST, CheckList, BFCL, Structured Outputs와 eval BP를 우리 Turn·slot·상태/경로 회귀 계약으로 번역한 참고 자료다. 공개 점수 자체는 제품 Gate가 아니다.
- `reference/datahub_search_flow.md`: DataHub의 일반 검색 개념과 Answervice의 실제 `lexical`/`hybrid` 검색, release·권한·Glossary·Trino 검증 경계를 대조한 참고 자료다. 구현 설명이며 live E2E 완료 증거는 아니다.
- `reference/DataHub_검색_구조_및_Answervice_적용.md`: DataHub 검색·색인 핵심 개념을 서론·본론·결론 순서로 설명하고, 호텔 업무 예시와 Answervice의 ingestion·governance·Context·Trino 실행 경계를 함께 정리한 학습용 참고 자료다.
- `reference/DataHub_검색_흐름_효율성_및_일반성_비교.md`: 현재 검색 흐름의 효율성과 일반성을 코드 기반 LLM 판단과 DataHub 공식 문서 조사로 각각 평가하고, 두 결론과 control/request plane 개선 방향을 비교한 참고 자료다.
- `reference/DataHub_사용_방식_객관적_재평가_및_실사용_사례_2026-08-20.md`: 최신 `dev`의 DataHub 검색·권한·Metric governance를 LLM 코드 평가와 Pinterest·Deutsche Telekom·Trustpilot 등 실제 사례 조사로 재평가하고 두 결론을 비교한 참고 자료다.
- `reference/DataHub_Core_UI_설정_상태_점검_2026-08-19.md`: Docker Compose 포트와 실제 호스팅 IP의 DataHub UI 접근을 점검한 기록이다. 현재 UI 접근 차단으로 Glossary·Domain·Owner는 `NOT_OBSERVED`이며, live 완료 증거가 아니다.
- `reference/Runtime_governance_V4.3_승인검토안.md`: V4.3 serving SQL AST와 컬럼 설명에서 생성한 비권위 DRAFT다. 업무 승인 전에는 DataHub runtime governance로 발행하지 않는다.
- `reference/Runtime_governance_V4.3_업무승인.md`: V4.3 생성식과 동일하게 제한한 통합매출·이벤트·VOC·연회 취소의 업무 승인 기록이다. 실제 발행은 별도의 live check에서 확인한 target·predecessor checksum과 전체 read-back을 요구한다.
- `reference/BI_범용질문_시맨틱_확장설계.md`: 특정 예시 문장이 아닌 범용 BI 질문을 위한 재사용 fact·시맨틱·AnalysisPlan 계약, 현재 검증 증거, 승인·배포 Gate를 정의한다.
- `reference/dev_Canonical_Semantic_구조_변경_비교_2026-08-21.md`: 이전 검토 기준과 현재 `dev`를 비교해 Canonical Semantic Release, grain-safe AnalysisPlan, typed SQL compiler와 SQL Guard의 적용 범위 및 아직 남은 Native 전환 경계를 정리한 구현 점검 보고서다.
- `architecture/`: 최신 Archify 원본 JSON 4개와 HTML 4개만 유지한다. 모두 showcase 9/9와 1440·1600·1920·2048 containment를 통과했고 1440 light/dark를 수동 확인했다. 이는 그림 품질 `GO`이며 제품 구현 완료 증거는 아니다.
- `reference/Walkerhill_V4.1_SQL_검토.md`와 V4.3 교체 보고서는 삭제된 생성·적재 구현의 역사적 감사 기록이다. 현재 runtime 입력이나 rollback 절차로 실행하지 않는다.
- `daily_reports/`, `deliverables/`, `templates/`: 일지·제출물·양식이다. 제품 요구의 권위 원본이 아니다.

## 상태와 증거 규칙

요구사항 상태는 `NOT_STARTED`, `PARTIAL`, `BLOCKED`, `READY_TO_VERIFY`, `VERIFIED`만 사용한다.

- 코드나 테스트가 있다는 이유만으로 `VERIFIED`로 올리지 않는다.
- `VERIFIED`는 같은 릴리스 후보의 commit, 데이터 릴리스, 모델·정책 버전, 실행 시각과 검증 결과가 연결될 때만 사용한다.
- mock·fixture·fake 기반 테스트는 계약 회귀 증거이지 제품 E2E 증거가 아니다.
- 화면 PNG는 보조 증거다. 실제 HTTP 응답, Trino query ID, 저장된 request/trace/artifact와 연결되지 않으면 실행 증거가 아니다.
- 새 데이터 릴리스로 전환하면 과거 데이터의 금액·행 수·query ID 기반 성공 판정은 새 릴리스에 승계하지 않는다.

## 파일 위생

- 테스트 임시 파일은 OS 임시 디렉터리에 만들고 저장소나 상위 작업 폴더에 남기지 않는다.
- 재현에 필요한 결과만 `docs/`에 요약하고, 대용량 raw 로그·cache·build 결과는 Git에 넣지 않는다.
- 과거 기록은 삭제보다 명확한 상태 표기와 링크를 우선한다.
- 현재 사용자 변경이 있는 파일은 명시적 요청 없이 이동·복원·정리하지 않는다.
