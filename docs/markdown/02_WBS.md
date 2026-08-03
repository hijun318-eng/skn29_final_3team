# Answervice — DataHub 대화형 분석·자동 리포팅 WBS

| 항목 | 내용 |
|---|---|
| 문서 설명 | Answervice의 실행 작업, 담당, 상태, 일정, 산출물, Gate와 병합 순서를 관리하는 공식 WBS 작업본 |
| 문서 분류 | 산출물 작업본 |
| 버전 | v7.69 |
| 문서 기준일 | 2026-08-04 04:03 |
| 작성·수정 | 김재홍·박준희·정승·윤대성·송민지 / 3팀 사용자 요청·Codex 반영 |
| 산출물 번호 | 02 |
| 제출 일자 | 2026-07-16 |
| 대응 템플릿 | `docs/templates/[기획] WBS_양식 (1)_27기_0팀.xlsx`, `docs/templates/[기획] WBS_양식(2)_27기_0팀.xlsx` |

> 전체 프로젝트 기간 2026-07-10~09-03 · 역할 개편 적용일 2026-07-29 · 5인 · 실행 일정 99개 태스크 · I5 이후 비차단 후속 4건 · 공식 산출물 21건 + 옵션 1건
>
> 기준 기획서는 `docs/Answervice_기획서.md`, 화면 기준은 `docs/markdown/05_화면설계서.md`, AI 실행 절차는 `docs/markdown/ai_docs/5인_병렬구현_*_매뉴얼_최종안.md`, Gate별 발행 값은 `docs/markdown/collaboration/Gate_실행_카드_원장.md`다.

## 대응 양식 구조

목록형과 갠트형 원본 양식을 함께 사용한다. Markdown에서는 대공정을 절 제목으로 두고, 실행 행에 목록형 필수 필드와 갠트형 입력 필드를 함께 유지한다.

| 양식 필드 | Markdown 대응 위치 | 적용 원칙 |
|---|---|---|
| 프로젝트 이름·관리자·기준 날짜 | 제목·상단 메타데이터 | 기술 PM은 박준희, 일정 기준은 KST |
| `Task ID`·`WBS 번호` | 실행 WBS의 `ID` | 숫자 ID는 공식 WBS, 괄호 안 `R*-**`는 역할 매뉴얼 카드 |
| 주요 업무·작업 제목 | 실행 WBS의 단계 제목 | 역할의 최종 책임 단위로 분리 |
| 세부 업무 | 실행 WBS의 `작업 항목` | 검증 가능한 결과와 카드 ID를 함께 기록 |
| 담당자·작업 소유자 | 실행 WBS의 `담당` | 첫 번째 담당자가 결과 책임자 |
| 상태 | 실행 WBS의 `현황` | `대기`, `진행`, `검토`, `차단`, `완료`, `취소`만 사용 |
| 시작일·마감일 | 실행 WBS의 `시작`·`마감` | 시작일은 마감일보다 늦을 수 없음 |
| 우선순위 | 실행 WBS의 `우선순위` | `높음`, `중간`, `조건부`로 구분 |
| 기간·완료 비율 | XLSX 변환 시 계산 | 근거 없는 백분율을 추정하지 않음 |
| Gantt timeline | 5.4주 실행 일정·Mermaid | 07/10~07/24 선행 산출물 구간과 07/29~09/03 확정 실행 구간을 구분하고, 일정 변경 시 실행 WBS와 함께 갱신 |

## 역할·책임·충돌 방지 기준

| 역할 | 담당자 | branch | 최종 책임 | 공용 경계 |
|---|---|---|---|---|
| R1 기술 PM·통합 플랫폼·품질·릴리스 | 박준희 | `junhee` | 계약·결정, root Compose·env·CI, 통합·보안·복구·release | 다른 역할의 서비스 내부를 대신 수정하지 않음 |
| R2 데이터 플랫폼·메타데이터·연합조회 | 정승 | `seung` | 5 source·4 engine, 합성 DDL·seed, DataHub, Trino, adapter·gold fixture | 공통 FastAPI·AI·frontend를 수정하지 않음 |
| R3 AI·모델·프롬프트·ModelOps | 윤대성 | `daesung` | Node 1·2·2′·3, prompt, 평가, serving, 시간·횟수 제한 LoRA 비교·조건부 채택 | 권한·Gate·SQL 실행·결과 정답을 판정하지 않음 |
| R4 백엔드 Control Plane | 김재홍 | `jaehong` | FastAPI, Controller, Context, G1·G2·G3, cache·artifact·audit, worker | 공통 OpenAPI·Alembic chain의 단일 작성자 |
| R5 프론트엔드·자동 리포팅 | 송민지 | `minji` | 활성 frontend, Chat·Evidence·Report·Catalog·Audit UI | Report proposal은 R4가 공통 backend에 등록 |

운영 규칙:

1. 한 AI에는 한 번에 현재 통합 Wave의 역할별 실행 묶음 하나를 준다.
2. 담당자는 실행 묶음의 `TASK_CARD_RANGE`를 번호 순서대로 수행하며 카드 사이에 별도 승인을 기다리지 않는다.
3. 실행 묶음의 `ALLOWED_PATHS`만 수정하고 다른 역할 소유 파일은 change request로 넘긴다.
4. `CHECKPOINT_GATES`에서는 계약·증거만 확인하고, 목표 통합 Gate 또는 중단 조건에 도달할 때까지 역할 branch에서 계속 진행한다. 현재 일정의 단독 checkpoint는 I0다.
5. 목표 통합 Gate 도달·카드 범위 완료·허용 경로 밖 변경·계약 충돌·필수 검증 실패 시 멈추고 통합 판정을 기다린다.
6. 실제 연동 전에는 versioned fixture와 fake adapter로 병렬 개발한다.
7. 달력상 checkpoint나 부분 구현만으로 병합하지 않고 소비 가능한 산출물·검증·handoff가 준비된 역할 결과만 통합한다.
8. `fixture 통과`, `MERGED_DEV`, `VERIFIED_GATE`를 별도 상태로 관리한다.
9. R1은 통합 실패를 원 소유 역할에 반환하고 기능 내부를 대신 고치지 않는다.
10. `app/react`와 `app/enterprise-react` 중 활성 frontend 하나를 I0에서 결정하기 전에는 양쪽 구현을 병행하지 않는다.
11. Django와 자유 ReAct loop는 범위에서 제외하고 FastAPI의 고정 상태 전이를 기준으로 한다.

## Gate·병합 일정

| Gate | 기간 | 통과 기준 | 운영·`dev` 병합 기준 |
|---|---|---|---|
| I0 기준 정렬 | 07/29~07/31 | 역할·branch·P0/P1/P2·backend·frontend·파일 소유권 확정 | checkpoint: R1 기준 결정만 공유하고 역할 구현은 branch에서 계속 |
| I1 Contract Freeze | 08/03~08/07 | metric·time·schema·API·model·Report·health 계약과 fake 소비 가능 | Wave 1: 공통 계약·schema·fake·skeleton만 최소 병합 |
| I2 Deterministic Slice | 08/10~08/14 | PMS+CRM 대표 질문의 Context→G1→G2→Trino→G3→Artifact→화면 trace | Wave 2: `seung` → `daesung` → `jaehong` → `minji` → `junhee` |
| I3 General LLM | 08/17~08/21 | 5 catalog 단독·승인 JOIN·Node 통합·보안 기준선 | Wave 3: `seung` → `daesung` → `jaehong` → `minji` → `junhee` |
| I4 Reporting | 08/24~08/28 | Chat→Artifact→Report→manual/schedule→history, partial·retry 검증 | Wave 4 시작: `minji` proposal → `jaehong` 등록 후 역할별 완료분 통합 |
| RC1 | 08/31 | 필수 30건과 역할별 release 후보 판정 | Critical·High 결함만 소유 branch에서 수정 |
| 리허설 1 | 09/01 | 빈 환경 기동·재적재·성공·차단·partial·재시작 시연 | 승인된 순서로 전 역할 확인 |
| RC2·I5 | 09/02 | release SHA·runbook·code·data·model·prompt·policy 동결 | 승인 후 `dev`→`main`은 별도 승인 |
| 최종 발표 | 09/03 | 승인 SHA와 고정 fixture로 시연·질의응답 | 발표 중 code·설정 변경 금지 |

병합 직후 생산자 test와 소비자 contract test를 실행한다. 실행하지 않은 검증은 `Not Run`, 외부 환경 부족은 `Blocked`로 기록하며 병합만으로 Gate 통과라고 표시하지 않는다.

## 🗓️ 8주 핵심 개발 일정

기획서 v1.2의 확정 실행 기간은 **2026-07-29~09-03(약 5.4주)**다. 아래 선행 1~2는 5.4주 실행 전의 기획·제출 이력이며, 실행 1~6만 현재 역할·Gate 실행 구간이다. 10주 참조 모델은 선후관계와 종료 조건을 설명할 뿐 실제 기간으로 사용하지 않는다. 압축은 작업 중첩이 아니라 I2 대표 2-source 우선, gold 120건 I3까지 분할 제작, I5 이후 후속 이관처럼 범위를 줄여 수행한다.

| 구간 | 기간 | 목표 | 마감·Gate |
|---|---|---|---|
| 선행 1 | 07/10~07/16 | 요구사항·WBS 수립 | 요구사항 정의서·WBS |
| 선행 2 | 07/20~07/24 | 기획·데이터·화면 작업본 | 프로젝트 기획서·수집 데이터 보고서·화면설계서 |
| 실행 1 | 07/29~07/31 | 새 5인 역할·소유권 정렬, 데이터 계약 착수 | I0·DB/저장소 설계·전처리 결과 |
| 실행 2 | 08/03~08/07 | 계약·fixture·골격 동결, 중간 발표 | I1·중간 발표·ML/DL·공식 DB 관련 산출물 |
| 실행 3 | 08/10~08/14 | 대표 2-source 결정론적 전체 왕복 | I2·AI 아키텍처·LLM·sLLM 산출물 |
| 실행 4 | 08/17~08/21 | 5 source·일반 질문·보안 기준선 | I3·역할 분리 Node 비교 보고·시스템 구성도 |
| 실행 5 | 08/24~08/28 | 자동 리포팅·장애·복구·회귀 | I4·기능 동결·웹앱·서비스 테스트 |
| 실행 6 | 08/31~09/03 | RC1·리허설·I5·최종 발표 | 최종 PT·소스코드·시연영상 |

## 📈 Mermaid 일정 가시화

```mermaid
gantt
    title 3팀 Answervice 통합 WBS
    dateFormat  YYYY-MM-DD
    axisFormat  %m/%d

    section 기준 정렬
    I0 역할·범위·소유권             :crit, active, i0, 2026-07-29, 2026-07-31

    section 계약·병렬 골격
    I1 Contract Freeze              :crit, i1, 2026-08-03, 2026-08-07

    section 통합 Slice
    I2 Deterministic Slice           :crit, i2, 2026-08-10, 2026-08-14
    I3 General LLM                   :crit, i3, 2026-08-17, 2026-08-21
    I4 Reporting                     :crit, i4, 2026-08-24, 2026-08-28

    section 릴리스
    기능 동결                        :milestone, freeze_feature, 2026-08-28, 0d
    RC1                              :milestone, rc1, 2026-08-31, 0d
    1차 전체 리허설                  :rehearsal, 2026-09-01, 1d
    RC2·I5 최종 동결                 :milestone, rc2, 2026-09-02, 0d
    최종 발표                        :milestone, final, 2026-09-03, 0d
```

## 📊 단계별 요약

| 단계 | 태스크 | 기간 |
|---|:--:|---|
| 기준 정렬·통합 기반 | 8 | 07/29~08/07 |
| 데이터 플랫폼·메타데이터·연합조회 | 20 | 07/29~08/28 |
| AI·모델·프롬프트·ModelOps | 16 | 07/29~09/02 |
| 백엔드 Control Plane | 22 | 07/29~09/02 |
| 프론트엔드·자동 리포팅 | 20 | 07/29~09/03 |
| 통합 Gate·품질·릴리스 | 6 | 08/03~09/03 |
| 발표·공식 산출물 | 7 | 08/03~09/03 |

### 일정·부하 검증 결과

- R1은 공통 계약·통합·품질·릴리스의 결과 책임자지만 R2~R5 서비스 내부 구현을 대신하지 않는다.
- R2~R5는 I1 이전에도 fake·fixture를 사용할 수 있으나 실제 연동 완료로 표시하지 않는다.
- I2의 대표 질문은 PMS PostgreSQL과 CRM SQL Server를 사용하는 2-source 경로로 고정하고, 이후 5 catalog 단독과 승인된 2~3-source JOIN으로 확장한다.
- R4는 Report 공통 등록과 worker를, R5는 독립 Report domain·router·migration proposal과 UI를 담당해 Alembic·entrypoint 충돌을 피한다.
- 기획서 v1.2의 기술 스택 표는 계획과 2026-07-31 실측을 분리한다. 활성 frontend는 React 19·Vite이며, TypeScript·TanStack Query·`react-grid-layout`·`dnd-kit`은 미도입 상태를 완료로 간주하거나 일정에 자동 편입하지 않는다. 차트는 현재 `recharts`를 유지하고 교체는 별도 계약 변경으로만 처리한다.
- 모든 Node는 Base를 기준선으로 유지한다. 평가 데이터·baseline·외부 비용 권한이 준비되면 R3가 시간·횟수를 제한한 LoRA/QLoRA 비교를 1회 수행하고, 선행 조건이 없으면 `Blocked` 또는 `Not Run` 사유를 남긴다. 제품 채택은 별도 Gate 통과 시에만 허용한다.
- 08/28 이후 P0 신규 기능을 추가하지 않고, 09/02 승인 후 code·dependency·model·seed·설정을 변경하지 않는다.

## 실행 WBS

공식 WBS의 숫자 ID와 역할 매뉴얼의 `R*-**` 카드를 작업 항목에 함께 적는다. 담당자가 여러 명이면 첫 번째 담당자가 결과 책임자다.

## 🗂️ 전체 태스크 (99개)

### 기준 정렬·통합 기반

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 1.1 | R1-00 저장소·기획서·AGENTS·WBS·역할 기준 정렬 | 결정·충돌 원장 | 박준희 | 완료 | 07/29 | 07/31 | 높음 |
| 1.2 | R1-01 P0/P1/P2·비목표·공식 산출물 대응 고정 | 범위표·제외 목록 | 박준희 | 완료 | 07/29 | 07/31 | 높음 |
| 1.3 | R1-02 파일 소유권·서비스 경계 Freeze | ownership matrix | 박준희 | 완료 | 07/29 | 07/31 | 높음 |
| 1.4 | R1-03 metric·time·schema·API·state·error 공통 계약 | contract version | 박준희 | 완료 | 08/03 | 08/07 | 높음 |
| 1.5 | R1-04 dev·full·split-host Compose skeleton | 통합 profile | 박준희 | 완료 | 08/03 | 08/07 | 높음 |
| 1.6 | R1-05 환경변수·Secret 계약 | `.env.example`·secret matrix | 박준희 | 완료 | 08/03 | 08/07 | 높음 |
| 1.7 | R1-06 역할별 CI·품질 Gate | CI jobs·fail policy | 박준희 | 완료 | 08/03 | 08/07 | 높음 |
| 1.8 | R1-08 I1 Contract Freeze 판정 | I1 판정서·fixture 소비 증거 | 박준희 | 완료 | 08/06 | 08/07 | 높음 |

### 데이터 플랫폼·메타데이터·연합조회

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 2.1 | R2-00 공통 데이터 계약 확인 | source·engine·owner 표 | 정승 | 완료 | 07/29 | 07/31 | 높음 |
| 2.2 | R2-01 5 source·4 engine registry | source registry | 정승 | 완료 | 07/29 | 07/31 | 높음 |
| 2.3 | R2-02 논리 모델·grain 정의 | entity 관계·grain | 정승 | 완료 | 07/29 | 07/31 | 높음 |
| 2.4 | R2-03 물리 schema·DDL·제약·index | versioned DDL | 정승 | 완료 | 07/29 | 08/07 | 높음 |
| 2.5 | R2-04 deterministic synthetic seed·scenario | seed·scenario manifest | 정승 | 완료 | 07/29 | 08/07 | 높음 |
| 2.6 | R2-05 customer identity bridge | `customer_identity_map` | 정승 | 완료 | 07/29 | 08/07 | 높음 |
| 2.7 | R2-06 event-time 회원 등급 이력 | `member_grade_history` | 정승 | 완료 | 07/29 | 08/07 | 높음 |
| 2.8 | R2-07 데이터 품질·전처리·reject 관리 | DQR·PREP 결과 | 정승 | 완료 | 07/30 | 08/07 | 높음 |
| 2.9 | R2-08 source·application read-only 계정 요구 | account matrix | 정승 | 완료 | 07/29 | 08/07 | 높음 |
| 2.10 | R2-09 DataHub ingestion recipe 5개 | versioned recipes | 정승 | 진행 | 07/29 | 08/21 | 높음 |
| 2.11 | R2-10 Metadata·owner·domain·tag·lineage 보강 | URN·lineage manifest | 정승 | 진행 | 08/10 | 08/21 | 높음 |
| 2.12 | R2-11 DataHub typed adapter | search·graph·health adapter | 정승 | 진행 | 08/10 | 08/21 | 높음 |
| 2.13 | R2-12 Trino catalog 5개 | connector·catalog 설정 | 정승 | 진행 | 07/29 | 08/21 | 높음 |
| 2.14 | R2-13 source↔Trino type mapping | type mapping matrix | 정승 | 진행 | 08/10 | 08/21 | 높음 |
| 2.15 | R2-14 승인 JOIN Registry | JOIN ID·cardinality·time 계약 | 정승 | 진행 | 08/10 | 08/21 | 높음 |
| 2.16 | R2-15 대표 2·3-source 정답 조회 | 정답 SQL·result hash | 정승 | 진행 | 08/10 | 08/21 | 높음 |
| 2.17 | R2-16 Trino/source 실행 adapter | query·status·cancel·health | 정승 | 진행 | 08/10 | 08/21 | 높음 |
| 2.18 | R2-17 source watermark·cache 무효화 입력 | watermark set | 정승 | 진행 | 08/17 | 08/28 | 높음 |
| 2.19 | R2-18 필수 30건·gold용 데이터 fixture | 평가 fixture | 정승 | 완료 | 08/17 | 08/28 | 높음 |
| 2.20 | R2-19 5번째 source 온보딩·재현 | runbook·URN→FQN trace | 정승 | 대기 | 08/24 | 08/28 | 높음 |

### AI·모델·프롬프트·ModelOps

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 3.1 | R3-00 AI P0/P2·공식 모델 산출물 대응 범위 확인 | model decision 초안 | 윤대성 | 완료 | 07/29 | 07/31 | 높음 |
| 3.2 | R3-01 Node 1·2·2′·3 I/O schema | versioned JSON schema | 윤대성 | 완료 | 08/03 | 08/07 | 높음 |
| 3.3 | R3-02 deterministic fake model adapter | fake adapter | 윤대성 | 완료 | 08/03 | 08/10 | 높음 |
| 3.4 | R3-03 Node 1 질문 정규화 | intent·metric·time 후보 | 윤대성 | 완료 | 08/03 | 08/21 | 높음 |
| 3.5 | R3-04 Node 2 Context 제한 SQL 생성 | Trino SQL·참조 목록 | 윤대성 | 진행 | 08/17 | 08/21 | 높음 |
| 3.6 | R3-05 Node 2′ 정규화 오류 1회 수정 | corrected SQL | 윤대성 | 진행 | 08/17 | 08/21 | 높음 |
| 3.7 | R3-06 G3 통과 결과의 Node 3 설명 | 근거·조건·주의 설명 | 윤대성 | 완료 | 08/10 | 08/21 | 높음 |
| 3.8 | R3-07 Prompt Registry | prompt ID·version·hash | 윤대성 | 완료 | 08/03 | 08/07 | 높음 |
| 3.9 | R3-08 필수 30건 평가 runner | schema·linking·SQL·result 평가 | 윤대성 | 완료 | 08/10 | 08/31 | 높음 |
| 3.10 | R3-09 Base model·Analytics Agent 기준선 비교 | 정확도·p50·p95·자원 비교표 | 윤대성 | 완료 | 08/17 | 08/21 | 높음 |
| 3.11 | R3-10 train·val·gold manifest 검수 | 학습 데이터 검수 기록 | 윤대성 | 완료 | 08/17 | 08/21 | 높음 |
| 3.12 | R3-11 time-boxed LoRA/QLoRA 1회 비교와 제품 채택 Gate | 비교 결과·adapter·rollback 증거 | 윤대성 | 완료 | 08/24 | 08/28 | 조건부 |
| 3.13 | R3-12 vLLM·RunPod serving | endpoint·health·manifest | 윤대성 | 완료 | 08/17 | 08/28 | 높음 |
| 3.14 | R3-13 production model client | retry·fallback·circuit 계약 | 윤대성 | 완료 | 08/17 | 08/28 | 높음 |
| 3.15 | R3-14 model trace·비용·재현성 | version·token·cost trace | 윤대성 | 완료 | 08/17 | 08/28 | 중간 |
| 3.16 | R3-15 model·prompt·adapter release 후보 고정 | model release manifest | 윤대성 | 대기 | 08/24 | 09/02 | 높음 |

### 백엔드 Control Plane

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 4.1 | R4-00 backend 경계·의존 방향 | architecture decision | 김재홍 | 완료 | 07/29 | 07/31 | 높음 |
| 4.2 | R4-01 공통 객체·OpenAPI·오류 계약 | versioned API contract | 김재홍 | 완료 | 07/29 | 08/07 | 높음 |
| 4.3 | R4-02 인증·request context middleware | role·as_of·trace context | 김재홍 | 완료 | 08/03 | 08/07 | 높음 |
| 4.4 | R4-03 application DB model·Alembic | migration head | 김재홍 | 완료 | 08/03 | 08/07 | 높음 |
| 4.5 | R4-04 Router·Template Binding | route decision | 김재홍 | 완료 | 08/03 | 08/10 | 높음 |
| 4.6 | R4-05 Controller 고정 상태 머신 | transition table | 김재홍 | 완료 | 08/03 | 08/10 | 높음 |
| 4.7 | R4-06 Context Registry·Builder | versioned Context Package | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.8 | R4-07 G1 Context Gate | decision·evidence | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.9 | R4-08 R3 Node typed client | model client·오류 처리 | 김재홍 | 완료 | 08/10 | 08/21 | 높음 |
| 4.10 | R4-09 G2 SQL Policy Gate | AST·policy decision | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.11 | R4-10 Node 2′·G2′ 수정 1회 통제 | repair counter | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.12 | R4-11 R2 Trino 실행 lifecycle 통제 | pass token·timeout·cancel | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.13 | R4-12 Result Shaper·G3 | shaped result·evidence | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.14 | R4-13 Node 3·승인 후 수정 불가 Artifact | artifact contract | 김재홍 | 완료 | 08/10 | 08/14 | 높음 |
| 4.15 | R4-14 SQL Plan·Result Cache | versioned cache key | 김재홍 | 완료 | 08/17 | 08/21 | 중간 |
| 4.16 | R4-15 Audit·Trace·관측 | linked request trace | 김재홍 | 완료 | 08/10 | 08/21 | 높음 |
| 4.17 | R4-16 R5 Report module 공통 등록 | analysis run contract | 김재홍 | 대기 | 08/24 | 08/28 | 높음 |
| 4.18 | R4-17 worker·schedule runtime | 영속 job·같은 요청 한 번만 처리·실패 격리 | 김재홍 | 대기 | 08/24 | 08/28 | 높음 |
| 4.19 | R4-18 권한·mask·민감정보 가림(redaction) | 보안 검증 증거 | 김재홍 | 완료 | 08/17 | 08/28 | 높음 |
| 4.20 | R4-19 retention·backup·restore hook | 보존 job·복구 절차 | 김재홍 | 대기 | 08/24 | 09/02 | 높음 |
| 4.21 | R4-20 health·backend Dockerfile·회귀 | service fragment | 김재홍 | 완료 | 08/24 | 09/02 | 높음 |
| 4.22 | R4-21 API·migration·policy release 동결 | backend release manifest | 김재홍 | 대기 | 08/31 | 09/02 | 높음 |

### 프론트엔드·자동 리포팅

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 5.1 | R5-00 frontend 후보·fixture 조사와 활성 app 결정안 | reuse·remove 결정표 | 송민지 | 완료 | 07/29 | 07/31 | 높음 |
| 5.2 | R5-01 IA·routing·design token | route·layout | 송민지 | 완료 | 07/29 | 07/31 | 높음 |
| 5.3 | R5-02 OpenAPI type·client·mock | typed client·fixture | 송민지 | 완료 | 08/03 | 08/07 | 높음 |
| 5.4 | R5-03 Chat shell·질문 흐름 | conversation UI | 송민지 | 완료 | 08/03 | 08/14 | 높음 |
| 5.5 | R5-04 실행 상태·오류 UI | state components | 송민지 | 완료 | 08/03 | 08/21 | 높음 |
| 5.6 | R5-05 Evidence·출처·조건 panel | URN·metric·filter·as_of UI | 송민지 | 완료 | 08/10 | 08/14 | 높음 |
| 5.7 | R5-06 결과 표·차트 | result components | 송민지 | 완료 | 08/10 | 08/14 | 높음 |
| 5.8 | R5-07 Chat→Report Artifact bridge | artifact action | 송민지 | 완료 | 08/10 | 08/14 | 높음 |
| 5.9 | R5-08 Report definition·version·run·block domain | Report contract | 송민지 | 완료 | 08/03 | 08/24 | 높음 |
| 5.10 | R5-09 독립 Report router·API module | router·contract test | 송민지 | 완료 | 08/17 | 08/24 | 높음 |
| 5.11 | R5-10 Report migration proposal | 단일 migration proposal | 송민지 | 완료 | 08/17 | 08/24 | 높음 |
| 5.12 | R5-11 12-column Report editor | add·move·resize·draft | 송민지 | 대기 | 08/24 | 08/28 | 높음 |
| 5.13 | R5-12 수동 실행·Run History | run·status·history UI | 송민지 | 대기 | 08/24 | 08/28 | 높음 |
| 5.14 | R5-13 daily·weekly·monthly schedule UI | schedule contract | 송민지 | 대기 | 08/24 | 08/28 | 높음 |
| 5.15 | R5-14 Catalog·Connection UI | source·asset·ingestion UI | 송민지 | 완료 | 08/17 | 08/28 | 중간 |
| 5.16 | R5-15 Operations·Audit trace UI | request trace UI | 송민지 | 대기 | 08/24 | 08/28 | 높음 |
| 5.17 | R5-16 접근성·반응형·보안 상태 표시 | QA evidence | 송민지 | 대기 | 08/24 | 08/31 | 높음 |
| 5.18 | R5-17 실제 API integration | production client | 송민지 | 대기 | 08/24 | 08/31 | 높음 |
| 5.19 | R5-18 frontend Dockerfile·build·E2E | service fragment | 송민지 | 대기 | 08/24 | 09/02 | 높음 |
| 5.20 | R5-19 발표 route·fallback fixture | demo runbook | 송민지 | 대기 | 08/31 | 09/03 | 높음 |

### 통합 Gate·품질·릴리스

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 6.1 | R1-07 필수 30건·gold 120건 평가 원장 관리 | reviewer·split·expected 원장 | 박준희·정승·윤대성 | 완료 | 08/03 | 08/31 | 높음 |
| 6.2 | R1-09 I2 Deterministic Slice 통합·판정 | 대표 질문 trace·result hash | 박준희·정승·윤대성·김재홍·송민지 | 완료 | 08/10 | 08/14 | 높음 |
| 6.3 | R1-10 I3 General LLM·보안 기준선 통합 | 일반 질문·model 비교·보안 결과 | 박준희·정승·윤대성·김재홍·송민지 | 진행 | 08/17 | 08/21 | 높음 |
| 6.4 | R1-11 I4 Reporting·worker·partial 통합 | Report 왕복 trace | 박준희·김재홍·송민지 | 대기 | 08/24 | 08/28 | 높음 |
| 6.5 | R1-12 read-only·mask·장애·복구·성능 검증 | 수용 시험 증거 | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 08/24 | 09/02 | 높음 |
| 6.6 | R1-13 RC1·RC2·I5·최종 Release | release manifest·runbook·승인 SHA | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 08/31 | 09/03 | 높음 |

### 발표·공식 산출물

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 우선순위 |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| 7.1 | 중간 발표 자료·역할별 진행 근거·리허설 | 중간 발표 PT | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 08/03 | 08/06 | 높음 |
| 7.2 | 최종 발표 story·PT·시간 배분 | 최종 발표 PT | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 08/24 | 09/02 | 높음 |
| 7.3 | 데이터·AI·Control Plane·UI 역할별 근거와 Q&A | 발표 근거 묶음 | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 08/31 | 09/02 | 높음 |
| 7.4 | 승인 SHA 소스·README·version manifest 패키징 | 프로젝트 소스코드 | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 08/31 | 09/03 | 높음 |
| 7.5 | 성공·차단·partial·Report 시연 녹화 | 시연영상 | 송민지·박준희 | 대기 | 08/31 | 09/03 | 높음 |
| 7.6 | 1차·2차 전체 리허설과 결함 회귀 | 리허설 기록 | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 09/01 | 09/02 | 높음 |
| 7.7 | 승인 환경 최종 발표·질의응답 | 발표 결과 | 박준희·정승·윤대성·김재홍·송민지 | 대기 | 09/03 | 09/03 | 높음 |

## 📦 산출물 제출 일정 (공식 21 + 옵션 1)

공식 산출물 번호·마감은 일정 참고 문서를 유지하고, 새 역할의 결과 책임자와 관련 WBS를 연결한다. 제출 여부는 저장소 증거를 확인하기 전까지 추정하지 않는다.

| 단계 | 산출물 | 제출일 | 내부검토 | WBS | 담당 | 현황 |
|---|---|:--:|:--:|:--:|:--:|:--:|
| 기획 | 요구사항 정의서 | **07/16** | 07/15 | 1.1 | 박준희 | 완료 |
| 기획 | WBS | **07/16** | 07/15 | 1.1 | 박준희 | 완료 |
| 기획 | 프로젝트 기획서 | **07/24** | 07/23 | 1.2 | 박준희 | 검토 |
| 데이터 수집 및 저장 | 수집 데이터 보고서 | **07/24** | 07/23 | 2.5 | 정승 | 대기 |
| 모델 배포 | 화면설계서 | **07/24** | 07/23 | 5.2 | 송민지 | 검토 |
| 데이터 수집 및 저장 | 데이터베이스/저장소 설계 문서 | **07/31** | 07/30 | 2.4 | 정승 | 검토 |
| 데이터 전처리 | 데이터 전처리 결과서 | **07/31** | 07/30 | 2.8 | 정승 | 검토 |
| 발표 및 시연 | 중간 발표 PT 자료 | **08/06** | 08/05 | 7.1 | 박준희·전원 | 대기 |
| 데이터 전처리 | 머신러닝/딥러닝 학습결과서 | **08/07** | 08/05 | 3.10 | 윤대성 | 대기 |
| 데이터 전처리 | 학습한 ML/DL 모델 | **08/07** | 08/05 | 3.16 | 윤대성 | 대기 |
| 모델링 및 평가 | 벡터DB/GraphDB 구축 결과서 | **08/07** | 08/05 | 3.1 | 윤대성·박준희 | 차단 |
| 모델링 및 평가 | AI 시스템 아키텍처 | **08/14** | 08/13 | 4.6 | 박준희·김재홍 | 대기 |
| 모델링 및 평가 | LLM 활용 소프트웨어 | **08/14** | 08/13 | 4.14 | 김재홍·윤대성 | 대기 |
| 모델링 및 평가 | 자체 sLLM 인공지능 | **08/14** | 08/13 | 3.16 | 윤대성 | 대기 |
| 모델링 및 평가 | 멀티 에이전트 테스트 계획 및 결과 보고서(공식 명칭; 역할 분리 Node 비교로 작성) | **08/21** | 08/20 | 3.10 | 윤대성·박준희 | 대기 |
| 모델 배포 | 시스템 구성도 | **08/21** | 08/20 | 1.5 | 박준희·김재홍 | 대기 |
| 모델 배포 | 개발된 LLM 연동 웹 애플리케이션 | **08/28** | 08/27 | 5.19 | 송민지·김재홍 | 대기 |
| 모델 배포 | 서비스 테스트 계획 및 결과 보고서 | **08/28** | 08/27 | 6.5 | 박준희·전원 | 대기 |
| 발표 및 시연 | 최종 발표 PT 자료 | **09/03** | 09/02 | 7.2 | 박준희·전원 | 대기 |
| 발표 및 시연 | 프로젝트 개발 소스코드 | **09/03** | 09/02 | 7.4 | 박준희·전원 | 대기 |
| 발표 및 시연 | 시연영상 | **09/03** | 09/02 | 7.5 | 송민지·박준희 | 대기 |
| 모델링 및 평가 | AI 윤리/편향성 점검 결과서(옵션) | **옵션** | 08/26 | 3.11 | 윤대성·박준희 | 대기 |

`docs/deliverables/01_요구사항정의서_29기_3팀.xlsx`와 `docs/deliverables/02_WBS_29기_3팀.xlsx`는 현재 Answervice 기준으로 교정해 공식 근거로 사용한다. `docs/deliverables/03_프로젝트기획서_29기_3팀.docx`는 기획서 v1.2 내용으로 갱신됐으나 PNG 시각 검증이 `Not Run`이므로 `검토`를 유지한다.

`벡터DB/GraphDB 구축 결과서`는 공식 산출물 목록에는 있으나 현재 기획서의 P0/P1 구현 범위에는 VectorDB·GraphDB가 없다. R1·R3가 08/05까지 “미도입 근거와 비교 실험 보고로 제출 가능한지”를 확인하기 전까지 `차단`으로 유지하며, 확인 없이 P0에 신규 인프라를 추가하지 않는다.

## 기획서 추적성

| 기획서 영역 | 주 책임 | WBS | 처리 기준 |
|---|---|---|---|
| §1~5 목표·범위·사용자·기능 | R1 박준희 | 1.1~1.4 | I0에서 P0/P1/P2와 비목표 고정 |
| §7 전체 아키텍처·추적 ID | R4 김재홍·R1 박준희 | 4.1~4.6, 4.16 | 고정 상태 전이·trace 계약 |
| §8 DataHub·Trino | R2 정승 | 2.1~2.20 | 5 catalog 단독·승인 2~3-source JOIN |
| §9 Context·Guarded Text-to-SQL | R4 김재홍 | 4.7~4.14 | G1·G2·G3 우회 0건 |
| §10 sLLM·RunPod | R3 윤대성 | 3.2~3.16 | 전 Node Base 기준선, 제한된 1회 비교·LoRA 채택 조건부 |
| §11 자동 리포팅 | R5 송민지·R4 김재홍 | 5.8~5.14, 4.17~4.18 | definition/run 분리·일부 실패·중복 실행 방지 |
| §12 MCP·문서 RAG | R1 박준희 | 1.2, F-01~F-02 | I5 이후 P2 후속, 현재 완료선 비차단 |
| §13 ML-as-a-Tool | R1 박준희 | 1.2, F-03 | I5 이후 P2 후속, 현재 완료선 비차단 |
| §14 합성 데이터 | R2 정승 | 2.4~2.9, 2.19 | deterministic seed·참조·기간 무결성 |
| §15 화면·메뉴 | R5 송민지 | 5.1~5.20 | P0/P1·접근성·오류 상태 |
| §16 애플리케이션 구조 | R1·R4·R5 | 1.3~1.8, 4.1~4.6, 5.1~5.3 | I0/I1에서 단일 entrypoint·frontend 결정 |
| §17 보안·권한·감사·복구 | R1·R2·R4·R5 | 2.9, 4.3, 4.16, 4.19~4.21, 6.5 | read-only·mask·민감정보 가림·restore |
| §18 평가 | R1·R2·R3 | 2.19, 3.9~3.15, 6.1~6.5 | 필수 30건·gold 120건·재현 |
| §19 MVP·후속 범위 | R1 박준희 | 1.2, F-01~F-04 | I5 이후 후속, 현재 완료선 비차단 |
| §20 개발·산출물 | 전 역할 | 1.1~7.7 | 07/29~09/03 압축 일정 적용 |
| §21 리스크 | R1 박준희 | 1.5~1.8, 6.5~6.6 | blocker·rollback·잔여 위험 기록 |
| §22 결정·가정 | R1 박준희 | 1.1~1.4 | I0/I1 결정 원장에 version 기록 |

## I5 이후 후속 단계 백로그

아래 네 항목은 기획서에 이미 포함된 후속 범위다. 현재 99개 실행 태스크, I1~I5 Gate, 09/03 발표 완료율에는 포함하지 않는다. I5 이후 R1이 별도 일정·계약·비용·보안 Gate를 승인할 때만 새 실행 묶음으로 발행하며, 그 전 상태가 `대기`, `Blocked`, `Not Run`이어도 현재 릴리스 실패로 판정하지 않는다.

| 후속 ID | 항목 | 착수 조건 | 주 책임 | 필수 인계 | 현재 상태 |
|---|---|---|---|---|:--:|
| F-01 | P2 MCP Tool Registry·호출 통제 | I5 완료, Tool I/O·권한·감사·오류 계약 승인 | R4 김재홍 | R3 adapter, R5 관리 UI, R1 보안 Gate | 대기 |
| F-02 | P2 사내 운영 문서 RAG | I5 완료, 문서 권한·버전·발효일·인용·평가 계약 승인 | R3 윤대성 | R2 metadata, R4 authz·trace, R5 근거 UI | 대기 |
| F-03 | P2 ML-as-a-Tool | I5 완료, feature·model I/O·버전·평가·표시 계약 승인 | R3 윤대성 | R2 feature data, R4 Tool Gate, R5 예측 표시 | 대기 |
| F-04 | 고객 360 | I5 완료, identity·중복·mask·role·감사 Gate와 별도 수용 기준 승인 | R5 송민지 | R2 identity·mask, R4 authz·trace, R1 범위 Gate | 대기 |

## 추가 결정 필요

| 항목 | 현재 운용 기준 | 결정 시점 | 결정 책임 |
|---|---|---|---|
| 활성 frontend | `app/react`와 `app/enterprise-react` 중 하나만 선택 | I0 | R1·R5 |
| full·dev·split-host | dev로 병렬 개발, full 실패 시 split-host 전환 | I0/I1 | R1 |
| DataHub·Trino·connector 고정 version | 실행 전 고정하고 manifest 기록 | I1 | R1·R2 |
| Result Cache 구현 | versioned key 계약 우선, PostgreSQL·Redis는 profile 측정 후 선택 | I1/I3 | R1·R4 |
| model checkpoint·RunPod profile | Base 기준선 우선, 비용·자원 승인 후 외부 실행 | I1/I3 | R1·R3 |
| SQL LoRA 제품 채택 | 실제 결과 일치는 향상됐지만 p95가 증가해 Base 유지, serving 최적화·SLO 승인 뒤 재판정 | I4 이전 | R1·R3 |
| 공식 VectorDB/GraphDB 산출물 | 미도입 근거 제출 가능 여부 확인 전 `차단` | 08/05 | R1·R3 |
| 공식 03 제출본 시각 검증 | DOCX는 기획서 v1.2 내용으로 갱신됐으며 PNG render 전까지 `검토` | 다음 공식 제출 전 | R1·R3 |

## WBS 작업 로그

최신 기록을 위에 추가한다. 작업 로그는 문서 변경 자체를 구현 완료 근거로 사용하지 않는다.

| 일시(KST) | WBS ID | 변경 요약 | 결과 구분 |
|---|---|---|---|
| 2026-08-04 04:03 | 3.14, 4.9, 6.3 | R3의 node2 한 줄 compact SQL PROMPT-v1.0.2가 15건·전체 CI를 통과해 dev에 통합됐다. raw finish/schema/LIMIT을 먼저 확인하고 동일 Base·I2 read-only 제품 전체 trace를 재검증하는 R1-W3-F4를 발행했다. 실행 전이므로 3.14·4.9 완료와 6.3 진행, 일정·간트는 유지한다. | compact prompt 완료·최종 제품 재검증 승인 |
| 2026-08-04 03:59 | 3.14, 4.9, 6.3 | 실제 PROMPT-v1.0.1 trace에서 LIMIT은 생성됐지만 SQL 문자열의 불필요한 개행 881줄로 completion 1,500 token에 도달해 JSON이 미완성으로 MODEL 안전 실패했다. QUERY·Artifact는 없고 task resource를 제거해 active Pods 0을 확인했다. 신규 비용 상한은 약 USD0.066224다. R3-W3-F7로 node2 한 줄 compact SQL 문구만 보완하며 상태·일정·간트는 유지한다. | MODEL 길이 병목 확인·R3 compact prompt 승인 |
| 2026-08-04 03:48 | 3.14, 4.9, 6.3 | R3의 node2·repair PROMPT-v1.0.1이 LIMIT 1~1000과 RESOURCE_POLICY_MISSING 단일 수정 행동을 명시하고 15건·전체 CI를 통과해 dev에 통합됐다. 동일 Base·I2 synthetic read-only 제품 trace를 재검증하는 R1-W3-F3를 발행했다. 실행 전이므로 3.14·4.9 완료와 6.3 진행, 일정·간트는 유지한다. | R3 prompt 보완 완료·실제 제품 재검증 승인 |
| 2026-08-04 03:42 | 3.14, 4.9, 6.3 | 실제 I2 Context·read-only Trino 제품 trace에서 guided MODEL은 통과했지만 node2 SQL에 필수 LIMIT가 없고 repair도 동일 SQL을 반환해 G2가 안전 차단했다. QUERY·Artifact는 실행되지 않았고 task Pod·container·image·tunnel을 제거해 active Pods 0을 확인했다. 신규 비용 상한은 약 USD0.066601이다. R3-W3-F6로 resource limit·단일 repair prompt 계약만 보완하며 3.14·4.9 완료와 6.3 진행, 일정·간트는 유지한다. | G2 prompt 병목 확인·R3 최소 보완 승인 |
| 2026-08-04 03:27 | 3.14, 4.9, 6.3 | R4의 node별 R3 response schema guided transport가 관련 22건과 source 전체 CI를 통과해 dev에 통합됐다. task A40·backend와 기존 hotel-synthetic-db Trino의 read-only synthetic 조회만 사용하는 R1-W3-F2를 발행해 실제 MODEL→G2→QUERY→G3→ARTIFACT trace를 재검증한다. 실행 전이므로 3.14·4.9 완료와 6.3 진행, 일정·간트는 유지한다. | R4 schema 보완 완료·실제 I2 제품 trace 승인 |
| 2026-08-04 03:21 | 3.14, 4.9, 6.3 | 실제 Base endpoint와 FastAPI 제품 trace에서 기본·60초 timeout 모두 MODEL 안전 실패를 확인했다. 원응답은 JSON이 아니었고 JSON object mode도 R3 필수 field를 누락했지만 실제 R3 schema의 guided_json은 schema PASS였다. 이후 fake Context의 asset·metric 불일치로 G2 repair 뒤 차단돼 R4-W3-F2 structured output 보완과 I2 synthetic Context 재검증으로 분리했다. task Pod·container·image·tunnel을 제거했고 신규 비용은 약 USD0.107045로 추정된다. 상태·일정·간트는 유지한다. | 안전 실패 확인·R4 transport 재작업 승인 |
| 2026-08-04 03:01 | 4.9, 6.3 | R4 endpoint 연결과 dev CI PASS 뒤 실제 제품 trace를 확인하는 R1-W3-F1을 발행했다. 누적 USD 15 안에서 task 전용 A40 Base endpoint와 task backend를 연결해 synthetic `/analysis`의 성공 trace 또는 MODEL 안전 실패를 판정하고 정확한 resource cleanup을 요구한다. 실제 실행 전이므로 4.9 완료와 6.3 진행, 일정·간트는 유지한다. | R1 live product trace 승인·실행 전 |
| 2026-08-04 02:58 | 3.14, 4.9, 6.3 | R4-W3-F1의 실제 Base endpoint transport를 FastAPI 분석 경로에 통합했다. 고정 생성 옵션과 R3 schema 선검증을 적용하고 timeout·잘못된 JSON·fallback·circuit open이 query나 Artifact 성공으로 저장되지 않음을 관련 21건과 source CI Python 전체 150건·OpenAPI 4건으로 확인했다. 3.14·4.9 완료는 유지하며 실제 RunPod endpoint의 제품 전체 trace 전이므로 6.3과 일정·간트는 유지한다. | R4 제품 연결 code 완료·R1 live trace 대기 |
| 2026-08-04 02:43 | 3.14, 4.9, 6.3 | R3 Base serving과 최종 dev CI PASS 뒤 실제 endpoint를 FastAPI Control Plane이 소비하는 R4-W3-F1을 발행했다. 기존 ContractModelAdapter와 ProductionModelClient를 재사용하고 명시적 openai mode, 고정 request 옵션, schema 선검증, timeout·HTTP·잘못된 JSON·circuit·fallback의 안전 실패를 완료 조건으로 두었다. 실제 RunPod 재기동과 제품 전체 trace 전이므로 3.14·4.9의 완료 상태와 6.3·일정·간트는 유지한다. | R4 실제 endpoint transport 승인·외부 실행 제외 |
| 2026-08-04 02:37 | 3.13~3.15, 6.3 | 고정 Qwen3-4B Base revision으로 vLLM endpoint를 기동해 initial readiness 101.623초, warm p50 724.472ms·p95 725.808ms, peak 39,280 MiB, 동시 2건과 동일 revision 재시작을 확인했다. 기존 model client의 정상·timeout·fallback·circuit 검사를 포함한 AI 45건과 artifact hash, task Pod 삭제 404·활성 0개를 검수했다. 신규 비용은 약 USD 0.062802, 예상 누적은 USD 1.015075로 한도 USD 15 이하다. 3.13~3.15를 완료로 전환하되 FastAPI 제품 연결과 I3 전체 trace가 남아 6.3과 일정·간트는 유지한다. | Base serving·client·trace 완료·I3 제품 연결 대기 |
| 2026-08-04 02:11 | 3.13~3.15, 6.3 | Base·LoRA 비교 뒤 남은 실제 serving 증거를 위해 R3-W3-F5를 발행했다. 고정 Qwen3-4B Base revision의 vLLM endpoint, cold·warm p50/p95, 최대 VRAM·동시 2건·재시작과 기존 model client의 timeout·fallback·circuit trace를 완료 조건으로 두었다. 이전 USD 0.9523을 포함한 누적 비용은 USD 15 이하로 제한하고 결과 회수 뒤 task Pod 삭제를 요구했다. 실제 실행 전이므로 상태·일정·간트는 유지한다. | Base serving 실측 승인·제품 연결 미승인 |
| 2026-08-04 01:49 | 3.10, 3.12, 3.13, 3.15, 6.3 | 같은 Qwen3-4B·held-out·decoding 조건에서 Base와 BF16 LoRA를 비교했다. LoRA는 Gold JSON 구조 120/120·SQL 정확 일치 85/120·실제 Trino 결과 일치 116/120을 기록했고 held-out 전체 G2·Trino 실행은 150/150 PASS였다. Gold p95는 Base 15.42초에서 LoRA 43.84초로 증가하고 peak VRAM은 8,511,364,096 bytes여서 3.10·3.12만 완료로 전환하고 제품 기본값은 Base로 유지한다. 실측 비용 USD 0.9523, artifact hash와 task Pod 삭제를 확인했으며 실제 serving·운영 trace·I3 전체 상태와 일정은 유지한다. | Base·LoRA 1회 비교 완료·제품 기본값 전환 보류 |
| 2026-08-03 18:49 | 3.10~3.12, 3.15, 6.3 | R3-W3-F3가 기존 Train·Validation 생성을 보존하면서 Gold 120건·Acceptance 30건을 명시적으로 승인·생성했다. split 누수 0건, 로컬 G2·Trino 150건 전수 PASS, compiled validate·AI 42건과 branch/dev CI를 확인해 dev `aede5a5`에 통합했다. 실제 Base model·RunPod 미실행으로 관련 상태·일정은 유지한다. | held-out 150건 준비·검증 완료·dev 통합 |
| 2026-08-03 18:36 | 3.10~3.12, 3.15, 6.3 | 제공된 Qwen compiled 1,350건이 Train·Validation만 포함하고 현재 생성기도 held-out split을 만들 수 없어 실제 Base·LoRA 평가 입력이 없는 것을 확인했다. 기본 생성 동작을 유지하면서 2,000건 원장의 Gold 120건·Acceptance 30건을 명시적으로 승인·생성하고 로컬 G2·Trino로 전수 검증하는 R3-W3-F3를 발행했다. 외부 model·RunPod 작업과 상태·일정은 변경하지 않는다. | held-out 평가 입력 누락 해소 승인·외부 실행 제외 |
| 2026-08-03 18:20 | 3.10, 3.13~3.15, 6.3 | 평가 150건 승인과 R2~R5 Wave 3 통합 뒤 R1이 dev·junhee 동일 SHA·양쪽 CI, 통합 23건과 Context·G1/G2·repair·cache 격리·동시 실행 제한 보안 회귀 29건을 확인했다. 로컬 CUDA와 Qwen3-4B cache가 없고 model download·RunPod 비용은 미승인이므로 실제 Base model·LoRA·serving은 Not Run이며 관련 상태와 일정은 유지한다. | R1-W3 평가·보안 기준선 확인·외부 model 실행 대기 |
| 2026-08-03 18:03 | 3.10~3.12, 3.15, 6.3 | R3-W3-F2의 training source 10개·전용 AI test 3개, 1,350건 validate·재빌드 SHA-256 일치·AI 41건·branch/dev CI를 확인해 dev에 통합했다. 학습 도구 반입은 완료됐지만 setup 계정 SQL 검증과 실제 Base model·RunPod·LoRA·serving 미실행이 남아 해당 작업 상태와 일정은 유지한다. | R3 학습 도구 dev 통합·외부 실행 대기 |
| 2026-08-03 17:55 | 3.10~3.12, 3.15, 6.3 | 원격 R3 결과 `d15977f`가 training package source 10개와 그 동작을 고정하는 전용 AI test 3개를 함께 제출했음을 확인했다. R3-W3-F2의 허용 경로를 해당 test 3개로만 좁게 확장하고, 나머지 역할 경계와 dependency·model download·RunPod·비용·학습 실행 금지는 유지했다. 상태와 일정은 변경하지 않는다. | R3 학습 도구 전용 test 범위 정합화 |
| 2026-08-03 17:46 | 3.10~3.12, 3.15, 6.3 | 사용자 제공 `training.zip`의 19개 entry를 검사해 경로 탈출 0건을 확인하고 source·README·example·requirements 10개만 `src/ai/training`에 반입하는 R3-W3-F2를 발행했다. compiled cache 8개는 제외하고 1,350건 validate·검증 원본 재빌드 SHA-256 일치·기존 AI 회귀를 완료 조건으로 고정했다. 이 카드는 코드 반입만 승인하며 dependency 설치·model download·RunPod·비용·학습 실행은 승인하지 않아 Base model·LoRA·I3 관련 상태와 일정은 유지한다. | R3 학습 도구 반입 승인·외부 실행 제외 |
| 2026-08-03 17:42 | 1.7, 2.19, 3.11, 6.1, 6.3 | R2-W3-F2의 평가 150건 reviewer/status 동기화, 상태 제외 SHA-256 일치, data 21건·AI 32건과 branch/dev CI PASS를 확인해 평가 fixture·manifest 검수·평가 원장 관리를 완료로 전환했다. R5-W3-F1C의 실제 `MERGED_DEV` 상태와 어긋난 Gate 회귀 테스트 기대값도 교정했다. 저장소 밖 sLLM 데이터의 1,200/150 split·Trino PASS는 참고 근거로만 기록하고, `src/ai/training` 부재·setup 계정 검증·RunPod 미착수 때문에 실제 Base model·LoRA가 필요한 6.3은 진행으로 유지했다. | 평가 150건 최종 승인·Gate 회귀 교정·I3 model 비교 대기 |
| 2026-08-03 17:28 | 2.19, 3.11, 6.1, 6.3 | 평가 150건의 전수 질문·범주·기대 결과와 중복·split·필수 필드·data/AI/integration 검증을 대조해 R1·R3 검토를 승인했다. 질문·정답·근거는 보존하고 reviewer/status만 동기화하는 R2-W3-F2를 발행했으며 실제 Base model 비교 전까지 3.11·6.3의 진행 상태와 일정은 유지한다. | 평가 reviewer 승인·상태 동기화 후속 |
| 2026-08-03 17:21 | 2.19, 3.11, 6.1, 6.3 | 실제 구현·handoff·CI·dev 병합이 완료된 R2-W3-F1과 R3-W3-F1C의 Gate 요약 상태만 `MERGED_DEV`로 정합화했다. 평가 데이터 행의 완료와 I3 통합 행의 진행 상태·일정은 변경하지 않는다. | Wave 3 후속 상태 원장 정합화 |
| 2026-08-03 17:15 | 5.15, 6.3 | R5-W3-F1C에서 Catalog 계약 상수를 실제 I3 계약과 일치시키고 minji CI `30796547226`의 production build·frontend contract·Python·문서·역할 범위 통과를 확인해 dev `4825c0c`에 통합했다. 5.15의 기존 완료 상태와 6.3의 진행 일정은 유지한다. | R5 계약 소비 호환 완료·dev 통합 |
| 2026-08-03 17:05 | 5.15, 6.3 | `origin/dev`의 minji 기획서 재구성 병합 뒤에도 frontend I3 계약 상수 불일치가 동일하게 재현돼 R5-W3-F1C 기준을 `3d6bed7`로 갱신했다. 허용 경로·제품 동작·일정은 변경하지 않는다. | R5 계약 호환 기준 SHA 재발행 |
| 2026-08-03 16:57 | 5.15, 6.3 | R2-W3-F1 통합 뒤 frontend contract test가 실제 I3 data contract `v1.1.0-DRAFT`와 R5 Catalog fixture의 이전 상수 `v1.0.0` 불일치로 실패해 R5-W3-F1C를 발행했다. 상수 한 곳과 소비자 회귀만 보완하고 R2 계약·Catalog 내용·UI·일정은 변경하지 않는다. | R5 계약 버전 소비 호환 승인 |
| 2026-08-03 16:04 | 2.19, 3.11, 6.1, 6.3 | R2-W3-F1의 gold120 확장과 충돌하는 R3 consumer test 하드코딩을 확인해 R3-W3-F1C를 선행 발행했다. partial 5건과 full 120건을 같은 선언 count 계약으로 소비하도록 test만 보완하고 model runtime·Node·일정·외부 권한은 변경하지 않는다. | R3 평가 소비 호환 승인 |
| 2026-08-03 15:56 | 2.19, 3.9~3.11, 6.1, 6.3 | dev `e780b75`·CI `30791740474` PASS를 기준으로 R2-W3-F1을 발행했다. required30 성공 case를 실제 SQL·result hash에 연결하고 gold120을 범주별 120건으로 완성한 뒤 R3가 동일 manifest를 실제 Node chain으로 소비하도록 순서를 고정했다. 외부 model·비용·secret 미승인과 기존 일정은 유지했다. | I3 평가 fixture 후속 승인 |
| 2026-08-03 15:42 | 4.15, 4.19, 5.5, 5.10~5.11, 5.15, 6.3~6.4 | R4-W3의 권한별 SQL Plan·Result Cache, model call budget, 동시 2건·HTTP 429·Audit trace와 R5-W3의 전체 오류 UI, Artifact→Report, immutable Report proposal, 5원천 Catalog를 branch/dev CI로 확인해 dev에 통합했다. 해당 역할 행은 완료로 전환하되 R4-16 실제 Report 등록·worker·browser 접근성과 외부 Base model·Gold 잔여 근거가 남아 I3·I4 통합 행과 일정·간트 날짜는 유지했다. | Wave 3 R4·R5 통합·후속 분리 |
| 2026-08-03 13:54 | 2.18~2.19, 3.5~3.6, 3.10~3.11, 3.13~3.15, 4.15, 4.19, 5.10~5.11, 5.15, 6.3 | I2 통합 dev `744592a`·CI `30785580556` PASS를 기준으로 R1~R5 Wave 3 실행 묶음을 READY 발행했다. 5-source·평가 fixture, Node·Base 비교·serving client, Cache·권한, Report proposal·Catalog와 I3 통합 판정 행을 진행으로 전환했다. model download·RunPod·비용·secret·외부 배포·데이터 전송은 승인하지 않았고 일정·간트 날짜는 변경하지 않았다. | Wave 3 실행 승인 |
| 2026-08-03 13:30 | 4.21, 5.4~5.8, 6.2 | R4 production image의 blank·기존 DB startup과 실제 Template→Trino runtime, R5 제품 `dae606f`·최종 `ab1d725`의 production HTTP client 및 성공·재질문·차단·source 실패 browser trace, branch CI `30782796303`, dev `56cbf08`·CI `30784368551`, R1 통합 22건 PASS를 확인했다. R4-20, R5-03·05~07과 I2 판정을 완료로 전환하되 W3까지 이어지는 R5-04와 필수 30·Gold 120 관리는 진행으로 유지했다. 일정·간트 날짜는 변경하지 않았다. | I2 실제 전체 왕복 완료 |
| 2026-08-03 12:28 | 1.6~1.7, 4.4, 4.20~4.21, 5.1, 5.4~5.8, 6.2 | R4-W2-F3 최종 `51947de`의 기존 migration 무변경, built image blank·기존 DB normal entrypoint, head `20260731_03`, health·전체 readiness·실제 Trino·cleanup, branch CI `30781472877` PASS를 확인해 dev `158a493`에 통합했다. Production image blocker를 해제하고 보존된 frontend diff로 실제 화면 검증을 재개하는 `R5-W2-F2-RESUME@158a493`을 승인했다. 화면 결과 전 일정·행 상태·간트는 유지했다. | R4 image startup 통합·R5 화면 재개 |
| 2026-08-03 12:06 | 1.6~1.7, 4.4, 4.20~4.21, 5.1, 5.4~5.8, 6.2 | R5 실제 browser trace 준비에서 accepted backend image의 normal entrypoint가 빈 DB의 immutable `20260730_02` repository-relative DDL 경로에서 종료되는 것을 확인했다. bind mount·migration bypass는 수용하지 않고 R5-W2-F2를 일시 정지했으며, 기존 migration을 보존한 Dockerfile layout·blank DB startup·readiness만 보완하는 `R4-W2-F3@cee1ca2`를 승인했다. 실제 결과 전 일정·행 상태·간트는 유지했다. | production image startup blocker·R4 최소 보완 |
| 2026-08-03 11:44 | 1.4, 1.7, 4.4~4.5, 4.8, 4.12, 4.16, 4.21, 5.1, 5.4~5.8, 6.2 | R4-W2-F2 최종 `80c30ec`의 기존 migration 불변성, 빈·기존 DB upgrade, `hotel_analyst` 전용 Template, 실제 Trino PARTIAL·query_id·Artifact, exact CORS와 branch CI `30779910256` PASS를 확인해 dev `b1e33c6`에 통합했다. 실제 backend runtime은 3/4를 통과했고 production 화면 연결 `R5-W2-F2@b1e33c6`을 승인했다. 화면 결과 전 일정·행 상태·간트는 유지했다. | R4 runtime 통합·R5 실제 화면 승인 |
| 2026-08-03 10:50 | 1.7 | R1 정책 commit의 역할 범위 검사에서 새 root Docker 제외 파일과 공통 접근 정책 파일이 기존 R1-W2 허용 목록에 빠진 것을 확인했다. 두 R1 소유 경로만 원장에 추가하고 다른 역할 서비스·공식 제출본 범위는 확장하지 않았으며, 통합 테스트와 역할 범위 검사를 다시 실행하도록 정합화했다. 일정·행 상태·간트는 유지했다. | R1 역할 범위 원장 교정 |
| 2026-08-03 10:41 | 1.4, 1.6~1.7, 4.4~4.5, 4.8, 4.12, 4.16, 4.21, 6.2 | R4-W2-F2 제출의 branch CI는 통과했지만 기존 Alembic revision 수정으로 기존 DB upgrade가 누락되고, Template 역할·권한 검사와 실제 Trino PARTIAL 처리, real mode HTTP 증거가 수용 기준을 충족하지 못해 dev 병합을 보류했다. R1은 `ACCESS-POLICY-v1.0.0`과 root Docker build-context secret 제외 기준을 고정하고, 기존 revision 원복·새 후속 migration·권한 거부·PARTIAL·실제 HTTP 회귀만 재작업 승인했다. 실제 결과 전 일정·행 상태·간트는 유지했다. | R4 runtime 제출 거부·최소 재작업 승인 |
| 2026-07-31 17:28 | 1.7, 4.4, 4.7, 4.11, 4.20, 5.4, 6.2 | R5-W2-F1 제품 `f356f1a`·handoff `dce723b`의 API `retryable` 표시, Artifact 미생성, partial 보존, build·contract·integration·role gate와 branch CI run `30612008099`를 확인해 `6bd191c`로 dev에 통합하고 dev CI run `30614284494`를 확인했다. 이어 R1 증거 Gate 보강 `0e756e7`의 dev CI run `30616159454` PASS를 기준으로 실제 DB Template·Trino port·migration startup·HTTP trace·정확한 CORS 연결 범위 `R4-W2-F2@0e756e7`을 READY로 발행했다. 실제 runtime 결과 전 기존 일정·행 상태는 유지했다. | R5 follow-up 통합·R4 runtime 보완 승인 |
| 2026-07-31 17:19 | 1.1, 1.7 | 확장자만 XLSX이고 실제 바이트가 PNG였던 공식 WBS 제출본을 마지막 정상 workbook에서 복구하고, 현재 Markdown 기준 99개 작업의 제목·담당·기간·상태·완료율을 template 서식과 기간 수식을 보존해 다시 동기화했다. 재열기·99개 ID·수식·완료율·전체 시트 렌더를 검증했다. | 공식 WBS XLSX 복구·동기화 |
| 2026-07-31 17:11 | 1.7 | 실행 묶음의 수용·검증 ID 전수 대조에서 ID 없는 추가 결과와 자동 생성 placeholder 증거를 거부하고, 제출된 `REVIEW_REQUIRED`가 CI Summary와 최종 quality 판정에서도 차단되도록 동기화했다. 일정·행 상태는 변경하지 않았다. | R1 증거 Gate 우회 차단 |
| 2026-07-31 17:03 | 1.7, 4.4, 4.7, 4.11, 4.20, 5.1, 5.4~5.8, 6.2 | 독립 정적 runtime 검토에서 backend의 빈 Template registry·fake data adapter와 frontend mock client를 확인해 기존 component·fixture 검증과 실제 통합 승인을 분리했다. 새 실행 묶음은 필수 수용·검증 ID를 handoff 증거와 전수 대조하도록 R1 Gate를 보강하고, R4 실제 Template·Trino·migration·정확한 CORS 연결 뒤 R5 실제 HTTP 연결과 R1 E2E를 수행하는 순차 follow-up을 계획했다. 일정·행 상태는 진행으로 유지했다. | I2 통합 재검증·증거 Gate 보강 |
| 2026-07-31 15:38 | 5.4~5.8, 6.2 | R5-W2 제품 `58aa706`·handoff `d1f6a74`의 재질문 구분, R4 fixture 계약, build·role gate·branch CI run `30609754303`과 독립 browser 증거를 확인해 제품 `555ea14`·팀 보고 `79ba385`로 dev에 통합하고 dev CI run `30610065590` PASS를 확인했다. I2 성공·재질문·차단은 승인했으나 source 실패 화면이 API `retryable`을 표시하지 않아 6.2와 5.4~5.8의 진행 상태를 유지하고 기준 `79ba385`의 최소 R5 follow-up을 발행했다. | R5-W2 통합·I2 3/4 판정 |
| 2026-07-31 15:21 | 4.5~4.14, 4.16, 6.2 | R4-W2-F1의 model 계약 오류·timeout, query timeout·cancel 종료, G2 hard LIMIT, G3 결과 범위·정상/의심 0건 검증을 최신 dev 기준 role gate·handoff와 branch CI run `30609007535`로 확인했다. 제품을 `f8e4740`으로 통합하고 pipeline 15건·integration 16건·compileall·보고 validator와 팀 보고 `4db0503`, dev CI run `30609351155` 전체 PASS를 확인했으며 기존 완료 상태와 일정은 유지했다. | R4 안전성 보강 통합 |
| 2026-07-31 14:55 | 5.4~5.8, 6.2 | R5-W2 제품 `9a4d4e9`·handoff `b7f26f9`의 build·contract·integration·role gate·branch CI는 통과했지만, R4 `CONTEXT_INCOMPLETE`를 정책 차단과 구분하는 재질문 화면·contract/browser 증거가 없어 dev 병합을 보류했다. 실제 착수한 5개 카드를 진행으로 전환하고 새 기준 `6b37f57`의 REWORK를 발행했으며 일정 날짜는 유지했다. | R5-W2 재질문 상태 보완 |
| 2026-07-31 14:34 | 1.7, 4.5~4.14, 4.16 | R4-W2의 MERGED_DEV 전환 뒤 junhee CI run `30607094428`에서 실행 묶음 선택 테스트가 과거 `READY`를 고정 기대해 1건 실패한 것을 확인했다. 현재 원장 상태 `MERGED_DEV`를 기대하도록 R1 통합 테스트 한 줄을 교정했으며 R4 제품·계약과 WBS 일정·상태는 유지했다. | R4 상태 회귀 테스트 교정 |
| 2026-07-31 14:30 | 4.5~4.14, 4.16, 6.2 | R4-W2 제품 `cd9e9c6`·handoff `2924d0b`의 Context→G1→model→G2→repair 1회→query→G3→Artifact 흐름과 네 결과 trace, branch CI run `30606533152` PASS를 확인해 `e34442d`로 dev에 통합했다. pipeline 8건·integration 16건과 dev CI run `30606915908` PASS를 근거로 완료 카드를 완료로 전환하고 R1 평가 원장에 trace 근거를 연결했다. | R4-W2 dev 통합 |
| 2026-07-31 14:20 | 1.1, 1.7 | 기획서 v1.2와 동기화한 공식 WBS XLSX 단일 경로가 R1-W2 허용 범위에서 누락돼 junhee CI run `30606452633`의 role-scope만 실패한 것을 확인했다. 사용자 요청 범위인 해당 XLSX 경로만 Gate 원장에 승인하고 다른 deliverable은 계속 금지했으며 문서·Python·Compose PASS 결과는 유지했다. | 공식 WBS 경로 승인 |
| 2026-07-31 14:12 | 1.1~1.2, 3.10, 7.1~7.7 | 기획서 v1.2를 우선 기준으로 다시 대조해 10주 참조 모델과 5.4주 확정 실행 기간을 분리하고, 압축을 기간 중첩이 아닌 범위 축소로 명시했다. 실제 5인 역할·React/Vite 실측·미도입 frontend 후보·결정론적 역할 분리 Node·Git/CI 운영 경계를 유지했으며, 공식 WBS XLSX를 현행 99개 작업으로 교정하는 근거를 연결했다. | 기획서 v1.2·공식 WBS 동기화 |
| 2026-07-31 14:05 | 2.10~2.17, 6.2 | R2-W2 제품 `75f148b`·handoff `de0a26f`의 PMS/CRM metadata·adapter·승인 JOIN·GOLD hash·query lifecycle, data 14건·통합 16건·branch CI run `30605617536` PASS를 확인해 `5afb90b`으로 dev에 통합하고 dev CI run `30605760842` PASS를 확인했다. R2-W2는 완료했지만 WBS 행은 후속 5-source·3-source 확장이 남아 진행으로 전환하고 R1 평가 원장에 data 근거를 연결했다. | R2-W2 dev 통합 |
| 2026-07-31 13:58 | 3.7, 3.9, 6.2 | R3-W2 제품 `345a788`·handoff `f4f2563`의 G3 pass 전용 Node 3, deterministic 평가 runner, 허용 경로, AI 20건·통합 14건·branch CI run `30605387557` PASS를 확인해 `f2817a0`으로 dev에 통합하고 dev CI run `30605486384` PASS를 확인했다. R3-06·08을 완료로 전환하고 R1 평가 원장에 runner 도착 근거를 연결했으며 일정·간트 날짜는 유지했다. | R3-W2 dev 통합 |
| 2026-07-31 13:49 | 6.2 | 승인된 R1-W2를 시작하고 평가 원장 v0.2에 I2 성공·재질문·차단·source 실패 수용 슬롯과 역할별 필수 trace 근거를 고정했다. R2~R5 Wave 2 제품·handoff가 아직 없어 질문·SQL·hash·runner 출력은 만들지 않고 생산자 입력 대기를 유지했으며 일정·간트 날짜는 변경하지 않았다. | R1-W2 수용 기준 준비 |
| 2026-07-31 13:36 | 1.4~1.8, 3.1~3.4, 3.8, 4.1~4.4, 5.1~5.3, 5.9 | R3 제품 `4c8eedf`·handoff `cb10eca`와 R4 제품 `2fa5b49`·handoff `825a0c2`의 최종 version·범위·회귀·branch CI를 확인해 각각 `14259c8`·`04e5e6d`로 dev에 통합했다. data 8건·AI 15건·integration 16건·frontend build/contract·dev/full/split-host Compose·service fragment와 dev CI run `30604495881` PASS를 근거로 I0 `I0-v1.0.0`, common I1 `I1-v1.0.0`을 동결하고 R1-W1을 `VERIFIED_GATE`로 승인했다. Wave 1에서 완료 증거가 확정된 R1·R3·R4·R5 작업 상태를 완료로 갱신하고 기준 `04e5e6d`의 전 역할 Wave 2를 READY로 발행했다. 일정·간트 날짜는 유지했다. | I1 VERIFIED_GATE·Wave 2 승인 |
| 2026-07-31 13:14 | 1.4, 1.7, 2.1 | R2 제품 `7051f91`·handoff `510981b`의 data actual version `I1-v1.0.0`, 허용 범위, data·integration 회귀와 branch CI run `30603374739` PASS를 확인해 `7e5e16c`로 dev에 통합하고 dev CI run `30603556566` PASS를 확인했다. R2-W1-F4는 MERGED_DEV·WAIT로 전환하고 R1-03 blocker를 R3·R4로 축소했으며 기존 일정·간트와 Wave 2 PLANNED 상태는 유지했다. | R2 I1 최종 version 통합 |
| 2026-07-31 13:01 | 1.4, 1.7, 2.1 | R1의 data/model version 전환 테스트와 최신 R4 bundle 선택 보완을 `f3038c9`로 dev에 통합하고 GitHub Actions run `30603031072` PASS를 확인했다. 보관된 R2 변경을 새 기준에서 재검증하도록 `R2-W1-F4@f3038c9`를 재발행했으며 다른 역할 범위와 Wave 2는 변경하지 않았다. 기존 WBS 상태·일정·간트는 유지했다. | R2 finalization 재승인 |
| 2026-07-31 12:59 | 1.4, 1.7, 2.1, 3.2, 4.2 | R2-W1-F4의 data 8건은 통과했지만 R1 통합 테스트가 과거 DRAFT data version을 단일 기대해 중단된 것을 확인했다. R2 변경은 commit·push 없이 보관하고, R1 소유 통합 테스트가 승인된 data·model 최종 version의 전환 기간을 검증하도록 최소 수정했으며 새 R4-W1-F4 선택 기대도 원장과 정합화해 통합 14건을 통과했다. 새 dev 기준 SHA와 token 발행 전 기존 WBS 상태·일정·간트는 변경하지 않았다. | I1 version 전환 테스트 보완 |
| 2026-07-31 12:46 | 1.4, 1.7, 2.1, 3.1~3.3, 3.8, 4.2, 5.2, 5.9 | R5 제품 `c600f65`·handoff `3f143af`의 허용 경로·version·clean install·build·contract·role gate와 branch CI run `30602136889` PASS를 확인해 `5a52c8f`로 dev에 통합하고 dev CI run `30602295894` PASS를 확인했다. I1 최종 동결 전 실제 DRAFT를 재점검해 R2 data actual version, R3 model I/O·prompt·fixture version, R4 README OpenAPI 표기만 승격하는 `R2-W1-F4`·`R3-W1-F1`·`R4-W1-F4`를 READY로 발행했으며 Wave 2는 보류했다. 기존 WBS 상태·일정·간트는 변경하지 않았다. | R5 최종 version 통합·I1 승격 승인 |
| 2026-07-31 12:25 | 1.4, 1.7, 5.2 | 최신 `origin/dev` `b81f8e1`과 GitHub Actions run `30601436187` PASS를 확인해 남은 I1 차단 항목인 `R5-W1-F2`의 기준 SHA와 실행 token을 갱신하고 기존 허용 경로의 commit·minji push 승인을 유지했다. R2·R3·R4는 추가 작업 없이 대기하고 Wave 2는 I1 `VERIFIED_GATE` 전까지 `PLANNED`를 유지한다. 기존 WBS 상태·일정·간트는 변경하지 않았다. | R5 I1 동결 승인 갱신 |
| 2026-07-31 12:21 | 1.7, 3.1 | 사용자가 R3 최신 기획 문서를 dev에 병합하고 충돌 시 R3 작성물을 우선하도록 지시해 기존 cleanup 방침을 종료했다. origin/daesung `733307c`의 요약본과 공식 03 DOCX를 `a0ac7ed`로 dev에 통합하고 문서 정책·DOCX ZIP/구조·diff를 통과했으며, LibreOffice 부재로 PNG render는 Not Run으로 기록했다. 기존 상태·일정·간트는 변경하지 않았다. | R3 최신 기획 문서 사용자 override 통합 |
| 2026-07-31 12:14 | 1.7, 3.1 | R3가 복구 지시를 읽은 뒤 제출한 `733307c`에서 요약본 추가와 공식 `03_프로젝트기획서` DOCX 수정이 고유 diff로 남고 CI run `30600969172`가 실패한 것을 확인했다. `R3-W1-CLEAN`의 허용 경로를 현재 두 파일로 교정해 `origin/dev` 상태 복구 commit·push만 재허가했으며 기존 상태·일정·간트는 변경하지 않았다. | R3 branch 복구 범위 교정 |
| 2026-07-31 12:01 | 1.7, 3.1 | R3 `d044fb7`이 terminal 역할 허용 범위 밖 기획 요약 Markdown과 공식 DOCX를 추가해 CI가 실패한 것을 확인하고 dev 병합을 거부했다. 해당 두 파일만 `origin/dev` 상태로 복구하는 `R3-W1-CLEAN`을 READY·REWORK로 발행했으며 기능·Wave 2·다른 경로 변경은 허가하지 않았다. 기존 WBS 상태·일정·간트는 변경하지 않았다. | R3 branch 복구 발행 |
| 2026-07-31 11:55 | 1.4, 1.7, 2.10 | R2 제품 `23059a6`·handoff `b8ec6b9`의 허용 경로·manifest·data 8건·소비자 계약·CI run `30599951597` PASS를 확인해 `47c1f94`로 dev에 통합했다. `actual_checkout_at`, 승인 JOIN `pms_stay_to_crm_membership_grade_event_time_v1`, data candidate `I1-v1.0.0`을 I1 입력으로 승인했으며 R5 제출 전까지 기존 상태·일정·간트는 변경하지 않았다. R3 `d044fb7`은 terminal 허용 범위 밖 문서 추가와 CI failure로 병합하지 않았다. | R2 metric·JOIN 동결·dev 통합 |
| 2026-07-31 11:44 | 1.4, 1.7, 4.2 | R4 제품 `c83809a`와 handoff `9da78aa`의 허용 경로·manifest·backend 55건·GitHub Actions run `30599636125` PASS를 확인해 dev에 통합했다. R1 통합 test를 `OPENAPI-v1.0.0` 단일 version으로 고정하고 R4-W1-F3을 MERGED_DEV로 전환했으며, R2 metric·JOIN과 R5 UI·Report version 제출 전까지 기존 상태·일정·간트는 변경하지 않았다. | R4 OpenAPI 동결·dev 통합 |
| 2026-07-31 11:30 | 1.4, 1.7, 4.2 | R4 제품 결과 `c83809a`의 역할 범위와 전체 52건 중 51건 통과를 확인했다. 남은 1건은 R1 공통 계약이 기존 OpenAPI 초안 version만 기대한 전환 오류로 판정해 원장·통합 test에 `OPENAPI-v1.0.0` 후보를 추가하고, R4에는 제품 변경 없이 최신 dev와 handoff manifest만 재제출하도록 허가했다. R4 dev 통합 전까지 기존 상태·일정·간트는 변경하지 않았다. | R4 OpenAPI 전환 계약 보완 |
| 2026-07-31 11:24 | 1.4, 1.7, 4.2, 5.2 | R1 변경 `4f08263`을 `dev`에 통합하고 CI run `30598777511` PASS를 확인했다. 경로 정합성 제안의 안전한 항목을 승인해 R4 기본 경로를 실제 backend로 교정하고 활성 frontend·기획서·요구사항·화면설계서 소유권을 고정했으며, `app/react/**` 삭제는 별도 결정으로 보류했다. R2·R4·R5 후속 제출 전까지 기존 WBS 상태·일정·간트는 변경하지 않았다. | R1 경로·소유권 정합화 |
| 2026-07-31 11:05 | 1.4, 1.7, 2.10, 4.2 | `origin/dev` `e5eea60`과 CI run `30598022457` PASS를 확인하고 결과 전달 파일만 뒤따르는 commit을 허용하도록 R1 자동 검사를 수정했다. R2 제품 결과 `23059a6`은 전달 manifest 재제출만 허가하고, R4 복구 결과 `14bedf8`은 dev 대비 고유 diff 0건으로 수용해 OpenAPI version 동결 작업을 재발행했다. R2 통합과 R4·R5 version 동결 전까지 기존 WBS 행 상태·일정·간트는 변경하지 않았다. | R1 Gate 보완·R4 재발행 |
| 2026-07-31 10:25 | 1.4, 2.10, 4.2, 5.2 | 최신 `origin/dev` `e2ecee3`과 CI run `30596060168` PASS를 기준으로 R2 데이터 계약과 R5 화면·보고서 version 동결의 commit·개인 branch push를 승인했다. R4는 개인 branch의 허용 범위 밖 제출본 변경을 `origin/dev` 상태로 복구하는 작업만 승인하고 backend 동결은 보류했으며 R3와 Wave 2는 대기를 유지했다. 기존 WBS 행 상태·일정·간트는 변경하지 않았다. | I1 역할별 실행 허가 |
| 2026-07-31 10:12 | 1.4, 2.10, 4.2, 5.2 | `origin/dev` `68fc068`과 GitHub Actions run `30528089815` PASS를 확인해 원격 동기화 차단을 해제했다. I1 입력을 실제 schema와 대조해 기획 예시의 존재하지 않는 PMS 수익 필드와 PMS↔CRM event-time 승인 JOIN 미등록, OpenAPI·UI·Report의 `DRAFT` version을 남은 차단 원인으로 확정했다. R2·R4·R5에 version 동결만 수행하는 follow-up을 발행했으며 기존 상태·일정·간트는 유지했다. | I1 동결 보완 발행 |
| 2026-07-30 17:09 | 1.4~1.7, 2.10 | R2 DataHub consumer `731399d`를 dev에 통합하고 공식 source revision·blob, root dev 3개와 full·split-host 16개 service의 정적 구성을 검증했다. R1이 profile 소유 위치·env·seung Compose CI·한글 경로·공용 보고 예외를 보완했으며 실제 DataHub container 기동과 대표 질문·metric·최종 계약 version 동결 전까지 기존 진행·차단 상태와 일정은 유지했다. | R2 DataHub 통합·R1 Gate 보완 |
| 2026-07-30 15:47 | 1.4~1.7, 2.10, 4.21, 5.2, 5.19 | R4·R5 handoff를 dev에 통합하고 root Compose가 dev 3개 service와 full·split-host 9개 service를 정적으로 소비하도록 구성했으며 root `.env.example`과 Compose CI를 추가했다. DataHub Core consumer fragment·immutable version·official source가 없어 1.5~1.6은 진행, R1-03은 차단을 유지하고 R2-W1-F2를 READY로 발행했다. | R1 통합 profile 진행·R2 보완 발행 |
| 2026-07-30 14:57 | 1.7 | 기존 읽기 전용 CI에 실행 카드 원장의 최신 비-PLANNED `ALLOWED_PATHS`를 사용하는 role scope 검사를 추가하고, terminal 역할의 신규 구현 차단·개인 일일보고 허용·R5 npm ci/build/contract job을 구성했다. 자동 상태 변경·commit·push·merge는 제외했으며 전체 tests 29건을 통과했다. | R1 역할 Gate 자동화 1단계 |
| 2026-07-30 14:52 | 1.4, 4.21, 5.2, 5.19 | R2~R5 원격 작업을 확인해 R4 cleanup 전용 R4-W1-F2를 READY로 발행하고, R5 clean handoff `ba5617b`의 허용 경로·고정 lockfile·npm ci·production build·contract·container health·OpenAPI version을 독립 검증했다. R4·R5 dev 통합과 combined profile 검증 전 상태·일정·간트는 유지했다. | R4 READY·R5 재검토 |
| 2026-07-30 14:39 | 1.4, 2.10 | R2 handoff `055b265`의 지정 3개 파일을 dev에 통합하고 `R2_SERVICE_FRAGMENT_VERIFIED`와 전체 tests 26건을 통과해 R2-W1-F1을 MERGED_DEV로 전환했다. R4·R5 보완과 combined root Compose 검증 전 R1-03 차단·R2-W2 PLANNED 및 일정·간트는 유지했다. | R2 I1 fragment 통합 |
| 2026-07-30 14:16 | 1.4, 2.10, 4.21 | R2 handoff `055b265`의 service fragment·data 7건·Compose config를 검토해 REVIEW로 전환하고, R4 clean handoff `af6cc10`의 허용 경로 정리와 container readiness를 확인했다. R4 cleanup 결함·R2/R4 dev 통합·root Compose 소비자 검증과 R5 보완이 남아 상태·일정·간트는 유지했다. | R2·R4 I1 제출 재검토 |
| 2026-07-30 14:01 | 1.4, 5.2, 5.19 | R5 handoff `140563f`의 typed analysis·Report contract, deterministic mock, 금지 route 차단과 frontend contract test를 R1이 검토해 R5-01을 검토로 전환했다. branch net diff 오염, lockfile·고정 dependency·`npm ci` build·Dockerfile/health fragment·OpenAPI version 보완 전 R1-03 차단과 R5-18 대기를 유지하며 일정·간트 날짜는 변경하지 않았다. | R5 I1 제출 검토 |
| 2026-07-30 13:39 | 1.4, 2.10 | R2-W1-F1 READY 카드 `9925a88`이 최신 `origin/dev=4527375`에 이미 포함된 것을 확인하고 보고된 fragment 3개 파일만 commit·seung push하도록 허가했다. 최신 `origin/seung=cd8fdfc`에는 아직 제출되지 않아 R2-09 진행과 R1-03 차단을 유지하며 일정·간트 날짜는 변경하지 않았다. | R2 제출 허가 |
| 2026-07-30 12:56 | 1.4, 4.21 | `origin/jaehong` handoff `06632fa`의 backend image·non-root·health·OpenAPI와 backend 17건·AI 15건·data 7건·integration 1건을 R1이 독립 검토해 R4-20을 검토로 전환했다. 허용 경로 밖 application DDL 분리·dev 통합·combined database readiness와 R2·R5 follow-up 전 R1-03 차단은 유지하며 일정·간트 날짜는 변경하지 않았다. | R4 I1 제출 검토 |
| 2026-07-30 12:36 | 1.4, 2.10, 4.21, 5.2, 5.19 | R2-W1-F1·R4-W1-F1·R5-W1-F1을 READY로 발행해 역할별 허용 경로·완료 증거·검증·중단 조건을 고정했다. 대표 질문·metric은 승인 전 N/A로 유지하고 follow-up 결과 검증 전 기존 WBS 상태는 변경하지 않았다. | I1 보완 실행 허가 |
| 2026-07-30 12:32 | 1.4 | R3 model serving Dockerfile·실행 manifest는 I1 필수가 아니며 in-process fake adapter로 계약을 검증하고 R3-W3에서 제출하도록 판정했다. R3 service fragment blocker만 해제하고 R2·R4·R5 보완 대기로 R1-03 차단은 유지한다. | I1 blocker 범위 정정 |
| 2026-07-30 12:03 | 1.4 | R2 schema·seed·scenario와 R3 model I/O·prompt·fixture를 I1 입력으로 승인했다. R4·R5는 기존 Wave 1 계약 결함 재작업만 허가하고 clean package·runtime·typed contract·금지 route 차단·build 증거 도착 전 R1-03 차단과 Wave 2 불허를 유지한다. | R1 계약 승인·재작업 허가 |
| 2026-07-30 11:53 | 1.7, 6.1 | R1-03 차단 중 독립 진행 가능한 현재 Python producer·integration·문서 검증 CI baseline과 필수 30·gold 120 평가 원장 schema를 추가했다. 역할별 service build와 실제 평가 case는 handoff 대기로 남긴다. | R1 독립 기반 진행 |
| 2026-07-30 11:35 | 1.4 | 최신 통합 SHA에서 R2 data, R3 model I/O·prompt·fixture, R4 OpenAPI/state/error 계약을 확인했다. R5 typed UI·Report 계약과 P2·고객 360 route 차단 증거, R2~R5 service fragment는 미도착으로 R1-03 차단을 유지한다. | I1 계약 부분 입력·차단 유지 |
| 2026-07-30 10:49 | 1.1~1.2 | 재검토 결과를 반영해 `01_요구사항정의서.md`와 공식 XLSX의 대분류·75개 ID·본문을 v1.1로 양방향 동기화하고 최신 WBS·화면설계 참조와 XLSX 유효 데이터 범위 `A1:G79`·전체 시트 렌더링을 재검증 | 공식 요구사항 산출물 |
| 2026-07-30 10:41 | 2.1~2.9 | R2-W1의 5 source·4 engine·18 entity registry, DDL·seed state manifest, CRM identity·event-time 중첩 차단, DQR/PREP·reject, Trino read-only 정책을 구현하고 정적 7건·live DB 계약 검증을 통과했다. I1 통합 판정은 R1 검토 대기로 유지한다. | R2-W1 생산자 검증 |
| 2026-07-30 10:36 | 1.1~1.4 | `app/enterprise-react`를 활성 frontend로 확정하고 R1-00~02의 기준·범위·소유권 원장을 작성했다. R1-03은 R3 model과 R5 UI·Report contract 미도착으로 차단했다. | I0 결정·I1 계약 대기 |
| 2026-07-30 10:25 | 1.1 | R1~R5 Wave 1 실행 묶음의 기준 SHA를 현재 `dev`의 `2c2779d23738038d5cd0560cffa70c5b509991c3`으로 교정하고 개인 branch 기준 포함 여부를 확인 | 역할·실행 기준 |
| 2026-07-30 09:54 | 1.1~1.2 | 첨부 요구사항 템플릿의 1시트·7열·병합 헤더·그룹 형식을 유지해 요구사항 75개를 `docs/deliverables/01_요구사항정의서_29기_3팀.xlsx` v1.0으로 변환하고 전체 시트 렌더링·ID·값을 검증 | 공식 요구사항 산출물 |
| 2026-07-30 09:49 | 5.2 | 기획 v1.0·요구사항 v1.0·활성 React 목업을 대조해 13개 공식 화면 ID와 IA·route·진입 조건·요구사항 추적·범위 제외 Gate·UI QA를 `05_화면설계서.md` v6.0으로 확정 | 화면설계 산출물 |
| 2026-07-30 09:42 | 1.1~1.2 | 최종 기획 v1.0의 P0/P1/P2 경계와 기능·데이터·AI·보고서·UI·보안·운영·비기능 요구사항 75개를 `01_요구사항정의서.md` v1.0으로 구조화하고 R1 계약 검토 대상으로 등록 | 요구사항 계약 초안 |
| 2026-07-30 09:32 | 1.1~1.4, F-01~F-04 | 기획·WBS·통합 일정·역할 매뉴얼·Gate 절차를 교차 검토해 LoRA 기준선, worker·trace·보안·복구·UI 상태 계약을 교정하고 P2·고객 360을 I5 이후 비차단 후속 단계로 명시 | 문서·절차 계약 |
| 2026-07-29 18:41 | 4.1~4.6 | R4 경계·공통 API/오류 계약, request/trace context, 단일 Alembic skeleton, Fake `/analysis` route와 최소 상태 전이 골격을 추가했다. 실제 DB migration·FastAPI 기동·R2/R3/R5 연동은 미완료로 유지한다. | Control Plane 골격 |
| 2026-07-29 17:24 | 1.1 | 역할별 자율 진행량과 병합 충돌을 균형화해 I1·I2·I3·I4~I5의 4개 통합 Wave로 조정하고 역할별 상세 카드 원장을 보강 | 역할·일정 계약 |
| 2026-07-29 17:07 | 1.1 | 역할별 실행을 단일 카드 승인 방식에서 Gate별 카드 범위 자율 실행·Gate 중단·통합 방식으로 변경하고 AGENTS·역할 매뉴얼·통합 일정·실행 카드 원장과 동기화 | 역할·일정 계약 |
| 2026-07-29 11:15 | 2.4~2.7, 2.9, 2.10, 2.13 | 6개 격리 DB Compose와 18개 source table·Application bootstrap, deterministic manifest, identity·등급 이력, read-only 계정, DataHub recipe 5개·Trino catalog 5개를 구성하고 health·권한·재시작·볼륨 재생성 fingerprint를 실구동 검증 | DB bootstrap·검증 자동화 |
| 2026-07-29 10:48 | 2.4 | `origin/dev`의 `docs/deliverables/05_데이터베이스저장소설계서_29기_3팀.xlsx` 등록·구조 검증 근거를 새 역할 WBS에 통합하고 기존 일정·담당·상태는 유지 | 설계 산출물 |
| 2026-07-29 10:33 | 1.1 | `AGENTS.md`와 `docs/markdown/02_WBS.md`를 기획서·최종 5인 매뉴얼의 역할·카드·Gate·병합·09/03 일정에 동기화하고 미결정 항목을 차단·결정 필요로 분리 | 역할·일정 계약 |
| 2026-07-28 16:11 | 이전 1.5 | 공식 프로젝트명을 Answervice로 동기화 | 기획 계약 |
| 2026-07-28 15:18 | 이전 1.6 | 최종 기획 기반 화면설계서 개편 근거 연결 | 설계 산출물 |
| 2026-07-27 17:44 | 이전 2.8 | 데이터 허브 기반 데이터베이스/저장소 설계 초안 근거 연결 | 설계 산출물 |

> v4.8 이전의 상세 작업 로그는 Git 이력에서 확인한다. v5.0은 기존 VOC·Django 중심 실행 행을 새 DataHub·FastAPI·5인 역할 기준으로 대체했으며 이전 완료 상태를 새 구현 카드의 완료로 승계하지 않았다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v7.69 | 2026-08-04 04:03 | R3 PROMPT-v1.0.2를 dev에 통합하고 raw 응답과 동일 Base·I2 read-only 제품 전체 trace를 위한 R1-W3-F4를 3.14·4.9·6.3에 연결했다. 실행 전 상태·일정·간트는 유지했다. |
| v7.68 | 2026-08-04 03:59 | 실제 Base의 LIMIT 생성과 881줄 개행·completion length 미완성 JSON 병목, 안전 실패·cleanup을 3.14·4.9·6.3에 연결하고 R3 compact SQL prompt 보완을 승인했다. 상태·일정·간트는 유지했다. |
| v7.67 | 2026-08-04 03:48 | R3 PROMPT-v1.0.1을 dev에 통합하고 동일 Base·I2 read-only 제품 전체 trace를 위한 R1-W3-F3를 3.14·4.9·6.3에 연결했다. 실행 전 상태·일정·간트는 유지했다. |
| v7.66 | 2026-08-04 03:42 | 실제 I2 제품 trace의 LIMIT 누락·무효 repair G2 병목과 안전 차단·정확한 cleanup을 3.14·4.9·6.3에 연결하고 R3 prompt 최소 보완을 승인했다. 상태·일정·간트는 유지했다. |
| v7.65 | 2026-08-04 03:27 | R4 guided transport를 dev에 통합하고 실제 I2 synthetic Context·read-only Trino 제품 trace를 위한 R1-W3-F2를 3.14·4.9·6.3에 연결했다. 실행 전 상태·일정·간트는 유지했다. |
| v7.64 | 2026-08-04 03:21 | R1 live product trace의 Base schema 실패와 fake Context 불일치를 확인해 R4 structured output 보완과 실제 I2 synthetic trace로 분리했다. cleanup과 예상 비용을 기록하고 6.3 진행·일정·간트를 유지했다. |
| v7.63 | 2026-08-04 03:01 | 실제 Base endpoint와 FastAPI 제품 경로의 synthetic HTTP trace를 확인하는 R1-W3-F1을 4.9·6.3에 연결했다. 실행 전이라 상태·일정·간트는 유지했다. |
| v7.62 | 2026-08-04 02:58 | R4-W3-F1의 Base endpoint transport와 실패 안전 처리를 dev에 통합했다. 실제 RunPod 제품 전체 trace 전이므로 3.14·4.9 완료와 6.3 진행, 일정·간트를 유지했다. |
| v7.61 | 2026-08-04 02:43 | SERVING-v0.2를 FastAPI Control Plane에 안전하게 연결하는 R4-W3-F1을 3.14·4.9·6.3에 연결했다. 실제 구현·제품 trace 전 기존 상태와 일정·간트는 유지했다. |
| v7.60 | 2026-08-04 02:37 | Qwen3-4B Base vLLM endpoint의 readiness·warm p95·peak VRAM·동시 2건·재시작, model client 실패 trace, artifact hash·비용·Pod 삭제를 확인해 3.13~3.15를 완료로 전환했다. FastAPI 제품 연결과 I3 전체 trace가 남아 6.3과 일정·간트는 유지했다. |
| v7.59 | 2026-08-04 02:11 | Qwen3-4B Base serving endpoint의 cold·warm·VRAM·동시 실행·재시작·model client 실패 trace를 실측하는 R3-W3-F5를 3.13~3.15·6.3에 연결했다. 누적 RunPod 비용 USD 15 한도와 task Pod 삭제를 고정했으며 실제 결과 전 상태·일정·간트는 유지했다. |
| v7.58 | 2026-08-04 01:49 | Qwen3-4B Base·LoRA 1회 비교와 held-out 150건 G2·Trino 검증, Gold 지연시간·VRAM, artifact hash, 실측 비용·Pod 삭제를 확인해 3.10·3.12를 완료로 전환했다. LoRA p95 증가로 제품 기본값은 Base를 유지하며 serving·I3 상태와 일정은 변경하지 않았다. |
| v7.57 | 2026-08-03 18:49 | R3-W3-F3의 held-out Gold 120건·Acceptance 30건 생성, 누수 0건, 로컬 G2·Trino 150건 전수 PASS와 compiled validate·CI를 확인해 dev에 통합했다. 외부 model·RunPod 상태와 일정은 유지했다. |
| v7.56 | 2026-08-03 18:36 | Qwen 학습용 데이터와 생성기의 held-out 입력 누락을 확인해 2,000건 원장의 Gold 120건·Acceptance 30건을 명시적으로 승인·생성하고 로컬 Trino로 검증하는 R3-W3-F3를 3.10~3.12·3.15·6.3에 연결했다. 외부 model·RunPod 상태와 일정은 유지했다. |
| v7.55 | 2026-08-03 18:20 | R1-W3의 평가·보안·통합 근거를 3.10·3.13~3.15·6.3에 연결했다. 실제 Base model·RunPod 실행은 로컬 GPU·model 부재와 외부 비용 미승인으로 Not Run이므로 상태·일정·간트는 유지했다. |
| v7.54 | 2026-08-03 18:03 | R3 학습 도구와 전용 test의 재현성·회귀·branch/dev CI를 확인해 dev에 통합했다. 실제 Base model·RunPod·LoRA·serving 미실행으로 관련 WBS 상태와 일정은 유지했다. |
| v7.53 | 2026-08-03 17:55 | 원격 R3 결과에 포함된 training 전용 AI test 3개를 R3-W3-F2 허용 경로에 한정 추가했다. 제품·외부 실행 범위와 WBS 상태·일정은 변경하지 않았다. |
| v7.52 | 2026-08-03 17:46 | 사용자 제공 training package를 R3 소유 경로에 반입·재현성 검증하는 R3-W3-F2를 발행했다. compiled cache와 외부 JSONL 반입, dependency·model download·RunPod·비용·학습 실행은 제외해 기존 Base model·LoRA·I3 상태와 일정은 유지했다. |
| v7.51 | 2026-08-03 17:42 | 평가 150건의 최종 reviewer/status 승인과 내용 보존·소비자·CI 근거를 확인해 2.19·3.11·6.1을 완료로 전환하고 R5-W3-F1C Gate 상태 회귀 기대값을 교정했다. 외부 sLLM JSONL은 참고 근거로만 연결하고 재생성 코드·읽기 전용 권한·RunPod 학습·Base model 비교가 없어 6.3은 진행으로 유지했다. |
| v7.50 | 2026-08-03 17:28 | 평가 150건의 R1·R3 검토를 승인하고 reviewer/status 동기화를 R2-W3-F2로 분리했다. 실제 Base model 비교가 남아 관련 행의 진행 상태와 일정은 유지했다. |
| v7.49 | 2026-08-03 17:21 | R2-W3-F1·R3-W3-F1C의 실제 dev 통합 결과와 Gate 요약 상태를 정합화했다. WBS 작업 상태와 일정은 변경하지 않았다. |
| v7.48 | 2026-08-03 17:15 | R5 Catalog의 I3 계약 버전 상수를 원본 계약과 일치시키고 CI 전체 통과 후 dev에 통합했다. 5.15 완료와 6.3 진행 상태·일정은 유지했다. |
| v7.47 | 2026-08-03 17:05 | minji 기획서 재구성 병합 뒤 최신 dev `3d6bed7`에서도 재현된 R5 계약 상수 불일치를 기준으로 R5-W3-F1C를 재발행했다. 일정·상태·제품 범위는 변경하지 않았다. |
| v7.46 | 2026-08-03 16:57 | R2 I3 data contract 갱신을 소비하지 못한 R5 Catalog fixture 상수 한 곳을 동기화하는 R5-W3-F1C를 5.15·6.3에 연결했다. 제품 동작·R2 계약·일정은 변경하지 않는다. |
| v7.45 | 2026-08-03 16:04 | R2 gold120 확장을 차단하는 R3 consumer test의 5/35 하드코딩을 제거하는 R3-W3-F1C를 3.11·6.1·6.3에 연결했다. R2 구현은 유지하고 R3 호환 보완을 dev에 선반영한 뒤 재검증하도록 순서를 조정했으며 일정은 변경하지 않았다. |
| v7.44 | 2026-08-03 15:56 | R2-W3-F1을 READY로 발행해 required30 결과 hash 연결과 gold120 완성을 2.19·6.1·6.3에 연결했다. R3 실제 manifest 소비는 R2 통합 후로 순서를 고정했으며 일정과 외부 권한은 변경하지 않았다. |
| v7.43 | 2026-08-03 15:42 | R4-W3·R5-W3 제품·handoff·branch/dev CI를 4.15·4.19·5.5·5.10~5.11·5.15에 연결해 완료로 전환했다. Report 공통 등록·worker·browser 접근성과 외부 Base model·Gold 잔여 근거가 남아 6.3~6.4는 진행·대기로 유지하고 일정·간트 날짜는 변경하지 않았다. |
| v7.42 | 2026-08-03 13:54 | I2 검증 dev·CI를 기준으로 R1~R5 Wave 3를 READY 발행하고 5-source·model·Cache·Report·Catalog·I3 관련 행을 진행으로 전환했다. 외부 비용·model download·secret·배포는 승인하지 않았으며 일정·간트 날짜는 유지했다. |
| v7.41 | 2026-08-03 13:30 | R4 실제 Template·Trino/image와 R5 production HTTP/browser 네 경로, 통합 22건 및 branch/dev CI PASS를 4.21·5.4~5.8·6.2에 연결해 해당 I2 완료분을 완료로 전환했다. W3 범위인 5.5와 필수 30·Gold 120 관리는 진행으로 유지하고 일정·간트 날짜는 변경하지 않았다. |
| v7.40 | 2026-08-03 12:28 | R4-W2-F3 production image의 blank·기존 DB normal entrypoint·전체 readiness·실제 Trino 통합 근거를 1.6~1.7·4.4·4.20~4.21·5.1·5.4~5.8·6.2에 연결하고 R5-W2-F2 화면 검증을 재개했다. 실제 결과 전 일정·행 상태·간트는 유지했다. |
| v7.39 | 2026-08-03 12:06 | Production backend image의 빈 DB entrypoint 경로 결함과 R5 실제 화면 차단 근거를 1.6~1.7·4.4·4.20~4.21·5.1·5.4~5.8·6.2에 연결하고 R4-W2-F3 최소 보완을 승인했다. 실제 결과 전 일정·행 상태·간트는 유지했다. |
| v7.38 | 2026-08-03 11:44 | R4-W2-F2의 migration·역할 정책·실제 Trino·PARTIAL·CORS 결과와 dev 통합 근거를 1.4·1.7·4.4~4.5·4.8·4.12·4.16·4.21·6.2에 연결하고, production 화면 연결을 위한 R5-W2-F2를 승인했다. 화면 결과 전 일정·행 상태·간트는 유지했다. |
| v7.37 | 2026-08-03 10:50 | R1 정책 commit의 역할 범위 검사에서 확인된 `.dockerignore`·`config/access-policy.yaml` 허용 목록 누락을 1.7에 기록하고 두 R1 소유 경로만 교정했다. 일정·행 상태·간트는 유지했다. |
| v7.36 | 2026-08-03 10:41 | R4-W2-F2 제출의 기존 DB migration·Template 역할 권한·Trino PARTIAL·real HTTP 증거 결함으로 dev 병합을 보류하고, R1 정책·Docker build-context 안전 기준과 최소 재작업 승인을 1.4·1.6~1.7·4.4~4.5·4.8·4.12·4.16·4.21·6.2에 연결했다. 실제 결과 전 일정·행 상태·간트는 유지했다. |
| v7.35 | 2026-07-31 17:28 | R5-W2-F1의 제품·handoff·branch/dev CI 통합 근거와 R1 증거 Gate 보강 dev CI PASS를 연결하고, 실제 runtime 연결을 수행할 `R4-W2-F2@0e756e7` 승인 근거를 1.7·4.4·4.7·4.11·4.20·5.4·6.2에 기록했다. 실제 결과 전 일정·행 상태는 유지했다. |
| v7.34 | 2026-07-31 17:19 | PNG로 잘못 저장된 공식 WBS 제출본을 마지막 정상 XLSX에서 복구하고 Markdown 기준 99개 작업을 재동기화했으며, 재열기·ID·기간 수식·완료율·전체 렌더 검증 근거를 1.1·1.7에 연결했다. |
| v7.33 | 2026-07-31 17:11 | 1.7의 handoff 증거 Gate에서 ID 없는 결과와 placeholder 증거를 거부하고, 제출된 `REVIEW_REQUIRED` 차단 정책을 CI 최종 판정까지 동기화한 근거를 추가했다. 일정·행 상태는 유지했다. |
| v7.32 | 2026-07-31 17:03 | 기존 component·fixture 검증과 실제 runtime 통합 승인을 분리해 I2를 재검증 대상으로 기록하고, 필수 수용·검증 ID 전수 대조 Gate와 R4→R5→R1 순차 follow-up 근거를 1.7·4.4·4.7·4.11·4.20·5.1·5.4~5.8·6.2에 연결했다. 기존 일정·행 상태는 유지했다. |
| v7.31 | 2026-07-31 15:38 | R5-W2 재질문·화면·Artifact 결과와 제품·branch/dev CI 통합 근거를 5.4~5.8·6.2에 연결했다. source 실패 화면의 API `retryable` 표시 누락으로 최소 follow-up을 발행하고 기존 진행 상태·일정·공식 XLSX 상태를 유지했다. |
| v7.30 | 2026-07-31 15:21 | R4-W2-F1의 model·query 경계 오류, timeout·cancel, G2 hard LIMIT, G3 결과 범위·0건 구분 보강과 제품·branch/dev CI 통합 근거를 4.5~4.14·4.16·6.2에 연결하고 기존 완료 상태·일정은 유지 |
| v7.29 | 2026-07-31 14:55 | R5-W2 제출의 build·contract·CI는 통과했으나 `CONTEXT_INCOMPLETE` 재질문 화면·증거 누락으로 병합을 보류하고 5.4~5.8을 진행으로 전환했으며 최소 REWORK 근거를 6.2에 연결 |
| v7.28 | 2026-07-31 14:34 | R4-W2 MERGED_DEV 전환에 맞춰 R1 실행 묶음 선택 회귀 테스트의 과거 READY 고정 기대를 교정한 근거를 1.7에 연결 |
| v7.27 | 2026-07-31 14:30 | R4-W2 고정 제어 흐름·네 결과 trace의 제품·handoff·branch/dev CI와 dev 통합 근거를 4.5~4.14·4.16·6.2에 연결하고 완료 카드를 완료로 전환 |
| v7.26 | 2026-07-31 14:20 | 공식 WBS XLSX 단일 경로의 R1-W2 scope 누락으로 발생한 junhee CI role-scope 실패를 기록하고 사용자 요청 범위에 맞춰 해당 경로만 승인 |
| v7.25 | 2026-07-31 14:12 | 기획서 v1.2 우선 대조 결과를 반영해 5.4주 실행 기간과 선행 산출물 구간을 분리하고, 범위 축소 원칙·현재 frontend 실측·결정론적 Node 비교·공식 01~03 제출본 상태를 교정했으며 공식 WBS XLSX 갱신 근거를 연결 |
| v7.24 | 2026-07-31 14:05 | R2-W2 data 계약·GOLD hash·adapter의 제품·handoff·branch/dev CI와 dev 통합 근거를 2.10~2.17·6.2에 연결하고 후속 확장 대상 행을 진행으로 전환 |
| v7.23 | 2026-07-31 13:58 | R3-W2 Node 3·평가 runner의 제품·handoff·branch/dev CI와 dev 통합 근거를 3.7·3.9·6.2에 연결하고 R3-06·08을 완료로 전환 |
| v7.22 | 2026-07-31 13:49 | R1-W2 착수와 I2 수용 슬롯·trace 근거 고정을 6.2에 연결하고 상태를 진행으로 전환했으며 생산자 handoff 전 실제 fixture·trace 생성은 보류 |
| v7.21 | 2026-07-31 13:36 | R3·R4 최종 version 통합과 전체 I1 회귀·dev CI PASS를 근거로 R1-W1을 VERIFIED_GATE로 승인하고 Wave 1 완료 증거가 확정된 R1·R3·R4·R5 행을 완료로 갱신했으며 기준 `04e5e6d`의 전 역할 Wave 2 READY 발행을 연결 |
| v7.20 | 2026-07-31 13:14 | R2 data actual version `I1-v1.0.0`의 제품·handoff·branch/dev CI와 dev 통합 근거를 1.4·1.7·2.1에 연결하고 R1-03 blocker를 R3·R4로 축소했으며 기존 일정·간트와 Wave 2 상태는 유지 |
| v7.19 | 2026-07-31 13:01 | R1 전환 테스트 보완의 dev 통합·CI PASS와 새 기준의 R2-W1-F4 재발행 근거를 1.4·1.7·2.1에 연결했으며 다른 역할과 Wave 2 상태는 유지 |
| v7.18 | 2026-07-31 12:59 | R2 finalization 중 발견한 R1 DRAFT 단일 기대를 전환 허용 통합 테스트로 보완하고 최신 R4 READY 선택 기대를 정합화한 근거를 1.4·1.7·2.1·3.2·4.2에 연결했으며 새 승인 발행 전 기존 상태·일정·간트는 유지 |
| v7.17 | 2026-07-31 12:46 | R5 UI·Report·fixture 최종 version 통합과 branch/dev CI 근거를 연결하고 I1 최종 승격만 수행하는 R2·R3·R4 follow-up 발행을 1.4·1.7·2.1·3.1~3.3·3.8·4.2·5.2·5.9에 기록했으며 기존 상태·일정·간트는 유지 |
| v7.16 | 2026-07-31 12:25 | 최신 dev·CI 기준으로 유일한 실행 가능 follow-up인 R5-W1-F2의 기준 SHA와 token을 갱신하고 R2·R3·R4 대기·Wave 2 PLANNED 판정을 1.4·1.7·5.2에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.15 | 2026-07-31 12:21 | 사용자 override에 따라 R3 최신 요약본·공식 03 DOCX를 R3 우선으로 dev에 통합한 근거와 검증을 1.7·3.1에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.14 | 2026-07-31 12:14 | R3 `733307c`의 최신 고유 diff와 CI failure를 재판정해 복구 허용 경로를 요약본·공식 03 DOCX로 교정한 근거를 1.7·3.1에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.13 | 2026-07-31 12:01 | R3 허용 범위 밖 문서 제출과 CI failure를 확인해 dev 병합을 거부하고 두 파일 복구 전용 `R3-W1-CLEAN` 발행 근거를 1.7·3.1에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.12 | 2026-07-31 11:55 | R2 metric·time field·event-time JOIN·data candidate 결과와 handoff·CI를 검증해 dev에 통합하고 근거를 1.4·1.7·2.10에 연결했으며 R5 제출 전까지 기존 상태·일정·간트는 유지 |
| v7.11 | 2026-07-31 11:44 | R4 OpenAPI 동결 결과·handoff·CI를 검증해 dev에 통합하고 `OPENAPI-v1.0.0` 단일 version 고정 근거를 1.4·1.7·4.2에 연결했으며 R2·R5 제출 전까지 기존 상태·일정·간트는 유지 |
| v7.10 | 2026-07-31 11:30 | R4 OpenAPI 후보의 교차 역할 test 1건 실패를 R1 전환 계약 결함으로 판정하고 원장·통합 test 보완과 manifest-only 재제출 근거를 1.4·1.7·4.2에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.9 | 2026-07-31 11:24 | R1 변경의 dev 통합·CI PASS와 R4/R5 실제 경로·문서 소유권 정합화 근거를 1.4·1.7·4.2·5.2에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.8 | 2026-07-31 11:05 | R1 handoff 자동 검사의 self-reference 결함 수정, R2 manifest-only 재제출 허가와 R4 branch 복구 수용·OpenAPI 동결 재발행 근거를 1.4·1.7·2.10·4.2에 연결했으며 기존 상태·일정·간트는 유지 |
| v7.7 | 2026-07-31 10:25 | 최신 dev·CI 기준으로 R2·R5의 I1 동결 보완 실행과 개인 branch push를 승인하고 R4 branch 원상복구 전용 REWORK를 분리했으며 R3·Wave 2 대기와 기존 상태·일정·간트를 유지 |
| v7.6 | 2026-07-31 10:12 | `origin/dev` `68fc068`·GitHub Actions run `30528089815` PASS로 원격 동기화 차단을 해제하고, I1 차단 원인을 실제 PMS 수익 필드·PMS↔CRM event-time JOIN·최종 계약 version으로 좁혀 R2/R4/R5 동결 follow-up 발행 근거를 1.4·2.10·4.2·5.2에 연결했으며 상태·일정·간트는 유지 |
| v7.5 | 2026-07-30 17:09 | R2 DataHub consumer의 dev 통합과 root 3-profile 정적 검증, R1 Gate 오탐·Compose CI 보완 근거를 1.4~1.7·2.10에 연결하고 실제 runtime·I1 계약 동결 전 기존 상태·일정·간트를 유지 |
| v7.4 | 2026-07-30 15:47 | R4·R5 dev 통합과 root Compose·env·CI 진행 근거를 1.4~1.7에 연결하고 1.5~1.6을 진행으로 전환했으며 DataHub consumer fragment 보완을 2.10의 R2-W1-F2 READY로 기록 |
| v7.3 | 2026-07-30 14:57 | R1-06 읽기 전용 역할 경로·R5 build 자동 검사와 검증 근거를 1.7에 연결하고 진행 상태·기존 일정·간트를 유지 |
| v7.2 | 2026-07-30 14:52 | R4 cleanup 전용 READY와 R5 clean handoff 재검토 근거를 1.4·4.21·5.2·5.19에 연결하고 통합 전 기존 상태·일정·간트를 유지 |
| v7.1 | 2026-07-30 14:39 | R2 I1 service fragment의 dev 통합·정적 소비 검증 근거를 1.4·2.10에 연결하고 common blocker 대기로 기존 상태·일정·간트를 유지 |
| v7.0 | 2026-07-30 14:16 | R2 fragment 제출과 R4 clean handoff 재검토 근거를 1.4·2.10·4.21에 연결하고 기존 상태·일정·간트를 유지 |
| v6.9 | 2026-07-30 14:01 | R5 handoff 부분 검토 근거를 1.4·5.2·5.19에 연결하고 R5-01을 검토로 전환했으며 R5-18과 기존 일정은 유지 |
| v6.8 | 2026-07-30 13:39 | R2-W1-F1 지정 파일의 commit·seung push 허가 근거를 1.4·2.10에 연결하고 제출 전 상태와 일정은 유지 |
| v6.7 | 2026-07-30 12:56 | R4 handoff 독립 검토 근거를 1.4·4.21에 연결하고 R4-20을 검토로 전환했으며 I1 차단과 기존 일정은 유지 |
| v6.6 | 2026-07-30 12:36 | R2·R4·R5 I1 follow-up READY 발행 근거를 1.4·2.10·4.21·5.2·5.19에 연결하고 검증 전 상태 유지 |
| v6.5 | 2026-07-30 12:32 | R3 Dockerfile·실행 manifest를 I1 비필수·R3-W3 제출로 판정하고 R1-03 blocker 범위를 R2·R4·R5 보완 대기로 정정 |
| v6.4 | 2026-07-30 12:03 | R2·R3 I1 입력 승인과 R4·R5 Wave 1 재작업 허가, R1-03 차단·Wave 2 불허 판정을 작업 근거에 반영 |
| v6.3 | 2026-07-30 11:53 | R1-03 차단 중 선행한 R1-06 Python CI baseline과 R1-07 평가 원장 schema를 진행 상태와 근거로 반영 |
| v6.2 | 2026-07-30 11:35 | R1-03의 R2·R3·R4 계약 도착과 R5 UI·Report·route 및 역할별 service fragment 차단 근거를 최신 통합 SHA에서 재판정 |
| v6.1 | 2026-07-30 11:28 | R1·R2 통합 WBS에 R5 요구사항·화면설계 산출물 근거를 시간순으로 통합 |
| v6.0 | 2026-07-30 11:20 | R1 I0 결정·계약 대기 기록과 R2-W1 생산자 검증 결과를 시간순으로 통합 |
| v5.9 | 2026-07-30 10:36 | 활성 frontend·범위·소유권 결정 완료와 R1-03 계약 입력 차단 상태를 WBS 1.1~1.4에 반영 |
| v5.8 | 2026-07-30 10:25 | Wave 1 실행 묶음의 기준 SHA 교정 근거를 WBS 1.1 작업 로그에 반영 |
| v5.7 | 2026-07-30 09:55 | 최신 dev의 R4 Control Plane 진행 근거와 기획·실행 절차 교정 및 I5 이후 후속 백로그를 충돌 없이 통합 |
| v5.4 | 2026-07-29 17:35 | R2 DB bootstrap 진행 근거를 보존하면서 4개 통합 Wave와 상세 실행 카드 운영 기준을 통합 |
