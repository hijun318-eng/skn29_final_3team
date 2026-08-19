# Answervice MVP E2E 참고 문서

> **문서 상태: SUPPORTING / NON-NORMATIVE**
> 현재 제품 기준은 [`../README.md`](../README.md)와 [`../product/`](../product/)의 4개 문서다. 이 폴더는 원문·과거 E2E 계약·실행 이력을 보존한다. 과거 완료 상태를 현재 V4.1 완료 증거로 사용하지 않는다.

## 현재 작업의 읽는 순서

1. `../product/00_기획서.md`
2. `../product/01_PRD.md`
3. `../product/02_유저플로우.md`
4. `../product/03_아키텍처.md`

## 이 폴더를 참고할 때의 읽는 순서

1. 보존 원문이 필요하면 `source/`에서 사용자가 지정한 00~04를 읽는다.
2. 과거 contract가 필요하면 `derived/01_MVP_PRD.md` → `02_Golden_Path_유저플로우.md`를 읽되, 아키텍처는 과거 사본을 두지 않고 [`../product/03_아키텍처.md`](../product/03_아키텍처.md)만 사용한다.
3. 과거 진행 기록은 `derived/21_AI_작업_인수인계_현재진행상황.md`를 읽되 현재 코드·runtime에서 재검증한다.
4. 모델 배포 작업일 때만 RunPod 운영 가이드를 읽는다.

원문 사이에 범위 차이가 있으면 현재 `docs/product/` 계약을 우선한다. 원문의 보안 경계, read-only, G1·G2·G3, Definition/Run/Result 분리는 현재 문서가 명시적으로 대체하지 않는 한 보존한다.

## 정리 문서

| 파일 | 용도 |
|---|---|
| `derived/01_MVP_PRD.md` | 과거 MVP 범위와 완료 조건 |
| `derived/02_Golden_Path_유저플로우.md` | 과거 화면부터 분석 결과까지의 정상·실패 흐름 |
| `derived/04_P0_사용자기능_요구사항_및_검증계획.txt` | 평가 피드백을 반영한 P0 기능 ID, Slice 순서와 검증 시나리오 |
| `derived/21_AI_작업_인수인계_현재진행상황.md` | 2026-08-13 구현·E2E snapshot |
| `derived/05_sLLM_RunPod_연결_가이드.md` | Adapter 검증과 endpoint 연결 |
| `derived/22_RunPod_Serverless_vLLM_배포_가이드.md` | Serverless endpoint 전환 절차 |

`06_데이터_SQL_Web_작업지시서.md`는 과거 Docker 감사 근거일 뿐 신규 작업 지시로 사용하지 않는다. 요청별 seed·정답 SQL·Compose를 모았던 `derived/service_demo_v3/`는 삭제됐으며, 현재 runtime은 Source DB schema와 DataHub·Trino 동적 discovery 외의 데모 적재 경로를 제공하지 않는다.

## 고정 원문

아래 SHA-256은 2026-08-12에 사용자가 제공한 파일을 그대로 복사한 값이다.

```text
d257c7222279d698eaab2be0ef7f98b7bb2003a4ef61b3e8c836284578355f5f  00_Answervice_프로젝트_기획서.md
63261f0ef888a7c57c9a73d4095b8766c9b8eac65d0c735b6395855fef22f097  01_Answervice_데이터_분석_Core_설계.md
64b775512fdedd87bbd88b2a56550d4417d9d1c19192820e342a943b988d95e9  02_Answervice_sLLM_모델_학습_평가.md
19e2b66630d7d9ca62f8340992b10106560481a9b7dad29ff1b2d881a3afe88d  03_Answervice_구현_운영_검증.md
d4752286098dde36e2217e8f7abb2904fd319c0a454598838ef4899cc3dca571  04_Answervice_단계별_구현_가이드.md
429bc6753a87de097f87a474e75d9b119d64b0357cde3473c333db242945c172  05_프로젝트_구조조정_평가서.md
```

모델 ZIP은 크기와 weight 때문에 저장소에 복사하지 않는다.

```text
파일: C:\Users\Playdata\Downloads\answervice-sllm-results (3).zip
SHA-256: 22510f0de36d0121c350c4cd5ba3705a4db95dea27ce78baf70434ff1e24f29e
```
