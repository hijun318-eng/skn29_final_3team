# Answervice MVP E2E 문서

이 폴더는 앞으로 구현 AI가 제품 요구를 확인하는 단일 문서 위치다. 저장소의 다른 문서는 제출 산출물과 과거 이력으로 남아 있을 수 있지만, 사용자가 현재 요청에서 특정하지 않으면 구현 근거로 사용하지 않는다.

## 읽는 순서

1. `derived/01_MVP_PRD.md`
2. `derived/02_Golden_Path_유저플로우.md`
3. `derived/03_E2E_아키텍처_및_계약.md`
4. `derived/04_P0_사용자기능_요구사항_및_검증계획.txt`
5. 현재 상태 확인이 필요하면 `derived/21_AI_작업_인수인계_현재진행상황.md`
6. 모델 배포 작업일 때만 RunPod 운영 가이드
7. 판단 근거가 필요할 때만 `source/` 원문과 `source/08_구조조정_판단기록.md`

원문 사이에 범위 차이가 있으면 구조조정 평가서의 “첫 Golden Path를 먼저 연결한다”는 결정을 우선한다. 보안 경계, read-only, G1·G2·G3는 축소하지 않는다.

## 정리 문서

| 파일 | 용도 |
|---|---|
| `derived/01_MVP_PRD.md` | 현재 MVP 범위와 완료 조건 |
| `derived/02_Golden_Path_유저플로우.md` | 화면부터 실제 분석 결과까지의 정상·실패 흐름 |
| `derived/03_E2E_아키텍처_및_계약.md` | 컴포넌트 책임, 모델 계약과 안전 경계 |
| `derived/04_P0_사용자기능_요구사항_및_검증계획.txt` | 평가 피드백을 반영한 P0 기능 ID, Slice 순서와 검증 시나리오 |
| `derived/21_AI_작업_인수인계_현재진행상황.md` | 현재 구현 범위, E2E 결과, 미완료 항목과 다음 순서 |
| `derived/05_sLLM_RunPod_연결_가이드.md` | Adapter 검증과 endpoint 연결 |
| `derived/22_RunPod_Serverless_vLLM_배포_가이드.md` | Serverless endpoint 전환 절차 |

`06_데이터_SQL_Web_작업지시서.md`는 과거 Docker 감사 근거로만 보존하며 신규 작업 지시로 사용하지 않는다. 현재 적재 중인 SQL·Compose·검증 파일은 `derived/service_demo_v3/`에만 둔다.

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
