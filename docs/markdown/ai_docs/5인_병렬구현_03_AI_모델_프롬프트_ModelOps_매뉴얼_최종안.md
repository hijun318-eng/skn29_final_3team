# 역할 3 — AI·모델·프롬프트·ModelOps 매뉴얼

> 문서 상태: 역할 도메인 참고서 — 현재 실행 상태·권한은 Git Gate 원장 참조
> 작성 기준일: 2026-08-11
> 담당자: 윤대성
> 개인 브랜치: `daesung`
> 역할 ID: `R3`
> 기준 기획서: `docs/Answervice_기획서.md`
> 통합 일정: `docs/markdown/ai_docs/5인_병렬구현_통합일정_20260729-20260903.md`
> 쉬운 용어: Gate는 통과 검사, fixture는 고정 테스트 데이터, trace는 처리 기록, rollback은 이전 버전으로 되돌리기를 뜻한다.

## 0. 역할 한 문장

윤대성은 승인된 Context와 정형 결과만 입력받는 Node 1·2·2′·3, prompt·모델 평가·model serving을 구현하고, 권한·실행 허용·Gate 판정은 백엔드에 남긴다.

## 1. 최종 책임과 경계

### 1.1 R3 최종 책임

- Node 1 질문 정규화
- Node 2 승인 Context 기반 Trino SQL 생성
- Node 2′ G2 오류를 입력받는 1회 SQL 수정
- Node 3 검증된 shaped result 기반 설명
- 역할별 입력·출력 JSON schema와 prompt version
- model adapter와 fake implementation
- Base model 후보 비교와 평가 runner
- 학습·validation·gold split 검증
- 시간·횟수를 제한한 LoRA/QLoRA 1회 비교와 조건부 제품 채택·되돌리기(rollback)
- RunPod·vLLM model serving manifest·health·resource 측정
- model/prompt/version/latency/token/cost trace
- model endpoint 장애·timeout·잘못된 schema fallback

### 1.2 R3가 판정하지 않는 것

- 사용자 권한과 asset 허용 여부
- SQL 실행 허용·차단
- G1·G2·G3 합격
- 수치 재계산과 정답 판정
- DataHub·Trino 직접 실행
- Report 상태와 release 합격

위 판정은 R4 결정론적 Controller와 Gate가 담당한다. R3는 pass token을 만들거나 사용자 입력의 `approved=true`를 신뢰하지 않는다.

### 1.3 직접 수정하지 않는 영역

- 루트 Compose·CI·`.env.example`: R1 박준희
- DB·DataHub·Trino·정답 SQL: R2 정승
- FastAPI·Controller·Gate·Artifact·worker: R4 김재홍
- frontend·Report: R5 송민지

## 2. 파일·인터페이스 소유권

| R3 단일 소유 | 소비자 |
|---|---|
| Node별 prompt와 output schema | R4 Controller |
| model adapter·fake·serving client | R4 Controller |
| model server Dockerfile/manifest | R1 Compose |
| 평가 runner·model benchmark | R1 수용 판정 |
| LoRA config·checkpoint manifest | R1 release, R4 runtime |

R3는 공통 OpenAPI를 직접 수정하지 않고 R4에게 model contract 변경 요청을 제출한다. R1에게는 service fragment와 env 이름만 전달한다.

## 3. AI 실행 방식

공통 작업 시작·branch 동기화·CI·handoff·Git 절차는 `docs/markdown/collaboration/README.md`와 현재 `Gate_실행_카드_원장.md`를 단일 기준으로 사용한다. 이 매뉴얼의 과거 공통 prompt·CI 표·handoff 필드 복제본은 제거하며, 현재 카드의 `ALLOWED_PATHS`·`ACCEPTANCE_CRITERIA`·`TEST_COMMANDS`·`STOP_CONDITIONS`를 우선한다.

1. 본인 branch에서 `python .github/scripts/agent_workflow.py --branch <본인 branch>`를 실행한다.
2. `PASS`와 실행 가능한 카드가 확인된 경우에만 현재 `TASK_CARD_RANGE`를 번호 순서대로 수행한다.
3. R3는 Node·prompt·model·evaluation 소유 경로와 카드별 AI 검증만 수행하고 권한·SQL 실행·Gate 판정은 하지 않는다.
4. 완료 후 협업 README의 공통 handoff 절차로 실제 검증·미실행·잔여 위험을 기록한다.
5. 범위 밖 변경·계약 충돌·필수 검증 실패는 직접 우회하지 않고 원 소유자와 R1에게 반환한다.

## 4. 순차 작업 카드

| 카드 | 작업 | 출력 | 완료 검증 |
|---|---|---|---|
| R3-00 | AI 범위·실험 계약 확인 | model decision 초안 | P0와 P2 혼입 0건 |
| R3-01 | Node I/O schema | versioned JSON schemas | 유효·누락·초과 field test |
| R3-02 | fake model adapter | deterministic fake | R4 contract test 소비 가능 |
| R3-03 | Node 1 질문 정규화 | intent/metric/time 후보 | 모호성·금지 판정 미수행 |
| R3-04 | Node 2 SQL 생성 | Trino SQL+참조 목록 | Context 밖 asset·column 0건 |
| R3-05 | Node 2′ 1회 수정 | corrected SQL | 정규화 G2 오류만 사용 |
| R3-06 | Node 3 설명 | 근거·조건·주의 설명 | G3 실패 입력 거부 |
| R3-07 | Prompt Registry | prompt ID/version/hash | Node·환경별 추적 가능 |
| R3-08 | 평가 runner | schema/linking/SQL/result 평가 | 필수 30건 자동 실행 |
| R3-09 | Base model·Analytics Agent 기준선 비교 | 동일 조건 비교표 | 정확도·p50/p95·자원·기능 경계 측정 |
| R3-10 | 학습 데이터 검수 | train/val/gold manifest | paraphrase group 누수 0건 |
| R3-11 | LoRA/QLoRA 1회 비교·조건부 채택 | 비교 결과·adapter·되돌리기 증거 | 실행·`Not Run` 사유와 채택 결정을 분리 |
| R3-12 | vLLM·RunPod serving | endpoint·health·manifest | cold/warm·timeout·restart |
| R3-13 | production model client | retry/fallback/circuit 계약 | 오류 redaction·schema fail |
| R3-14 | Trace·비용·재현성 | version/cost/token trace | 동일 설정 재현 |
| R3-15 | Release 후보 고정 | model release manifest | R1/R4 회귀 통과 |

## 5. Node별 상세 계약

### 5.1 Node 1 — 질문 정규화

입력:

- 원문 질문
- 사용자에게 노출 가능한 role hint
- 고정 `as_of`, timezone, calendar
- 허용된 route와 업무 용어

출력:

- normalized question
- intent·metric·dimension 후보
- 절대 기간 후보
- ambiguity와 사용자에게 물을 최소 질문

금지:

- DataHub asset 최종 확정
- 권한 허용·거부
- 임의 기본값으로 업무 의미 확정
- SQL 생성

평가:

- intent·metric·기간 추출
- 모호한 질문의 재질문 필요 신호
- 현재 등급과 event-time 등급 구분
- 정상 질문을 불필요하게 차단하지 않는지

### 5.2 Node 2 — SQL 생성

입력은 R4가 G1 통과 후 전달한 승인 Context Package로 제한한다.

출력:

- Trino SQL
- 참조한 URN/FQN·column·JOIN ID·metric ID
- parameter binding 목록
- 생성 model/prompt version

금지:

- Context 밖 table·column·JOIN
- `now()`·`current_date`
- DDL·DML·복수 statement
- 원문 DB 오류·secret·내부 allowlist 수신
- 실행 또는 EXPLAIN

R3 평가는 SQL parse·schema linking·reference 일치까지 수행할 수 있으나 최종 정책 판정은 R4 G2가 한다.

### 5.3 Node 2′ — 1회 수정

입력:

- 거절 SQL
- 동일 승인 Context
- 정규화된 G2 오류 코드
- 수정 가능한 범위

규칙:

1. 최초 SQL과 수정 시도를 같은 trace에 연결한다.
2. 원문 DB 오류·stack trace를 입력하지 않는다.
3. R3 내부에서 반복 호출하지 않는다.
4. 수정 출력도 반드시 R4 G2′로 되돌린다.
5. 재실패하면 종료하며 새로운 SQL을 무한 생성하지 않는다.

### 5.4 Node 3 — 근거 기반 설명

입력:

- G3 pass shaped result
- metric·기간·filter·단위
- sampling·mask·partial 상태
- source 식별자와 `query_execution_id` 또는 `result_cache_key`

출력:

- 사용자가 이해할 설명
- 조건·기간·단위·출처
- 부분 결과 또는 제한의 안전한 안내

금지:

- shaped result 밖 수치 생성
- 비율·합계를 다시 계산
- 원인을 근거 없이 단정
- G3 실패·증적 누락 결과 설명
- 내부 SQL policy와 민감 parameter 노출

## 6. 모델 비교·학습·서빙

### 6.1 Base 비교

동일 조건:

- 동일 필수 30건과 gold subset
- 동일 prompt·max output·temperature 정책
- batch size 1
- cold/warm 분리
- schema validity, linking, execution result, 설명 근거성
- p50/p95, GPU memory, token, 비용

모델 이름과 버전은 실제 실행 manifest에 기록하고 실행하지 않은 후보는 `Not Run`으로 둔다.

DataHub Analytics Agent 비교는 동일 데이터·대표 질문·권한 조건을 사용한다. 문서 기능 비교와 실제 실행 비교를 분리하고, 본 프로젝트의 결정론적 Gate·상태·model serving·Artifact 재사용 경계가 무엇이 다른지 증거로 남긴다.

### 6.2 LoRA/QLoRA 1회 비교와 제품 채택 Gate

1회 비교는 다음이 모두 충족될 때 시작한다.

- Context Package와 Base 평가가 안정됨
- 학습·validation·gold 누수 검사가 완료됨
- R1이 외부 비용·시간·비교 기준을 승인함
- R2 gold SQL·result가 검수됨
- rollback 가능한 Base endpoint가 존재함

조건이 부족하거나 외부 실행 권한이 없으면 이유를 `Blocked` 또는 `Not Run`으로 남긴다. 이것만으로 I5 실패로 처리하지 않는다. 제품 채택은 비교 결과에서 모델 원인 오류가 실제로 줄고 안전·속도·비용이 나빠지지 않았을 때만 별도로 승인한다. 승인 전에는 Node 1·2·2′·3 모두 Base를 사용하고, 승인 후에도 SQL adapter는 Node 2·2′에만 적용한다.

### 6.3 Model Serving

R3가 작성:

- model server Dockerfile 또는 실행 manifest
- image/model/adapter version
- port, env 이름, health/readiness
- GPU·CPU·memory 요구
- timeout·concurrency·max token
- model preload와 restart 절차
- `/workspace` 영속 저장소와 외부 backup 위치
- 실행 최대 시간·비용 한도, 한도 도달 시 중단과 Pod 종료 절차

R1이 작성:

- 루트 Compose 등록
- profile과 secret reference
- 통합 health·CI·release 실행

외부 RunPod 작업은 사용자 승인 전까지 비용 없는 준비 작업만 수행한다.

데모 동시 실행은 2건으로 제한한다. 이를 넘는 요청은 대기시키거나 `429`로 반환한다. model·dataset·checkpoint는 container disk에만 두지 않고 실험 종료 전에 외부로 백업한다.

### 6.4 외부 모델에 보내는 데이터

- 승인된 질문, Context Package와 필요한 최소 metadata만 보낸다.
- 실제 고객 원문, credential, 민감 parameter, 불필요한 sample value는 보내지 않는다.
- sample value가 꼭 필요하면 R1의 별도 데이터 전송 승인을 받고 합성·마스킹 여부와 전송 범위를 trace에 남긴다.

## 7. 평가와 인수인계

핵심 지표:

- JSON schema valid rate
- Node 1 intent/metric/time 정확도
- Node 2 schema linking·JOIN·execution result 정확도
- G2 repair success와 수정 1회 준수
- Node 3 unsupported claim·numeric mismatch
- p50/p95·token·GPU memory·비용
- timeout·invalid output·endpoint failure 처리

| 받는 역할 | R3 전달물 |
|---|---|
| R1 박준희 | model service fragment, resource·cost, benchmark, release manifest |
| R2 정승 | gold 오류·schema linking 누락 목록 |
| R4 김재홍 | Node schema, fake/real client, timeout/error, model/prompt version |
| R5 송민지 | 사용자에게 노출 가능한 model 상태·설명 fixture |

I5 이후 후속 단계에서는 R3가 F-01 MCP adapter 계약, F-02 문서 RAG, F-03 ML-as-a-Tool을 맡는다. F-04 고객 360은 별도 모델을 기본 전제로 하지 않고, 승인된 기존 Node 계약으로 처리 가능한지 먼저 확인한다. 이 후속 작업들은 현재 I5 완료 조건에 포함하지 않는다.

```text
작업 카드:
model/prompt/fixture version:
변경 파일:
Node 입력·출력 schema:
사용 모델·환경:
평가 결과:
지연·자원·비용:
실패 case:
R4/R1 handoff:
미실행·남은 위험:
```

## 8. 병합 패키지

| 패키지 | 완료 범위 | 소비자 |
|---|---|---|
| R3-M1 | Node schema·fake adapter | R4·R5 |
| R3-M2 | Node 1·2·2′·3·prompt | R4 |
| R3-M3 | 평가 runner·Base 비교·serving | R1·R4 |
| R3-M4 | 1회 LoRA 비교·조건부 채택, production client·release manifest | R1·R4 |

공통 FastAPI·Gate·루트 Compose를 함께 수정한 R3 패키지는 병합하지 않는다.

## 9. 최종 체크리스트

- [ ] Node 1·2·2′·3 입력·출력이 versioned schema다.
- [ ] 모든 Node가 권한·Gate·실행을 판정하지 않는다.
- [ ] Node 2가 승인 Context 밖 자산을 사용하지 않는다.
- [ ] Node 2′ 자율 반복이 없고 최대 1회다.
- [ ] G3 실패 후 Node 3 호출이 0건이다.
- [ ] Node 3 수치 재계산·근거 없는 원인 단정이 0건이다.
- [ ] 필수 30건 자동 평가와 gold split 누수 검사가 있다.
- [ ] Base 비교가 동일 조건으로 수행됐다.
- [ ] LoRA/QLoRA 1회 비교는 승인 조건 아래 수행됐거나 `Blocked`·`Not Run` 사유가 기록됐다.
- [ ] 제품 채택 전에는 모든 Node가 Base이고, 채택 후에도 Node 1·3에는 SQL adapter가 적용되지 않는다.
- [ ] model server health·timeout·restart·fallback이 검증됐다.
- [ ] 데모 동시 2건·초과 대기/`429`, 영속 저장·외부 backup·시간/비용 중단 조건이 기록됐다.
- [ ] model/prompt/adapter version이 trace와 release manifest에 연결된다.
