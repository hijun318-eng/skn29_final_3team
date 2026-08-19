# ANSWERVICE 개발 변경 사항 및 기술 아키텍처 기록서
> **문서 버전**: v1.0.0  
> **최종 갱신 일자**: 2026-08-18  
> **대상 저장소**: `SKN_FINAL / skn29_final_3team`  
> **작성 목적**: GitHub 브랜치 변경 사항 및 멀티턴 데이터 분석 파이프라인의 엔드투엔드(E2E) 구현 상세를 사람이 확인하고 검증할 수 있도록 명확하고 객관적으로 기록함.

---

## 1. 개요 (Overview)

본 문서는 대화형 데이터 인텔리전스 서비스 **ANSWERVICE**의 단일 턴(Single-turn) 프로토타입에서 **제약된 거버넌스 멀티턴(Bounded Governed Multi-turn)** 체계로 전환된 전체 기술 변경 사항을 정리한 문서입니다.

모든 변경은 **데이터 거버넌스(DataHub 카탈로그 승인 규칙)**, **SQL 안전 정책(SQLGlot AST 기반 Gate 2 검증)**, **하드코딩 배제 원칙**을 엄격히 준수하여 수행되었습니다.

---

## 2. 핵심 변경 영역 및 주요 구현 내역

```
[사용자 자연어 입력]
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 백엔드 오케스트레이션 및 리졸버                         │
│    - ConversationSlotResolver: 일반화된 날짜 대수 파싱      │
│    - query_governance: 한국어 형태소 분리 및 DataHub 매칭   │
│    - 3대 라우트 분기 (ANALYSIS / PRESENTATION / REPORT)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  [ANALYSIS]  │       │[PRESENTATION]│       │[REPORT_ACTION│
│ Node 1/2/3   │       │ Trino 0건    │       │ Draft Block  │
│ Trino 실행   │       │ ViewSpec 생성│       │ 아티팩트 연결│
└───────┬──────┘       └───────┬──────┘       └───────┬──────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 대화 상태 영속화 (chat.conversations, chat.turns)        │
│    - 단일 DB 트랜잭션 커밋, Head 갱신, 불변 스냅샷 보존     │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 프론트엔드 수화 (Hydration) 및 렌더링                   │
│    - TurnCard: 지표/차원 상속 칩, KPI 카드, 차트/표 렌더링  │
│    - 하드코딩 제거 및 409 충돌 자동 치유                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.1. 백엔드 (FastAPI / Services / Adapters)

1. **일반화된 한국어 시계열 대수(Date Algebra) 리졸버 탑재**
   - **대상 파일**: `app/backend/app/services/conversation_slot_resolver.py`
   - **변경 내용**:
     - 기존의 단순 키워드 매칭(`"그 전 달"`, `"전월"`)을 전면 개선하여, 정규식 기반의 일반화된 날짜 대수 파서를 탑재함.
     - **단일 월 질의 (`"3월달은?"`, `"5월은?"`)**: 직전 턴의 기준 연도(`2026`)를 자동으로 결합하여 `[2026-03-01, 2026-04-01)`의 KST 월간 반개구간으로 계산.
     - **N개월 상대 오프셋 (`"2달 전은?"`, `"3개월 전은?"`)**: 직전 턴의 시작일 기준 연/월 롤오버를 수학적으로 계산.
     - **절대 기간 (`"2026년 7월"`)**: 독립된 KST 날짜 범위로 파싱.

2. **한국어 조사/접미사 분리 및 DataHub 메타데이터 결정론적 검색 고도화**
   - **대상 파일**: `app/backend/app/adapters/query_governance.py`
   - **변경 내용**:
     - `_unicode_tokens`에 한국어 조사 및 접미사(`에서는`, `에서`, `으로`, `에는`, `별로`, `마다`, `부터`, `까지`, `은`, `는`, `이`, `가`, `을`, `를`, `의`, `에`, `로`, `별`, `도`, `과`, `와`, `만`) 분리 정규화 로직을 추가함.
     - `"GRAND 호텔의 운영매출은 얼마야?"`, `"취소된 연회 행사 수는?"`과 같은 복합 조사 문맥에서도 DataHub 용어사전의 키워드(`호텔`, `운영매출`, `취소`, `연회`)가 정확히 토큰화되어 단일 앵커 에셋(`hotel_operations_daily`, `banquet_daily`)으로 매칭되도록 개선함.

3. **멀티턴 3대 라우트 오케스트레이션 및 트랜잭션 완결**
   - **대상 파일**: `app/backend/app/services/conversation_orchestrator.py`
   - **변경 내용**:
     - `POST /conversations/{id}/commands` 요청 수명주기 확립:
       - `ANALYSIS`: 슬롯 델타 확정 후 AI 파이프라인(`AnalysisPipeline.run()`)을 호출하여 새 아티팩트 생성.
       - `PRESENTATION`: 이전 아티팩트의 스키마를 재사용하여 Trino 쿼리 없이 불변 `ViewSpec`만 생성.
       - `REPORT_ACTION`: 선택된 아티팩트를 보고서 초안(Draft)의 블록으로 연결.
     - 단일 DB 트랜잭션으로 `chat.turns` 영속화 및 `chat.conversations.head_turn_id` 전진, 동시성 lease 안전 해제.

4. **동시성 충돌(409 CONFLICT) 완화**
   - **대상 파일**: `app/backend/app/adapters/conversation_repository.py`
   - **변경 내용**:
     - `expected_head_turn_id`가 명시되지 않은 경우 현재 head에 자동으로 append하도록 처리하여, 불필요한 동시성 예외 발생을 차단함.

---

### 2.2. 프론트엔드 (React / Vite / Vanilla CSS)

1. **하드코딩 배열 잔재 완전 제거 및 런타임 안정화**
   - **대상 파일**: `app/frontend/src/pages/AgentPage.jsx`
   - **변경 내용**:
     - 에러 발생 시 고정된 3개 질문을 노출하던 `DEFAULT_PROMPTS` 배열을 삭제하고 백엔드 동적 응답을 직접 바인딩함.
     - 초기 빈 화면(Empty State) 렌더링 시 발생했던 `ReferenceError`를 수정하여 화면 멈춤(White screen) 결함을 해결함.
     - 409 충돌 발생 시 새 대화방을 자동 생성하여 재시도하는 자기 치유(Self-healing) 로직 추가.

2. **엔터프라이즈 멀티턴 턴 카드(TurnCard) 컴포넌트**
   - **대상 파일**: `app/frontend/src/components/TurnCard.jsx`
   - **변경 내용**:
     - 턴 번호, 라우트 배지(`심층 분석`, `시각화 전환`, `보고서 연계`) 표시.
     - 상속된 지표/기간/차원과 신규 변경된 슬롯을 구분하는 슬롯 칩 UI 렌더링.
     - KPI 메트릭 카드, 반응형 차트(`EnterpriseChart`), 데이터 테이블 및 증적 확인 버튼 제공.

3. **엔터프라이즈 다크 테마 디자인 시스템 정비**
   - **대상 파일**: `app/frontend/src/styles.css`
   - **변경 내용**:
     - 다크 네이비(`Dark Navy #070a10`, `Deep Slate #1d2a3d`, `Accent Blue #1c69d4`, `Gold #a77a3d`) 테마를 전역 적용.
     - Pretendard/Inter 폰트 기반의 가독성 위계 확립 및 카드 패딩, 보더, 마이크로 인터랙션 개선.

---

### 2.3. 인프라 및 거버넌스 (DataHub / Trino / Docker)

1. **Trino 서빙 뷰 및 DataHub 승인 메트릭 카탈로그 정합성 확보**
   - Trino 서빙 뷰 13종(`serving.analytics_v4_3.*`) 적재 상태 점검 및 DataHub Glossary Term 7종과의 매핑 검증 완료.
2. **배포 환경 변수 및 Nginx 리버스 프록시 단일화**
   - 루트 `.env`의 `VITE_BACKEND_BASE_URL=/api`와 프론트엔드 Nginx의 `location /api/ -> backend:8000/` 프록시를 일치시켜 CORS 및 인증 쿠키 단절 문제 원천 차단.

---

## 3. 파일별 변경 상세 대조표 (File-by-File Changes)

| 구분 | 파일 경로 | 변경 전 (Before) | 변경 후 (After) | 해결된 문제 / 목적 |
| :--- | :--- | :--- | :--- | :--- |
| **Backend** | [`conversation_slot_resolver.py`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/backend/app/services/conversation_slot_resolver.py) | "그 전 달", "전월" 등 소수 키워드만 고정 파싱 | 정규식 기반 일반화된 한국어 시계열 대수(Date Algebra) 파서 탑재 | "3월달은?", "5월은?", "2달 전은?" 등 임의의 월/기간 변경 정상 처리 |
| **Backend** | [`query_governance.py`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/backend/app/adapters/query_governance.py) | 공백 기준 단순 토큰 분리로 한국어 조사 붙은 단어 검색 실패 | 22종 한국어 조사/접미사 분리 토큰화 및 단일 앵커 에셋 우선 연결 | "GRAND 호텔의 운영매출은" 등 자연스러운 한국어 문맥에서 DataHub 매칭 성공 |
| **Backend** | [`conversation_orchestrator.py`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/backend/app/services/conversation_orchestrator.py) | 단일 턴 덮어쓰기 구조 | 멀티턴 3대 라우트 분기 및 `chat.turns` 트랜잭션 커밋 | 멀티턴 대화 연속성 및 상태 영속화 완성 |
| **Backend** | [`conversation_repository.py`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/backend/app/adapters/conversation_repository.py) | 엄격한 CAS 체크로 인한 409 CONFLICT 발생 | `expected_head_turn_id` 부재 시 자동 append 허용 | 불필요한 동시성 예외 제거 및 안정적인 턴 추가 |
| **Frontend** | [`AgentPage.jsx`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/frontend/src/pages/AgentPage.jsx) | 고정된 3개 프롬프트 배열 참조 및 ReferenceError 발생 | `DEFAULT_PROMPTS` 삭제, 동적 메시지 바인딩 및 런타임 오류 수정 | 흰 화면(Blank screen) 발생 방지 및 하드코딩 완전 제거 |
| **Frontend** | [`TurnCard.jsx`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/frontend/src/components/TurnCard.jsx) | 단순 텍스트 나열 | 턴별 슬롯 상속 칩, KPI 지표, 차트/표 복합 렌더링 | 엔터프라이즈 BI 수준의 시각적 위계 및 사용성 제공 |
| **Frontend** | [`styles.css`](file:///c:/Users/Playdata/Desktop/SKN_FINAL/skn29_final_3team/app/frontend/src/styles.css) | 레거시 라이트/다크 혼용 스타일 | 통일된 다크 네이비 테마 및 반응형 레이아웃 | 시각적 완성도 및 가독성 확보 |

---

## 4. 실시간 검증 결과 (Verification Evidence)

### 4.1. 6-턴 연속 대화 시나리오 완주 증적
실제 Trino 분산 쿼리 엔진 및 백엔드 API 상에서 실행된 6-턴 연속 대화의 검증 결과입니다:

```text
Turn 1: "2026년 7월 호텔별 운영매출 보여줘"
  • Route: ANALYSIS (신규 지표)
  • 확정 기간: 2026-07-01 ~ 2026-08-01
  • Trino 쿼리 결과: DOUGLAS 28.2억 / GRAND 189.7억 / VISTA 112.1억 (총합 330.0억 원)

Turn 2: "3월달은?" (연도 생략 단일 월 변경)
  • Route: ANALYSIS (지표 상속, 2026년 연도 자동 결합)
  • 확정 기간: 2026-03-01 ~ 2026-04-01
  • Trino 쿼리 결과: DOUGLAS 23.2억 / GRAND 141.3억 / VISTA 80.4억 (총합 244.9억 원)

Turn 3: "5월은?"
  • Route: ANALYSIS (지표 상속)
  • 확정 기간: 2026-05-01 ~ 2026-06-01
  • Trino 쿼리 결과: DOUGLAS 26.4억 / GRAND 183.1억 / VISTA 105.0억 (총합 314.5억 원)

Turn 4: "2달 전은?" (5월 기준 -2개월 상대 계산)
  • Route: ANALYSIS (지표 상속)
  • 확정 기간: 2026-03-01 ~ 2026-04-01
  • Trino 쿼리 결과: DOUGLAS 23.2억 / GRAND 141.3억 / VISTA 80.4억 (총합 244.9억 원)

Turn 5: "표로도 보여줘"
  • Route: PRESENTATION (Trino 쿼리 0건 실행)
  • 결과: ViewSpec 생성 (Chart Type: TABLE)

Turn 6: "이 결과들을 보고서에 담아줘"
  • Route: REPORT_ACTION (Trino 쿼리 0건 실행)
  • 결과: Report Definition 초안 블록 연결 완료
```

### 4.2. 프로젝트 코드 무결성 검사
- **문서화 검사 (`scripts/check_code_documentation.py`)**: **255개 소스 파일 통과** (100% Pass)
- **아키텍처 불변식 검사 (`scripts/lint_architectural_invariants.py`)**: **225개 소스 파일 통과** (100% Pass)
- **프론트엔드 번들 빌드 (`npm run build`)**: 오류 0건, 빌드 성공

---

## 5. 시스템 지원 범위 및 거버넌스 제약 (Boundaries)

### 5.1. 공식 지원 지표 (DataHub 7대 승인 메트릭)
아래 7종의 승인 지표는 임의의 기간, 호텔, 채널, 멀티턴 조건 변경에 대해 **완전 동적으로 쿼리 및 분석**이 지원됩니다:
1. `total_operating_revenue_krw` (합성 통합 운영매출)
2. `voc_review_count` (합성 VOC 리뷰 수)
3. `voc_positive_reviews` (합성 긍정 리뷰 수)
4. `voc_negative_reviews` (합성 부정 리뷰 수)
5. `voc_low_rating_reviews` (합성 저평점 1~2점 리뷰 수)
6. `voc_followup_reviews` (합성 후속확인 필요 리뷰 수)
7. `banquet_cancelled_events` (합성 취소 연회 건수)

### 5.2. 의도적 안전 차단(Fail-Closed) 규칙
- **미승인 세부 컬럼 질의**: DataHub Glossary에 등록되지 않은 물리 컬럼(예: `occupancy_rate`, `revpar_krw` 등)은 AI의 임의 SQL 환각을 차단하기 위해 `Gate 1 (Context Schema)`에서 안전하게 요청을 차단합니다.
- **임의 다대다 조인**: 카탈로그 계통도에 정의되지 않은 원천 테이블 간 크로스 조인은 `Gate 2 (AST Policy)`에서 차단됩니다.
- **개인정보(PII)**: 고객 식별자 원문 조작은 마스킹 처리됩니다.
