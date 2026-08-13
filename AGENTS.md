# Answervice E2E 작업 지침

## 현재 목표

지금의 최우선 목표는 기능 수를 늘리는 일이 아니라 첫 번째 MVP Vertical Slice를 실제 사용자 경로로 끝까지 연결하는 것이다.

```text
질문과 기간 입력
→ 인증·권한 확인
→ 승인 Context
→ SQL 선택 또는 생성
→ G1·G2
→ Trino 조회
→ G3
→ 결과·근거 저장
→ 화면 표시
→ Report 초안 저장·재조회
```

R1~R5 역할, 역할별 허용 경로, 실행 카드, Wave, handoff, 최종 승인자 방식은 더 이상 사용하지 않는다. G1·G2·G3는 협업 Gate가 아니라 제품 런타임의 Context·SQL·Result 안전 경계다.

## 문서 참조 범위

- 제품 요구와 구현 판단에 사용할 문서는 `docs/e2e_mvp/` 안의 문서뿐이다.
- 새 작업을 시작할 때는 `docs/e2e_mvp/README.md`를 진입점으로 삼고, `01_MVP_PRD.md` → `02_Golden_Path_유저플로우.md` → `03_E2E_아키텍처_및_계약.md` 순서로 읽는다.
- 이전 작업에서 이어갈 때는 위 세 문서 다음에 `21_AI_작업_인수인계_현재진행상황.md`를 읽고, 문서의 실행 상태는 현재 코드·Docker·HTTP 결과로 다시 확인한다.
- 원문과 사용자 지정 구조조정 판단 기록은 `docs/e2e_mvp/source/`에 있으며 내용을 임의로 수정하지 않는다.
- 정리 문서는 `docs/e2e_mvp/derived/`에 있으며 원문에 없는 요구를 추가하지 않는다.
- 저장소의 다른 `.md`, `.docx`, `.xlsx`, `.pptx`는 제출 산출물 또는 과거 이력이다. 사용자가 현재 요청에서 특정하지 않으면 구현 근거로 읽거나 인용하지 않는다.
- 코드, 설정, migration, 테스트, runtime artifact는 현재 동작을 확인하기 위해 읽을 수 있다.
- 문서와 코드가 다르면 코드가 맞다고 가정하지 않는다. 차이를 확인된 사실로 기록하고, 첫 Slice를 막는 부분만 수정한다.

## 작업 방식

1. repository root, branch, `git status --short`를 먼저 확인한다.
2. 한 번에 하나의 Vertical Slice만 진행한다.
3. Slice 완성에 필요하면 frontend·backend·data·infrastructure 경계를 함께 수정한다.
4. interface, fixture, mock, queued 상태, 문서 작성만으로 완료 처리하지 않는다.
5. 제품 E2E는 실제 컨테이너와 HTTP 요청으로 검증한다. fake·mock 경로는 제품 성공 근거가 아니다.
6. 브라우저 저장소나 하드코딩 KPI를 서버 결과의 대체물로 사용하지 않는다.
7. 가장 작은 일관된 변경을 적용하되 인증, G1·G2·G3, read-only, 오류 처리, trace를 생략하지 않는다.
8. Ponytail 또는 다른 coding-style plugin을 필수 도구·버전 계약·완료 증거로 사용하지 않는다. plugin 설치·버전 확인을 작업 산출물로 만들지 않는다.
9. 요청받지 않은 stage, commit, push, PR, 외부 배포, 유료 API 호출은 하지 않는다.

## 데이터와 모델

- 일반 E2E 구현 작업에서는 합성 데이터 행이나 대량 생성 SQL을 임의로 만들지 않는다.
- 데이터 재설계는 사용자가 현재 요청에서 별도로 위임한 경우에만 수행한다. 저장소 안에는 데이터 생성 에이전트 전용 지시서를 두지 않는다.
- 현재 적재에 사용하는 SQL·Compose·검증 파일은 `docs/e2e_mvp/derived/service_demo_v3/`에만 있으며, 사용자의 명시적 요청 없이 삭제·재생성·대체하지 않는다.
- 기존 `06_데이터_SQL_Web_작업지시서.md`는 2026-08-12 Docker 감사 근거로만 보존하며 신규 구현 지시로 사용하지 않는다.
- 모델 weight와 adapter는 Git에 넣지 않는다.
- Secret은 `.env`에만 두고 출력·로그·문서·commit에 남기지 않는다.
- OpenAI와 RunPod 호출은 사용자가 key와 endpoint 준비를 확인한 뒤 별도 승인된 검증에서만 실행한다.

## 완료 기준

완료 보고에는 다음을 구분한다.

- 실제로 연결된 사용자 흐름
- 변경 파일
- 실행한 검증과 결과
- 실행하지 못한 검증과 이유
- fixture·mock·외부 환경 때문에 아직 제품 완료로 볼 수 없는 부분
- 다음 한 가지 Slice
